"""真实目录数据的验收测试：服务端 3020 行目录全量并入 items.json（v0.4.0「完整目录」）。

`data/catalogs/items.json` 是 tools/gen_catalogs.py 的确定性产物——这里守的是**产品承诺**，
不是重新实现生成器：
  * 服务端 `/api/Progression/items` 的 3020 行全部在 items 里（in_catalog=3020）；
  * 目录外的研究线条目保留并标 in_catalog=False（含 3 条 unlock_template），不丢老功能；
  * 空号默认拥有 **55** 项，且每条空号基线都能在 default 行里找到对应（附件 optionId 被
    大量共享，标记只允许按「唯一 itemId」补充匹配，见 test_catalog_completion.py）；
  * 没解析出名字的行 name=None（不编造），类别无证据的记 unknown 并保留服务端 cat 编号；
  * GUI 侧 catalog_summary / catalog_entries 与文件里的 coverage 段一致。

数值会随研究数据更新而变，但「3020 行 / 1455 条附件 / 55 项默认」是不可漂移的验收线。
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ITEMS = REPO / "data" / "catalogs" / "items.json"
CATALOG = REPO / "data" / "sources" / "progression_item_catalog.json"
FRESH = REPO / "data" / "sources" / "fresh_account_inventory.json"


@pytest.fixture(scope="module")
def items_doc():
    return json.loads(ITEMS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def items(items_doc):
    return items_doc["items"]


@pytest.fixture(scope="module")
def catalog_rows():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["rows"]


@pytest.fixture(scope="module")
def fresh_mix_ids():
    return [int(x) for x in json.loads(FRESH.read_text(encoding="utf-8"))["mix_ids"]]


# ---------------------------------------------------------------- 行集与标记


def test_items_doc_has_catalog_coverage_section(items_doc, catalog_rows):
    cov = items_doc.get("catalog") or {}
    assert cov, "items.json 缺 catalog 覆盖段（重新跑 tools/gen_catalogs.py）"
    assert cov["catalog_rows"] == len(catalog_rows) == 3020
    assert cov["in_catalog"] == 3020
    assert cov["default_owned"] == 55
    assert cov["note"] and "与账号无关" in cov["note"]


def test_items_contain_all_catalog_rows_and_keep_extras(items, catalog_rows):
    in_catalog = [it for it in items if it.get("in_catalog")]
    extras = [it for it in items if it.get("in_catalog") is False]
    assert len(in_catalog) == 3020 == len(catalog_rows)
    assert len(items) == 3062                       # 3020 目录行 + 42 条目录外研究条目
    assert len(extras) == 42
    # 目录外条目是「研究线没上架」的老功能：3 条带 unlock_template，不能丢
    assert sum(1 for it in items if it.get("unlock_template")) == 3
    # 每条 item 都必须有确定的 in_catalog/default_owned 布尔（界面总览靠它筛）
    assert all(isinstance(it.get("in_catalog"), bool) for it in items)
    assert all(isinstance(it.get("default_owned"), bool) for it in items)
    # 附件仍是 1455 行 / 57 把武器（一键解锁的粒度）
    attachments = [it for it in items if it.get("category") == "attachment"]
    assert len(attachments) == 1455
    assert len({int(it["parent_id"]) for it in attachments if it.get("parent_id")}) == 57


def test_catalog_category_is_server_category_int(items, catalog_rows):
    """in_catalog 的行必须带服务端 catalog_category（int），目录外条目没有。"""
    server_cats = {int(row["cat"]) for row in catalog_rows}
    for it in items:
        cat = it.get("catalog_category")
        if it.get("in_catalog"):
            assert isinstance(cat, int), it
            assert cat in server_cats
        else:
            assert cat is None, it


def test_no_invented_names_for_completed_rows(items, items_doc):
    """没解析出名字的行 name=None（界面显示 mixId + 类别占位），有名字的行必须非空字符串。"""
    named = [it for it in items if it.get("name")]
    unnamed = [it for it in items if not it.get("name")]
    assert all(isinstance(it["name"], str) and it["name"].strip() for it in named)
    assert all(it.get("name") is None for it in unnamed)
    cov = items_doc["catalog"]
    assert cov["named"] == len(named)
    assert cov["unnamed"] == len(unnamed)
    assert cov["named"] + cov["unnamed"] == len(items)
    assert len(named) >= 1821                      # 名字覆盖只会涨；生成器不能倒退


def test_categories_are_registered_labels(items):
    from hd2proxy.gui.catalogs import ITEM_CATEGORY_LABELS

    kinds = {str(it.get("category")) for it in items}
    assert kinds <= set(ITEM_CATEGORY_LABELS), kinds - set(ITEM_CATEGORY_LABELS)
    # 类别无证据的行：category=unknown 且保留服务端 cat 编号（界面显示「未分类 catN」）
    unknown = [it for it in items if it.get("category") == "unknown"]
    assert unknown and all(isinstance(it.get("catalog_category"), int) for it in unknown)


def test_inferred_names_carry_confidence(items):
    """非「直接 id→名字」的名字必须带 name_confidence，便于追溯。

    v2 的推断来源：战备 hash / 许可子行 / 套装子行；
    v3 新增客户端 game.dll 静态表来源：其中 cat0 战团名（warbond 表 + SeasonPass premiumToken 配对）、
    cat21 礼包短名、cat16 难度名、以及 56 条「mixId 本身就是 locid」的行是 medium（id=locid 约定），
    其余静态表行（banner/pose/voice/sample）是显式 id→名字映射（high，不记 confidence）。
    """
    # high 来源（显式 id→名字映射）：不允许带 confidence
    high_only = {"catalog-option", "armor-table", "loadout-entity", "boosters",
                 "dlbin-banner-table", "dlbin-victory-pose-table", "dlbin-voice-table",
                 "dlbin-resource-sample-table"}
    for it in items:
        if it.get("name_source") in high_only:
            assert not it.get("name_confidence"), it
    # 非显式来源必须带 medium/low
    non_explicit = {"stratagem-hash", "stratagem-permit-child", "armor-set-child",
                    "loadout-entry", "dlbin-warbond-table", "dlbin-item-pack-table",
                    "dlbin-difficulty-table", "locid-id"}
    inferred = [it for it in items if it.get("name_source") in non_explicit
                and it.get("name_confidence")]           # loadout-entry 有 high 也有 medium
    assert inferred, "名称快照（v2/v3）没生效？"
    assert all(it.get("name_confidence") in ("medium", "low") for it in inferred)
    assert any(it.get("name_confidence") == "low" for it in inferred)   # 仅 1 个单子行套装名
    # 已知 medium 来源必须全部带 confidence
    must_medium = {"stratagem-hash", "stratagem-permit-child", "armor-set-child",
                   "dlbin-warbond-table", "dlbin-item-pack-table", "dlbin-difficulty-table"}
    for it in items:
        if it.get("name_source") in must_medium:
            assert it.get("name_confidence") in ("medium", "low"), it
    # 战备许可名字全部来自 1:1 子行推断，且占三分之二以上（108 行里 73 行）
    stratagems = [it for it in items if it.get("category") == "stratagem"]
    named_stratagems = [it for it in stratagems if it.get("name")]
    assert len(named_stratagems) >= 70
    assert all(it.get("name_source") == "stratagem-permit-child"
               for it in named_stratagems)


# ---------------------------------------------------------------- 空号默认拥有


def test_default_owned_is_55_and_maps_to_fresh_account_baseline(items, catalog_rows,
                                                                fresh_mix_ids):
    """空号基线 55 项 → default_owned 55 行，且每条基线都能找到对应行（名字/编号任一路径）。

    为什么不是简单的「mix_id 相等」：外观（cat 3）的研究行只有 item_id、mix_id=None，
    空号给的是目录行 mixId，所以这类默认项标在 itemId 相同的行上（14 条）。附件 optionId
    被大量共享，补充匹配必须要求 itemId 在目录里唯一（否则会从 55 涨到 150，实测踩过）。
    """
    assert len(fresh_mix_ids) == 55 and len(set(fresh_mix_ids)) == 55
    catalog_by_mix = {int(row["mix"]): row for row in catalog_rows}
    defaults = [it for it in items if it.get("default_owned")]
    assert len(defaults) == 55
    unmapped = []
    for mix in fresh_mix_ids:
        row = catalog_by_mix.get(mix)
        hit = False
        for it in defaults:
            if it.get("mix_id") == mix:
                hit = True
                break
            if row is not None and row.get("item") is not None and (
                    it.get("item_id") == row["item"] or it.get("option_id") == row["item"]):
                hit = True
                break
            if row is None and mix in (it.get("item_id"), it.get("option_id")):
                hit = True
                break
        if not hit:
            unmapped.append(mix)
    assert not unmapped, "空号基线里有项没标成 default_owned：%r" % unmapped


# ---------------------------------------------------------------- GUI 数据层


def test_catalog_summary_matches_coverage_section(items_doc):
    from hd2proxy.gui.catalogs import Catalogs

    cat = Catalogs()
    summary = cat.catalog_summary()
    cov = items_doc["catalog"]
    assert summary["has_catalog_doc"] is True
    assert summary["rows"] == cov["catalog_rows"] == 3020
    assert summary["in_catalog"] == cov["in_catalog"] == 3020
    assert summary["items"] == len(items_doc["items"]) == 3062
    assert summary["extra"] == 42
    assert summary["named"] == cov["named"]
    assert summary["unnamed"] == cov["unnamed"]
    assert summary["default_owned"] == cov["default_owned"] == 55
    # by_kind 行数之和 = 目录行数；by_category 的服务端 cat 数与 coverage 段一致
    assert sum(stat["rows"] for stat in summary["by_kind"].values()) == 3020
    assert {int(k) for k in summary["by_category"]} == {int(k) for k in cov["by_category"]}


def test_catalog_entries_scopes_match_search_items():
    from hd2proxy.gui.catalogs import Catalogs

    cat = Catalogs()
    summary = cat.catalog_summary()
    assert len(cat.catalog_entries()) == len(cat.items) == 3062
    assert len(cat.catalog_entries(scope="default")) == 55
    assert len(cat.catalog_entries(scope="extra")) == summary["extra"] == 42
    for scope, category in (("weapon", "weapon"), ("attachment", "attachment"),
                            ("cosmetic", "cosmetic"), ("stratagem", "stratagem"),
                            ("unknown", "unknown")):
        assert len(cat.catalog_entries(scope=scope)) == len(
            cat.search_items("", category=category)), scope
    # id 不重复（外观行 mix_id=None 时用 item_id，仍是唯一键）
    ids = [mix for mix, _label in cat.catalog_entries()]
    assert len(ids) == len(set(ids)) == 3062


def test_catalog_entry_labels_are_explicit_about_unknowns():
    """未命名行必须写「内部名未解」+ 类别（unknown 带 cat 编号）；标记词只用于对应行。"""
    from hd2proxy.gui.catalogs import Catalogs

    cat = Catalogs()
    unknown_entries = cat.catalog_entries(scope="unknown")
    assert unknown_entries
    unnamed = [(mix, label) for mix, label in unknown_entries
               if "内部名未解" in label]
    named = [(mix, label) for mix, label in unknown_entries
             if "内部名未解" not in label]
    assert unnamed and all("未分类 cat" in label for _mix, label in unnamed)
    # 类别语义仍 unknown 但有名字的行：名字照给、类别仍标「未分类」（末尾可能还有「默认已有」标记）
    assert named and all("（未分类）" in label for _mix, label in named)
    default_labels = [label for _mix, label in cat.catalog_entries(scope="default")]
    assert all(label.endswith("默认已有") for label in default_labels)
    extra_labels = [label for _mix, label in cat.catalog_entries(scope="extra")]
    assert all("目录缺" in label for label in extra_labels)
    # 目录外研究线武器（Shear / Ombudsman）在 extra 里出现，且不在服务端目录
    assert any("Shear" in label for label in extra_labels)
    assert cat.is_in_server_catalog(2112173638) is False
    assert cat.is_in_server_catalog(4591677) is True
    assert cat.is_default_owned(2112173638) is False
