"""变种目录单测：虫族 strain 全覆盖、GUI 目录与引擎目录不漂移、覆盖层合并规则。

背景（2026-11-17 用户报的问题）
    「变种」里虫族少了 Caustic Strain / Noxious Strain。根因不是「没改数据」而是两层：
      1. `caustic_strain` 在 items 里但**没进 groups** —— 界面只渲染 groups，所以看不见；
      2. Noxious 完全没收录（源目录冻结在 2026-11-01，那时它还没上线）。
    修复方式见 tools/gen_catalogs.py 的覆盖层 + data/sources/variant_overlay.json，
    证据/推导见 docs/VARIANT-INVENTORY-2026-11-17.md。

这份测试守三件事：
    * 虫族 7 个项目（5 个 strain + 蟑龙 + 霸王虫）都在分组里、ids 对得上（wiki 口径）；
    * GUI 目录与引擎目录（data/legacy/variant_catalog.json）对同一个变种给同样的 ids/faction；
    * 覆盖层的合并规则（改名、追加进组、组名数量、别名冲突）不静默改变语义。
"""

import copy
import json
import sys
from pathlib import Path

import pytest

from hd2proxy.engine import config
from hd2proxy.gui.catalogs import Catalogs

REPO = Path(__file__).resolve().parents[2]
GUI_CATALOG = REPO / "data" / "catalogs" / "variants.json"
ENGINE_CATALOG = REPO / "data" / "legacy" / "variant_catalog.json"

# wiki（helldivers.wiki.gg/wiki/Effects 的 Combatant Forces + Terminids）口径：
# 虫族 5 个 strain + 2 个特殊变种。ids = [tag(type40), mechanic(type71)]，单项表示无 tag。
TERMINID_VARIANTS = {
    "掠食变种": ([1243, 1245], "bugs_super_predator"),
    "孢裂变种": ([1244, 1386], "bugs_gloom"),
    "爆裂变种": ([1303, 1310], "bugs_burrower"),
    "蟑龙": ([1306, 1309], "bugs_dragon"),
    "霸王虫": ([1307, 1308], "bugs_hive_lord"),
    "腐蚀变种": ([1430, 1431], "bugs_acid"),        # Caustic Strain（2026-11-17 线上验证配对）
    "毒瘴变种": ([1434, 1433], "bugs_defiler"),     # Noxious Strain（tag 在前，与 mechanic 成对）
}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gui():
    return _load(GUI_CATALOG)


@pytest.fixture(scope="module")
def engine():
    return _load(ENGINE_CATALOG)


def _terminid_group(doc):
    groups = [g for g in doc.get("groups") or []
              if "虫族" in str(g.get("name") or "")]
    assert len(groups) == 1, groups
    return groups[0]


# ---------------------------------------------------------------- 虫族覆盖


def test_terminid_group_covers_every_strain(gui):
    """分组 = 界面唯一入口：7 个项目必须全部在组里，缺一个用户就少一个。"""
    group = _terminid_group(gui)
    assert set(group["variants"]) == set(TERMINID_VARIANTS), group
    # 组名里的数量要跟实际条数一致（"虫族 7"），否则用户会以为漏了
    assert group["name"].endswith(str(len(group["variants"]))), group["name"]


def test_terminid_group_order_is_stable(gui):
    group = _terminid_group(gui)
    # 原有 5 个顺序不变，新增的两个追加在尾部（避免老用户界面顺序跳动）
    assert group["variants"][:5] == ["掠食变种", "孢裂变种", "爆裂变种", "蟑龙", "霸王虫"]
    assert group["variants"][5:] == ["腐蚀变种", "毒瘴变种"]


@pytest.mark.parametrize("name,ids,presence", [
    (name, ids, presence) for name, (ids, presence) in TERMINID_VARIANTS.items()
])
def test_terminid_variant_ids_and_presence(gui, engine, name, ids, presence):
    gui_item = gui["items"][name]
    assert gui_item["ids"] == ids
    assert gui_item["faction"] == "terminid"
    assert gui_item["presence"] == presence
    # 引擎目录是注入时真正查的那份：ids 必须一致
    assert engine["variants"][name] == ids
    assert engine["meta"][name]["presence"] == presence
    assert engine["meta"][name]["faction"] == "terminid"


