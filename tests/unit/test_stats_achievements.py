"""G4 终身统计（Stats/profile）+ G5 成就上报 单测。

用 `data/fixtures/saves/{main,fresh}/stats_profile.json` 当事实底（主号有战绩 / 空号全 0），
外加构造场景（非数值字段、未知键、坏形状）。
"""

import json
from pathlib import Path

from hd2proxy.engine import active_save, saves
from hd2proxy.engine.hooks import achievements, stats

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves"
STEAM_A = "76561198968648344"


def _stats(account):
    return (FIXTURES / account / "stats_profile.json").read_bytes()


def _numbers(account):
    return json.loads(_stats(account))


def make_save(root, steam_id=STEAM_A, experience=1000):
    sid = saves.save_id_for(steam_id)
    st = saves.SaveStore(sid, root=root)
    doc = saves.empty_save(sid)
    doc["earned"]["experience"] = experience
    doc["identity"] = {"hd2_account_id": None, "steam_id": steam_id,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    st.save(doc)
    saves.write_last(sid, steam_id, None, root=root)
    return sid


# ---------------------------------------------------------------- 路径判定


def test_stats_path_matching():
    assert stats.is_stats_path("/api/Stats/profile/summary")
    assert stats.is_stats_path("/api/Stats/profile/801/summary")
    assert stats.is_stats_path("/api/Stats/profile/801/summary?x=1")
    assert not stats.is_stats_path("/api/Stats/war/801/summary")     # 战局统计：语义未证，不碰
    assert not stats.is_stats_path("/api/Stats/profile/summaryX")
    assert not stats.is_stats_path("")


def test_achievements_path_matching():
    assert achievements.is_path("/api/Progression/Achievements")
    assert achievements.is_path("/api/Progression/Achievements?x=1")
    assert not achievements.is_path("/api/Progression/Achievements/x")
    assert not achievements.is_path("/api/Progression")


# ---------------------------------------------------------------- Stats 纯函数


def test_apply_stats_raises_from_ledger():
    """主号战绩（存档）> 空号服务端（全 0）→ 逐 key 抬上去。"""
    doc = saves.empty_save("steam_76561198968648344")
    doc["earned"]["stats"] = {"profile": _numbers("main")}
    out, changed = saves.apply_to_stats(_stats("fresh"), doc)
    assert changed == 23          # 27 项里 4 项主号也是 0（无法"抬"）
    got = json.loads(out)
    assert got["totalEnemyKills"] == 356065 and got["totalBugKills"] == 206358


def test_apply_stats_never_lowers():
    """服务端值更大时保持服务端（只抬不降）。"""
    doc = saves.empty_save("steam_76561198968648344")
    doc["earned"]["stats"] = {"profile": _numbers("fresh")}
    body = _stats("main")
    out, changed = saves.apply_to_stats(body, doc)
    assert changed == 0 and out is body


def test_apply_stats_ignores_unknown_and_non_numeric():
    doc = saves.empty_save()
    doc["earned"]["stats"] = {"profile": {"totalEnemyKills": 999999,
                                          "notInResponse": 5,
                                          "flagTrue": True}}
    body = json.dumps({"totalEnemyKills": 1, "flagTrue": False, "name": "x"}).encode()
    out, changed = saves.apply_to_stats(body, doc)
    got = json.loads(out)
    assert changed == 1 and got["totalEnemyKills"] == 999999
    assert "notInResponse" not in got          # 不往响应里凭空加字段
    assert got["flagTrue"] is False            # bool 不当数值


def test_stats_profile_of_compat_shapes():
    assert saves.stats_profile_of({}) == {}
    nested = {"earned": {"stats": {"profile": {"a": 1}}}}
    assert saves.stats_profile_of(nested) == {"a": 1}
    legacy = {"earned": {"stats": {"b": 2}}}   # 老档/手改档：stats 直接是数值字典
    assert saves.stats_profile_of(legacy) == {"b": 2}
    assert saves.stats_profile_of({"earned": {"stats": {"profile": {}}}}) == {}


def test_merge_stats_into_picks_max_per_key():
    # _merge_earned_into 吃**整份存档文档**（adopt_identity 的迁移路径）
    dst = {"save_id": "steam_a", "earned": {"stats": {"profile": {"a": 5, "b": 1}}}}
    src = {"save_id": "local", "earned": {"stats": {"profile": {"a": 3, "b": 9}}}}
    merged = saves._merge_earned_into(dst, src)
    assert merged["stats"]["profile"] == {"a": 5, "b": 9}


# ---------------------------------------------------------------- Stats 记录（ActiveSave）


def test_record_stats_records_and_marks_dirty(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_stats(_stats("main"))
    assert out["ok"] is True and out["recorded"] == 27
    got = saves.stats_profile_of(saves.SaveStore(sid, root=tmp_path).load())
    assert got["totalEnemyKills"] == 356065
    assert mgr.session_dirty is True
    assert any(e["kind"] == "stats" for e in mgr.status()["events"])
    mgr.close()


def test_record_stats_all_zero_is_skipped(tmp_path):
    """空号首局全 0：没有信息量，不写盘（不刷 .bak / 不置 dirty）。"""
    sid = make_save(tmp_path)
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_stats(_stats("fresh"))
    assert out["ok"] is True and out["skipped"] == "all-zero"
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    mgr.close()


def test_record_stats_never_lowers(tmp_path):
    sid = make_save(tmp_path)
    st = saves.SaveStore(sid, root=tmp_path)
    doc = st.load()
    doc["earned"]["stats"] = {"profile": _numbers("main")}
    st.save(doc)
    before = st.path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_stats(_stats("fresh"))       # 服务端全 0 → 不降级、不写盘
    assert out["ok"] is True and out["recorded"] == 0
    assert mgr.session_dirty is False
    assert st.path().read_bytes() == before
    mgr.close()


def test_record_stats_bad_body(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.record_stats(b"not json")["ok"] is False
    assert mgr.record_stats(json.dumps({"name": "x"}).encode())["ok"] is False
    assert mgr.session_dirty is False
    mgr.close()


def test_apply_stats_after_record_roundtrip(tmp_path):
    """记录 → 下一次启动时把空号服务端的 0 抬成存档战绩（重启后可见）。"""
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_stats(_stats("main"))
    mgr.close()

    mgr2 = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr2.start()
    out, changed = mgr2.apply_stats(_stats("fresh"))
    assert changed == 23
    assert json.loads(out)["totalEnemyKills"] == 356065
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 1000
    mgr2.close()


# ---------------------------------------------------------------- 成就上报（G5）


def test_extract_achievements_shapes():
    rows = [{"id": 1, "value": 5}, {"id": 2, "value": 3}]
    for body in ({"achievements": rows}, rows, {"items": rows}, {"values": rows}):
        assert achievements.extract_achievements(json.dumps(body).encode()) == {"1": 5, "2": 3}
    # 同 id 取大、坏行跳过、负值跳过
    body = {"achievements": [{"id": 1, "value": 2}, {"id": 1, "value": 7},
                            {"id": "x", "value": 1}, {"id": 3, "value": -1},
                            {"id": 4}, "junk", {"value": 9}]}
    assert achievements.extract_achievements(json.dumps(body).encode()) == {"1": 7}


def test_extract_achievements_unknown_shape():
    for body in (b"not json", b"{}", b'{"foo": 1}', json.dumps([1, 2]).encode(), b"", None):
        assert achievements.extract_achievements(body) == {}


def test_record_achievements_per_key_max(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_achievements(json.dumps(
        {"achievements": [{"id": 6, "value": 1679}, {"id": 8, "value": 386201}]}).encode())
    assert out["ok"] is True and out["recorded"] == 2
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["achievements"] == {
        "6": 1679, "8": 386201}

    # 旧快照把值改小 → per-key max 不会降级，也不写盘
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    mgr.session_dirty = False
    out2 = mgr.record_achievements(json.dumps(
        {"achievements": [{"id": 6, "value": 100}, {"id": 8, "value": 386201}]}).encode())
    assert out2["ok"] is True and out2["recorded"] == 0
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["achievements"]["6"] == 1679
    mgr.close()


def test_record_achievements_unparsed_does_not_write(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    out = mgr.record_achievements(b'{"unknownShell": [{"x": 1}]}')
    assert out["ok"] is False and out["reason"] == "unparsed"
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    mgr.close()


def test_record_achievements_strict_refused(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, strict=True, run_id="r1")
    mgr.start()
    mgr.record_achievements(json.dumps({"achievements": [{"id": 1, "value": 5}]}).encode())
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["achievements"] == {}
    assert mgr.session_dirty is False
    mgr.close()


def test_achievements_roundtrip_into_progression(tmp_path):
    """上报 → 存进 earned；下次启动的 `/api/Progression` 合并应把它抬进响应（G2 钩子）。"""
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_achievements(json.dumps(
        {"achievements": [{"id": 6, "value": 1679}]}).encode())
    mgr.close()

    body = json.dumps({"experience": 0, "achievements": [{"id": 6, "value": 100}],
                       "packageProgress": [], "purchasedSeasonPassItems": []}).encode()
    mgr2 = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr2.start()
    out, changed = mgr2.apply_progression(body)
    got = json.loads(out)
    assert changed >= 1 and got["achievements"][0]["value"] == 1679
    mgr2.close()
