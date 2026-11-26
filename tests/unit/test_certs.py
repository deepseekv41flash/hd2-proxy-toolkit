"""会话证书单测：ca 模式签发 / 状态快照 / 自动续期 / preflight。

关键约束（研究线实测）：只有 ca 模式能握手（leaf 没有 CRL，游戏在握手前断开）；
有效期 ≤2 天；签完立刻删 CA 私钥；目录里不能留多余私钥。
"""

import json
import socket
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hd2proxy.engine import certs

HOST = certs.DEFAULT_HOST


def _make(tmp_path, days=1):
    return certs.generate_session(tmp_path / "certs", host=HOST, days=days, force=True)


def test_generate_ca_session(tmp_path):
    report = _make(tmp_path)
    cert_dir = tmp_path / "certs"
    assert report["mode"] == "ca"
    assert report["self_check"] == "OK"
    assert report["stray_keys"] == []
    for name in ("anchor.pem", "anchor.cer", "ca.crl", "server.pem", "server.key",
                 "session.json"):
        assert (cert_dir / name).exists(), name
    info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    assert info["san_dns"] == [HOST]
    assert info["days"] <= 2
    assert not (cert_dir / "ca.key").exists(), "签完必须删 CA 私钥"


def test_cert_status_usable(tmp_path):
    _make(tmp_path)
    st = certs.cert_status(tmp_path / "certs")
    assert st["exists"] and st["usable"] is True
    assert st["mode"] == "ca"
    assert st["san"] == [HOST]
    assert 0 < st["remaining_hours"] <= 25
    assert st["warnings"] == []
    assert len(st["thumbprint"]) == 40


def test_cert_status_missing(tmp_path):
    st = certs.cert_status(tmp_path / "nope")
    assert st["exists"] is False and st["usable"] is False
    assert any("没有会话证书" in w for w in st["warnings"])


