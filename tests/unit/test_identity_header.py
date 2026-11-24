"""v0.7.0 身份头（自建服按玩家分档）：ActiveSave.identity_header() + 引擎盖章纯函数。"""

import json

from hd2proxy.engine import active_save, saves
from hd2proxy.engine.server import stamp_identity_header

STEAM_A = "76561198968648344"
STEAM_B = "76561199881579811"
HD2_A = "13887067702231565058"


def _make_save(root, steam_id=STEAM_A, hd2=HD2_A):
    sid = saves.save_id_for(steam_id)
    st = saves.SaveStore(sid, root=root)
    doc = saves.empty_save(sid)
    doc["identity"] = {"hd2_account_id": hd2, "steam_id": steam_id,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    st.save(doc)
    saves.write_last(sid, steam_id, hd2, root=root)
    return sid


# ---------------------------------------------------------------- ActiveSave


def test_identity_header_prebind_before_getmotd(tmp_path):
    _make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.identity_header() == (STEAM_A, "prebind")
    mgr.close()


def test_identity_header_after_getmotd_is_authoritative(tmp_path):
    _make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_A)
    assert mgr.identity_header() == (STEAM_A, "getmotd")
    mgr.close()


def test_identity_header_tracks_account_switch(tmp_path):
    _make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_B)
    assert mgr.identity_header() == (STEAM_B, "getmotd")
    mgr.on_getmessages(HD2_A)          # 别名到达：值仍优先 SteamID64
    assert mgr.identity_header() == (STEAM_B, "getmotd")
    mgr.close()


def test_identity_header_hd2_only_source(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()                        # 无 _last → local
    assert mgr.identity_header() is None
    mgr.on_getmessages(HD2_A)
    value, source = mgr.identity_header()
    assert value == HD2_A and source == "getmessages"
    mgr.close()


def test_identity_header_none_without_identity(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.identity_header() is None
    mgr.close()


# ---------------------------------------------------------------- 盖章纯函数


def test_stamp_identity_header_adds_two_lines():
    lines = [b"GET /api/Progression HTTP/1.1", b"Host: api.live.prod.thehelldiversgame.com"]
    out = stamp_identity_header(lines, (STEAM_A, "prebind"))
    assert out[:2] == lines                      # 原头保留
    assert b"X-HD2-Account: " + STEAM_A.encode() in out
    assert b"X-HD2-Account-Source: prebind" in out
    assert len(out) == len(lines) + 2
    assert lines == [b"GET /api/Progression HTTP/1.1",
                     b"Host: api.live.prod.thehelldiversgame.com"]   # 不改入参


def test_stamp_identity_header_skips_when_client_already_sent():
    """客户端 lobby 请求自带 X-HD2-Account → 引擎不重复加（多值头会让服务端取错）。"""
    lines = [b"PUT /api/lobby HTTP/1.1", b"X-HD2-Account: " + STEAM_A.encode()]
    assert stamp_identity_header(lines, (STEAM_B, "getmotd"), has_account=True) is lines


def test_stamp_identity_header_noop_without_identity():
    lines = [b"GET / HTTP/1.1"]
    assert stamp_identity_header(lines, None) is lines


def test_stamp_identity_header_uncertain_sends_only_source():
    """uncertain：只发 Source 头（不发 Account），自建服据此跳过 IP 兜底。"""
    lines = [b"GET /api/Progression HTTP/1.1"]
    out = stamp_identity_header(lines, ("", "uncertain"))
    assert out == lines + [b"X-HD2-Account-Source: uncertain"]
    assert not any(x.startswith(b"X-HD2-Account: ") for x in out)


def test_stamp_identity_header_uncertain_skipped_when_client_has_account():
    lines = [b"PUT /api/lobby HTTP/1.1", b"X-HD2-Account: " + STEAM_A.encode()]
    assert stamp_identity_header(lines, ("", "uncertain"), has_account=True) is lines


def test_identity_header_stops_after_getmotd_failure(tmp_path, monkeypatch):
    """研究线建议：GetMotd 到了却没校验成功 → 宁可不盖身份头（自建服回落公共数据更安全）。"""
    _make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.identity_header() == (STEAM_A, "prebind")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(active_save.saves, "save_id_for_identity", boom)
    info = mgr.on_getmotd(STEAM_A)
    assert info["ok"] is False and info["action"] == "error"
    # v0.7.0-alpha.3：不再断言账号，但发 source=uncertain 让自建服跳过 IP 兜底、回落公共数据
    assert mgr.identity_header() == ("", "uncertain")
    assert any(e["kind"] == "identity-uncertain" for e in mgr.status()["events"])
    mgr.close()


def test_identity_header_still_works_after_normal_getmotd(tmp_path):
    _make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_A)
    assert mgr.identity_header() == (STEAM_A, "getmotd")
    mgr.close()
