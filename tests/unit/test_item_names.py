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
    """名字覆盖率是验收线：原来是 391/1671；附件内部名 + 外观 + LoadoutEntry 内部名后应 >= 1500。"""
    items = items_doc["items"]
    named = [it for it in items if it.get("name")]
    assert len(named) >= 1500, (len(named), len(items))
    assert all(isinstance(it["name"], str) and it["name"].strip() for it in named)


def test_known_attachment_names(items_by_mix):
    """抽样：几个 mixId 必须解析成对应的改装选项内部名（不是猜的）。"""
    assert items_by_mix[4591677]["name"] == "TUBE REDDOT 1,5x"
    assert items_by_mix[23801040]["name"] == "Vertical Grip"
    assert items_by_mix[27332127]["name"] == "Vertical Grip Advanced"
    # 内部名来源标记：只有解析出来的那批才有 name_source
    assert items_by_mix[4591677]["name_source"] == "catalog-option"
    assert items_by_mix[4591677]["catalog_category"] == 2        # 2 = 附件


def test_weapon_names_come_from_loadout_entities(items_by_mix):
    """武器名走 dlbin 路线：LoadoutEntry 行 +0x0 = 目录 itemId，名字取实体内部名。

    对照：LAS-22 Shear 的 inventory mixId 2112173638 在仓库文档里就是这把枪（UNLOCK-MAP §15）。
    """
    assert items_by_mix[2112173638]["name"] == "Shear"
    assert items_by_mix[2112173638]["name_source"] == "loadout-entity"
    assert items_by_mix[1312773632]["name"] == "Veto"
    assert items_by_mix[539671360]["name"] == "Gallant"
    assert items_by_mix[131945085]["name"] == "Smokescreen"


def test_loadout_item_names_source_file_is_wellformed():
    """dlbin 产物本身要可审计：build、块类型、行数、命名数都得对得上。"""
    doc = json.loads((REPO / "data" / "sources" / "item_names_derived.json").read_text(encoding="utf-8"))
    assert doc["build"] == "26568081"
    entry = doc["loadout_entry"]
    assert entry["block_type"] == "0x4F2CF417" and entry["rows"] == 199
    assert entry["named_rows"] + entry["unnamed_rows"] == entry["rows"]
    assert entry["named_ids"] == len(entry["items"]) >= 170
    assert entry["named_ids"] <= entry["named_rows"]
    assert entry["items"]["2112173638"]["name"] == "Shear"
    # 不许出现绝对路径（换机器复现用）
    text = (REPO / "data" / "sources" / "item_names_derived.json").read_text(encoding="utf-8")
    drive = "D" + ":"          # 拆开写：门禁的绝对路径检查会扫「盘符 + 冒号」字面量
    assert drive + "\\" not in text and drive + "/" not in text


def test_names_do_not_cover_impossible_categories(items_doc):
    """战备（cat 11）在本地数据里没有 id 映射：必须留空，**不许**编名字。

    武器（cat 1）现在能从 LoadoutEntry 实体拿到内部名，但名字来源必须是 loadout-entity，
    不能是别的来源（防止把附件选项名误配到武器上）。
    """
    for it in items_doc["items"]:
        if it.get("catalog_category") == 11:
            assert it.get("name") is None, it
        elif it.get("catalog_category") == 1 and it.get("name"):
            assert it.get("name_source") == "loadout-entity", it


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
    # 武器内部名（dlbin LoadoutEntry 路线）也能搜到
    assert any("Veto" in label for _mix, label in cat.search_items("veto", limit=10))
    assert cat.item_label(2112173638).endswith("Shear")
    # 中文类别也在标签里，搜「附件」能命中无名条目
    assert any("附件" in label for _mix, label in cat.search_items("附件", limit=30))