def test_cert_status_expired(tmp_path):
    _make(tmp_path)
    cert_dir = tmp_path / "certs"
    info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    info["not_after"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    (cert_dir / "session.json").write_text(json.dumps(info), encoding="utf-8")
    st = certs.cert_status(cert_dir)
    assert st["usable"] is False
    assert any("已过期" in w for w in st["warnings"])
    assert certs.session_remaining_hours(cert_dir) == 0.0


def test_cert_status_trust_check_untrusted(tmp_path, monkeypatch):
    """续期换了新 CA 但没重装信任 —— 这是本轮现场踩到的坑，状态里必须显式报出来。"""
    _make(tmp_path)
    from hd2proxy.engine import sysprobe
    monkeypatch.setattr(sysprobe, "cert_trusted", lambda thumb, scope: False)
    st = certs.cert_status(tmp_path / "certs", check_trust=True)
    assert st["trusted"] is False
    assert st["trust_scope"] is None
    assert any("未受信任" in w and "TLS" in w for w in st["warnings"])


def test_cert_status_trust_check_currentuser(tmp_path, monkeypatch):
    _make(tmp_path)
    from hd2proxy.engine import sysprobe
    monkeypatch.setattr(sysprobe, "cert_trusted", lambda thumb, scope: scope == "CurrentUser")
    st = certs.cert_status(tmp_path / "certs", check_trust=True)
    assert st["trusted"] is True and st["trust_scope"] == "CurrentUser"
    assert st["warnings"] == []


def test_cert_status_default_skips_trust_check(tmp_path, monkeypatch):
    """默认路径（控制面 /status 的 0.6s 热路径）绝不能 spawn certutil 查信任。"""
    _make(tmp_path)
    from hd2proxy.engine import sysprobe

    def boom(*a, **k):
        raise AssertionError("默认 cert_status 不该查信任")
    monkeypatch.setattr(sysprobe, "cert_trusted", boom)
    st = certs.cert_status(tmp_path / "certs")
    assert st["trusted"] is None and st["trust_scope"] is None


def test_ensure_session_reuses_when_fresh(tmp_path):
    _make(tmp_path)
    cert_dir = tmp_path / "certs"
    before = (cert_dir / "session.json").read_text(encoding="utf-8")
    result = certs.ensure_session(cert_dir, host=HOST, days=1, min_remaining_hours=12)
    assert result["action"] == "reused"
    assert (cert_dir / "session.json").read_text(encoding="utf-8") == before


def test_ensure_session_regenerates_when_expired(tmp_path):
    _make(tmp_path)
    cert_dir = tmp_path / "certs"
    info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    old_thumb = info["thumbprint_sha1"]
    info["not_after"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    (cert_dir / "session.json").write_text(json.dumps(info), encoding="utf-8")
    result = certs.ensure_session(cert_dir, host=HOST, days=1, min_remaining_hours=12)
    assert result["action"] == "generated"
    new_info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    assert new_info["thumbprint_sha1"] != old_thumb


def test_preflight_ok_and_rejects_bad(tmp_path):
    _make(tmp_path)
    cert_dir = tmp_path / "certs"
    assert certs.preflight(HOST, cert_dir) == []

    info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    info["days"] = 8                      # 超硬上限（7 天；v0.10.0 起 2~7 天合法）
    info["san_dns"] = ["example.com"]     # SAN 不符
    (cert_dir / "session.json").write_text(json.dumps(info), encoding="utf-8")
    problems = certs.preflight(HOST, cert_dir)
    assert any("硬上限" in p for p in problems)
    assert any("SAN" in p for p in problems)


def test_preflight_rejects_extra_private_key(tmp_path):
    _make(tmp_path)
    cert_dir = tmp_path / "certs"
    (cert_dir / "leaked.key").write_text("not a real key", encoding="utf-8")
    problems = certs.preflight(HOST, cert_dir)
    assert any("多余私钥" in p for p in problems)


def test_generate_refuses_stray_private_key(tmp_path):
    """目录里出现多余私钥时拒绝生成（不静默删除用户文件，也不留「能签任意域名」的钥匙）。

    注意：ca 模式从不把 CA 私钥写盘（只在内存里签完即 del），所以磁盘上的 ca.key 必是残留。
    """
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / "ca.key").write_text("stale", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stray_keys"):
        certs.generate_session(cert_dir, host=HOST, days=1, force=True)
    assert (cert_dir / "ca.key").read_text(encoding="utf-8") == "stale"   # 未被删除


@pytest.mark.parametrize("days", [1, 2])
def test_generate_days_within_cap(tmp_path, days):
    report = certs.generate_session(tmp_path / "c", host=HOST, days=days, force=True)
    assert report["days"] <= 2
    assert report["self_check"] == "OK"
    assert Path(tmp_path / "c" / "ca.crl").exists()


# ---- 有效期策略（v0.10.0-alpha.1）：默认 2 天 / 显式放宽到硬上限 7 天 -----------


def test_clamp_days_policy_and_hard_cap():
    """默认策略 2 天；显式 max_days 才放行；硬上限 7 天不可被参数突破。"""
    assert certs.MAX_DAYS_DEFAULT == 2
    assert certs.MAX_DAYS_HARD == 7
    assert certs.clamp_days(7, None) == 2      # 未显式设置策略 → 仍是默认 2 天
    assert certs.clamp_days(7, 7) == 7         # 显式设置 → 放行
    assert certs.clamp_days(99, 99) == 7       # 硬上限不可突破（不是只看 days<=max_days）
    assert certs.clamp_days(8, 7) == 7
    assert certs.effective_max_days(99) == 7
    assert certs.effective_max_days(0) == 1
    assert certs.clamp_days(0, 7) == 1


def test_generate_seven_days_when_explicit(tmp_path):
    report = certs.generate_session(tmp_path / "certs", host=HOST, days=7,
                                    max_days=7, force=True)
    assert 6.9 <= report["days"] <= 7.0
    assert report["self_check"] == "OK"
    assert not (tmp_path / "certs" / "ca.key").exists(), "签完必须删 CA 私钥"


def test_generate_default_still_two_days(tmp_path):
    """只传 days=7、不传 max_days（默认策略 2 天）→ 仍然只签 2 天。"""
    report = certs.generate_session(tmp_path / "certs", host=HOST, days=7, force=True)
    assert report["days"] <= 2


def test_preflight_accepts_seven_rejects_eight(tmp_path):
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=7, max_days=7, force=True)
    assert not [p for p in certs.preflight(HOST, cert_dir) if "硬上限" in p]

    sess = cert_dir / "session.json"
    info = json.loads(sess.read_text(encoding="utf-8"))
    info["days"] = 8
    sess.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    assert any("硬上限" in p for p in certs.preflight(HOST, cert_dir))


def test_ensure_session_seven_days(tmp_path):
    r = certs.ensure_session(tmp_path / "certs", host=HOST, days=7, max_days=7,
                             min_remaining_hours=12)
    assert r["action"] == "generated"
    assert r["remaining_hours"] > 24 * 6


def test_profile_cert_days_validation():
    from hd2proxy.engine import config
    ok, errors, _ = config.validate({"schema": 2, "name": "t", "cert": {"days": 7}})
    assert errors == []
    assert ok["cert"]["days"] == 7
    _, bad, _ = config.validate({"schema": 2, "name": "t", "cert": {"days": 8}})
    assert any("硬上限" in e for e in bad)
    assert config.default_profile()["cert"]["days"] == 2


# ---- CRL 端口（v0.11.0-alpha.3）：CDP 跟随端口 / 端口降级 / 绑不上不崩 ----------
#
# 现场（2026-11-27 用户报障）：8080 落在 Hyper-V/WSL/Docker 的保留端口段里，
# serve_crl 绑 127.0.0.1:8080 抛 PermissionError [WinError 10013]，
# 异常冒到 cmd_engine 把整个引擎带崩（GUI 弹「引擎启动失败」）。三条护栏都在这里钉死。


def _cdp_uris(pem_path):
    """读证书里的 CRL 分发点（CDP）URI 列表。"""
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(Path(pem_path).read_bytes())
    ext = cert.extensions.get_extension_for_class(x509.CRLDistributionPoints)
    return [n.value for d in ext.value for n in d.full_name]


def _occupy(port=0):
    """占住一个本机端口（返回 (sock, port)），模拟「8080 被保留段/别人挡住」。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(4)
    return s, s.getsockname()[1]


def test_cdp_url_follows_port():
    assert certs.cdp_url(8080) == "http://127.0.0.1:8080/ca.crl"
    assert certs.cdp_url(18080) == "http://127.0.0.1:18080/ca.crl"
    assert certs.cdp_url(0) == certs.cdp_url(certs.CDP_PORT_DEFAULT)   # 0/None → 默认端口
    assert certs.cdp_url(None) == certs.cdp_url(certs.CDP_PORT_DEFAULT)
    assert certs.CDP_PORT_DEFAULT == 8080
    assert 8080 not in certs.CRL_PORT_FALLBACKS          # 降级表不能把首选混进去


def test_certificates_carry_cdp_with_the_given_port(tmp_path):
    """换端口签出来的证书，CDP 必须指向新端口（叶子与 CA 都要有）。"""
    cert_dir = tmp_path / "certs"
    report = certs.generate_session(cert_dir, host=HOST, days=1, force=True, crl_port=18080)
    assert report["crl_port"] == 18080
    assert json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))["crl_port"] == 18080
    assert _cdp_uris(cert_dir / "server.pem") == ["http://127.0.0.1:18080/ca.crl"]
    assert _cdp_uris(cert_dir / "anchor.pem") == ["http://127.0.0.1:18080/ca.crl"]


def test_leaf_mode_has_no_cdp_by_design(tmp_path):
    """leaf 模式没有 CA 就没有 ca.crl：**故意不加 CDP**（加了只是指向 404）。

    这条钉住「不要把 leaf 也加 CDP」——那是本轮改动的反例，别再来一次。
    """
    from cryptography import x509
    cert_dir = tmp_path / "leafcerts"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True, mode="leaf",
                           crl_port=28080)
    cert = x509.load_pem_x509_certificate((cert_dir / "server.pem").read_bytes())
    with pytest.raises(x509.extensions.ExtensionNotFound):
        cert.extensions.get_extension_for_class(x509.CRLDistributionPoints)
    assert not (cert_dir / "ca.crl").exists()


def test_pick_crl_port_skips_blocked_preferred():
    busy, busy_port = _occupy()
    probe = _occupy()                 # 先占一个拿到端口号，再放掉当「空闲」备选
    probe[0].close()
    free_port = probe[1]
    try:
        picked, why = certs.pick_crl_port(busy_port, (free_port,))
        assert picked == free_port
        assert why and str(busy_port) in why, "降级必须说清首选为什么不可用（不能只印 None）"
    finally:
        busy.close()


def test_pick_crl_port_passes_through_when_preferred_free():
    probe = _occupy()
    probe[0].close()
    port = probe[1]
    picked, why = certs.pick_crl_port(port, (18080,))
    assert (picked, why) == (port, None), "首选可用时不该有降级原因"


def test_pick_crl_port_all_blocked_returns_none():
    busy, busy_port = _occupy()
    try:
        picked, err = certs.pick_crl_port(busy_port, (busy_port,))
        assert picked is None
        assert err and str(busy_port) in err
    finally:
        busy.close()


def test_serve_crl_returns_none_instead_of_raising(tmp_path):
    """★ 回归点：端口被占/被保留时 serve_crl 必须返回 None，绝不能再抛出去带崩引擎。"""
    certs.generate_session(tmp_path / "certs", host=HOST, days=1, force=True)
    busy, busy_port = _occupy()
    try:
        assert certs.serve_crl(tmp_path / "certs", busy_port) is None
    finally:
        busy.close()


def test_serve_crl_serves_the_crl(tmp_path):
    certs.generate_session(tmp_path / "certs", host=HOST, days=1, force=True)
    srv = certs.serve_crl(tmp_path / "certs", 0)          # 0 = 临时端口
    assert srv is not None
    try:
        port = srv.server_address[1]
        with urllib.request.urlopen("http://127.0.0.1:%d/ca.crl" % port, timeout=5) as r:
            assert r.status == 200
            assert r.read() == (tmp_path / "certs" / "ca.crl").read_bytes()
    finally:
        srv.shutdown()
        srv.server_close()


def test_existing_ok_rejects_port_change(tmp_path):
    """存下来的证书 CRL 端口和现在要用的不一致 → 视为不可用（强制重签）。"""
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True, crl_port=8080)
    assert certs.existing_ok(cert_dir, HOST, 1, crl_port=8080) is not None
    assert certs.existing_ok(cert_dir, HOST, 1, crl_port=18080) is None


def test_ensure_session_resigns_when_port_changes(tmp_path):
    cert_dir = tmp_path / "certs"
    first = certs.ensure_session(cert_dir, host=HOST, days=1, crl_port=8080)
    assert first["action"] == "generated"
    again = certs.ensure_session(cert_dir, host=HOST, days=1, crl_port=18080)
    assert again["action"] == "generated", "端口变了必须重签，否则证书 CDP 指向无人监听的端口"
    info = json.loads((cert_dir / "session.json").read_text(encoding="utf-8"))
    assert info["crl_port"] == 18080
    reused = certs.ensure_session(cert_dir, host=HOST, days=1, crl_port=18080)
    assert reused["action"] == "reused"


def test_resolve_crl_port_defaults():
    assert certs._resolve_crl_port(None) in ({certs.CDP_PORT_DEFAULT}
                                             | set(certs.CRL_PORT_FALLBACKS))
    assert certs._resolve_crl_port(18080) == 18080

