"""G5 下半：`inventory/consume` 扣减（`hooks/consume.py` + `ActiveSave.record_consume`）单测。

请求体真实形状尚未采样 ⇒ 解析是防御式的；这里钉住口径：
**下限 0、保留行 amount=0 不删行、只扣已跟踪 mixId、形状不认识不扣、INFO 对账日志带 missionId**。
"""

import json

from hd2proxy.engine import active_save, saves
from hd2proxy.engine.hooks import consume

STEAM_A = "76561198968648344"


def make_save(root, amounts=None, experience=1000):
    sid = saves.save_id_for(STEAM_A)
    st = saves.SaveStore(sid, root=root)
    doc = saves.empty_save(sid)
    doc["earned"]["experience"] = experience
    doc["earned"]["inventory_amounts"] = dict(amounts or {})
    doc["identity"] = {"hd2_account_id": None, "steam_id": STEAM_A,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    st.save(doc)
    saves.write_last(sid, STEAM_A, None, root=root)
    return sid


# ---------------------------------------------------------------- 路径 / 解析


def test_is_path():
    assert consume.is_path("/api/Progression/inventory/consume")
    assert consume.is_path("/api/Progression/inventory/consume?x=1")
    assert not consume.is_path("/api/Progression/inventory")
    assert not consume.is_path("/api/Progression/Items/Customize/v2")
    assert not consume.is_path("")


def test_extract_shapes():
    row = {"mixId": 3901895556, "amount": 5}
    for body in ({"items": [row]}, [row], {"consumables": [row]}, {"entries": [row]}):
        assert consume.extract_consumes(json.dumps(body).encode()) == [
            {"mixId": 3901895556, "amount": 5}]
    # 单条目摊平 + mixId32 兼容
    assert consume.extract_consumes({"mixId": 7, "amount": 2}) == [{"mixId": 7, "amount": 2}]
    assert consume.extract_consumes({"items": [{"mixId32": 9, "amount": 1}]}) == [
        {"mixId": 9, "amount": 1}]


def test_extract_real_consumeditems_shell():
    """2026-11-23 实机真实报文外壳：`{"consumedItems":[…],"boosters":[]}`。"""
    body = {"consumedItems": [{"mixId": 548295611, "amount": 1},
                              {"mixId": 2446402932, "amount": 1},
                              {"mixId": 1228689284, "amount": 1},
                              {"mixId": 2616066963, "amount": 1},
                              {"mixId": 3467463065, "amount": 1}],
            "boosters": []}
    rows = consume.extract_consumes(json.dumps(body).encode())
    assert len(rows) == 5 and rows[0] == {"mixId": 548295611, "amount": 1}
    assert consume.is_path("/api/Progression/inventory/consume")


def test_extract_skips_bad_rows():
    body = {"items": [
        {"mixId": 1, "amount": 2},
        {"mixId": 1, "amount": 0},          # 数量 0 → 跳过
        {"mixId": 2, "amount": -3},         # 负数 → 跳过
        {"mixId": "x", "amount": 1},        # 非数字 mixId
        {"mixId": 3},                       # 缺 amount
        "junk",
        {"mixId": 4, "amount": True},       # bool 不当数量
    ]}
    assert consume.extract_consumes(json.dumps(body).encode()) == [{"mixId": 1, "amount": 2}]


def test_extract_unknown_shape():
    for body in (b"not json", b"{}", b'{"foo":1}', json.dumps([1, 2]).encode(), b"", None):
        assert consume.extract_consumes(body) == []


# ---------------------------------------------------------------- 扣减


def test_record_consume_decrements_and_keeps_row(tmp_path):
    sid = make_save(tmp_path, amounts={"3901895556": 10, "897894480": 3})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_consume(json.dumps(
        {"items": [{"mixId": 3901895556, "amount": 4}]}).encode())
    assert out["ok"] is True and out["written"] == 1
    doc = saves.SaveStore(sid, root=tmp_path).load()
    amounts = doc["earned"]["inventory_amounts"]
    assert amounts["3901895556"] == 6           # 10 - 4
    assert amounts["897894480"] == 3            # 其它行不受影响
    assert mgr.session_dirty is True
    mgr.close()


def test_record_consume_floors_at_zero_and_keeps_row(tmp_path):
    """研究线口径：下限 0，但**保留行 amount=0 不删行**（库存行=拥有语义）。"""
    sid = make_save(tmp_path, amounts={"3901895556": 2})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_consume(json.dumps(
        {"items": [{"mixId": 3901895556, "amount": 9}]}).encode())
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert amounts["3901895556"] == 0 and "3901895556" in amounts
    mgr.close()


def test_record_consume_untracked_is_skipped(tmp_path):
    """没基线的 mixId（本机账本没这个数量）→ 不扣、也不凭空造行。"""
    sid = make_save(tmp_path, amounts={"3901895556": 2})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_consume(json.dumps(
        {"items": [{"mixId": 123456, "amount": 1}]}).encode())
    assert out["ok"] is True and out["written"] == 0
    assert out["untracked"] == [{"mixId": "123456", "amount": 1}]
    amounts = saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"]
    assert "123456" not in amounts
    assert mgr.session_dirty is False
    mgr.close()


def test_record_consume_noop_does_not_write(tmp_path):
    """已为 0 的行再消耗 → 不写盘（不留无意义版本）。"""
    sid = make_save(tmp_path, amounts={"3901895556": 0})
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_consume(json.dumps(
        {"items": [{"mixId": 3901895556, "amount": 3}]}).encode())
    assert out["ok"] is True and out["written"] == 0
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    mgr.close()


def test_record_consume_unparsed_does_not_write(tmp_path):
    sid = make_save(tmp_path, amounts={"3901895556": 5})
    before = saves.SaveStore(sid, root=tmp_path).path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_consume(b'{"unknownShell": [{"x": 1}]}')
    assert out["ok"] is False and out["reason"] == "unparsed"
    assert mgr.session_dirty is False
    assert saves.SaveStore(sid, root=tmp_path).path().read_bytes() == before
    mgr.close()


def test_record_consume_strict_refused(tmp_path):
    sid = make_save(tmp_path, amounts={"3901895556": 5})
    mgr = active_save.ActiveSave(root=tmp_path, strict=True, run_id="r1")
    mgr.start()
    mgr.record_consume(json.dumps({"items": [{"mixId": 3901895556, "amount": 2}]}).encode())
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["inventory_amounts"][
        "3901895556"] == 5
    assert mgr.session_dirty is False
    mgr.close()


def test_record_consume_logs_info_with_mission(tmp_path, monkeypatch):
    """实机对账日志：`CONSUME mixId=… amount=…：存档 A → B（mission …）`。"""
    lines = []
    monkeypatch.setattr(active_save, "log", lambda msg, *a, **kw: lines.append(msg))
    sid = make_save(tmp_path, amounts={"3901895556": 8})
    st = saves.SaveStore(sid, root=tmp_path)
    doc = st.load()
    doc["earned"]["missions"] = {"count": 1, "recent_ids": ["m-1"],
                                 "last": {"mission": {"mission_id": "m-1"}}}
    st.save(doc)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_consume(json.dumps({"items": [{"mixId": 3901895556, "amount": 3}]}).encode())
    text = "\n".join(lines)
    assert "UNLOCK-COST mixId=3901895556 amount=3：存档 8 → 5（mission m-1）" in text
    mgr.close()


def test_consumed_amount_shows_when_ledger_was_above_server(tmp_path):
    """账本数量高于服务端时（本机收益场景），扣减后的数量会如实显示出来。"""
    sid = make_save(tmp_path, amounts={"3901895556": 10})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_consume(json.dumps({"items": [{"mixId": 3901895556, "amount": 4}]}).encode())
    mgr.close()

    body = json.dumps({"items": [{"mixId": 3901895556, "amount": 2, "isDiscovered": False}]}).encode()
    mgr2 = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr2.start()
    import hd2proxy.engine.saves as _saves
    out, changed = _saves.apply_to_inventory(body, mgr2._store.load())
    got = json.loads(out)
    assert changed == 1 and got["items"][0]["amount"] == 6      # 账本 10-4=6 > 服务端 2
    assert len(got["items"]) == 1                              # 行保留（不新增、不删除）
    mgr2.close()


def test_consumed_amount_never_lowers_real_server_value(tmp_path):
    """账本低于服务端（历史基线未知）时，扣减不会把服务端数量改小 —— 只抬不降。"""
    sid = make_save(tmp_path, amounts={"3901895556": 2})
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_consume(json.dumps({"items": [{"mixId": 3901895556, "amount": 5}]}).encode())
    mgr.close()

    body = json.dumps({"items": [{"mixId": 3901895556, "amount": 500, "isDiscovered": False}]}).encode()
    mgr2 = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr2.start()
    import hd2proxy.engine.saves as _saves
    out, changed = _saves.apply_to_inventory(body, mgr2._store.load())
    assert changed == 0 and json.loads(out)["items"][0]["amount"] == 500
    mgr2.close()
