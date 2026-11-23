"""G5+ 购买/解锁响应入账（`hooks/purchase.py` + `ActiveSave.record_purchase`）单测。

样本来自旧研究仓 `variant-net` 的逐字节实证（UNLOCK-MAP-2026-11-06 §3.1 / API-ENDPOINTS §8·§10）。
钉住三条约束：增量去重（防双扣）、正负语义、seasonpass 的 +85 是累计计数器不是"获得"。
"""

import json

from hd2proxy.engine import active_save, saves
from hd2proxy.engine.hooks import purchase

STEAM_A = "76561198968648344"

ACQUIRE_RESP = {"packageId32": 2221505542,
                "inventoryChanges": [{"mixId": 3608481516, "amount": -5000},
                                     {"mixId": 718265621, "amount": 1}]}
ACQUIRE_REQ = {"expectedCost": [{"mixId": 3608481516, "amount": 5000}],
               "itemMixId": 718265621, "targetLevel": 7, "packageId32": 2221505542}
SEASONPASS_RESP = {"items": [{"mixId": 1276729503, "amount": -85},
                             {"mixId": 3859732805, "amount": 1},
                             {"mixId": 905852432, "amount": 85}],
                   "packageProgress": []}
SEASONPASS_REQ = {"expectedCost": [{"mixId": 1276729503, "amount": 85}],
                  "seasonPassItemId": 919, "warId": 801}


def make_save(root, amounts=None):
    sid = saves.save_id_for(STEAM_A)
    st = saves.SaveStore(sid, root=root)
    doc = saves.empty_save(sid)
    doc["earned"]["inventory_amounts"] = dict(amounts or {})
    doc["identity"] = {"hd2_account_id": None, "steam_id": STEAM_A,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    st.save(doc)
    saves.write_last(sid, STEAM_A, None, root=root)
    return sid


# ---------------------------------------------------------------- 纯函数


def test_kind_of():
    assert purchase.kind_of("/api/Progression/ProgressionPackage/AcquireUnlockableItem") == "acquire"
    assert purchase.kind_of("/api/SeasonPass/item/buy") == "seasonpass"
    assert purchase.kind_of("/api/SeasonPass/item/buy?x=1") == "seasonpass"
    assert purchase.kind_of("/api/SeasonPass") == ""
    assert purchase.kind_of("/api/Progression/inventory/consume") == ""
    assert purchase.kind_of("") == ""


def test_extract_acquire_real_sample():
    parsed = purchase.extract_acquire(json.dumps(ACQUIRE_RESP).encode())
    assert parsed["ok"] is True and parsed["kind"] == "acquire"
    assert parsed["package_id32"] == 2221505542
    assert parsed["deltas"] == [{"mixId": 3608481516, "amount": -5000},
                                {"mixId": 718265621, "amount": 1}]


def test_extract_seasonpass_real_sample():
    parsed = purchase.extract_seasonpass(json.dumps(SEASONPASS_RESP).encode())
    assert parsed["ok"] is True and parsed["kind"] == "seasonpass"
    # +85 是 medalsSpentMixId（已花奖章累计计数器），照常作为增量处理，但不描述成"获得"
    assert {"mixId": 905852432, "amount": 85} in parsed["deltas"]
    assert {"mixId": 3859732805, "amount": 1} in parsed["deltas"]


def test_extract_bad_bodies():
    for body in (b"not json", b"{}", b'{"items": "x"}', b"", None):
        assert purchase.extract_acquire(body)["deltas"] == []
        assert purchase.extract_seasonpass(body)["deltas"] == []


def test_expected_cost_and_context():
    assert purchase.extract_expected_cost(json.dumps(ACQUIRE_REQ).encode()) == [
        {"mixId": 3608481516, "amount": 5000}]
    assert purchase.request_context(json.dumps(SEASONPASS_REQ).encode()) == {
        "seasonPassItemId": 919, "warId": 801}
    assert purchase.extract_expected_cost(b"bad") == []


def test_dedupe_key():
    acquire = purchase.extract_acquire(json.dumps(ACQUIRE_RESP).encode())
    assert purchase.dedupe_key(acquire, {}) == "acquire:2221505542:718265621"
    seasonpass = purchase.extract_seasonpass(json.dumps(SEASONPASS_RESP).encode())
    ctx = purchase.request_context(json.dumps(SEASONPASS_REQ).encode())
    assert purchase.dedupe_key(seasonpass, ctx) == "seasonpass:919:801"


# ---------------------------------------------------------------- 入账


def test_record_purchase_applies_negative_and_positive(tmp_path):
    sid = make_save(tmp_path, amounts={"3608481516": 6000})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire",
                              request_body=json.dumps(ACQUIRE_REQ).encode())
    assert out["ok"] is True and out["kind"] == "acquire"
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 1000        # 6000 - 5000
    assert amounts["718265621"] == 1            # 授予：未跟踪 → 建行
    earned = saves.SaveStore(sid, root=tmp_path).load()["earned"]
    assert earned["purchases"]["count"] == 1
    assert earned["purchases"]["recent_keys"] == ["acquire:2221505542:718265621"]
    assert mgr.session_dirty is True
    mgr.close()


