"""存档层底座（G1）单测：持久化 / 损坏回退 / 合并语义。

全部离线：不依赖引擎、不依赖游戏；存档根目录用 tmp_path 注入。
"""

import json

import pytest

from hd2proxy.engine import saves


# ---------------------------------------------------------------- 基础


def test_empty_save_shape():
    doc = saves.empty_save("abc")
    assert doc["schema"] == saves.SAVE_SCHEMA
    assert doc["save_id"] == "abc"
    e = doc["earned"]
    assert e["experience"] == 0
    assert e["achievements"] == {} and e["inventory_amounts"] == {}
    assert e["inventory_ids"] == []


def test_normal_save_id_rejects_bad():
    assert saves.normal_save_id("local") == "local"
    assert saves.normal_save_id("p-01_x") == "p-01_x"
    assert saves.normal_save_id("../etc/passwd") == saves.DEFAULT_SAVE_ID
    assert saves.normal_save_id("") == saves.DEFAULT_SAVE_ID
    assert saves.normal_save_id("a" * 65) == saves.DEFAULT_SAVE_ID


# ---------------------------------------------------------------- 持久化


def test_store_roundtrip(tmp_path):
    st = saves.SaveStore("s1", root=tmp_path)
    assert st.load()["save_id"] == "s1" and st.load()["earned"]["experience"] == 0
    st.add_experience(936)
    st.grant_items({"3901895556": 699}, ids=[1945105139])
    doc = st.load()
    assert doc["earned"]["experience"] == 936
    assert doc["earned"]["inventory_amounts"]["3901895556"] == 699
    assert 1945105139 in doc["earned"]["inventory_ids"]
    assert json.loads(st.path().read_text(encoding="utf-8"))["schema"] == saves.SAVE_SCHEMA


def test_store_backup_on_second_write(tmp_path):
    st = saves.SaveStore("s1", root=tmp_path)
    st.add_experience(10)
    st.add_experience(5)
    bak = tmp_path / "s1.json.bak"
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8"))["earned"]["experience"] == 10
    assert st.load()["earned"]["experience"] == 15


def test_corrupt_file_quarantined_and_falls_back(tmp_path):
    st = saves.SaveStore("s1", root=tmp_path)
    (tmp_path / "s1.json").write_text("{ not json", encoding="utf-8")
    doc = st.load()
    assert doc["earned"]["experience"] == 0          # 回退空档，不抛异常
    assert list(tmp_path.glob("s1.corrupt-*"))       # 现场保留


def test_unknown_schema_quarantined(tmp_path):
    st = saves.SaveStore("s1", root=tmp_path)
    st.path().write_text(json.dumps({"schema": 99, "earned": {}}), encoding="utf-8")
    assert st.load()["earned"]["experience"] == 0
    assert list(tmp_path.glob("s1.corrupt-*"))


def test_grant_items_keeps_max_and_reset(tmp_path):
    st = saves.SaveStore(root=tmp_path)
    st.grant_items({"111": 5})
    st.grant_items({"111": 3})              # 不回退
    assert st.load()["earned"]["inventory_amounts"]["111"] == 5
    st.reset()
    assert st.load()["earned"]["inventory_amounts"] == {}


# ---------------------------------------------------------------- 合并：Progression


def _progression():
    return {
        "experience": 1,
        "onboardingFlags": 0,
        "onboardingState": 0,
        "shipName": [],
        "location": {"warId": 801, "planetIndex": 0},
        "purchasedSeasonPassItems": [510],
        "achievements": [{"id": 6, "value": 10}],
        "packageProgress": [{"id32": 100, "level": 1, "progress": 2, "sortOrder": 0,
                             "claimedLevels": [1]}],
    }


def _save_with_earned(**earned):
    doc = saves.empty_save()
    doc["earned"].update(earned)
    return doc


