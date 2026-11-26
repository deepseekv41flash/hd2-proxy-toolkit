"""一键解锁全部物品（v0.10.1-alpha.2）单测。

alpha.1 用离线目录在规格期展开 → 实机护甲/披风只出 3 件、舰船模块 0 件（2026-11-25 反馈）。
alpha.2 改为：**请求期**按运行时客户端目录展开（isDiscovered=true）+ 舰船模块 6 条包等级置满
+ 6 个 requiredItems 补进库存。覆盖：目录缓存/回退、授予行、包等级、幂等、配置校验。
"""

import json

import pytest

from hd2proxy.engine import config, item_catalog, unlock_all
from hd2proxy.engine.hooks import inventory as inv_hook
from hd2proxy.engine.hooks import progression as prog_hook

LIVE = [
    {"mixId": 111, "itemId": 111, "progressionCategory": 1, "requiredLevel": 0},
    {"mixId": 222, "itemId": None, "progressionCategory": 2, "parentId": 111},
    {"mixId": 333, "itemId": 333, "progressionCategory": 3},     # 披风
    {"mixId": 444, "itemId": 444, "progressionCategory": 4},     # 护甲
    {"mixId": 555, "itemId": None, "progressionCategory": 11},   # 战备
    {"mixId": 999, "itemId": 999, "progressionCategory": 18},    # 货币 → 排除
]


@pytest.fixture(autouse=True)
def _clear_cache():
    unlock_all.reset()
    yield
    unlock_all.reset()


# ---------------------------------------------------------------- 目录与展开

def test_set_catalog_and_ownable_ids():
    assert unlock_all.set_catalog(LIVE) == len(LIVE)
    ids = unlock_all.ownable_ids()
    assert ids[:5] == [111, 222, 333, 444, 555]      # 目录顺序（全部类目，仅排除货币）
    assert 999 not in ids, "货币（pc18）不注入"
    for mid in unlock_all.SHIP_MODULE_REQUIRED_ITEMS:
        assert mid in ids, "6 个舰船模块前置物品必须补进库存"


def test_fallback_to_offline_catalog_when_no_live():
    ids = unlock_all.ownable_ids()
    off, _ = item_catalog.unlock_all_ids()
    assert len(ids) >= len(off) > 2000
    for mid in unlock_all.SHIP_MODULE_REQUIRED_ITEMS:
        assert mid in ids


def test_inject_marks_discovered_and_is_idempotent():
    unlock_all.set_catalog(LIVE)
    items = [{"mixId": 111, "amount": 1, "isDiscovered": False}]
    added, skipped = unlock_all.inject_inventory(items)
    assert added == len(unlock_all.ownable_ids()) - 1      # 111 已有
    assert skipped == 0
    row = next(r for r in items if r["mixId"] == 333)
    assert row["isDiscovered"] is False, "默认 false（真实数据 1030 行全 false；true 会坏改装）"
    assert unlock_all.inject_inventory(items) == (0, 0), "二次调用幂等"


# ---------------------------------------------------------------- 舰船模块包等级

def test_patch_progression_sets_six_packages_to_max():
    doc = {"experience": 1, "packageProgress": [
        {"id32": 131213678, "level": 0, "progress": 5, "sortOrder": 0, "claimedLevels": []},
        {"id32": 999, "level": 2, "progress": 0, "sortOrder": 0, "claimedLevels": []},
    ]}
    body, changed = unlock_all.patch_progression(json.dumps(doc))
    out = json.loads(body)
    assert changed >= len(unlock_all.SHIP_MODULE_PACKAGES) - 1 + len(unlock_all.WEAPON_PACKAGES)
    by_id = {e["id32"]: e for e in out["packageProgress"]}
    for pid in unlock_all.SHIP_MODULE_PACKAGES:
        assert by_id[pid]["level"] == unlock_all.SHIP_MODULE_MAX_LEVEL
    for pid in unlock_all.WEAPON_PACKAGES:
        assert by_id[pid]["level"] == unlock_all.WEAPON_LEVEL_DEFAULT
    assert by_id[999]["level"] == 2, "不相关包不动"
    # 幂等
    assert unlock_all.patch_progression(body) == (None, 0)


