"""G6 存档预演（`engine/save_preview.py`）单测。

全部离线：存档用 tmp 目录注入，样本用 `data/fixtures/saves/` 的真实抓包。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import save_preview, saves

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves"
STEAM_A = "76561198968648344"


def make_doc(experience=2760000, enemy_kills=999999, mix_amount=800):
    sid = saves.save_id_for(STEAM_A)
    doc = saves.empty_save(sid)
    doc["earned"]["experience"] = experience
    doc["earned"]["stats"] = {"profile": {"totalEnemyKills": enemy_kills}}
    doc["earned"]["inventory_amounts"] = {"3901895556": mix_amount}
    doc["earned"]["achievements"] = {"6": 5000}
    doc["identity"] = {"hd2_account_id": None, "steam_id": STEAM_A,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    doc["catalog_build"] = "93e7575a/3021/1007203"
    return doc


# ---------------------------------------------------------------- 载入


def test_load_save_from_last(tmp_path):
    sid = saves.save_id_for(STEAM_A)
    st = saves.SaveStore(sid, root=tmp_path)
    st.save(make_doc(experience=4321))
    saves.write_last(sid, STEAM_A, None, root=tmp_path)
    doc, source = save_preview.load_save(root=tmp_path)
    assert doc["save_id"] == sid and doc["earned"]["experience"] == 4321
    assert "_last.json" in source and sid in source


def test_load_save_explicit_id_and_missing(tmp_path):
    sid = saves.save_id_for(STEAM_A)
    saves.SaveStore(sid, root=tmp_path).save(make_doc(experience=99))
    doc, source = save_preview.load_save(save_id=sid, root=tmp_path)
    assert doc["earned"]["experience"] == 99 and "指定" in source

    # 全新的空目录：没有 _last.json、也没有档 → local 空档
    empty_root = tmp_path / "empty"
    empty, source2 = save_preview.load_save(root=empty_root)
    assert empty["save_id"] == "local" and empty["earned"]["experience"] == 0
    assert "local" in source2


def test_load_save_from_file_and_broken(tmp_path):
    path = tmp_path / "my_save.json"
    path.write_text(json.dumps(make_doc(experience=777)), encoding="utf-8")
    doc, source = save_preview.load_save(save_file=str(path))
    assert doc["earned"]["experience"] == 777 and "文件" in source

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    doc2, source2 = save_preview.load_save(save_file=str(bad))
    assert doc2["earned"]["experience"] == 0 and "读取失败" in source2


# ---------------------------------------------------------------- 摘要 / 合并


def test_summarize_save():
    info = save_preview.summarize_save(make_doc())
    assert info["experience"] == 2760000
    assert info["achievements"] == 1 and info["stats_fields"] == 1
    assert info["inventory_amounts"] == 1
    assert info["identity"]["steam_id"] == STEAM_A
    assert info["catalog_build"] == "93e7575a/3021/1007203"
    assert info["missions_count"] == 0
    assert save_preview.summarize_save(saves.empty_save())["experience"] == 0


def test_preview_merges_all_three_kinds():
    result = save_preview.preview(save_doc=make_doc())
    main = result["merge"]["main"]
    # Progression 根：经验被抬高（2760000 > main 2759938）+ 成就合并
    assert main["progression"]["applied"] is True
    fields = {d["field"]: d for d in main["progression"]["diffs"]}
    assert fields["experience"]["after"] == 2760000
    # Stats：主号 356065 → 存档 999999
    assert main["stats_profile"]["applied"] is True
    assert {d["field"]: d["after"] for d in main["stats_profile"]["diffs"]}[
        "totalEnemyKills"] == 999999
    # 库存：mixId 行级差异（3901895556 在 main 里是多少→800）
    assert main["inventory"]["applied"] is True
    assert any(d["mixId"] == 3901895556 for d in main["inventory"]["diffs"])


def test_preview_empty_save_changes_nothing():
    result = save_preview.preview(save_doc=saves.empty_save())
    for account in ("main", "fresh"):
        for name, info in result["merge"][account].items():
            assert info["applied"] is False, (account, name)


def test_preview_mission_projection():
    result = save_preview.preview(save_doc=make_doc())
    mission = result["missions"][0]
    assert mission["ok"] is True and mission["label"] == "12b9a872.json"
    assert mission["experience_delta"] == 936
    assert mission["experience_before"] == 2760000
    assert mission["experience_after"] == 2760936
    items = {d["mixId"]: d for d in mission["item_delta"]}
    assert items["3608481516"]["amount"] == 4434
    assert items["3608481516"]["after"] == 4434
    assert mission["packages"] == {"277818845": {"level": 5, "progress": 459}}
    assert "repeatingPlayer" in mission["unknown_keys"]


def test_preview_mission_accumulates_on_existing_amounts():
    doc = make_doc()
    doc["earned"]["inventory_amounts"]["3608481516"] = 100
    mission = save_preview.preview(save_doc=doc)["missions"][0]
    items = {d["mixId"]: d for d in mission["item_delta"]}
    assert items["3608481516"]["before"] == 100 and items["3608481516"]["after"] == 4534


def test_preview_missing_fixtures_dir(tmp_path):
    result = save_preview.preview(save_doc=make_doc(), base_dir=str(tmp_path / "nope"))
    assert result["merge"] == {} and result["warnings"]
    assert "不存在" in result["warnings"][0]


def test_preview_selected_mission(tmp_path):
    result = save_preview.preview(save_doc=make_doc(), mission_names=["e899f6af.json"])
    mission = result["missions"][0]
    assert mission["label"] == "e899f6af.json" and mission["experience_delta"] == 0


# ---------------------------------------------------------------- 人读文本


def test_format_text_contains_key_sections():
    text = save_preview.format_text(save_preview.preview(save_doc=make_doc()))
    assert "存档预演" in text and "saveId=steam_" in text
    assert "合并到 main/ 样本" in text
    assert "Progression 根" in text and "Stats/profile" in text
    assert "模拟一局结算（12b9a872.json）" in text
    assert "经验 +936" in text
    assert "未消费字段" in text


def test_format_text_empty_save():
    text = save_preview.format_text(save_preview.preview(save_doc=saves.empty_save()))
    assert "未识别（local 档）" in text
    assert "无改动" in text
    assert "经验 +936" in text          # 空档也能模拟结算后长多少


def test_format_text_missing_fixtures(tmp_path):
    result = save_preview.preview(save_doc=make_doc(), base_dir=str(tmp_path / "none"))
    assert "注意：" in save_preview.format_text(result)