def test_apply_progression_merges_all_fields():
    body = json.dumps(_progression()).encode("utf-8")
    save = _save_with_earned(experience=936, onboarding_flags=1, onboarding_state=128,
                             ship_name=[7, 47],
                             location={"warId": 801, "planetIndex": 5},
                             purchased_season_pass_items=[510, 511],
                             achievements={"6": 20, "7": 3},
                             package_progress={"100": {"level": 2, "progress": 9,
                                                       "claimedLevels": [2]}})
    out, changed = saves.apply_to_progression(body, save)
    doc = json.loads(out)
    assert changed > 0
    assert doc["experience"] == 936
    assert doc["onboardingFlags"] == 1 and doc["onboardingState"] == 128
    assert doc["shipName"] == [7, 47]
    assert doc["location"]["planetIndex"] == 5
    assert doc["purchasedSeasonPassItems"] == [510, 511]
    ids = {a["id"]: a["value"] for a in doc["achievements"]}
    assert ids == {6: 20, 7: 3}
    pkg = doc["packageProgress"][0]
    assert pkg["level"] == 2 and pkg["progress"] == 9
    assert sorted(pkg["claimedLevels"]) == [1, 2]


def test_apply_progression_noop_returns_same_body():
    body = json.dumps(_progression()).encode("utf-8")
    out, changed = saves.apply_to_progression(body, saves.empty_save())
    assert changed == 0
    assert out is body                       # 未改动时不重编码（省一次序列化）


def test_apply_progression_never_lowers_existing():
    body = json.dumps(dict(_progression(), experience=2759938)).encode("utf-8")
    out, changed = saves.apply_to_progression(body, _save_with_earned(experience=936))
    assert changed == 0 and json.loads(out)["experience"] == 2759938


def test_apply_progression_accepts_dict_and_bad_body():
    doc = _progression()
    out, changed = saves.apply_to_progression(doc, _save_with_earned(experience=5))
    assert isinstance(out, dict) and out["experience"] == 5 and changed >= 1
    bad = b"{ not json"
    assert saves.apply_to_progression(bad, _save_with_earned(experience=5)) == (bad, 0)


# ---------------------------------------------------------------- 合并：Inventory


def _inventory():
    return {"items": [{"mixId": 111, "amount": 2, "isDiscovered": False},
                      {"mixId": 3901895556, "amount": 699, "isDiscovered": False}]}


def test_apply_inventory_overwrites_amount_and_appends():
    save = _save_with_earned(inventory_amounts={"3901895556": 500, "222": 3},
                             inventory_ids=[333])
    out, changed = saves.apply_to_inventory(json.dumps(_inventory()).encode("utf-8"), save)
    items = {i["mixId"]: i["amount"] for i in json.loads(out)["items"]}
    assert items[3901895556] == 500          # 绝对数量覆盖（consume 会往下减）
    assert items[222] == 3 and items[333] == 1
    assert changed >= 2


def test_apply_inventory_noop():
    body = json.dumps(_inventory()).encode("utf-8")
    out, changed = saves.apply_to_inventory(body, saves.empty_save())
    assert changed == 0 and out is body


def test_apply_inventory_skips_bad_entries():
    save = _save_with_earned(inventory_amounts={"bad": 5, "111": 9})
    out, changed = saves.apply_to_inventory({"items": [{"mixId": 111, "amount": 9}]}, save)
    assert changed == 0 and out["items"][0]["amount"] == 9


# ---------------------------------------------------------------- 更新器


def test_earned_normalized_on_load(tmp_path):
    st = saves.SaveStore("s1", root=tmp_path)
    st.path().parent.mkdir(parents=True, exist_ok=True)
    st.path().write_text(json.dumps({"schema": saves.SAVE_SCHEMA, "save_id": "s1",
                                     "earned": {"experience": 7}}), encoding="utf-8")
    doc = st.load()
    assert doc["earned"]["experience"] == 7
    assert doc["earned"]["inventory_amounts"] == {}   # 老/残缺档会被补齐


# ---------------------------------------------------------------- 身份 / 目录追溯（v2）

def test_save_id_for_steam_primary():
    # SteamID64 为主键（每会话稳定）；HD2 20 位 id 只作别名
    assert saves.save_id_for("76561199881579811") == "steam_76561199881579811"
    assert saves.save_id_for(None, "13887067702231565058") == "hd2_13887067702231565058"
    assert saves.save_id_for("76561199881579811", "13887067702231565058") ==         "steam_76561199881579811"
    assert saves.save_id_for() == saves.DEFAULT_SAVE_ID
    assert saves.save_id_for("abc123", "bad") == saves.DEFAULT_SAVE_ID


