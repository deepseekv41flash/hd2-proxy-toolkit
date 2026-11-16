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
    info["days"] = 5                      # 超硬上限
    info["san_dns"] = ["example.com"]     # SAN 不符
    (cert_dir / "session.json").write_text(json.dumps(info), encoding="utf-8")
    problems = certs.preflight(HOST, cert_dir)
    assert any("有效期过长" in p for p in problems)
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
