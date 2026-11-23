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
