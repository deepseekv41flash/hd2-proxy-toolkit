"""一键解锁全部物品（v0.10.1）单测。

覆盖：目录展开规则、范围收窄、profile 校验、规格注入（inventory hook）、幂等、缺目录兜底。
设计见 `engine/item_catalog.py`：在架 + 有 mixId + 非货币 + 非空号默认拥有。
"""

import json

import pytest

from hd2proxy.engine import config, item_catalog
from hd2proxy.engine.hooks import inventory as inv_hook

HOST = "api.live.prod.thehelldiversgame.com"


# ---------------------------------------------------------------- 目录展开

def test_expand_real_catalog():
    ids, st = item_catalog.unlock_all_ids()
    assert st["catalogRows"] > 3000, st
    assert len(ids) > 2000, st
    assert len(ids) == len(set(ids)), "展开结果必须去重"
    assert all(isinstance(i, int) and i > 0 for i in ids)
    assert st["rows"] == len(ids)
    # 排除规则真的生效
    assert st["skippedCurrency"] > 0
    assert st["skippedDefaultOwned"] > 0
    assert st["skippedNotInCatalog"] > 0


def test_expand_scope_weapon_only():
    rows = item_catalog.load_rows()
    expected = [int(r["mix_id"]) for r in rows
                if r.get("in_catalog") is not False
                and str(r.get("category") or "").lower() == "weapon"
                and not r.get("default_owned")
                and r.get("mix_id") is not None]
    ids, st = item_catalog.unlock_all_ids(scope=["weapon"])
    assert st["scope"] == ["weapon"]
    assert ids == list(dict.fromkeys(expected))
    assert 50 < len(ids) < 200, len(ids)
    assert st["skippedScope"] > 0


def test_expand_missing_catalog_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(item_catalog, "CATALOG_PATH", tmp_path / "nope.json")
    ids, st = item_catalog.unlock_all_ids()
    assert ids == [] and st["catalogRows"] == 0


def test_unlock_all_summary_counts():
    st = item_catalog.unlock_all_summary()
    ids, _ = item_catalog.unlock_all_ids()
    assert st["count"] == len(ids)


# ---------------------------------------------------------------- 规格注入

def test_spec_expands_and_enables_inventory():
    prof = config.default_profile()
    assert prof["inventory"]["unlock_all"] is False
    assert config.to_engine_spec(prof).inventory is None

    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    assert spec.inventory is not None
    ids, _st = item_catalog.unlock_all_ids()
    assert len(spec.inventory["items"]) == len(ids)
    assert spec.inventory["unlockAll"]["added"] == len(ids)
    assert all(row["amount"] == 1 and row["isDiscovered"] is False
               for row in spec.inventory["items"])


def test_spec_does_not_duplicate_explicit_rows():
    prof = config.default_profile()
    first = item_catalog.unlock_all_ids()[0][0]
    prof["inventory"]["weapons"] = [{"mixId": first, "amount": 1, "isDiscovered": True}]
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    mids = [row["mixId"] for row in spec.inventory["items"]]
    assert mids.count(first) == 1
    assert len(mids) == len(set(mids))


def test_inventory_hook_injects_all_and_is_idempotent():
    prof = config.default_profile()
    prof["inventory"]["unlock_all"] = True
    spec = config.to_engine_spec(prof)
    raw = json.dumps({"items": [{"mixId": 897894480, "amount": 1,
                                 "isDiscovered": False}]}).encode()
    body, added, removed = inv_hook.inventory_rewrite(raw, spec=spec.inventory)
    assert added == spec.inventory["unlockAll"]["added"]
    assert removed == 0
    doc = json.loads(body)
    assert len(doc["items"]) == added + 1
    # 再跑一次（客户端轮询）→ 不重复注入
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
    assert doc["inventory"]["unlock_scope"] == ["weapon", "attachment"]   # 归一化小写

    prof["inventory"]["unlock_scope"] = ["weapon", "banana"]
    _doc, errors, _ = config.validate(prof)
    assert any("unlock_scope" in e for e in errors), errors