def test_record_purchase_floors_at_zero(tmp_path):
    sid = make_save(tmp_path, amounts={"3608481516": 100})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 0 and "3608481516" in amounts
    mgr.close()


def test_record_purchase_dedupes_retry(tmp_path):
    sid = make_save(tmp_path, amounts={"3608481516": 6000})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    dup = mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    assert dup["ok"] is True and dup["duplicate"] is True
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 1000        # 只扣一次
    mgr.close()


def test_record_purchase_after_window_applies_again(tmp_path):
    sid = make_save(tmp_path, amounts={"3608481516": 6000})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    mgr._purchase_seen = {k: 0.0 for k in mgr._purchase_seen}   # 模拟窗口过期
    out = mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    assert out.get("duplicate") is not True
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 0           # 两次扣完（floor 0）
    mgr.close()


def test_record_purchase_seasonpass(tmp_path):
    sid = make_save(tmp_path, amounts={"1276729503": 200})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_purchase(json.dumps(SEASONPASS_RESP).encode(), "seasonpass",
                              request_body=json.dumps(SEASONPASS_REQ).encode())
    assert out["key"] == "seasonpass:919:801"
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["1276729503"] == 115         # 200 - 85
    assert amounts["3859732805"] == 1           # 授予物品
    assert amounts["905852432"] == 85           # 累计计数器 +85（不是"获得奖章"）
    mgr.close()


def test_record_purchase_expected_cost_fallback(tmp_path):
    """响应没有增量（例如被中间层剥掉）→ 用请求 expectedCost 兜底扣费。"""
    sid = make_save(tmp_path, amounts={"3608481516": 6000})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_purchase(b"{}", "acquire",
                              request_body=json.dumps(ACQUIRE_REQ).encode())
    assert out["ok"] is True
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 1000
    mgr.close()


def test_record_purchase_no_data(tmp_path):
    sid = make_save(tmp_path)
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.record_purchase(b"{}", "acquire")["ok"] is False
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    mgr.close()


def test_record_purchase_strict_refused(tmp_path):
    sid = make_save(tmp_path, amounts={"3608481516": 6000})
    mgr = active_save.ActiveSave(root=tmp_path, strict=True, run_id="r1")
    mgr.start()
    mgr.record_purchase(json.dumps(ACQUIRE_RESP).encode(), "acquire")
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3608481516"] == 6000
    assert mgr.session_dirty is False
    mgr.close()


# ---------------------------------------------------------------- 成就对照日志


def test_achievements_lower_value_is_reported(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_achievements(json.dumps(
        {"achievements": [{"id": 6, "value": 1000}]}).encode())
    out = mgr.record_achievements(json.dumps(
        {"achievements": [{"id": 6, "value": 900}]}).encode())
    assert out["ok"] is True and out["recorded"] == 0
    assert out["lower"] == {"6": 900}
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["achievements"]["6"] == 1000
    mgr.close()
