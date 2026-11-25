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
    body = json.dumps({"experience": 1, "packageProgress": []}).encode()
    new_body, n = prog_hook.apply(body, None, unlock_all_enabled=True)
    assert n == len(unlock_all.SHIP_MODULE_PACKAGES) + len(unlock_all.WEAPON_PACKAGES)
    assert new_body is not None
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