def test_caustic_rename_keeps_old_profiles_resolvable(gui, engine):
    """旧内部名 caustic_strain 不再作为独立条目，但老 profile 里存的这个名字仍要能解析。"""
    assert "caustic_strain" not in gui["items"]
    assert "caustic_strain" not in engine["variants"]
    assert gui["aliases"]["caustic_strain"] == "腐蚀变种"
    assert engine["aliases"]["caustic_strain"] == "腐蚀变种"
    assert engine["aliases"]["Caustic Strain"] == "腐蚀变种"
    assert engine["aliases"]["Noxious Strain"] == "毒瘴变种"
    # 引擎侧按名字解析（别名 → 正式名）
    plan, warnings = config.build_status_plan(
        {"status": {"variants": [{"name": "caustic_strain", "planets": [100]},
                                 {"name": "Noxious Strain", "planets": [76]}]}},
        engine,
    )
    assert warnings == [], warnings
    assert plan[100]["variants"][0]["name"] == "腐蚀变种"
    assert plan[100]["variants"][0]["ids"] == [1430, 1431]
    assert plan[76]["variants"][0]["name"] == "毒瘴变种"
    assert plan[76]["variants"][0]["ids"] == [1434, 1433]


# ---------------------------------------------------------------- 两份目录一致性


def test_gui_and_engine_catalogs_do_not_drift(gui, engine):
    """同一个变种在 GUI 目录与引擎目录里必须同 ids；分组里的名字引擎侧都得能解析。"""
    variants = engine["variants"]
    for group in gui["groups"]:
        for name in group["variants"]:
            assert name in gui["items"], (group.get("name"), name)
            assert name in variants, (group.get("name"), name)
            assert gui["items"][name]["ids"] == variants[name], name
    # 反向：引擎目录里除了 dev/试验条目，正式名字都应该能在 GUI 目录查到
    for name in variants:
        assert name in gui["items"], name
    assert set(gui["items"]) == set(variants)


def test_no_grouped_variant_is_registered_twice(gui):
    """同一对 ids 挂在两个名字下会让用户选到重复项（caustic_strain 的老坑）。"""
    seen = {}
    for group in gui["groups"]:
        for name in group["variants"]:
            key = tuple(gui["items"][name]["ids"])
            assert key not in seen, (name, seen.get(key))
            seen[key] = name


def test_gui_catalog_exposes_new_strains_to_the_selector():
    """走 GUI 真正用的入口（Catalogs.variant_entries），确认下拉里能看到两个新变种。"""
    cat = Catalogs()
    labels = dict(cat.variant_entries())      # name -> "分组 · 名称"
    assert "腐蚀变种" in labels and "毒瘴变种" in labels
    assert labels["毒瘴变种"].startswith("虫族")
    assert cat.resolve_variant("毒瘴变种")["ids"] == [1434, 1433]
    assert cat.resolve_variant("腐蚀")["ids"] == [1430, 1431]      # 别名
    assert cat.resolve_variant("caustic_strain")["ids"] == [1430, 1431]


# ---------------------------------------------------------------- 覆盖层规则


def _gen_catalogs_module():
    """tools/ 不是包；按路径临时导入（模块顶层不做 IO，导入安全）。"""
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import gen_catalogs  # noqa: PLC0415 —— 只有本文件的覆盖层测试需要它
    return gen_catalogs


def _source_catalog():
    return {
        "build": "25988413",
        "gameVersion": "1.007.200",
        "note": "note",
        "groups": [
            {"name": "虫族 5", "variants": ["掠食变种"]},
            {"name": "机器人 3", "variants": ["生化人"]},
        ],
        "variants": {"掠食变种": [1243, 1245], "生化人": [1360, 1361]},
        "meta": {
            "掠食变种": {"faction": "terminid", "presence": "bugs_super_predator"},
            "生化人": {"faction": "automaton", "presence": "bots_cyborgs"},
        },
        "aliases": {"掠食": "掠食变种"},
    }


