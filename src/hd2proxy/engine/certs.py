"""会话证书（M1 从 legacy_proxy.py + tools/gen_session_certs.py 合并）。

关键结论（研究线实测，别动）：
  * **只有 ca 模式能握手**：叶子自签（leaf）时 Schannel 需要 CRL，拿不到就在握手前断开；
  * 证书有效期**默认 2 天**；显式配置（`cert.days` / `--days`）可放宽到 **7 天硬上限**
    （2026-11-25 与研究线双端定案：放宽是为了降低"每 ~36h 就得续一次证书 + 重装信任"的频次；
    硬上限 7 天**不可被参数突破**——`max_days` 再大也钳到 7）；
  * 签名后立刻删 CA 私钥，会话期内不再保留；
  * 代理必须在 127.0.0.1:8080 提供 ca.crl（Schannel 的 CDP 检查）；
  * preflight 拒绝：SAN 不符 / 有效期过长或已过期 / 模式非 ca / 目录里有多余私钥。
"""

import json
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509


# ---- 有效期策略（2026-11-25 与 research 线双端定案） --------------------------
MAX_DAYS_DEFAULT = 2      # 默认有效期：**默认行为不变**，仍是 2 天
MAX_DAYS_HARD = 7         # 硬上限：任何参数都突破不了（max_days 再大也钳到这里）


def effective_max_days(max_days=None) -> int:
    """策略上限：未显式传入 → 默认 2 天；显式传入也钳在 [1, 硬上限]。"""
    if max_days is None:
        return MAX_DAYS_DEFAULT
    try:
        want = int(max_days)
    except (TypeError, ValueError):
        return MAX_DAYS_DEFAULT
    return max(1, min(want, MAX_DAYS_HARD))


def clamp_days(days, max_days=None) -> int:
    """把请求的有效期钳进 [1, min(策略上限, 硬上限)]。

    为什么两层：``max_days`` 是策略开关（未显式设置时默认 2 天、不许悄悄放宽），
    :data:`MAX_DAYS_HARD` 是绝对天花板（就算调用方传 ``max_days=99`` 也只能到 7）。
    """
    try:
        want = int(days) if days is not None else MAX_DAYS_DEFAULT
    except (TypeError, ValueError):
        want = MAX_DAYS_DEFAULT
    return max(1, min(want, effective_max_days(max_days), MAX_DAYS_HARD))
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .logutil import log


def _session_mode(cert_dir):
    """读 session.json 里记录的证书模式（leaf / ca），决定握手时要不要带链。"""
    try:
        info = json.loads((Path(cert_dir) / "session.json").read_text(encoding="utf-8"))
        return info.get("mode") or "leaf"
    except Exception:
        return "leaf"


def serve_crl(cert_dir, port=8080):
    """在本机 8080 提供 ca.crl。

    Windows Schannel 看到证书里的 CDP 就会去取；取不到就报
    CRYPT_E_NO_REVOCATION_CHECK 并拒绝握手，所以这个服务是必需的。
    """
    crl = Path(cert_dir) / "ca.crl"
    if not crl.exists():
        log("no ca.crl -> skip CRL server（Schannel 可能会拒绝握手）")
        return None
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/ca.crl", "/ca.crl.der"):
                self.send_error(404)
                return
            data = crl.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pkix-crl")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log("CRL server on http://127.0.0.1:%d/ca.crl (%d B)" % (port, crl.stat().st_size))
    return srv