def test_patch_progression_no_array_is_noop():
    assert unlock_all.patch_progression(json.dumps({"experience": 1})) == (None, 0)
    assert unlock_all.patch_progression(b"not json") == (None, 0)


def test_progression_hook_applies_unlock():
    body = json.dumps({"experience": 1, "packageProgress": [],
                       "purchasedSeasonPassItems": []}).encode()
    new_body, n = prog_hook.apply(body, None, unlock_all_enabled=True)
    # 包补丁（舰船 6 + 武器 50）+ 战团领取名单 1 处
    assert n == len(unlock_all.SHIP_MODULE_PACKAGES) + len(unlock_all.WEAPON_PACKAGES) + 1
    assert new_body is not None
    assert len(json.loads(new_body)["purchasedSeasonPassItems"]) == 603
    # 关闭时原样返回
    same, z = prog_hook.apply(body, None, unlock_all_enabled=False)
    assert z == 0 and same is body


# ---------------------------------------------------------------- 规格与钩子

def test_spec_sets_flag_not_preexpanded():
    prof = config.default_profile()
    assert config.to_engine_spec(prof).inventory is None
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    ua = spec.inventory["unlockAll"]
    assert ua["enabled"] is True and ua["scope"] == []
    assert spec.inventory["items"] == [], "alpha.2 不在规格期展开（改运行时）"


def test_inventory_hook_injects_from_live_catalog():
    unlock_all.set_catalog(LIVE)
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    raw = json.dumps({"items": [{"mixId": 897894480, "amount": 1,
                                 "isDiscovered": False}]}).encode()
    body, added, removed = inv_hook.inventory_rewrite(raw, spec=spec.inventory)
    # alpha.4：added = 库存行 + 改装条目（LIVE 里只有 1 把带附件的武器）
    assert added == len(unlock_all.ownable_ids()) + 1
    assert json.loads(body)["customization"][0]["mixId32"] == 111
    rows = json.loads(body)["items"]
    assert all(r["isDiscovered"] is False for r in rows), "授予行必须 isDiscovered=false"
    body2, added2, _ = inv_hook.inventory_rewrite(body, spec=spec.inventory)
    assert added2 == 0 and body2 is None


# ---------------------------------------------------------------- 校验

@pytest.mark.parametrize("value,ok", [(True, True), (False, True), ("yes", False), (1, False)])
def test_config_validation_unlock_all(value, ok):
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = value
    _doc, errors, _warn = config.validate(prof)
    assert (not errors) is ok, errors


def test_config_validation_unlock_scope():
    prof = config.default_profile()
    prof["inventory"]["unlock_scope"] = ["weapon", "Attachment"]
    doc, errors, _ = config.validate(prof)
    assert errors == [], errors
    assert doc["inventory"]["unlock_scope"] == ["weapon", "attachment"]

    prof["inventory"]["unlock_scope"] = ["banana"]
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_scope" in e for e in errors), errors


# ---------------------------------------------------------------- 上限与类目白名单


def test_inventory_cap_guard():
    rows = [{"mixId": 10000 + i, "progressionCategory": 1} for i in range(6000)]
    unlock_all.set_catalog(rows)
    items = []
    added, skipped = unlock_all.inject_inventory(items)
    assert added == unlock_all.INVENTORY_CAP - unlock_all.INVENTORY_SAFE_MARGIN
    assert skipped == 6000 + len(unlock_all.SHIP_MODULE_REQUIRED_ITEMS) - added
    assert len(items) == added
    # 已接近上限时不再注入
    full = [{"mixId": i, "amount": 1, "isDiscovered": True} for i in range(4100)]
    assert unlock_all.inject_inventory(full)[0] == 0


# ---------------------------------------------------------------- 改装条目（alpha.4）
#
# 空白号 `/api/Progression/Items/Customize/v2` 是 `{"items":[]}`、主号 74 条 ⇒ 缺「改装」按钮。
# 形状取自客户端自己 PUT 过的空槽：{mixId32, modes:[], activeIndex:0, customizations:[{index:0,slots:[0]*8}]}


