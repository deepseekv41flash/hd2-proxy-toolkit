"""存档层 G2：会话基准快照 / pending 跨重启 / identity 审计 / orphan 差异摘要。

钉住研究线 2026-11-23 反馈的隐患：``.bak`` 是单槽「上一版」，同局连续写 3 次后再回滚
只能退到第 2 次 —— 部分写入留在错误身份的档里。所以回滚源改成会话基准快照。
"""

import json

from hd2proxy.engine import saves

SID = "steam_76561198968648344"


def test_begin_session_snapshot_records_pre_session_state(tmp_path):
    st = saves.SaveStore(SID, root=tmp_path)
    st.add_experience(1000)                       # 会话前就有的进度
    info = saves.begin_session(st, run_id="run1")
    assert info["action"] == "created" and info["existed"] is True
    snap = saves.read_session_snapshot(SID, root=tmp_path)
    assert snap["doc"]["earned"]["experience"] == 1000
    assert snap["run_id"] == "run1" and snap["save_id"] == SID
    # 快照落在 _session-start/ 下（不进档扫描）
    assert (tmp_path / "_session-start" / (SID + ".json")).exists()
    assert saves.find_save_by_hd2("13887067702231565058", root=tmp_path) == ""


def test_session_snapshot_rolls_back_three_writes(tmp_path):
    """研究线场景复现：预绑定身份错 → 本局写 3 次 → 整档回滚（不是只退一次）。"""
    st = saves.SaveStore(SID, root=tmp_path)
    st.add_experience(1000)
    saves.begin_session(st)
    st.add_experience(10)
    st.add_experience(20)
    st.add_experience(30)
    assert st.load()["earned"]["experience"] == 1060
    res = saves.restore_session_snapshot(st)
    assert res["ok"] is True and res["mode"] == "restored" and res["snapshot_sha"]
    # 三次写入全部撤回；而 .bak 单槽回滚只会退到 1050/1030 之间的某一版
    assert st.load()["earned"]["experience"] == 1000


def test_session_snapshot_deletes_save_that_did_not_exist_before(tmp_path):
    """会话前没有这份档（本局新建）→ 回滚 = 整份删除，不留空档占位。"""
    st = saves.SaveStore(SID, root=tmp_path)
    saves.begin_session(st)
    st.add_experience(500)
    assert st.path().exists()
    res = saves.restore_session_snapshot(st)
    assert res == {"ok": True, "mode": "deleted", "snapshot_sha": "",
                   "path": str(tmp_path / "_session-start" / (SID + ".json"))}
    assert not st.path().exists()
    assert st.load()["earned"]["experience"] == 0     # 读回空档，不残留脏数据


def test_restore_without_snapshot_is_noop(tmp_path):
    """无快照 = 本局没写过 → 不动档（研究线选项 3）。"""
    st = saves.SaveStore(SID, root=tmp_path)
    st.add_experience(77)
    before = st.path().read_bytes()
    res = saves.restore_session_snapshot(st)
    assert res["ok"] is False and res["mode"] == "none"
    assert st.path().read_bytes() == before


def test_reuse_keeps_oldest_baseline_across_restart(tmp_path):
    """上局没校验完就崩/关 → 本局沿用**最早**基准，而不是把脏档当基准。"""
    st = saves.SaveStore(SID, root=tmp_path)
    st.add_experience(1000)
    saves.begin_session(st, run_id="run1")
    st.add_experience(10)                          # run1 的脏写入
    info = saves.begin_session(st, run_id="run2", reuse=True)
    assert info["action"] == "reused"
    snap = saves.read_session_snapshot(SID, root=tmp_path)
    assert snap["doc"]["earned"]["experience"] == 1000
    assert snap["run_id"] == "run1"                # 基准还是第 1 局留的


def test_rebase_moves_baseline_to_validated_state(tmp_path):
    """身份校验通过 → 基准重建（= 最后一次已验证点），旧脏写入变成"可信"。"""
    st = saves.SaveStore(SID, root=tmp_path)
    st.add_experience(1000)
    saves.begin_session(st)
    st.add_experience(50)
    info = saves.rebase_session(st, run_id="r1")
    assert info["action"] == "rebased"
    assert saves.read_session_snapshot(SID, root=tmp_path)["doc"]["earned"]["experience"] == 1050


def test_clear_session_snapshot(tmp_path):
    st = saves.SaveStore(SID, root=tmp_path)
    saves.begin_session(st)
    assert saves.clear_session_snapshot(SID, root=tmp_path) is True
    assert saves.read_session_snapshot(SID, root=tmp_path) is None
    assert saves.clear_session_snapshot(SID, root=tmp_path) is False


