"""会话证书单测：ca 模式签发 / 状态快照 / 自动续期 / preflight。

关键约束（研究线实测）：只有 ca 模式能握手（leaf 没有 CRL，游戏在握手前断开）；
有效期 ≤2 天；签完立刻删 CA 私钥；目录里不能留多余私钥。
"""

import json
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