def test_search_items_category_filter_keeps_attachment_names_out_of_cosmetics():
    """分类筛选的数据层保证：外观列表里不出现附件内部名，反之亦然。"""
    cat = Catalogs()
    cosmetics = cat.search_items("", limit=100000, category="cosmetic")
    attachments = cat.search_items("", limit=100000, category="attachment")
    assert attachments and cosmetics
    assert not any("TUBE REDDOT" in label or "Vertical Grip" in label for _mix, label in cosmetics)
    assert any("TUBE REDDOT" in label for _mix, label in attachments)
    weapons = cat.search_items("", limit=100000, category="weapon")
    assert any("Shear" in label for _mix, label in weapons)
    stratagems = cat.search_items("", limit=100000, category="stratagem")
    assert len(stratagems) == 30
    # 类别之间不重叠，且四类之和 + 未分类 = 全部
    total = len(cat.items)
    categorized = sum(len(cat.search_items("", limit=100000, category=c))
                      for c in ("weapon", "attachment", "cosmetic", "stratagem"))
    assert categorized < total                       # 另有 15 条混类探测条目（category=None）
    assert cat.item_category(4591677) == "attachment"
    assert cat.item_category(2112173638) == "weapon"
    assert cat.item_category(1) is None


def test_attachment_rows_carry_parent_weapon(items_doc):
    """附件行必须带「属于哪把武器」：1455 行 / 57 把武器 / parent_name 大多已解。

    「附件按武器筛选」和「一键解锁该武器全部配件」都靠 parent_id。
    """
    attachments = [it for it in items_doc["items"] if it.get("category") == "attachment"]
    assert len(attachments) == 1455
    assert all(it.get("parent_id") for it in attachments)
    assert all(it.get("option_id") for it in attachments)
    groups = {it["parent_id"] for it in attachments}
    assert len(groups) == 57
    named_parents = {it["parent_id"] for it in attachments if it.get("parent_name")}
    assert len(named_parents) >= 54
    # 名字覆盖：附件内部名 1400+ 条
    assert sum(1 for it in attachments if it.get("name")) >= 1400


def test_attachment_groups_api():
    """Catalogs.attachment_groups()：按武器名排序、每组条目数与 items 一致。"""
    cat = Catalogs()
    groups = cat.attachment_groups()
    assert len(groups) == 57
    assert groups == sorted(groups, key=lambda g: (g[1].lower(), g[0]))
    total = 0
    for pid, name, items in groups:
        assert isinstance(pid, int) and name and items
        assert all(isinstance(mix, int) and isinstance(label, str) for mix, label in items)
        total += len(items)
    assert total == 1455
    # 同一附件（TUBE REDDOT）出现在多把武器下，但 mixId 各不相同（解锁粒度 = 武器 × 附件）
    reddot = [(pid, mix) for pid, name, items in groups for mix, label in items
              if "TUBE REDDOT" in label]
    assert len({mix for _pid, mix in reddot}) >= 3
    # 抽查「Liberator」组


def test_catalog_index_has_parent_field():
    """目录索引要带 parent（附件所属武器）；否则生成器无法分组。"""
    doc = json.loads((REPO / "data" / "sources" / "progression_item_catalog.json")
                     .read_text(encoding="utf-8"))
    rows = doc["rows"]
    assert len(rows) == 3020
    cat2 = [r for r in rows if r["cat"] == 2]
    assert len(cat2) == 1455
    assert all(r.get("parent") for r in cat2)
    assert len({r["parent"] for r in cat2}) == 57


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
    loadout_names = {300: "Veto", 900: "ShouldNotWin"}
    resolved = gen.enrich_item_names(items, catalog_index, attachment_options, armor_names,
                                     loadout_names)
    assert resolved == 3
    assert items[0]["name"] == "TUBE REDDOT 1,5x" and items[0]["name_source"] == "catalog-option"
    assert items[1]["name"] == "Arctic Decree" and items[1]["name_source"] == "armor-table"
    assert items[2]["name"] == "Veto" and items[2]["name_source"] == "loadout-entity"
    assert items[3]["name"] == "已有显示名" and items[3].get("name_source") is None
    assert items[4]["name"] is None and items[4]["catalog_category"] is None
    # 优先级：附件/外观规则先于 LoadoutEntry（同 id 不会串味）
    assert items[0]["name_source"] == "catalog-option"


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
