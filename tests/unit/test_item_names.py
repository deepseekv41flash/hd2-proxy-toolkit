"""物品目录「内部名」单测：items.json 的名字覆盖、GUI 标签与搜索、生成器的名字解析规则。

背景（2026-11-17 用户报）
    「物品与战备」里所有物品都只有 id 没有名字，没法用。要求先显示**内部名**方便区分，
    本地化译名（中文）暂不做。做法：
      * 附件：服务端目录行 `itemId` = 武器改装选项 id -> 选项内部名（"TUBE REDDOT 1,5x"）；
      * 外观：目录行 `itemId` = 外观表行 id -> 外观表 names；
      * 武器 / 战备等类别：目录行只有 id、没有可用名字来源 -> 留空，界面显示「内部名未解」。
    名字来源与覆盖见 data/catalogs/README.md。
"""

import json
import sys
from pathlib import Path

import pytest

from hd2proxy.gui.catalogs import Catalogs, item_display_label

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "data" / "catalogs" / "items.json"


@pytest.fixture(scope="module")
def items_doc():
    return json.loads(ITEMS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def items_by_mix(items_doc):
    return {it["mix_id"]: it for it in items_doc["items"] if it.get("mix_id") is not None}


# ---------------------------------------------------------------- 数据覆盖


def test_most_items_have_a_name(items_doc):
    """名字覆盖率是本功能的验收线：原来 391/1671，现在应 >= 1400（附件内部名是主力）。"""
    items = items_doc["items"]
    named = [it for it in items if it.get("name")]
    assert len(named) >= 1400, (len(named), len(items))
    assert all(isinstance(it["name"], str) and it["name"].strip() for it in named)


def test_known_attachment_names(items_by_mix):
    """抽样：几个 mixId 必须解析成对应的改装选项内部名（不是猜的）。"""
    assert items_by_mix[4591677]["name"] == "TUBE REDDOT 1,5x"
    assert items_by_mix[23801040]["name"] == "Vertical Grip"
    assert items_by_mix[27332127]["name"] == "Vertical Grip Advanced"
    # 内部名来源标记：只有解析出来的那批才有 name_source
    assert items_by_mix[4591677]["name_source"] == "catalog-option"
    assert items_by_mix[4591677]["catalog_category"] == 2        # 2 = 附件


def test_names_do_not_cover_impossible_categories(items_doc):
    """武器/战备类目录行没有名字来源：允许留空，但**不许**出现编造的名字。"""
    for it in items_doc["items"]:
        if it.get("catalog_category") in (1, 11):
            assert it.get("name") is None, it


def test_catalog_category_is_recorded_for_catalog_rows(items_doc):
    """能进目录的条目都应带上 catalog_category（用于界面类别与后续补名）。"""
    with_cat = [it for it in items_doc["items"] if it.get("catalog_category") is not None]
    assert len(with_cat) >= 1200, len(with_cat)
    assert all(isinstance(it["catalog_category"], int) for it in with_cat)


# ---------------------------------------------------------------- GUI 标签/搜索


def test_item_label_shows_name_or_explicit_unknown():
    cat = Catalogs()
    assert cat.item_label(4591677).endswith("TUBE REDDOT 1,5x")
    unknown = cat.item_label(8469881)          # cat 11 战备：没有名字来源
    assert "内部名未解" in unknown and "战备" in unknown
    # 目录里没有的 id 也不能崩
    assert "内部名未解" in cat.item_label(1)


def test_item_display_label_rules():
    assert item_display_label(7, {"name": "Vertical Grip"}) == "7 · Vertical Grip"
    assert item_display_label(7, {"category": "attachment"}) == "7 · 附件（内部名未解）"
    assert item_display_label(7, {}) == "7 · ?（内部名未解）"
    assert item_display_label(7, {"name": "  "}) == "7 · ?（内部名未解）"


def test_search_items_matches_names():
    """搜索框必须能按内部名搜到 —— 之前只能按 id 搜，等于不可用。"""
    cat = Catalogs()
    reddot = cat.search_items("reddot", limit=20)
    assert len(reddot) >= 3
    assert all("REDDOT" in label.upper() for _mix, label in reddot)
    grips = cat.search_items("vertical grip", limit=20)
    assert grips and all("Vertical Grip" in label for _mix, label in grips)
    # 中文类别也在标签里，搜「附件」能命中无名条目
    assert any("附件" in label for _mix, label in cat.search_items("附件", limit=30))


# ---------------------------------------------------------------- 生成器规则


def _gen_catalogs_module():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import gen_catalogs  # noqa: PLC0415
    return gen_catalogs


def test_enrich_item_names_rules():
    gen = _gen_catalogs_module()
    catalog_index = {
        100: {"item": 700, "cat": 2},    # 附件
        200: {"item": 800, "cat": 3},    # 外观
        300: {"item": 900, "cat": 1},    # 武器：无名字来源
    }
    attachment_options = {700: "TUBE REDDOT 1,5x"}
    armor_names = {800: "Arctic Decree"}
    items = [
        {"mix_id": 100, "name": None},                     # 附件 -> 内部名
        {"mix_id": 200, "name": None},                     # 外观 -> 外观表名
        {"mix_id": 300, "name": None},                     # 武器 -> 保持空
        {"mix_id": 100, "name": "已有显示名"},              # 不覆盖已有名字
        {"mix_id": 999, "name": None},                     # 目录里没有 -> 保持空
    ]
    resolved = gen.enrich_item_names(items, catalog_index, attachment_options, armor_names)
    assert resolved == 2
    assert items[0]["name"] == "TUBE REDDOT 1,5x" and items[0]["name_source"] == "catalog-option"
    assert items[1]["name"] == "Arctic Decree" and items[1]["name_source"] == "armor-table"
    assert items[2]["name"] is None and items[2]["catalog_category"] == 1
    assert items[3]["name"] == "已有显示名" and items[3].get("name_source") is None
    assert items[4]["name"] is None and items[4]["catalog_category"] is None


def test_catalog_index_rejects_conflicting_category(tmp_path):
    gen = _gen_catalogs_module()
    bad = tmp_path / "catalog.json"
    bad.write_text(json.dumps({"rows": [
        {"mix": 1, "item": 2, "cat": 2},
        {"mix": 1, "item": 2, "cat": 3},
    ]}), encoding="utf-8")
    with pytest.raises(gen.SourceError) as exc:
        gen._load_item_catalog_index(bad)
    assert "类别冲突" in str(exc.value)
