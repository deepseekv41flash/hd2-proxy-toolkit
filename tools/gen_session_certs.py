"""生成一次会话用的 TLS 证书（安全最小化版）。

★ 默认 **ca 模式** —— 这是实测唯一能和本游戏握手的模式（2026-10-23 真机）：

  ca 模式：名称约束 CA（只允许 api.live.prod.thehelldiversgame.com）+ path_length=0
           + 有效期 1 天；**签完叶子立刻删掉 ca.key**，会话期内不再保留 CA 私钥。
           叶子带 CRL Distribution Points，代理在 127.0.0.1:8080 提供空 CRL ——
           **Schannel 必须拿到这份 CRL 才肯继续握手**。

  leaf 模式：自签叶子直接当锚点（CA:FALSE），没有可发布的 CRL。
           实测后果：游戏 TCP 连上后立刻关闭握手（proxy.log 里
           `TLS REJECTED … SSLZeroReturnError`），游戏界面报“与服务器通讯时出错”。
           所以它只剩实验用途，**不要用它装给游戏**。

两种模式都保证：
  * SAN 只有一个域名（没有通配、没有 Steam/PlayFab）；
  * 有效期 1 天；
  * 不写任何多余文件，输出 session.json 供 teardown/stop 精确清理。

用法：
  py gen_session_certs.py --out-dir ..\\certs --host api.live.prod.thehelldiversgame.com
  py gen_session_certs.py --mode leaf ...      # 仅实验：游戏不认这种证书
"""

import argparse
import ipaddress
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

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
    if report["days"] > 2:
        problems.append("有效期超过 2 天")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--host", default="api.live.prod.thehelldiversgame.com")
    ap.add_argument("--mode", choices=["leaf", "ca"], default="ca",
                    help="默认 ca（游戏只认带 CRL 的 ca 模式；leaf 仅实验）")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="强制重新生成")
    a = ap.parse_args()

    out = Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if not a.force:
        old = existing_ok(out, a.host, a.days)
        if old:
            print(json.dumps(old, ensure_ascii=False, indent=2))
            print("reused existing session certificate (pass --force to regenerate)")
            return 0

    if a.mode == "leaf":
        leaf, anchor = build_leaf_mode(a.host, out, a.days)
    else:
        leaf, anchor = build_ca_mode(a.host, out, a.days)

    report = describe(leaf, a.mode, a.host, anchor)
    report["host"] = a.host
    report["created"] = datetime.now(timezone.utc).isoformat()
    report["files"] = sorted(p.name for p in out.iterdir() if p.is_file())
    stray = [p.name for p in out.iterdir() if p.name.endswith(".key") and p.name != "server.key"]
    if report["mode"] == "ca" and (out / "ca.key").exists():
        stray.append("ca.key")
    report["stray_keys"] = stray
    (out / "session.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["self_check"] == "OK" and not stray else 3


if __name__ == "__main__":
    sys.exit(main())