def test_save_schema_has_catalog_build_and_identity():
    doc = saves.empty_save()
    assert doc["catalog_build"] is None
    assert doc["identity"] == {"hd2_account_id": None, "steam_id": None}


def test_catalog_build_id_matches_handoff_evidence():
    """口径：<items_sha8>/<rows>/<clientVersion>；实测目录样例 d71655e6/3020。"""
    body = b'{"items": [{"mixId": 1}, {"mixId": 2}, {"mixId": 3}]}'
    info = saves.catalog_build_id(body, "1007203")
    assert len(info["sha8"]) == 8 and info["rows"] == 3
    assert info["value"] == "%s/3/1007203" % info["sha8"]
    # list 形态也支持；没有 clientVersion 时末段留空
    info2 = saves.catalog_build_id([{"a": 1}])
    assert info2["rows"] == 1 and info2["value"].endswith("/1/-")   # 缺 clientVersion 写 "-"


def test_store_record_catalog_and_identity(tmp_path):
    st = saves.SaveStore(root=tmp_path)
    info = st.record_catalog(b'{"items": [{"mixId": 1}]}', "1007203")
    st.bind_identity("13887067702231565058", "76561199881579811")
    doc = st.load()
    assert doc["catalog_build"] == info["value"]
    assert doc["identity"]["hd2_account_id"] == "13887067702231565058"
    assert doc["identity"]["steam_id"] == "76561199881579811"


def test_adopt_identity_migrates_local_content(tmp_path):
    local = saves.SaveStore(root=tmp_path)
    local.add_experience(936)
    migrated = local.adopt_identity(steam_id="76561199881579811", root=tmp_path)
    assert migrated.save_id == "steam_76561199881579811"
    doc = migrated.load()
    assert doc["earned"]["experience"] == 936
    assert doc["identity"]["steam_id"] == "76561199881579811"
    assert list(tmp_path.glob("local.merged-*.json"))


def test_adopt_identity_merges_when_target_exists(tmp_path):
    """目标档已存在也要合并（earned 取并/金额取大），绝不静默丢进度。"""
    target = saves.SaveStore("steam_76561199881579811", root=tmp_path)
    target.add_experience(50)
    target.grant_items({"111": 2})
    local = saves.SaveStore(root=tmp_path)
    local.add_experience(936)
    local.grant_items({"111": 5, "222": 1})
    merged = local.adopt_identity(steam_id="76561199881579811",
                                  hd2_account="13887067702231565058", root=tmp_path)
    doc = merged.load()
    assert doc["earned"]["experience"] == 936          # 取大
    assert doc["earned"]["inventory_amounts"]["111"] == 5
    assert doc["earned"]["inventory_amounts"]["222"] == 1
    assert doc["identity"]["hd2_account_id"] == "13887067702231565058"


def test_adopt_identity_skips_empty_local(tmp_path):
    local = saves.SaveStore(root=tmp_path)
    migrated = local.adopt_identity(steam_id="76561199881579811", root=tmp_path)
    assert migrated.save_id == "steam_76561199881579811"
    assert migrated.load()["earned"]["experience"] == 0
    assert not list(tmp_path.glob("local.merged-*.json"))


# ---------------------------------------------------------------- 时序：_last 指针 / HD2 反查 / 合并语义

def test_save_updates_last_pointer(tmp_path):
    st = saves.SaveStore(root=tmp_path)
    st.add_experience(10)
    last = saves.read_last(root=tmp_path)
    assert last["last_save_id"] == saves.DEFAULT_SAVE_ID
    assert last["updated_at"]


def test_write_read_last_roundtrip(tmp_path):
    saves.write_last("steam_76561199881579811", "76561199881579811",
                     "13887067702231565058", root=tmp_path)
    last = saves.read_last(root=tmp_path)
    assert last["last_save_id"] == "steam_76561199881579811"
    assert last["last_hd2_account_id"] == "13887067702231565058"
    (tmp_path / saves.LAST_FILE).write_text("{ bad", encoding="utf-8")
    assert saves.read_last(root=tmp_path) == {}


