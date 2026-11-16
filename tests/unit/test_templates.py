"""能力模板（gui/templates.py）单测。

要点：6 项核心模板 apply 后 profile 必须仍能通过 `config.validate`；
「战备试用」这种历史上会被静默丢掉的配置（只有 trials 没有星球）要能单独生效；
延后项必须有验证状态标注且同样不产生非法 profile。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import config, preview
from hd2proxy.gui import templates

CATALOG = Path(__file__).resolve().parents[2] / "data" / "legacy" / "variant_catalog.json"


def _catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _profile():
    prof = config.default_profile()
    prof["proxy"]["passthrough"] = False
    return prof


def _apply(template, prof, planet=100):
    return template.apply(prof, planet) if template.needs_planet else template.apply(prof)


# ---------------------------------------------------------------- 模板表


def test_template_table_shape():
    assert len(templates.CORE_TEMPLATES) == 6
    assert len(templates.DEFERRED_TEMPLATES) == 3
    tids = [t.tid for t in templates.TEMPLATES]
    assert len(tids) == len(set(tids))
    for t in templates.DEFERRED_TEMPLATES:
        assert t.deferred is True
        assert t.evidence, "%s 延后项必须标注验证状态" % t.tid
    for t in templates.CORE_TEMPLATES:
        assert t.deferred is False
        assert t.desc
    assert templates.get_template("nope") is None
    assert templates.get_template("variant_trial").title == "变种词条试用"


def test_planet_required_templates_raise_without_planet():
    for t in templates.TEMPLATES:
        if not t.needs_planet:
            continue
        with pytest.raises(ValueError):
            t.apply(_profile(), None)


# ---------------------------------------------------------------- 6 项核心


@pytest.mark.parametrize("template", templates.CORE_TEMPLATES, ids=lambda t: t.tid)
def test_core_template_keeps_profile_valid(template):
    prof = _profile()
    notes = _apply(template, prof)
    assert notes and all(isinstance(n, str) and n for n in notes)
    _, errors, _ = config.validate(prof)
    assert errors == []


@pytest.mark.parametrize("template", templates.TEMPLATES, ids=lambda t: t.tid)
def test_templates_are_idempotent(template):
    prof = _profile()
    _apply(template, prof)
    first = json.dumps(prof, ensure_ascii=False, sort_keys=True)
    _apply(template, prof)
    second = json.dumps(prof, ensure_ascii=False, sort_keys=True)
    assert first == second, "%s 第二次 apply 不应改变 profile" % template.tid


def test_variant_template_plan_and_preview():
    prof = _profile()
    notes = templates.apply_variant_trial(prof, 100)
    assert any("星球 100" in n for n in notes)
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.status_plan == {100: {"variants": [
        {"name": "掠食变种", "ids": [1243, 1245], "faction": "terminid"}], "trials": []}}
    res = preview.preview(prof, fixtures="status")
    assert res["fixtures"]["status"]["counts"]["effects"] == 2


def test_stratagem_template_works_without_variants():
    """只有战备试用、没有变种的 profile 也要能生效（靠 status.trials_planet）。"""
    prof = _profile()
    templates.apply_stratagem_trial(prof, 100)
    assert prof["status"]["trials"] == [1227, 1263]
    assert prof["status"]["trials_planet"] == 100
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.status_plan == {100: {"variants": [], "trials": [1227, 1263]}}
    res = preview.preview(prof, fixtures="status")
    assert "星球 100 追加效果 1227" in [c["summary"] for c in
                                        res["fixtures"]["status"]["changes"]]


def test_stratagem_template_caps_at_three():
    prof = _profile()
    prof["status"]["trials"] = [111, 222]
    templates.apply_stratagem_trial(prof, 100)
    assert prof["status"]["trials"] == [111, 222, 1227]


def test_global_effect_template():
    prof = _profile()
    templates.apply_global_effect(prof)
    assert prof["status"]["globalEffects"] == {"1501113": [1346]}
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.status_extra["globalEffects"] == {"1501113": [1346]}
    res = preview.preview(prof, fixtures="status")
    assert any("全局事件 1501113" in c["summary"] for c in
               res["fixtures"]["status"]["changes"])


def test_item_unlock_template():
    prof = _profile()
    templates.apply_item_unlock(prof)
    assert prof["inventory"]["weapons"] == [
        {"mixId": 2112173638, "amount": 1, "isDiscovered": False}]
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.inventory["items"][0]["mixId"] == 2112173638
    res = preview.preview(prof, fixtures="inventory")
    assert any("2112173638" in c["summary"] for c in
               res["fixtures"]["inventory"]["changes"])


def test_dormant_star_template_four_pieces():
    prof = _profile()
    templates.apply_dormant_star(prof, 300)
    wi = prof["warinfo"]
    assert [r["index"] for r in wi["planet_infos"]] == [300]
    assert wi["planet_infos"][0]["settingsHash"] == 694418289
    st = prof["status"]
    assert st["planet_nodes"][0]["index"] == 300
    assert st["campaigns"][0]["planet"] == 300
    assert st["owner"]["300"] == 1
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.warinfo["planet_infos"][0]["index"] == 300
    assert spec.status_extra["planet_nodes"][0]["index"] == 300


def test_dormant_star_template_defaults_to_bicep():
    prof = _profile()
    templates.apply_dormant_star(prof)
    assert prof["warinfo"]["planet_infos"][0]["index"] == templates.DORMANT_INDEX


def test_ecosystem_borrow_template():
    prof = _profile()
    templates.apply_ecosystem_borrow(prof, 100)
    assert prof["warinfo"]["settings_hash"] == {"100": 2995599666}
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.warinfo["settings_hash"] == {"100": 2995599666}
    res = preview.preview(prof, fixtures="warinfo")
    assert any("星球 100 生态 settingsHash" in c["summary"] for c in
               res["fixtures"]["warinfo"]["changes"])


# ---------------------------------------------------------------- 延后项


@pytest.mark.parametrize("template", templates.DEFERRED_TEMPLATES, ids=lambda t: t.tid)
def test_deferred_templates_apply_and_stay_valid(template):
    prof = _profile()
    notes = _apply(template, prof)
    assert notes and all(isinstance(n, str) and n for n in notes)
    _, errors, _ = config.validate(prof)
    assert errors == []


def test_defense_template_writes_defense_pieces():
    prof = _profile()
    templates.apply_defense_campaign(prof, 158)
    st = prof["status"]
    assert st["campaigns"][0]["type"] == 4
    assert {"source": 100, "target": 158} in st["attacks"]
    assert st["events"][0]["eventType"] == 2
    assert st["owner"]["158"] == 1
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.status_extra["campaigns"][0]["type"] == 4


def test_regions_template_adds_missing_only():
    prof = _profile()
    templates.apply_city_regions(prof, 158)
    assert len(prof["status"]["regions"]) == 3
    templates.apply_city_regions(prof, 158)
    assert len(prof["status"]["regions"]) == 3


def test_l2_template_writes_experimental_and_spec():
    prof = _profile()
    templates.apply_l2_customize(prof)
    cz = prof["experimental"]["customize"]
    assert cz["enabled"] is True
    assert cz["edits"][0]["mixId"] == templates.CUSTOMIZE_MIX
    spec = config.to_engine_spec(prof, _catalog())
    assert spec.customize["enabled"] is True
    res = preview.preview(prof, fixtures="customize")
    assert res["fixtures"]["customize"]["counts"]["slots"] >= 0   # 样本没有该 mixId -> 0
