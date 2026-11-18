"""目录补全单测：`_complete_catalog_items` 的行为（补行 / 不编造 / 默认标记收紧 / 类别投票）。

背景（2026-11-18 用户要求做 0.4.0「完整目录」）
    服务端 `/api/Progression/items` 有 3020 行（与账号无关），而 `data/catalogs/items.json`
    只覆盖了 1950 行：界面既看不到剩余 1070 行、也不知道它们属于哪个类别。生成器现在把它们
    全部并入 items.json，并标记 in_catalog / default_owned。

这些测试用**合成数据**锁规则；真实数据由 test_catalogs_data.py 与 test_gui 页面测试守。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _gen():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import gen_catalogs  # noqa: PLC0415 —— 生成器是工具脚本，按需导入

    return gen_catalogs


# ---------------------------------------------------------------- 补行集


def test_completion_appends_missing_rows_without_inventing_names():
    gen = _gen()
    catalog = {
        100: {"mix": 100, "item": 700, "cat": 2, "parent": 500},
        101: {"mix": 101, "item": 701, "cat": 2, "parent": 500},
        102: {"mix": 102, "item": 800, "cat": 3, "parent": None},
    }
    items = [{"mix_id": 100, "name": "TUBE REDDOT 1,5x", "category": "attachment",
              "catalog_category": 2}]
    coverage = gen._complete_catalog_items(
        items, catalog, {}, {2: "attachment", 3: "cosmetic"}, set())
    assert len(items) == 3
    assert coverage["catalog_rows"] == 3
    assert coverage["in_catalog"] == 3
    assert coverage["named"] == 1 and coverage["unnamed"] == 2
    by_mix = {it["mix_id"]: it for it in items}
    assert by_mix[100]["name"] == "TUBE REDDOT 1,5x"       # 已有名字不动
    for mix in (101, 102):
        assert by_mix[mix]["name"] is None                  # 没有解析结果 -> 绝不编造
        assert by_mix[mix]["in_catalog"] is True
        assert by_mix[mix]["source"] == "catalog-completion"
        assert by_mix[mix]["default_owned"] is False
    assert by_mix[101]["category"] == "attachment"
    assert by_mix[101]["parent_id"] == 500
    assert by_mix[101]["option_id"] == 701                  # cat 2 的附件选项 id
    assert by_mix[102]["category"] == "cosmetic"
    assert "catalog_rows" in coverage and "by_category" in coverage and coverage["note"]


def test_completion_only_uses_resolved_snapshot_names():
    """解析快照只给「有证据」的行填空；没进快照的行必须保持 name=None/name_source=None。"""
    gen = _gen()
    catalog = {
        10: {"mix": 10, "item": 900, "cat": 8, "parent": None},
        11: {"mix": 11, "item": 901, "cat": 8, "parent": None},
    }
    resolved = {10: {"name": "Helmet X", "name_source": "armor-table", "confidence": "high"}}
    items = []
    cov = gen._complete_catalog_items(items, catalog, resolved, {8: "cosmetic"}, set())
    by_mix = {it["mix_id"]: it for it in items}
    assert by_mix[10]["name"] == "Helmet X"
    assert by_mix[10]["name_source"] == "armor-table"
    assert by_mix[11]["name"] is None and by_mix[11]["name_source"] is None
    assert cov["named"] == 1


def test_completion_unknown_category_when_no_evidence():
    """类别没有投票/快照证据时写 unknown（界面显示服务端 cat 编号），不猜。"""
    gen = _gen()
    catalog = {20: {"mix": 20, "item": 2000, "cat": 21, "parent": None}}
    items = []
    gen._complete_catalog_items(items, catalog, {}, {}, set())
    assert items[0]["category"] == "unknown"
    assert items[0]["catalog_category"] == 21


def test_completion_marks_existing_items_in_catalog():
    """已有条目也要补 in_catalog 标记（此前 items.json 完全没这个字段）。"""
    gen = _gen()
    catalog = {30: {"mix": 30, "item": 3000, "cat": 1, "parent": None}}
    items = [{"mix_id": 30, "name": "Veto", "category": ""}]
    cov = gen._complete_catalog_items(items, catalog, {}, {1: "weapon"}, set())
    assert items[0]["in_catalog"] is True
    assert items[0]["category"] == "weapon"                 # 类别空缺按投票补
    assert items[0]["catalog_category"] == 1
    assert cov["in_catalog"] == 1 and len(items) == 1


# ---------------------------------------------------------------- 默认拥有标记


def test_completion_default_owned_by_mix_id():
    gen = _gen()
    catalog = {5: {"mix": 5, "item": 1000, "cat": 2, "parent": 1},
               6: {"mix": 6, "item": 1000, "cat": 2, "parent": 2}}
    items = []
    gen._complete_catalog_items(items, catalog, {}, {2: "attachment"}, {5})
    by_mix = {it["mix_id"]: it for it in items}
    assert by_mix[5]["default_owned"] is True
    assert by_mix[6]["default_owned"] is False


def test_completion_default_owned_does_not_leak_through_shared_option_ids():
    """收紧点：附件 optionId 在成百上千行里共享，按 itemId 泛匹配会把 150 行标成默认。

    实测：第一版按 itemId 泛匹配时 default_owned 从 55 涨到 150。这里锁住「只在该 itemId
    在目录里唯一时才补充匹配」。
    """
    gen = _gen()
    catalog = {
        5: {"mix": 5, "item": 1000, "cat": 2, "parent": 1},    # 空号默认项（自身 mix）
        6: {"mix": 6, "item": 1000, "cat": 2, "parent": 2},    # 共享同一 optionId 的另一行
        7: {"mix": 7, "item": 2000, "cat": 3, "parent": None},
    }
    items = [
        {"mix_id": 6, "option_id": 1000, "category": "attachment", "catalog_category": 2},
        {"mix_id": 7, "item_id": 2000, "category": "cosmetic", "catalog_category": 3},
    ]
    gen._complete_catalog_items(items, catalog, {}, {2: "attachment", 3: "cosmetic"}, {5})
    assert sum(1 for it in items if it["default_owned"]) == 1
    by_mix = {it.get("mix_id"): it for it in items}
    assert by_mix[5]["default_owned"] is True
    assert by_mix[6]["default_owned"] is False                 # 共享 optionId 不算
    assert by_mix[7]["default_owned"] is False


def test_completion_default_owned_supplements_unique_item_ids():
    """空号基线里少数项给的是目录行的 itemId（不是 mixId）：唯一时才补标。"""
    gen = _gen()
    catalog = {5: {"mix": 5, "item": 1000, "cat": 2, "parent": 1}}
    items = [{"mix_id": None, "item_id": 1000, "category": "attachment",
              "catalog_category": None}]
    gen._complete_catalog_items(items, catalog, {}, {2: "attachment"}, {5})
    assert len(items) == 1 and items[0]["mix_id"] is None      # 复用而不是再造一行
    assert items[0]["catalog_category"] == 2
    assert items[0]["default_owned"] is True                    # itemId 唯一 -> 补标


# ---------------------------------------------------------------- itemId 兜底匹配


def test_completion_item_id_fallback_claims_only_one_catalog_row():
    """外观行只有 item_id（mix_id=None）：兜底匹配只允许认领一次，否则会重复造行。"""
    gen = _gen()
    catalog = {10: {"mix": 10, "item": 777, "cat": 3, "parent": None},
               11: {"mix": 11, "item": 777, "cat": 3, "parent": None}}
    items = [{"mix_id": None, "item_id": 777, "category": "cosmetic",
              "catalog_category": None}]
    cov = gen._complete_catalog_items(items, catalog, {}, {3: "cosmetic"}, set())
    assert len(items) == 2                                      # 认领 1 行 + 补 1 行
    claimed = [it for it in items if it.get("catalog_category") == 3]
    assert len(claimed) == 2 and cov["in_catalog"] == 2
    assert any(it.get("mix_id") == 11 for it in items)


# ---------------------------------------------------------------- 类别投票 / 来源加载


def test_infer_catalog_kinds_requires_majority_evidence():
    """类别含义只从已有物品的多数类别投票（>=60%），证据不足就是 unknown。"""
    gen = _gen()
    items = [
        {"catalog_category": 2, "category": "attachment"},
        {"catalog_category": 2, "category": "attachment"},
        {"catalog_category": 2, "category": "cosmetic"},     # 2/3 = 66.7% -> attachment
        {"catalog_category": 8, "category": "weapon"},
        {"catalog_category": 8, "category": "cosmetic"},     # 1/2 = 50% -> 不认
        {"catalog_category": 9, "category": ""},             # 无有效票 -> 不认
    ]
    assert gen._infer_catalog_kinds(items) == {2: "attachment"}


def test_load_resolved_catalog_reads_names_and_category_meaning(tmp_path):
    gen = _gen()
    path = tmp_path / "resolved.json"
    path.write_text(json.dumps({
        "rows": [
            {"mix": 5, "name": "Foo", "name_source": "armor-table", "confidence": "high"},
            {"mix": 6, "name": None},                            # 未解的行忽略
            {"mix": "bad", "name": "X"},                         # 非法 mix 忽略
        ],
        "category_meaning": {"8": {"label": "wristband"}, "9": {"label": "cosmetic"}},
    }, ensure_ascii=False), encoding="utf-8")
    by_mix, cat_kind = gen._load_resolved_catalog(path)
    assert by_mix == {5: {"name": "Foo", "name_source": "armor-table",
                          "confidence": "high"}}
    assert cat_kind == {9: "cosmetic"}        # 不在 _ITEM_KINDS 里的 label 忽略


def test_load_resolved_catalog_missing_file_degrades(tmp_path):
    gen = _gen()
    assert gen._load_resolved_catalog(None) == ({}, {})
    assert gen._load_resolved_catalog(tmp_path / "nope.json") == ({}, {})


def test_load_fresh_defaults_parses_and_degrades(tmp_path):
    gen = _gen()
    path = tmp_path / "fresh.json"
    path.write_text(json.dumps({"count": 3, "mix_ids": [1, "2", "x", None]}),
                    encoding="utf-8")
    assert gen._load_fresh_defaults(path) == {1, 2}
    assert gen._load_fresh_defaults(None) == set()
    assert gen._load_fresh_defaults(tmp_path / "missing.json") == set()