def test_customizable_weapons_only_parents():
    """只有目录里**有子项(附件)**的 pc1 武器才算可改装（610/700 无子项 → 排除）。"""
    unlock_all.set_catalog(LIVE + [
        {"mixId": 610, "itemId": 610, "progressionCategory": 1},
        {"mixId": 700, "itemId": 700, "progressionCategory": 1},
        {"mixId": 711, "itemId": 700, "progressionCategory": 2, "parentId": 700},
    ])
    assert unlock_all.customizable_weapons() == [111, 700]


def test_customizable_weapons_empty_without_catalog():
    assert unlock_all.customizable_weapons() == []
    doc = {"items": []}
    assert unlock_all.inject_customizations(doc) == 0
    assert doc["items"] == []


def test_inject_customizations_shape_and_idempotent():
    unlock_all.set_catalog(LIVE)
    doc = {"items": []}
    assert unlock_all.inject_customizations(doc) == 1
    entry = doc["items"][0]
    assert entry == {"mixId32": 111, "modes": [], "activeIndex": 0,
                     "customizations": [{"index": 0, "slots": [0] * 8}]}
    assert unlock_all.inject_customizations(doc) == 0, "第二次必须幂等"


def test_inject_customizations_keeps_existing_presets():
    """玩家已有的真实条目不能动（主号那些非空槽预设必须原样保留）。"""
    unlock_all.set_catalog(LIVE)
    real = {"mixId32": 111, "modes": [1, 0, 0, 0], "activeIndex": 0,
            "customizations": [{"index": 0, "slots": [3441477456, 0, 0, 0, 0, 0, 0, 0]}]}
    doc = {"items": [real]}
    assert unlock_all.inject_customizations(doc) == 0
    assert doc["items"] == [real]


def test_inject_customizations_bad_doc():
    unlock_all.set_catalog(LIVE)
    assert unlock_all.inject_customizations(None) == 0
    assert unlock_all.inject_customizations({"items": "nope"}) == 0
    assert unlock_all.inject_customizations({"items": [{"mixId32": "x"}]}) == 1


def test_customize_hook_fills_when_unlock_all_enabled():
    """真机路径：钩子（无 research 规格）在 unlock_all_enabled 下补条目并返回 bytes。"""
    unlock_all.set_catalog(LIVE)
    raw = json.dumps({"items": []}).encode()
    body, changed = inv_hook.customize_rewrite(raw, spec={}, unlock_all_enabled=True)
    assert changed == 1 and body is not None
    assert json.loads(body)["items"][0]["mixId32"] == 111
    # 关闭时不动
    body2, changed2 = inv_hook.customize_rewrite(raw, spec={}, unlock_all_enabled=False)
    assert (body2, changed2) == (None, 0)


def test_inject_inventory_customizations_flat_shape():
    """inventory 响应里的 customization[]（扁平）同样要补，形状对齐真机（主号 149 条）。"""
    unlock_all.set_catalog(LIVE)
    doc = {"items": [], "customization": [
        {"mixId32": 897894480, "index": 0, "activeIndex": 0, "slots": [1, 0, 0, 0, 0, 0, 0, 0],
         "modes": [1, 0, 0, 0]}]}
    assert unlock_all.inject_inventory_customizations(doc) == 1
    new = [e for e in doc["customization"] if e["mixId32"] == 111]
    assert new == [{"mixId32": 111, "index": 0, "activeIndex": 0,
                    "slots": [0] * 8, "modes": []}]
    assert unlock_all.inject_inventory_customizations(doc) == 0, "幂等"
    assert len(doc["customization"]) == 2


def test_inject_inventory_customizations_creates_missing_key():
    unlock_all.set_catalog(LIVE)
    doc = {"items": []}
    assert unlock_all.inject_inventory_customizations(doc) == 1
    assert doc["customization"][0]["mixId32"] == 111


def test_inventory_hook_fills_customization_when_unlock_all_on():
    unlock_all.set_catalog(LIVE)
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    raw = json.dumps({"items": [], "customization": []}).encode()
    body, added, removed = inv_hook.inventory_rewrite(raw, spec=spec.inventory)
    assert removed == 0
    rows = json.loads(body)["customization"]
    assert [r["mixId32"] for r in rows] == [111]
    assert added == len(unlock_all.ownable_ids()) + 1, "added = 库存行 + 改装条目"