def test_overlay_appends_to_group_and_renumbers(monkeypatch, tmp_path):
    gen = _gen_catalogs_module()
    overlay = {
        "items": {"毒瘴变种": {"ids": [1434, 1433], "faction": "terminid",
                             "presence": "bugs_defiler", "tag": 1434, "mechanic": 1433}},
        "aliases": {"Noxious Strain": "毒瘴变种"},
        "groups": [{"match": "虫族", "append": ["毒瘴变种"]}],
    }
    merged = gen.apply_variant_overlay(_source_catalog(), overlay)
    group = merged["groups"][0]
    assert group["name"] == "虫族 2"           # 数量后缀跟着实际条数
    assert group["variants"] == ["掠食变种", "毒瘴变种"]
    assert merged["variants"]["毒瘴变种"] == [1434, 1433]
    assert merged["meta"]["毒瘴变种"]["presence"] == "bugs_defiler"
    assert merged["meta"]["毒瘴变种"]["tag"] == 1434
    assert merged["aliases"]["Noxious Strain"] == "毒瘴变种"
    assert merged["aliases"]["掠食"] == "掠食变种"   # 原有别名保留
    # 源数据不被就地修改（同一份源可重跑第二次）
    assert _source_catalog()["groups"][0]["name"] == "虫族 5"


def test_overlay_remove_then_readd_same_name():
    """改名场景：先 remove 旧名，再用同 id 建中文名（本仓库补 caustic 的做法）。"""
    gen = _gen_catalogs_module()
    source = _source_catalog()
    source["variants"]["caustic_strain"] = [1430, 1431]
    source["meta"]["caustic_strain"] = {"faction": "terminid", "presence": "bugs_acid"}
    overlay = {
        "remove": ["caustic_strain"],
        "items": {"腐蚀变种": {"ids": [1430, 1431], "faction": "terminid",
                             "presence": "bugs_acid"}},
        "aliases": {"caustic_strain": "腐蚀变种"},
        "groups": [{"match": "虫族", "append": ["腐蚀变种"]}],
    }
    merged = gen.apply_variant_overlay(source, overlay)
    assert "caustic_strain" not in merged["variants"]
    assert merged["variants"]["腐蚀变种"] == [1430, 1431]
    assert merged["aliases"]["caustic_strain"] == "腐蚀变种"


@pytest.mark.parametrize("overlay,needle", [
    ({"items": {"x": {"ids": []}}}, "ids"),
    ({"items": {"掠食变种": {"ids": [1]}}}, "重名"),
    ({"aliases": {"别名": "不存在"}}, "不存在"),
    ({"groups": [{"match": "虫族", "append": ["不存在"]}]}, "不存在的变种"),
    ({"groups": [{"match": "不存在的组", "append": []}]}, "命中 0 个分组"),
    ({"remove": ["不存在"]}, "不在源目录"),
])
def test_overlay_rejects_inconsistent_input(overlay, needle):
    """覆盖层写错要立刻炸，不能静默产出半对的目录。"""
    gen = _gen_catalogs_module()
    with pytest.raises(gen.SourceError) as exc:
        gen.apply_variant_overlay(_source_catalog(), overlay)
    assert needle in str(exc.value)


def test_overlay_none_is_noop():
    """干净 checkout（没有覆盖层文件）时按纯源目录生成，不报错。"""
    gen = _gen_catalogs_module()
    source = _source_catalog()
    assert gen.apply_variant_overlay(source, {}) == source


def test_engine_catalog_is_generated_from_the_same_source(tmp_path):
    """引擎目录的键序/结尾格式必须稳定（M0 迁入的那份文件逐字节可比）。"""
    gen = _gen_catalogs_module()
    merged = gen.apply_variant_overlay(_source_catalog(), {})
    doc = gen.build_legacy(merged)
    assert list(doc) == ["build", "gameVersion", "note", "groups", "variants", "meta", "aliases"]
    out = tmp_path / "variant_catalog.json"
    gen.write_legacy(out, doc)
    text = out.read_text(encoding="utf-8")
    assert not text.endswith("\n")             # 与迁入文件一致：结尾不带换行
    assert json.loads(text)["variants"] == merged["variants"]