def preflight(host, cert_dir, skipped=None):
    """启动前自检：证书与会话一致性。任一不满足就拒绝启动。"""
    problems = []
    session = Path(cert_dir) / "session.json"
    if not session.exists():
        problems.append("缺少 session.json（先跑 setup.ps1）")
    else:
        try:
            info = json.loads(session.read_text(encoding="utf-8"))
            if info.get("san_dns") != [host]:
                problems.append("证书 SAN 不是单一目标域名: %r" % (info.get("san_dns"),))
            if float(info.get("days", 99)) > MAX_DAYS_HARD:
                problems.append("证书有效期超过硬上限 %d 天: %s 天"
                                % (MAX_DAYS_HARD, info.get("days")))
            if info.get("self_check") != "OK":
                problems.append("证书自检未通过: %s" % info.get("self_check"))
        except Exception as e:
            problems.append("session.json 读取失败: %r" % e)
    keys = [p.name for p in Path(cert_dir).glob("*.key") if p.name != "server.key"]
    if keys:
        problems.append("会话目录里有多余私钥: %s" % keys)
    if skipped:
        problems.append("配置里有无法识别的目标: %r" % (skipped,))

    # 1.04：证书过期、或证书不是 ca 模式，都直接拒绝启动 ——
    # 这两种都会让游戏卡在“尝试与服务器通讯时出错”，但日志里看不出原因。
    try:
        info2 = json.loads(session.read_text(encoding="utf-8")) if session.exists() else {}
    except Exception:
        info2 = {}
    na = info2.get("not_after")
    if na:
        try:
            from datetime import datetime, timezone
            exp = datetime.fromisoformat(str(na).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= datetime.now(timezone.utc):
                problems.append("证书已过期（%s）-> 重跑 setup.ps1（或面板的安装按钮）" % na)
        except Exception:
            pass
    if info2 and info2.get("mode") != "ca":
        problems.append("证书模式是 %r：游戏只认 ca（leaf 没有 CRL，客户端会在握手前断开）"
                        " -> 重跑 setup.ps1" % (info2.get("mode"),))
    return problems



# ---- 证书签发（原 tools/gen_session_certs.py 的实现，逐字迁入） ----------------
ORDER = [
    ("BasicConstraints", "critical"),
    ("SubjectAlternativeName", "non-critical"),
    ("ExtendedKeyUsage", "non-critical"),
]


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write_key(path: Path, key):
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:  # 只给当前用户读写（Windows 上等价于把旁人挡在外面）
        os.chmod(path, 0o600)
    except Exception:
        pass


CDP_URL = "http://127.0.0.1:8080/ca.crl"


def add_crl_extensions(builder, is_ca: bool):
    """给证书加吊销检查点：没有 CDP 时 Windows Schannel 直接报
    CRYPT_E_NO_REVOCATION_CHECK（0x80092012）并拒绝握手。"""
    b = builder.add_extension(
        x509.CRLDistributionPoints([
            x509.DistributionPoint(
                full_name=[x509.UniformResourceIdentifier(CDP_URL)],
                relative_name=None, reasons=None, crl_issuer=None),
        ]), critical=False)
    if not is_ca:
        b = b.add_extension(
            x509.AuthorityInformationAccess([
                x509.AccessDescription(
                    x509.oid.AuthorityInformationAccessOID.CA_ISSUERS,
                    x509.UniformResourceIdentifier(CDP_URL)),
            ]), critical=False)
    return b


def leaf_cert(host: str, pub, issuer_name, issuer_key, days: int, is_self: bool):
    now = datetime.now(timezone.utc)
    b = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(issuer_name)
        .public_key(pub)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
    )
    if not is_self:
        b = b.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False)
        b = add_crl_extensions(b, False)
    return b.sign(issuer_key, hashes.SHA256())