# ---------------------------------------------------------------- 战团领取名单（alpha.5）
#
# 军械库的解锁态（武器等级 / 改装按钮）看 `purchasedSeasonPassItems`：主号 426 条 ⊆ 26 个战团
# `itemIds` 并集 603 条；空白号 0 条 ⇒ 一切按「未领取」显示。这里把并集全按已领取下发。


def test_seasonpass_union_and_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(unlock_all, "WARBOND_ITEMS_FILE", tmp_path / "warbond.json")
    monkeypatch.setattr(unlock_all, "WARBOND_FALLBACK_FILE", tmp_path / "none.json")
    unlock_all.reset()
    rows = [{"id32": 1, "itemIds": [3, 5, 9]}, {"id32": 2, "itemIds": [9, 12]}]
    assert unlock_all.set_seasonpass(rows) == 4        # 3,5,9,12 去重
    assert unlock_all.seasonpass_items() == [3, 5, 9, 12]
    assert (tmp_path / "warbond.json").exists(), "必须落盘（下次会话生效）"
    # 再喂一份更长的 → 取并集，且不丢旧的
    assert unlock_all.set_seasonpass([{"itemIds": [12, 20]}]) == 5
    assert unlock_all.seasonpass_items() == [3, 5, 9, 12, 20]
    assert unlock_all.set_seasonpass("nope") == 5, "坏输入不改缓存"


def test_patch_progression_claims_all_warbonds(tmp_path, monkeypatch):
    monkeypatch.setattr(unlock_all, "WARBOND_ITEMS_FILE", tmp_path / "warbond.json")
    monkeypatch.setattr(unlock_all, "WARBOND_FALLBACK_FILE", tmp_path / "none.json")
    unlock_all.reset()
    unlock_all.set_seasonpass([{"itemIds": [3, 5, 9]}])
    doc = {"packageProgress": [], "purchasedSeasonPassItems": [9, 11]}
    body, changed = unlock_all.patch_progression(json.dumps(doc).encode())
    out = json.loads(body)
    assert out["purchasedSeasonPassItems"] == [9, 11, 3, 5], "原有顺序保留，只补缺的"
    # packageProgress 是空数组 ⇒ 先补 56 条包（舰船 6 + 武器 50），再加 1 处领取名单
    assert changed == len(unlock_all.SHIP_MODULE_PACKAGES) + len(unlock_all.WEAPON_PACKAGES) + 1
    body2, changed2 = unlock_all.patch_progression(body)
    assert (body2, changed2) == (None, 0), "幂等"


def test_patch_progression_without_warbond_data_keeps_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(unlock_all, "WARBOND_ITEMS_FILE", tmp_path / "none.json")
    monkeypatch.setattr(unlock_all, "WARBOND_FALLBACK_FILE", tmp_path / "none2.json")
    unlock_all.reset()
    doc = {"packageProgress": [], "purchasedSeasonPassItems": [7]}
    body, changed = unlock_all.patch_progression(json.dumps(doc).encode())
    assert changed == len(unlock_all.SHIP_MODULE_PACKAGES) + len(unlock_all.WEAPON_PACKAGES)
    assert json.loads(body)["purchasedSeasonPassItems"] == [7], "拿不到战团表就不动领取名单"


def test_bundled_warbond_fallback_is_sane():
    """内置兜底 = 真机 SeasonPass 抓包的 itemIds 并集（603 条）。"""
    ids = unlock_all.seasonpass_items()
    assert len(ids) == 603
    assert min(ids) == 1 and max(ids) == 1007
    assert 510 in ids and 511 in ids, "主号真实领取项必须在名单里"
    assert len(set(ids)) == len(ids), "无重复"


# ---------------------------------------------------------------- 账号级开关（flags / xp，默认关）
#
# 实证：同为代理解锁出来的武器，主号能改装、测试号不能 ⇒ 门槛是**账号级开关**。
# 这里只提供两个可调旋钮用于定位（默认 0 = 不动）：教程位掩码、经验下限。


def test_patch_progression_forge_flags_or_merge():
    doc = {"packageProgress": [], "onboardingFlags": 0x40, "purchasedSeasonPassItems": []}
    body, changed = unlock_all.patch_progression(json.dumps(doc).encode(), forge_flags=0x100)
    out = json.loads(body)
    assert out["onboardingFlags"] == 0x140, "必须是按位或（不清已有位）"
    assert changed >= 1
    body2, changed2 = unlock_all.patch_progression(body, forge_flags=0x100)
    assert changed2 == 0, "已包含则不重复计改动"


