"""离线预演（engine/preview.py）单测。

覆盖六项核心能力在样本上的增量：变种词条 / 全局效果 / 星球效果 / 休眠星四件套 / 生态借用 /
物品解锁 / 物品目录 / L2 改装；以及「空 profile → 0 改动」「直通模式给警告」
「样本缺失/未知样本不崩」「预演不写日志」这些边界。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import config, logutil, paths, preview

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def _profile(**sections):
    """默认 profile + 指定段覆盖（passthrough 默认关掉，预演要看增量）。"""
    prof = config.default_profile()
    prof["proxy"]["passthrough"] = False
    for key, value in sections.items():
        prof[key] = value
    return prof


def _counts(res, name):
    return res["fixtures"][name]["counts"]


def _summaries(res, name):
    return [c["summary"] for c in res["fixtures"][name]["changes"]]


# ---------------------------------------------------------------- 基线


def test_empty_profile_has_no_changes():
    res = preview.preview(_profile())
    assert res["totals"] == {"changes": 0, "applied": 0}
    for name in preview.FIXTURE_NAMES:
        assert res["fixtures"][name]["changes"] == []
        assert res["fixtures"][name]["applied"] is False


def test_passthrough_warns_but_still_simulates():
    prof = _profile()
    prof["proxy"]["passthrough"] = True
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [100]}]
    res = preview.preview(prof)
    assert res["passthrough"] is True
    assert any("直通" in w for w in res["warnings"])
    # 直通只影响实机行为，预演仍算「关闭直通后的增量」，否则默认 profile 永远是 0 处改动
    assert _counts(res, "status")["effects"] == 2


def test_result_is_json_serializable():
    prof = _profile()
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [100]}]
    res = preview.preview(prof)
    assert json.loads(json.dumps(res, ensure_ascii=False))["totals"]["changes"] >= 2


# ---------------------------------------------------------------- status


def test_variant_effects_respect_faction_filter():
    prof = _profile()
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [76, 100]}]
    res = preview.preview(prof, fixtures="status")
    summaries = _summaries(res, "status")
    assert "星球 100 追加效果 1243" in summaries
    assert "星球 100 追加效果 1245" in summaries
    assert not any("星球 76 追加" in s for s in summaries)   # owner=1 未知阵营 -> 过滤
    warnings = res["fixtures"]["status"]["warnings"]
    assert any("不同阵营" in w and "76" in w for w in warnings)
    assert _counts(res, "status")["filtered"] == 1


def test_planet_effects_raw_channel():
    prof = _profile()
    prof["status"]["planet_effects"] = [{"index": 76, "ids": [1244]}]
    res = preview.preview(prof, fixtures="status")
    assert "星球 76 追加效果 1244" in _summaries(res, "status")
    assert _counts(res, "status")["effects"] == 1
    assert _counts(res, "status")["extra"] == 1


def test_status_extra_campaign_owner_events():
    prof = _profile()
    prof["status"]["campaigns"] = [{"planet": 300, "id": 52001, "type": 0, "count": 1, "race": 1}]
    prof["status"]["owner"] = {"158": 1}
    prof["status"]["events"] = [{"planet": 158, "eventType": 1, "id": 7002}]
    res = preview.preview(prof, fixtures="status")
    fixture = res["fixtures"]["status"]
    assert any("战役 +1" in c["summary"] for c in fixture["changes"])
    assert any("归属 2 → 1" in c["summary"] for c in fixture["changes"])
    assert any("星球事件 +1" in c["summary"] for c in fixture["changes"])
    assert fixture["applied"] is True


def test_status_duplicate_extra_is_noop():
    """campaign 已存在（样本 500 在 76 星）→ 去重后 0 改动。"""
    prof = _profile()
    prof["status"]["campaigns"] = [{"planet": 76, "id": 500, "type": 0, "count": 1, "race": 1}]
    res = preview.preview(prof, fixtures="status")
    assert res["fixtures"]["status"]["changes"] == []
    assert res["fixtures"]["status"]["applied"] is False


# ---------------------------------------------------------------- warinfo


def test_warinfo_settings_hash_and_new_node():
    prof = _profile(warinfo={
        "settings_hash": {"76": 999},
        "planet_infos": [{"index": 350, "settingsHash": 555,
                          "position": {"x": 0.3, "y": -0.55}}],
    })
    res = preview.preview(prof, fixtures="warinfo")
    summaries = _summaries(res, "warinfo")
    assert any("0x0000006F → 0x000003E7" in s for s in summaries)
    assert any("index=350" in s for s in summaries)
    assert _counts(res, "warinfo") == {"settings_hash": 1, "planet_infos": 1, "hook_changed": 2}
    assert res["fixtures"]["warinfo"]["applied"] is True


def test_warinfo_missing_planet_warns_and_dup_node_warns():
    prof = _profile(warinfo={
        "settings_hash": {"999": 123},
        "planet_infos": [{"index": 76, "settingsHash": 1}],
    })
    res = preview.preview(prof, fixtures="warinfo")
    fixture = res["fixtures"]["warinfo"]
    assert fixture["changes"] == []
    joined = "；".join(fixture["warnings"])
    assert "没有星球 999" in joined
    assert "已存在" in joined


# ---------------------------------------------------------------- inventory


def test_inventory_add_remove_and_customize_dedup():
    prof = _profile(inventory={
        "weapons": [{"mixId": 9001}],
        "remove": [1000],
        "customization": [
            {"mixId32": 3000, "index": 0, "slots": [9, 9, 9, 9, 9, 9, 9, 9]},   # 样本已有 -> 去重
            {"mixId32": 4444, "index": 0, "slots": [1, 2]},                       # 新增
        ],
    })
    res = preview.preview(prof, fixtures="inventory")
    summaries = _summaries(res, "inventory")
    assert "解锁物品 mixId 9001" in summaries
    assert "移除物品 mixId 1000" in summaries
    assert "补改装预设 mixId32=4444 index=0" in summaries
    assert not any("3000" in s for s in summaries)        # 已存在，钩子不会重复加
    assert _counts(res, "inventory")["items_added"] == 2   # 1 物品 + 1 改装预设
    assert _counts(res, "inventory")["items_removed"] == 1


def test_inventory_remove_missing_mixid_warns():
    prof = _profile(inventory={"remove": [424242]})
    res = preview.preview(prof, fixtures="inventory")
    assert res["fixtures"]["inventory"]["changes"] == []
    assert any("424242" in w for w in res["fixtures"]["inventory"]["warnings"])


# ---------------------------------------------------------------- items


def test_items_add_clone_template():
    prof = _profile(items={"template": 100, "add": [300, {"id": 400, "template": 200}]})
    res = preview.preview(prof, fixtures="items")
    summaries = _summaries(res, "items")
    assert any("itemId 300" in s and "100" in s for s in summaries)
    assert any("itemId 400" in s and "200" in s for s in summaries)
    assert _counts(res, "items") == {"items": 2}
    assert res["fixtures"]["items"]["applied"] is True


def test_items_missing_template_warns():
    prof = _profile(items={"template": 999, "add": [301]})
    res = preview.preview(prof, fixtures="items")
    fixture = res["fixtures"]["items"]
    assert fixture["changes"] == []
    assert any("999" in w and "模板" in w for w in fixture["warnings"])


def test_items_without_template_warns():
    prof = _profile(items={"add": [301]})
    res = preview.preview(prof, fixtures="items")
    fixture = res["fixtures"]["items"]
    assert fixture["changes"] == []
    assert any("template 为空" in w for w in fixture["warnings"])


# ---------------------------------------------------------------- customize


def test_customize_disabled_warns():
    res = preview.preview(_profile(), fixtures="customize")
    fixture = res["fixtures"]["customize"]
    assert fixture["changes"] == []
    assert any("L2" in w for w in fixture["warnings"])


def test_customize_enabled_reports_slot_diff():
    prof = _profile(experimental={"customize": {"enabled": True, "edits": [
        {"mixId": 2112173638, "slots": {"1": 3905063732}, "allIndexes": True}]}})
    res = preview.preview(prof, fixtures="customize")
    fixture = res["fixtures"]["customize"]
    assert _counts(res, "customize") == {"slots": 2}     # 样本有 index 0/1 两组预设
    assert all("3905063732" in c["summary"] for c in fixture["changes"])
    assert fixture["applied"] is True


# ---------------------------------------------------------------- 边界


def test_fixture_selection_and_unknown_name():
    res = preview.preview(_profile(), fixtures=["status", "nope"])
    assert list(res["fixtures"]) == ["status"]
    assert any("未知样本" in w for w in res["warnings"])


def test_missing_samples_dir_degrades(tmp_path):
    res = preview.preview(_profile(), samples_dir=tmp_path)
    assert set(res["fixtures"]) == set(preview.FIXTURE_NAMES)
    for name in preview.FIXTURE_NAMES:
        fixture = res["fixtures"][name]
        assert fixture["missing"] is True
        assert fixture["warnings"]
    assert res["totals"]["changes"] == 0


def test_empty_catalog_warns_instead_of_crashing():
    res = preview.preview(_profile(status={"variants": [{"name": "掠食变种", "planets": [100]}]}),
                          catalog_doc={})
    assert any("找不到" in w for w in res["warnings"])
    assert res["totals"]["changes"] == 0


def test_preview_writes_no_log(monkeypatch, tmp_path):
    """预演是纯计算：即使钩子内部调 log()，也不能落盘 / print。"""
    logdir = tmp_path / "logs"
    monkeypatch.setattr(logutil, "LOGDIR", logdir)
    monkeypatch.setattr(logutil, "PROXY_LOG", logdir / "proxy.log")
    monkeypatch.setattr(logutil, "AUDIT_LOG", logdir / "audit.log")
    assert logutil.SILENT is False
    prof = _profile(warinfo={"settings_hash": {"76": 999}})
    preview.preview(prof, fixtures="warinfo")
    assert not (logdir / "proxy.log").exists()
    assert logutil.SILENT is False          # quiet() 必须还原，不能把引擎日志也静音掉


def test_format_text_sections():
    prof = _profile(status={"variants": [{"name": "掠食变种", "planets": [100]}]})
    text = preview.format_text(preview.preview(prof))
    assert "离线预演" in text
    assert "战况 Status" in text
    assert "合计" in text
    assert "星球 100 追加效果 1243" in text


def test_format_text_truncates_long_lists():
    prof = _profile()
    prof["status"]["planet_effects"] = [{"index": 100, "ids": [f"130{i}" for i in range(10)]}]
    text = preview.format_text(preview.preview(prof), max_changes=3)
    assert "已截断到 3 条" in text
    assert text.count("  - ") == 3


def test_samples_dir_default_points_at_repo_samples():
    assert preview.samples_dir_default() == SAMPLES
    assert preview.samples_dir_default() == paths.SAMPLES_DIR