def build_leaf_mode(host: str, out: Path, days: int):
    days = max(1, min(int(days), MAX_DAYS_HARD))   # 硬上限兜底（不套默认 2 天）
    key = new_key()
    cert = leaf_cert(host, key.public_key(), x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, host + " (local session)")]),
        key, days, True)
    write_key(out / "server.key", key)
    (out / "server.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (out / "server.chain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (out / "anchor.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    # certutil / Import-Certificate 都更可靠地吃 DER，所以同时写一份 .cer
    (out / "anchor.cer").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    return cert, cert


def build_ca_mode(host: str, out: Path, days: int):
    days = max(1, min(int(days), MAX_DAYS_HARD))   # 硬上限兜底（不套默认 2 天）
    ca_key = new_key()
    now = datetime.now(timezone.utc)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HD2 Variant Mod Session CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        # 名称约束：这张 CA 只能为这一个域名签发
        .add_extension(x509.NameConstraints(permitted_subtrees=[
            x509.DNSName(host)], excluded_subtrees=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = new_key()
    leaf = leaf_cert(host, leaf_key.public_key(), ca.subject, ca_key, days, False)
    write_key(out / "server.key", leaf_key)
    (out / "server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (out / "server.chain.pem").write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    (out / "anchor.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (out / "anchor.cer").write_bytes(ca.public_bytes(serialization.Encoding.DER))

    # 生成一份空 CRL（没有吊销项），由本机 8080 提供；Schannel 需要它才肯握手。
    # 必须在这里签：签完就把 CA 私钥删掉。
    try:
        from cryptography.hazmat.primitives import hashes as _h
        crl = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(ca.subject)
            .last_update(datetime.now(timezone.utc) - timedelta(minutes=5))
            .next_update(datetime.now(timezone.utc) + timedelta(days=days + 1))
            .sign(ca_key, hashes.SHA256())
        )
        (out / "ca.crl").write_bytes(crl.public_bytes(serialization.Encoding.DER))
    except Exception as e:
        print("CRL generation failed:", e)

    # 关键：签完就删掉 CA 私钥，会话期内磁盘上不留"能签任意域名"的钥匙
    del ca_key
    return leaf, ca


def describe(leaf, mode: str, host: str, anchor=None):
    """描述会话证书。ca 模式下 leaf 是被签发的那张，anchor 是装进 Root 的 CA。"""
    cert = leaf
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    dns = []
    for n in san.get_values_for_type(x509.DNSName):
        dns.append(n if isinstance(n, str) else n.value)
    trust = anchor or leaf
    report = {
        "mode": mode,
        "subject": cert.subject.rfc4514_string(),
        "basic_constraints_ca": bool(bc.ca),
        "san_dns": dns,
        "san_count": len(dns),
        "eku": [str(e) for e in eku],
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "days": round((cert.not_valid_after_utc - cert.not_valid_before_utc).total_seconds() / 86400, 2),
        # 装进 Root 的是 trust（leaf 模式下就是自己，ca 模式下是 CA）
        "thumbprint_sha1": trust.fingerprint(hashes.SHA1()).hex().upper(),
        "trust_subject": trust.subject.rfc4514_string(),
        "trust_thumbprint_sha1": trust.fingerprint(hashes.SHA1()).hex().upper(),
    }
    problems = []
    if dns != [host]:
        problems.append("SAN 必须只有 %s，实际 %s" % (host, dns))
    if report["days"] > MAX_DAYS_HARD:
        problems.append("有效期超过硬上限 %d 天" % MAX_DAYS_HARD)
    if eku and ExtendedKeyUsageOID.SERVER_AUTH not in eku:
        problems.append("缺少 serverAuth EKU")
    report["self_check"] = "OK" if not problems else "FAIL: " + "; ".join(problems)
    return report


def existing_ok(out: Path, host: str, days: int):
    """已有会话证书是否还能用：SAN 唯一、有效期够、自检 OK、密钥在。"""
    session = out / "session.json"
    if not session.exists() or not (out / "server.key").exists():
        return None
    try:
        info = json.loads(session.read_text(encoding="utf-8"))
    except Exception:
        return None
    if info.get("san_dns") != [host] or info.get("self_check") != "OK":
        return None
    try:
        cert = x509.load_pem_x509_certificate((out / "anchor.pem").read_bytes())
    except Exception:
        return None
    left = (cert.not_valid_after_utc - datetime.now(timezone.utc)).total_seconds()
    if left < 3600:            # 剩不到 1 小时就重签
        return None
    info["reused"] = True
    info["left_hours"] = round(left / 3600.0, 1)
    return info


# ---- M1：会话证书生命周期（签发 / 状态 / 自动续期） ---------------------------

DEFAULT_HOST = "api.live.prod.thehelldiversgame.com"


def session_remaining_hours(cert_dir) -> float | None:
    """证书剩余小时数；读不到/无 not_after 返回 None。"""
    try:
        info = json.loads((Path(cert_dir) / "session.json").read_text(encoding="utf-8"))
        exp = datetime.fromisoformat(str(info["not_after"]).replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return max(0.0, (exp - datetime.now(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return None


def cert_status(cert_dir, *, check_trust: bool = False) -> dict:
    """给 GUI / control API 用的证书状态快照（只读）。

    ``check_trust=True`` 时额外查询「当前 CA 是否在受信任根存储里」——这要 spawn 一次
    ``certutil``（约 60–120ms），所以**只允许低频路径**（诊断 / 系统自检 / 续期后自检）打开；
    控制面 ``/status`` 是 GUI 0.6s 轮询的热路径，必须保持默认 False。
    """
    cert_dir = Path(cert_dir)
    info = {}
    try:
        info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    mode = info.get("mode")
    remaining = session_remaining_hours(cert_dir) if info else None
    thumb = info.get("trust_thumbprint_sha1") or info.get("thumbprint_sha1")
    trusted, trust_scope = None, None
    if info and thumb and check_trust:
        from . import sysprobe
        trusted = False
        for scope in ("LocalMachine", "CurrentUser"):
            if sysprobe.cert_trusted(thumb, scope):
                trusted, trust_scope = True, scope
                break
    return {
        "cert_dir": str(cert_dir),
        "exists": bool(info),
        "mode": mode,
        "host": info.get("host"),
        "san": info.get("san_dns"),
        "not_after": info.get("not_after"),
        "remaining_hours": None if remaining is None else round(remaining, 1),
        "thumbprint": info.get("thumbprint_sha1"),
        "trust_subject": info.get("trust_subject"),
        "trust_thumbprint": thumb,
        # None = 没查（check_trust=False）；False = 查过且两个根存储里都没有
        "trusted": trusted,
        "trust_scope": trust_scope,
        "usable": bool(info) and mode == "ca" and (remaining or 0) > 0,
        "warnings": _cert_warnings(info, remaining, trusted),
    }


def _cert_warnings(info, remaining, trusted=None):
    out = []
    if not info:
        out.append("没有会话证书（先运行 install，或 python -m hd2proxy certs renew）")
        return out
    if trusted is False:
        # 这一条最容易踩：证书本身没问题、但 CA 不在根存储 → 游戏在 TLS 握手阶段直接断开，
        # 客户端只显示通用错误（Error 60 / Status -1），普通用户完全看不出原因。
        out.append("证书未受信任：当前 CA 不在受信任根存储 → 游戏会在 TLS 握手阶段被拒绝"
                   "（引擎日志 TLS REJECTED）。请点「安装 / 修复」或运行 hd2proxy.exe install 重新导入")
    if info.get("mode") != "ca":
        out.append("证书模式是 %r：游戏只认 ca 模式（leaf 没有 CRL，握手前就会断开）" % (info.get("mode")))
    if remaining is not None and remaining <= 0:
        out.append("证书已过期（%s）" % info.get("not_after"))
    elif remaining is not None and remaining < 12:
        out.append("证书 %0.1f 小时后过期，建议续期" % remaining)
    if info.get("san_dns") != [info.get("host") or DEFAULT_HOST]:
        out.append("SAN 不是单一目标域名: %r" % (info.get("san_dns"),))
    return out


def generate_session(cert_dir, host=DEFAULT_HOST, days=2, max_days=None,
                     force=False, mode="ca") -> dict:
    """签发（或复用）一次会话证书。等价于原 tools/gen_session_certs.py 的主流程。

    安全约束：ca 模式 / SAN 单域名 / 签完删 CA 私钥 / 无多余私钥；
    有效期默认 2 天，显式传 ``max_days`` 才放宽（硬上限 7 天不可突破，见 :func:`clamp_days`）。
    返回 report dict；失败抛 RuntimeError。
    """
    days = clamp_days(days, max_days)
    out = Path(cert_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not force:
        old = existing_ok(out, host, days)
        if old:
            return old
    if mode == "leaf":
        leaf, anchor = build_leaf_mode(host, out, days)
    else:
        leaf, anchor = build_ca_mode(host, out, days)
    report = describe(leaf, mode, host, anchor)
    report["host"] = host
    report["created"] = datetime.now(timezone.utc).isoformat()
    report["files"] = sorted(p.name for p in out.iterdir() if p.is_file())
    stray = [p.name for p in out.iterdir() if p.name.endswith(".key") and p.name != "server.key"]
    if report["mode"] == "ca" and (out / "ca.key").exists():
        stray.append("ca.key")
    report["stray_keys"] = stray
    (out / "session.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report.get("self_check") != "OK" or stray:
        raise RuntimeError("证书自检未通过: self_check=%r stray_keys=%r"
                           % (report.get("self_check"), stray))
    return report


CA_HISTORY_FILE = "ca-history.json"


def ca_history(cert_dir) -> list:
    """CA 变更历史（thumbprint + 时间），排查「Error 60 是不是续期换 CA 导致的」用。"""
    p = Path(cert_dir) / CA_HISTORY_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return doc if isinstance(doc, list) else []


def _record_ca_history(cert_dir, old_thumb: str, new_thumb: str) -> None:
    p = Path(cert_dir) / CA_HISTORY_FILE
    doc = ca_history(cert_dir)
    doc.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "old": old_thumb or None, "new": new_thumb or None})
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(doc[-20:], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def ensure_session(cert_dir, host=DEFAULT_HOST, days=2, max_days=None,
                   min_remaining_hours=12.0, force=False) -> dict:
    """启动前保证证书可用：缺失/过期/剩余不足 → 自动重签；否则复用。

    返回 {"action": "reused"|"generated", "report": {...}, "remaining_hours": float}
    """
    cert_dir = Path(cert_dir)
    remaining = session_remaining_hours(cert_dir)
    usable = remaining is not None and remaining > min_remaining_hours
    if usable and not force and existing_ok(cert_dir, host, days):
        return {"action": "reused", "report": cert_status(cert_dir),
                "remaining_hours": remaining}
    before = cert_status(cert_dir)
    old_thumb = str(before.get("thumbprint") or "") if before.get("exists") else ""
    report = generate_session(cert_dir, host=host, days=days, max_days=max_days, force=True)
    new_thumb = str((report or {}).get("thumbprint_sha1")
                    or (report or {}).get("thumbprint") or "")
    if new_thumb and new_thumb != old_thumb:
        _record_ca_history(cert_dir, old_thumb, new_thumb)
        if old_thumb:
            # 换发 CA = 信任库里的旧 CA 立刻失效：不重装就会 Error 60（实机 2026-11-23 踩过）
            log("⚠ 证书续期换发了新 CA（%s → %s）：旧 CA 仍在信任库但已不匹配 —— "
                "需重新运行 install / GUI「安装 / 修复」，否则游戏会报 Error 60"
                % (old_thumb[:12], new_thumb[:12]), audit=True)
    return {"action": "generated", "report": report,
            "remaining_hours": session_remaining_hours(cert_dir)}