# ---------------------------------------------------------------- pending


def test_pending_survives_normal_writes_but_not_other_save(tmp_path):
    saves.mark_pending(SID, run_id="r1", root=tmp_path)
    pending = saves.read_pending(root=tmp_path)
    assert pending["save_id"] == SID and pending["run_id"] == "r1" and pending["since"]

    # 普通写档不能清掉 pending（清了就等于宣布"已校验"）
    saves.write_last(SID, "76561198968648344", root=tmp_path)
    assert saves.read_pending(root=tmp_path)["save_id"] == SID

    # 写到**另一个**档时，旧 pending 不跟过去
    saves.write_last("steam_76561199881579811", "76561199881579811", root=tmp_path)
    assert saves.read_pending(root=tmp_path) == {}


def test_clear_pending(tmp_path):
    saves.mark_pending(SID, root=tmp_path)
    saves.clear_pending(root=tmp_path)
    assert saves.read_pending(root=tmp_path) == {}
    assert saves.read_last(root=tmp_path)["last_save_id"] == SID   # 指针保留


def test_pending_age_and_reusable(tmp_path):
    saves.mark_pending(SID, root=tmp_path, since="2020-01-01T00:00:00")
    stale = saves.read_pending(root=tmp_path)
    assert saves.pending_age_hours(stale) > saves.PENDING_MAX_AGE_HOURS
    assert saves.pending_reusable(stale) is False        # 过期 → 宁可重新取基准

    saves.mark_pending(SID, root=tmp_path)               # 现在
    fresh = saves.read_pending(root=tmp_path)
    assert saves.pending_reusable(fresh) is True
    assert saves.pending_age_hours({}) is None
    assert saves.pending_age_hours({"since": "不是时间"}) is None
    assert saves.pending_reusable({}) is False


# ---------------------------------------------------------------- identity 审计


def test_identity_source_and_identified_at(tmp_path):
    st = saves.SaveStore(SID, root=tmp_path)
    st.set_identity("13887067702231565058", "76561198968648344", source="getmotd")
    ident = st.load()["identity"]
    assert ident["source"] == "getmotd"
    assert ident["identified_at"]
    first_at = ident["identified_at"]
    # 后到的来源不覆盖「第一次识别时刻」（排查用）
    st.set_identity(None, None, source="adopted")
    ident2 = st.load()["identity"]
    assert ident2["identified_at"] == first_at and ident2["source"] == "adopted"


def test_local_save_never_gets_identified_at(tmp_path):
    st = saves.SaveStore("local", root=tmp_path)
    st.set_identity(None, "76561198968648344", source="getmotd")
    ident = st.load()["identity"]
    assert ident["steam_id"] == "76561198968648344"
    assert ident["identified_at"] is None          # local 不算已识别


# ---------------------------------------------------------------- 审计工具


def test_earned_diff_reports_scalars_and_container_changes():
    before = {"experience": 100, "achievements": {"1": 1}, "inventory_ids": [1, 2]}
    after = {"experience": 150, "achievements": {"1": 1, "2": 3}, "inventory_ids": [2, 3]}
    diff = saves.earned_diff(before, after)
    assert diff["experience"] == {"before": 100, "after": 150}
    # 数值字典（成就计数/货币/数量）：给**具体数值**，人工才能判断"哪笔钱该不该退"
    assert diff["achievements"]["currency"] is True
    assert diff["achievements"]["added"] == {"2": 3}
    # 列表（解锁 id）只给增删项
    assert diff["inventory_ids"]["added"] == [3]
    assert diff["inventory_ids"]["removed"] == [1]
    assert saves.earned_diff(before, before) == {}


def test_earned_diff_truncates_long_change_sets():
    before = {str(i): i for i in range(20)}
    after = {str(i): i + 1 for i in range(20)}
    diff = saves.earned_diff({"achievements": before}, {"achievements": after})
    changed = diff["achievements"]["changed"]
    assert "…" in changed and len(changed) == 9            # 8 条 + 截断标记
    assert "+12" == changed["…"]
    assert set(changed) - {"…"} <= set(before)


def test_doc_sha_is_canonical():
    assert saves.doc_sha({"a": 1, "b": 2}) == saves.doc_sha({"b": 2, "a": 1})
    assert saves.doc_sha(None) == ""
    assert len(saves.doc_sha({"a": 1})) == 16
