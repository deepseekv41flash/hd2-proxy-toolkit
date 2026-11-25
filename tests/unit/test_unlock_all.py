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
    assert ids[:5] == [111, 222, 333, 444, 555]
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
    added = unlock_all.inject_inventory(items)
    assert added == len(unlock_all.ownable_ids()) - 1      # 111 已有
    row = next(r for r in items if r["mixId"] == 333)
    assert row["isDiscovered"] is True, "护甲/披风需要 isDiscovered=true"
    assert unlock_all.inject_inventory(items) == 0, "二次调用幂等"


# ---------------------------------------------------------------- 舰船模块包等级

def test_patch_progression_sets_six_packages_to_max():
    doc = {"experience": 1, "packageProgress": [
        {"id32": 131213678, "level": 0, "progress": 5, "sortOrder": 0, "claimedLevels": []},
        {"id32": 999, "level": 2, "progress": 0, "sortOrder": 0, "claimedLevels": []},
    ]}
    body, changed = unlock_all.patch_progression(json.dumps(doc))
    out = json.loads(body)
    assert changed >= len(unlock_all.SHIP_MODULE_PACKAGES) - 1
    by_id = {e["id32"]: e for e in out["packageProgress"]}
    for pid in unlock_all.SHIP_MODULE_PACKAGES:
        assert by_id[pid]["level"] == unlock_all.SHIP_MODULE_MAX_LEVEL
    assert by_id[999]["level"] == 2, "不相关包不动"
    # 幂等
    assert unlock_all.patch_progression(body) == (None, 0)


def test_patch_progression_no_array_is_noop():
    assert unlock_all.patch_progression(json.dumps({"experience": 1})) == (None, 0)
    assert unlock_all.patch_progression(b"not json") == (None, 0)


def test_progression_hook_applies_unlock():
    body = json.dumps({"experience": 1, "packageProgress": []}).encode()
    new_body, n = prog_hook.apply(body, None, unlock_all_enabled=True)
    assert n == len(unlock_all.SHIP_MODULE_PACKAGES)
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
    assert added == len(unlock_all.ownable_ids())
    rows = json.loads(body)["items"]
    assert all(r["isDiscovered"] is True or r["mixId"] == 897894480 for r in rows)
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
