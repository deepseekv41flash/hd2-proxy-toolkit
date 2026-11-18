"""效果名 target 链派生：覆盖层文件 ↔ effects.json 一致性 + 生成器合并规则。

数据侧断言（effects.json 里的派生名），生成器侧断言（_apply_effect_name_overlay 的合并规则）。
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EFFECTS = REPO / "data" / "catalogs" / "effects.json"
OVERLAY = REPO / "data" / "sources" / "effect_names_derived.json"


def _gen_catalogs():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import gen_catalogs as mod  # noqa: PLC0415

    return mod


@pytest.fixture(scope="module")
def effects():
    doc = json.loads(EFFECTS.read_text(encoding="utf-8"))
    return doc["items"]


@pytest.fixture(scope="module")
def overlay():
    doc = json.loads(OVERLAY.read_text(encoding="utf-8"))
    return doc


def test_effects_catalog_has_derived_names(effects):
    named = [e for e in effects if e.get("name")]
    derived = [e for e in named if e.get("name_source") == "target-chain"]
    assert len(named) >= 200, len(named)
    assert derived, "效果名 target 链派生没生效？"
    # 派生名只出现在语义已验证的两类：type32 临时配发战备 / type36 DSS 临时装备
    assert {e["effect_type"] for e in derived} == {32, 36}
    for item in derived:
        evidence = item.get("name_evidence") or {}
        assert evidence, item
        assert evidence.get("ref_mix") and evidence.get("ref_native_hash"), item
        assert re.fullmatch(r"[0-9a-f]{8}", str(evidence["ref_native_hash"])), item
        assert item["name"].strip(), item


def test_overlay_matches_catalog(effects, overlay):
    assert overlay["count"] == len(overlay["rows"]) > 0
    by_id = {e["effect_id"]: e for e in effects}
    for row in overlay["rows"]:
        effect = by_id.get(row["effect_id"])
        assert effect is not None, row
        assert effect["name"] == row["name"], (effect, row)
        assert effect.get("name_source") == "target-chain"
        assert re.fullmatch(r"[0-9a-f]{8}", row["value_hex"]), row


def test_overlay_apply_only_fills_empty_and_honours_missing_ids():
    mod = _gen_catalogs()
    items = [{"effect_id": 1, "name": None}, {"effect_id": 2, "name": "KEEP ME"}]
    overlay = {
        1: {"name": "Derived One", "value_index": 0, "value_hex": "00000001"},
    }
    applied = mod._apply_effect_name_overlay(items, overlay)
    assert applied == 1
    assert items[0]["name"] == "Derived One"
    assert items[0]["name_source"] == mod.EFFECT_DERIVED_NAME_SOURCE
    assert items[1]["name"] == "KEEP ME" and "name_source" not in items[1]

    with pytest.raises(mod.SourceError):
        mod._apply_effect_name_overlay(items, {999: {"name": "X"}})