def test_find_save_by_hd2_scans_save_files(tmp_path):
    st = saves.SaveStore("steam_76561199881579811", root=tmp_path)
    st.set_identity("13887067702231565058", "76561199881579811")
    assert saves.find_save_by_hd2("13887067702231565058", root=tmp_path) ==         "steam_76561199881579811"
    assert saves.find_save_by_hd2("999", root=tmp_path) == ""
    # 归档/备份文件不参与反查
    (tmp_path / "steam_76561199881579811.merged-20260101-000000.json").write_text(
        json.dumps({"save_id": "old", "identity": {"hd2_account_id": "111"}}), encoding="utf-8")
    assert saves.find_save_by_hd2("111", root=tmp_path) == ""


def test_save_id_for_identity_uses_hd2_reverse_lookup(tmp_path):
    st = saves.SaveStore("steam_76561199881579811", root=tmp_path)
    st.set_identity("13887067702231565058")
    assert saves.save_id_for_identity(None, "13887067702231565058", root=tmp_path) ==         "steam_76561199881579811"
    assert saves.save_id_for_identity(None, "12345678901234567890", root=tmp_path) ==         "hd2_12345678901234567890"


def test_merge_consumables_newer_wins_and_scalars_max(tmp_path):
    """可消耗量按 updated_at 较新档为准（不能取 max 复活花掉的钱）；单调量取大。"""
    older = {"save_id": "a", "updated_at": "2026-11-01T00:00:00",
             "earned": {"experience": 500, "inventory_amounts": {"1": 999},
                        "achievements": {"6": 10}}}
    newer = {"save_id": "b", "updated_at": "2026-11-02T00:00:00",
             "earned": {"experience": 100, "inventory_amounts": {"1": 50},
                        "achievements": {"6": 5}}}
    merged = saves._merge_earned_into(dict(older), newer)
    assert merged["experience"] == 500          # 单调量取大
    assert merged["achievements"]["6"] == 10    # 单调量取大
    assert merged["inventory_amounts"]["1"] == 50   # 较新档为准（未被 max 复活）
    # 反向：dst 较新时保留 dst 的金额
    merged2 = saves._merge_earned_into(dict(newer), older)
    assert merged2["inventory_amounts"]["1"] == 50
    assert merged2["achievements"]["6"] == 10


# ---------------------------------------------------------------- 换号切档（研究线口径）

def test_is_identified():
    assert saves.is_identified({"save_id": "local"}) is False
    assert saves.is_identified({"save_id": "steam_76561199881579811"}) is True
    assert saves.is_identified({}) is False


def test_switch_identity_merges_from_local(tmp_path):
    local = saves.SaveStore(root=tmp_path)
    local.add_experience(120)
    res = saves.switch_identity(local, steam_id="76561199881579811", root=tmp_path)
    assert res["action"] == "merged" and res["old_identified"] is False
    assert res["store"].load()["earned"]["experience"] == 120


def test_switch_identity_does_not_merge_two_identified_saves(tmp_path):
    old = saves.SaveStore("steam_11111111111111111", root=tmp_path)
    old.add_experience(999)
    old.grant_items({"111": 7})
    before = old.path().read_text(encoding="utf-8")
    res = saves.switch_identity(old, steam_id="76561199881579811", root=tmp_path)
    assert res["action"] == "switched" and res["old_identified"] is True
    assert res["store"].save_id == "steam_76561199881579811"
    assert old.path().read_text(encoding="utf-8") == before      # 旧档一个字节都不动
    assert res["store"].load()["earned"]["experience"] == 0     # 不合并
    assert saves.read_last(root=tmp_path)["last_save_id"] == "steam_76561199881579811"


def test_rollback_from_backup_restores_and_archives(tmp_path):
    st = saves.SaveStore(root=tmp_path)
    st.add_experience(10)          # 第一版 -> 成为 .bak（第二次写时）
    st.add_experience(20)          # 第二版（当前）
    assert st.load()["earned"]["experience"] == 30
    assert saves.rollback_from_backup(st) is True
    assert st.load()["earned"]["experience"] == 10
    assert list(tmp_path.glob("local.rollback-*.json"))


def test_write_orphan_under_orphan_dir(tmp_path):
    p = saves.write_orphan("local", {"earned": {"experience": 5}}, root=tmp_path)
    assert p and "_orphan" in p
    import json as _json
    assert _json.loads(open(p, encoding="utf-8").read())["earned"]["experience"] == 5
    # _orphan 目录不参与 HD2 反查
    assert saves.find_save_by_hd2("123", root=tmp_path) == ""