def test_patch_progression_forge_xp_only_raises(tmp_path, monkeypatch):
    # 隔离战团兜底：本用例只关心 experience
    monkeypatch.setattr(unlock_all, "WARBOND_ITEMS_FILE", tmp_path / "none.json")
    monkeypatch.setattr(unlock_all, "WARBOND_FALLBACK_FILE", tmp_path / "none2.json")
    unlock_all.reset()
    doc = {"packageProgress": [], "experience": 208, "purchasedSeasonPassItems": []}
    body, _n = unlock_all.patch_progression(json.dumps(doc).encode(), forge_xp=2760148)
    assert json.loads(body)["experience"] == 2760148
    # 用第一次的产物（包已齐）把经验抬高后再跑一次：不应再改动
    high = json.loads(body)
    high["experience"] = 9999999
    body2, n2 = unlock_all.patch_progression(json.dumps(high).encode(), forge_xp=2760148)
    assert (body2, n2) == (None, 0), "只抬不降"


def test_progression_hook_passes_forge_knobs():
    body = json.dumps({"packageProgress": [], "purchasedSeasonPassItems": [],
                       "experience": 10, "onboardingFlags": 0}).encode()
    new_body, n = prog_hook.apply(body, None, unlock_all_enabled=True,
                                  forge_flags=0x7F, forge_xp=500)
    out = json.loads(new_body)
    assert out["onboardingFlags"] == 0x7F and out["experience"] == 500
    assert n > 0


def test_config_validation_forge_knobs():
    prof = config.default_profile()
    assert prof["inventory"]["unlock_flags"] == 0 and prof["inventory"]["unlock_xp"] == 0
    prof["inventory"]["unlock_all"] = True
    prof["inventory"]["unlock_flags"] = 7962491
    prof["inventory"]["unlock_xp"] = 2760148
    _doc, errors, _w = config.validate(prof)
    assert errors == [], errors
    spec = config.to_engine_spec(prof)
    assert spec.inventory["unlockAll"]["flags"] == 7962491
    assert spec.inventory["unlockAll"]["xp"] == 2760148

    prof["inventory"]["unlock_flags"] = -1
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_flags" in e for e in errors)
    prof["inventory"]["unlock_flags"] = 0
    prof["inventory"]["unlock_xp"] = "many"
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_xp" in e for e in errors)


# ---------------------------------------------------------------- 账号等级门槛（alpha.6）
#
# 2026-11-26 实机实证：武器改装按**账号等级**解锁 —— 10 级 / 7,100 经验。
# 依据：wiki Levels 页 Unlocks 表 Level 10 奖励含 "Weapon Attachments"；本 build levelspec 同级 7,100。


def test_level_table_and_xp_lookup():
    rows = unlock_all.level_rows()
    assert len(rows) == 300, "内置等级表 300 级"
    assert unlock_all.xp_for_level(1) == 1
    assert unlock_all.xp_for_level(9) == 5850
    assert unlock_all.xp_for_level(10) == 7100, "10 级 = 7,100 经验（改装解锁阈值）"
    assert unlock_all.xp_for_level(11) == 8400
    assert unlock_all.xp_for_level(0) == 0
    assert unlock_all.xp_for_level("x") == 0
    assert unlock_all.xp_for_level(999) == 11080000, "超出表尾取最后一级"


def test_default_unlock_level_is_ten():
    assert unlock_all.DEFAULT_UNLOCK_LEVEL == 10
    prof = config.default_profile()
    assert prof["inventory"]["unlock_level"] == 10
    assert prof["inventory"]["unlock_xp"] == 0
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    assert spec.inventory["unlockAll"]["level"] == 10
    assert spec.inventory["unlockAll"]["xp"] == 7100, "默认补到 10 级（最小改动）"


def test_unlock_level_zero_keeps_experience():
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = True
    prof["inventory"]["unlock_level"] = 0
    spec = config.to_engine_spec(prof)
    assert spec.inventory["unlockAll"]["xp"] == 0, "0 级 = 不补等级"


def test_unlock_xp_override_wins():
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = True
    prof["inventory"]["unlock_level"] = 20
    prof["inventory"]["unlock_xp"] = 5000
    spec = config.to_engine_spec(prof)
    assert spec.inventory["unlockAll"]["xp"] == 5000


def test_unlock_level_validation():
    prof = config.default_profile()
    prof["inventory"]["unlock_level"] = 301
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_level" in e for e in errors)
    prof["inventory"]["unlock_level"] = True
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_level" in e for e in errors)


def test_level_for_xp():
    assert unlock_all.level_for_xp(0) == 0
    assert unlock_all.level_for_xp(208) == 2
    assert unlock_all.level_for_xp(7099) == 9
    assert unlock_all.level_for_xp(7100) == 10, "7,100 = 恰好 10 级"
    assert unlock_all.level_for_xp(9900) == 12
    assert unlock_all.level_for_xp("x") == 0


def test_patch_progression_raises_xp_only_below_target(tmp_path, monkeypatch):
    """判定式：低于 10 级 → 补到 7,100；≥10 级 → 经验一个字都不动。"""
    monkeypatch.setattr(unlock_all, "WARBOND_ITEMS_FILE", tmp_path / "n1.json")
    monkeypatch.setattr(unlock_all, "WARBOND_FALLBACK_FILE", tmp_path / "n2.json")
    unlock_all.reset()
    target = unlock_all.xp_for_level(unlock_all.DEFAULT_UNLOCK_LEVEL)

    low = {"packageProgress": [], "purchasedSeasonPassItems": [], "experience": 208}
    body, _n = unlock_all.patch_progression(json.dumps(low).encode(), forge_xp=target)
    out = json.loads(body)
    assert out["experience"] == 7100 and unlock_all.level_for_xp(out["experience"]) == 10

    for xp in (7100, 7300, 9900, 2760148):     # 恰好 10 级 / 10 级中段 / 12 级 / 199 级
        doc = json.loads(body)
        doc["experience"] = xp
        body2, n2 = unlock_all.patch_progression(json.dumps(doc).encode(), forge_xp=target)
        if body2 is None:
            continue                            # 完全无改动：经验当然没变
        assert json.loads(body2)["experience"] == xp, "≥10 级不许改经验"


# ---------------------------------------------------------------- 等级编辑（存档页，2026-11-26）


def test_levels_module_lookup():
    from hd2proxy.engine import levels
    levels.reset()
    assert len(levels.rows()) == 300
    assert levels.xp_for_level(10) == 7100
    assert levels.level_for_xp(7100) == 10
    assert levels.level_for_xp(7099) == 9
    assert levels.max_level() == 300
    assert "10 级" in levels.describe(7100)
    assert "距 3 级还差" in levels.describe(208)


def test_set_ledger_experience_writes_with_backup(tmp_path):
    from hd2proxy.engine import saves
    doc = saves.empty_save("steam_42")
    doc["earned"]["experience"] = 208
    saves.SaveStore("steam_42", tmp_path).save(doc)

    res = saves.set_ledger_experience(7100, root=tmp_path)
    assert res["before"] == 208 and res["after"] == 7100
    assert saves.ledger_experience(root=tmp_path)["experience"] == 7100
    assert (tmp_path / "steam_42.json.bak").exists(), "覆盖前必须留 .bak"

    # 合并效果：账本经验以 max 合并进 /api/Progression 响应
    body = json.dumps({"experience": 208, "packageProgress": [],
                       "purchasedSeasonPassItems": []}).encode()
    new_body, _n = saves.apply_to_progression(body, saves.SaveStore("steam_42", tmp_path).load())
    assert json.loads(new_body)["experience"] == 7100


def test_set_ledger_experience_without_ledger_raises(tmp_path):
    from hd2proxy.engine import saves
    with pytest.raises(ValueError):
        saves.set_ledger_experience(7100, root=tmp_path)
    assert saves.ledger_experience(root=tmp_path) == {"save_id": None, "experience": 0}


def test_set_ledger_experience_clamps_negative(tmp_path):
    from hd2proxy.engine import saves
    saves.SaveStore("steam_7", tmp_path).save(saves.empty_save("steam_7"))
    assert saves.set_ledger_experience(-5, root=tmp_path)["after"] == 0, "负值=清除覆盖"
