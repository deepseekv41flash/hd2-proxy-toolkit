"""引擎侧 activeSave（G2/G3）单测：首屏预绑定 / 身份校验 / 换号回滚 / 结算入账。

全部离线：存档根目录用 tmp_path 注入，不起代理、不碰真实状态目录。
"""

import json
import time
from pathlib import Path

from hd2proxy.engine import active_save, saves

STEAM_A = "76561198968648344"
STEAM_B = "76561199881579811"
HD2_A = "13887067702231565058"
HD2_B = "11893343864225233967"


def make_save(root, steam_id=STEAM_A, experience=1000):
    """造一份「已识别」的档 + 写 _last.json 指针（= 玩家上次玩过的状态）。"""
    sid = saves.save_id_for(steam_id)
    st = saves.SaveStore(sid, root=root)
    doc = saves.empty_save(sid)
    doc["earned"]["experience"] = experience
    doc["identity"] = {"hd2_account_id": None, "steam_id": steam_id,
                       "source": "getmotd", "identified_at": "2026-11-20T10:00:00"}
    st.save(doc)
    saves.write_last(sid, steam_id, None, root=root)
    return sid


def prog_body(experience=10):
    return json.dumps({"experience": experience, "achievements": [],
                       "packageProgress": []}).encode("utf-8")


# ---------------------------------------------------------------- 首屏


def test_start_prebinds_from_last(tmp_path):
    sid = make_save(tmp_path, experience=5000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    st = mgr.start()
    assert st["save_id"] == sid and st["origin"] == "last"
    assert st["verified"] is False and st["session_dirty"] is False
    # 会话基准 = 启动时状态；pending 已打标（身份尚未校验）
    assert saves.read_session_snapshot(sid, root=tmp_path)["doc"]["earned"]["experience"] == 5000
    assert saves.read_pending(root=tmp_path)["save_id"] == sid
    mgr.close()


def test_first_progression_renders_prebound_save(tmp_path):
    make_save(tmp_path, experience=5000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out, changed = mgr.apply_progression(prog_body(10))
    assert changed == 1
    assert json.loads(out)["experience"] == 5000        # 首屏按预绑定档渲染
    assert mgr.status()["events"][-1]["kind"] == "progression"
    mgr.close()


def test_progression_noop_returns_same_body(tmp_path):
    make_save(tmp_path, experience=0)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    body = prog_body(10)
    out, changed = mgr.apply_progression(body)
    assert changed == 0 and out is body                 # 无改动 → 引用不变（上层判等用）
    mgr.close()


def test_no_last_waits_limited_then_renders_local(tmp_path):
    """无 _last 且身份未知：首屏最多等 wait_seconds，等不到就按 local 渲染（不挂起）。"""
    st = saves.SaveStore("local", root=tmp_path)
    st.add_experience(700)                              # 空号第一局已经挣到的东西
    mgr = active_save.ActiveSave(root=tmp_path, wait_seconds=0.05, run_id="r1")
    mgr.start()
    assert mgr.save_id == "local" and mgr.origin == "local"
    t0 = time.monotonic()
    out, changed = mgr.apply_progression(prog_body(1))
    elapsed = time.monotonic() - t0
    assert 0.04 <= elapsed < 1.0                        # 等了但没挂住
    assert mgr.wait_took is not None and mgr.wait_took >= 0.04
    assert changed == 1 and json.loads(out)["experience"] == 700
    # 身份到达后：local 合并进 steam 档（不丢空号进度）
    info = mgr.on_getmotd(STEAM_A)
    assert info["action"] == "merged" and info["old_identified"] is False
    assert mgr.save_id == saves.save_id_for(STEAM_A) and mgr.verified is True
    assert saves.SaveStore(mgr.save_id, root=tmp_path).load()["earned"]["experience"] == 700
    assert saves.read_pending(root=tmp_path) == {}
    mgr.close()


def test_no_last_zero_wait_skips_waiting(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, wait_seconds=0, run_id="r1")
    mgr.start()
    t0 = time.monotonic()
    mgr.apply_progression(prog_body())
    assert time.monotonic() - t0 < 0.5 and mgr.wait_took is None
    mgr.close()


# ---------------------------------------------------------------- v0.8.0：结算原始响应落盘

def test_record_mission_end_stores_raw_response(tmp_path):
    """v0.8.0：结算原始响应整份存进账本（供自建服回放 mission_end.json）。"""
    sid = make_save(tmp_path, experience=0)
    payload = {"experience": 936, "campaignWon": False, "impact": 0,
               "missionId": "m-raw-1", "operationId": 1284,
               "rewards": [{"mixId": 3608481516, "amount": 4434}]}
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_mission_end(json.dumps(payload).encode())
    doc = saves.SaveStore(sid, root=tmp_path).load()
    ms = doc["earned"]["missions"]
    assert ms["last_response"] == payload
    assert ms["last_response_at"]
    assert ms["last"]["experience"] == 936 and ms["count"] == 1
    mgr.close()


def test_record_mission_end_duplicate_keeps_first_raw(tmp_path):
    sid = make_save(tmp_path, experience=0)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    first = {"experience": 936, "missionId": "dup-1"}
    second = {"experience": 936, "missionId": "dup-1", "extra": {"x": 1}}
    mgr.record_mission_end(json.dumps(first).encode())
    mgr.record_mission_end(json.dumps(second).encode())      # 同 missionId → 去重
    ms = saves.SaveStore(sid, root=tmp_path).load()["earned"]["missions"]
    assert ms["last_response"] == first                       # 不覆盖
    assert ms["count"] == 1
    mgr.close()


# ---------------------------------------------------------------- G5 live 库存合并


def test_apply_inventory_raises_and_fills_rows(tmp_path):
    """`/api/Progression/inventory` 响应合并账本：只抬不降 + 缺行补行（不缩小服务端值）。"""
    sid = make_save(tmp_path, experience=10)
    st = saves.SaveStore(sid, root=tmp_path)
    doc = st.load()
    doc["earned"]["inventory_amounts"] = {"3901895556": 699, "718265621": 1}
    st.save(doc)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1", preverify_merge="full")
    mgr.start()
    body = json.dumps({"items": [{"mixId": 3901895556, "amount": 999999,
                                  "isDiscovered": True}]}).encode("utf-8")
    out, changed = mgr.apply_inventory(body)
    rows = {int(r["mixId"]): r for r in json.loads(out)["items"]}
    assert rows[3901895556]["amount"] == 999999        # 服务端更大 → 听服务端
    assert rows[718265621]["amount"] == 1              # 上游没有 → 账本补行
    assert changed == 1 and mgr.status()["events"][-1]["kind"] == "inventory"
    # 无改动时引用不变（上层判等用）
    body2 = json.dumps({"items": [{"mixId": 3901895556, "amount": 999999},
                                  {"mixId": 718265621, "amount": 1}]}).encode("utf-8")
    out2, changed2 = mgr.apply_inventory(body2)
    assert changed2 == 0 and out2 is body2
    # 上游连 items 都不给（私服/极简 mock）→ 视为空库存，账本补行
    out3, changed3 = mgr.apply_inventory(b'{"id":801}')
    rows3 = {int(r["mixId"]): r["amount"] for r in json.loads(out3)["items"]}
    assert rows3 == {3901895556: 699, 718265621: 1} and changed3 == 2
    mgr.close()


# ---------------------------------------------------------------- 身份校验


def test_identity_match_verifies_and_clears_pending(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    info = mgr.on_getmotd(STEAM_A)
    assert info["action"] == "same" and mgr.verified is True
    assert saves.read_pending(root=tmp_path) == {}
    # 基准重建到「已验证状态」
    assert saves.read_session_snapshot(sid, root=tmp_path)["doc"]["identity"]["steam_id"] == STEAM_A
    mgr.close()


def test_repeated_getmotd_does_not_rewrite_save(tmp_path):
    """真实会话 46 分钟 7 次 GetMotd：重复到达不该反复写档/刷 .bak。"""
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_A)
    st = saves.SaveStore(sid, root=tmp_path)
    before = st.path().read_bytes()
    mgr.on_getmotd(STEAM_A)
    mgr.on_getmotd(STEAM_A)
    assert st.path().read_bytes() == before
    mgr.close()


def test_getmessages_records_hd2_alias_only(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_A)
    mgr.on_getmessages(HD2_A)
    ident = saves.SaveStore(sid, root=tmp_path).load()["identity"]
    assert ident["hd2_account_id"] == HD2_A and ident["steam_id"] == STEAM_A
    assert mgr.save_id == sid                            # 主键不变（HD2 只是别名）
    mgr.close()


def test_switch_on_getmotd_does_not_carry_previous_hd2(tmp_path):
    """换号时 GetMotd 先到（GetMessages 还没来）：新档不得带上一位玩家的 HD2 别名。

    2026-11-23 实机 ④ 换号验收暴露：预绑定档的 hd2 被写进空号新档，GetMessages 到达
    才纠正（约 1 分钟窗口）。身份别名属于「某账号」，跨账号切档时必须丢弃。
    """
    sid_a = make_save(tmp_path, STEAM_A, experience=1000)
    saves.SaveStore(sid_a, root=tmp_path).set_identity(HD2_A, STEAM_A, source="getmotd")
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    info = mgr.on_getmotd(STEAM_B)                     # 空号这局：GetMotd 先到
    assert info["action"] == "switched"
    fresh = saves.SaveStore(saves.save_id_for(STEAM_B), root=tmp_path).load()["identity"]
    assert fresh["steam_id"] == STEAM_B
    assert fresh.get("hd2_account_id") is None        # 不带主号别名
    mgr.on_getmessages(HD2_B)                          # 本局别名后到 → 同档补上
    fresh = saves.SaveStore(saves.save_id_for(STEAM_B), root=tmp_path).load()["identity"]
    assert fresh["hd2_account_id"] == HD2_B
    mgr.close()


def test_switch_back_does_not_overwrite_target_hd2(tmp_path):
    """切回主号：目标档已有自己的 hd2，本局（空号）的别名不得覆盖它。"""
    sid_a = make_save(tmp_path, STEAM_A, experience=1000)
    saves.SaveStore(sid_a, root=tmp_path).set_identity(HD2_A, STEAM_A, source="getmotd")
    sid_b = saves.save_id_for(STEAM_B)
    saves.SaveStore(sid_b, root=tmp_path).set_identity(HD2_B, STEAM_B, source="getmotd")
    saves.write_last(sid_a, STEAM_A, HD2_A, root=tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.on_getmotd(STEAM_B)          # 切到空号
    mgr.on_getmessages(HD2_B)        # 空号别名到达（本局观测=B）
    info = mgr.on_getmotd(STEAM_A)   # 切回主号
    assert info["action"] == "switched" and mgr.save_id == sid_a
    ident_a = saves.SaveStore(sid_a, root=tmp_path).load()["identity"]
    assert ident_a["hd2_account_id"] == HD2_A         # 主号自己的别名不被空号覆盖
    assert ident_a["steam_id"] == STEAM_A
    mgr.close()


def test_hd2_first_for_other_account_does_not_patch_prebound_steam(tmp_path):
    """GetMessages 先到且属别的账号：不得把它的别名写进预绑定（上一账号）的档。"""
    sid_a = make_save(tmp_path, STEAM_A, experience=1000)
    saves.SaveStore(sid_a, root=tmp_path).set_identity(HD2_A, STEAM_A, source="getmotd")
    before_a = saves.SaveStore(sid_a, root=tmp_path).path().read_bytes()
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    info = mgr.on_getmessages(HD2_B)                   # 本局先看到空号别名，主号 steam 只是预绑定
    assert info["action"] in ("switched", "same")
    assert saves.SaveStore(sid_a, root=tmp_path).path().read_bytes() == before_a   # 主号档未被改
    mgr.close()


def test_switch_warns_when_first_progression_merged_before_identity(tmp_path):
    """身份校验前已合并首屏 → 换号告警要写清"本局显示偏高、重启纠正"（显示窗口非写盘混档）。"""
    make_save(tmp_path, STEAM_A, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out, changed = mgr.apply_progression(prog_body(1))   # 身份未校验就合并（客户端已收到）
    assert changed == 1 and json.loads(out)["experience"] == 1000
    mgr.on_getmotd(STEAM_B)                              # 随后发现是另一个账号
    warns = [w["message"] for w in mgr.status()["warnings"]]
    assert any("首屏曾按旧档合并" in w and "重启游戏后按新档纠正" in w for w in warns), warns
    mgr.close()


def test_hd2_only_identity_reverse_lookup(tmp_path):
    """只有 20 位 HD2 id 时，反查已有 steam 档而不是新建 hd2_* 档。"""
    sid = make_save(tmp_path, experience=1200)
    st = saves.SaveStore(sid, root=tmp_path)
    st.set_identity(HD2_A, None, source="getmessages")
    (tmp_path / "_last.json").unlink()                   # 本局之前没有可用指针
    mgr = active_save.ActiveSave(root=tmp_path, wait_seconds=0, run_id="r1")
    mgr.start()                                          # 无 _last → local
    assert mgr.save_id == "local"
    info = mgr.on_getmessages(HD2_A)
    assert info["action"] == "merged"
    assert mgr.save_id == sid                            # 反查命中，回到 steam 档
    mgr.close()


# ---------------------------------------------------------------- 首屏合并策略（防回声污染）

def _prebind_with_ledger(tmp_path):
    """造一份带账本的预绑定档（成就/库存都有值），返回 mgr。"""
    sid = make_save(tmp_path, STEAM_A, experience=1000)
    st = saves.SaveStore(sid, root=tmp_path)
    doc = st.load()
    doc["earned"]["achievements"] = {"6": 1680, "8": 386242}
    doc["earned"]["inventory_amounts"] = {"3608481516": 910}
    doc["earned"]["stats"] = {"profile": {"totalEnemyKills": 400000}}
    st.save(doc)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")   # 默认 safe
    mgr.start()
    return mgr


def test_preverify_safe_merges_experience_but_not_achievements(tmp_path):
    """safe（新默认）：身份未校验时只合并服务端自算字段，成就/统计/库存不合并。"""
    mgr = _prebind_with_ledger(tmp_path)
    body = json.dumps({"experience": 1,
                       "achievements": [{"id": 6, "value": 10}],
                       "packageProgress": []}).encode()
    out, changed = mgr.apply_progression(body)
    doc = json.loads(out)
    assert doc["experience"] == 1000                     # 经验合并（服务端自算，回显不影响）
    assert doc["achievements"] == [{"id": 6, "value": 10}]   # 成就不合并（防回声污染）
    _stats_body = b'{"totalEnemyKills": 5}'
    out2, changed2 = mgr.apply_stats(_stats_body)
    assert changed2 == 0 and out2 is _stats_body
    inv = json.dumps({"items": []}).encode()
    out3, changed3 = mgr.apply_inventory(inv)
    assert changed3 == 0 and out3 is inv                 # 库存也不合并
    mgr.close()


def test_preverify_full_merges_everything_before_identity(tmp_path):
    """full（mock/自建服）：身份未校验也全合并，保证首屏能看到账本。"""
    mgr = _prebind_with_ledger(tmp_path)
    mgr.preverify_merge = "full"
    body = json.dumps({"experience": 1, "achievements": [], "packageProgress": []}).encode()
    out, changed = mgr.apply_progression(body)
    doc = json.loads(out)
    assert doc["experience"] == 1000
    assert {a["id"]: a["value"] for a in doc["achievements"]} == {6: 1680, 8: 386242}
    out2, n2 = mgr.apply_stats(b'{"totalEnemyKills": 5}')
    assert n2 == 1 and json.loads(out2)["totalEnemyKills"] == 400000
    out3, n3 = mgr.apply_inventory(json.dumps({"items": []}).encode())
    assert n3 == 1 and any(int(r["mixId"]) == 3608481516 for r in json.loads(out3)["items"])
    mgr.close()


def test_preverify_off_skips_all_merges_until_verified(tmp_path):
    """off：身份未校验一律不合并；校验之后恢复正常合并。"""
    mgr = _prebind_with_ledger(tmp_path)
    mgr.preverify_merge = "off"
    body = json.dumps({"experience": 1, "achievements": [], "packageProgress": []}).encode()
    out, changed = mgr.apply_progression(body)
    assert changed == 0 and out is body
    mgr.on_getmotd(STEAM_A)                              # 身份校验通过
    out2, changed2 = mgr.apply_progression(body)
    assert changed2 >= 1 and json.loads(out2)["experience"] == 1000
    mgr.close()


# ---------------------------------------------------------------- 换号回滚


def test_identity_mismatch_rolls_back_all_session_writes(tmp_path):
    """研究线场景：预绑定 A（错）→ 本局写 3 次 → GetMotd 说是 B → 整档回滚 + orphan。"""
    sid_a = make_save(tmp_path, STEAM_A, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.save_id == sid_a
    for amount in (10, 20, 30):
        mgr.update_earned(lambda e, d, n=amount: e.__setitem__("experience",
                                                               e["experience"] + n))
    assert mgr.session_dirty is True
    assert saves.SaveStore(sid_a, root=tmp_path).load()["earned"]["experience"] == 1060

    info = mgr.on_getmotd(STEAM_B)                       # 同机换号
    assert info["action"] == "switched" and info["old_identified"] is True
    assert info["session_dirty"] is True
    assert info["rollback"] == "restored"
    assert info["dirty_sha"] and info["restored_sha"]
    assert info["dirty_sha"] != info["restored_sha"]

    # 旧档整档回到会话前：3 次写入全部撤回（.bak 单槽只能退到 1060/1040 之间某一版）
    assert saves.SaveStore(sid_a, root=tmp_path).load()["earned"]["experience"] == 1000
    # 新档 = B，且不带走 A 的进度
    assert mgr.save_id == saves.save_id_for(STEAM_B)
    assert saves.SaveStore(mgr.save_id, root=tmp_path).load()["earned"]["experience"] == 0
    assert mgr.verified is True and mgr.session_dirty is False
    # _last 指向新档、pending 已清
    assert saves.read_last(root=tmp_path)["last_save_id"] == mgr.save_id
    assert saves.read_pending(root=tmp_path) == {}
    # 用户可见告警
    assert mgr.warnings and "身份切换" in mgr.warnings[-1]["message"]

    # orphan 审计：脏档全文 + 回滚后全文 + 双方 hash + 被丢弃条目摘要
    orphan = json.loads(open(info["orphan"], encoding="utf-8").read())
    assert orphan["doc"]["earned"]["experience"] == 1060
    assert orphan["restored_doc"]["earned"]["experience"] == 1000
    assert orphan["rollback_mode"] == "restored"
    assert orphan["doc_sha"] == info["dirty_sha"]
    assert orphan["restored_doc_sha"] == info["restored_sha"]
    assert orphan["discarded"]["experience"] == {"before": 1060, "after": 1000}
    mgr.close()


def test_identity_mismatch_without_writes_leaves_old_save_alone(tmp_path):
    """本局没写过 → 不动档、不产 orphan（研究线选项 3）。"""
    sid_a = make_save(tmp_path, STEAM_A, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    before = saves.SaveStore(sid_a, root=tmp_path).path().read_bytes()
    info = mgr.on_getmotd(STEAM_B)
    assert info["action"] == "switched"
    assert info["rollback"] == "none" and info["orphan"] == ""
    assert saves.SaveStore(sid_a, root=tmp_path).path().read_bytes() == before
    assert not list((tmp_path / "_orphan").glob("*.json")) if (tmp_path / "_orphan").exists() else True
    mgr.close()


def test_mismatch_rollback_restores_multi_field_writes(tmp_path):
    """不只是 experience：多字段写入也要整档撤回（部分写入正是研究线担心的）。"""
    sid_a = make_save(tmp_path, STEAM_A, experience=100)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()

    def _write(earned, doc):
        earned["experience"] = 500
        earned["inventory_amounts"]["3901895556"] = 699
        earned["achievements"]["9"] = 3
        earned["inventory_ids"].append(1945105139)

    mgr.update_earned(_write)
    info = mgr.on_getmotd(STEAM_B)
    restored = saves.SaveStore(sid_a, root=tmp_path).load()
    assert info["rollback"] == "restored"
    assert restored["earned"]["experience"] == 100
    assert restored["earned"]["inventory_amounts"] == {}
    assert restored["earned"]["achievements"] == {}
    assert restored["earned"]["inventory_ids"] == []
    orphan = json.loads(open(info["orphan"], encoding="utf-8").read())
    assert set(orphan["discarded"]) >= {"experience", "inventory_amounts",
                                       "achievements", "inventory_ids"}
    mgr.close()


# ---------------------------------------------------------------- 写入 / strict


def test_update_earned_marks_dirty(tmp_path):
    sid = make_save(tmp_path, experience=0)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.session_dirty is False
    mgr.update_earned(lambda e, d: e.__setitem__("experience", 42))
    assert mgr.session_dirty is True
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 42
    mgr.close()


def test_strict_refuses_write_before_verification(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, strict=True, run_id="r1")
    mgr.start()
    mgr.update_earned(lambda e, d: e.__setitem__("experience", 9999))
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 1000
    assert mgr.session_dirty is False
    assert mgr.events[-1]["kind"] == "strict"
    # 校验通过后允许写
    mgr.on_getmotd(STEAM_A)
    mgr.update_earned(lambda e, d: e.__setitem__("experience", 9999))
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 9999
    mgr.close()


# ---------------------------------------------------------------- 目录 / 登录 / 收摊


def test_record_items_catalog_includes_client_version(tmp_path):
    sid = make_save(tmp_path)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.note_login(json.dumps({"clientVersion": 1007203}).encode()) == "1007203"
    info = mgr.record_items(json.dumps([{"itemId": 1}, {"itemId": 2}]).encode())
    assert info["rows"] == 2
    assert info["value"].endswith("/2/1007203")
    assert saves.SaveStore(sid, root=tmp_path).load()["catalog_build"] == info["value"]
    assert mgr.status()["catalog_build"] == info["value"]
    mgr.close()


def test_note_login_ignores_bad_body(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.note_login(b"not json") is None
    assert mgr.note_login(json.dumps(["x"])) is None
    assert mgr.note_login(json.dumps({"noVersion": 1})) is None
    mgr.close()


def test_close_clears_snapshot_only_when_verified(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.close()
    # 未校验 → 保留基准 + pending，下次启动还能回滚
    assert saves.read_session_snapshot(sid, root=tmp_path) is not None
    assert saves.read_pending(root=tmp_path)["save_id"] == sid

    mgr2 = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr2.start()
    assert mgr2._snapshot["action"] == "reused"          # 跨重启沿用最早基准
    mgr2.on_getmotd(STEAM_A)
    mgr2.close()
    assert saves.read_session_snapshot(sid, root=tmp_path) is None
    assert saves.read_pending(root=tmp_path) == {}


def test_expired_pending_rebaselines_instead_of_reusing(tmp_path):
    """pending 过期（>24h）→ 重新取基准，不拿几周前的快照当回滚目标。"""
    sid = make_save(tmp_path, experience=1000)
    st = saves.SaveStore(sid, root=tmp_path)
    saves.begin_session(st, run_id="old")
    st.add_experience(50)                                # 上局脏写入
    saves.mark_pending(sid, run_id="old", root=tmp_path, since="2020-01-01T00:00:00")
    mgr = active_save.ActiveSave(root=tmp_path, run_id="new")
    mgr.start()
    assert saves.read_session_snapshot(sid, root=tmp_path)["doc"]["earned"]["experience"] == 1050
    mgr.close()


def test_status_shape(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    st = mgr.status()
    assert st["save_id"] == sid and st["origin"] == "last" and st["enabled"] is True
    assert st["verified"] is False and st["session_dirty"] is False
    assert st["snapshot"]["sha"] and st["events"]
    assert st["strict"] is False and st["wait_seconds"] == 1.2
    mgr.close()

# ---------------------------------------------------------------- G3 结算入账

MISSION_END_BODY = (Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves"
                    / "mission_end" / "12b9a872.json").read_bytes()


def test_record_mission_end_accumulates(tmp_path):
    """结算响应 → 经验累加 / 物品入账 / 包进度 max / 审计记录。"""
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_mission_end(MISSION_END_BODY)
    assert out["ok"] is True and out["experience"] == 936
    assert out["item_source"] == "rewards"

    doc = saves.SaveStore(sid, root=tmp_path).load()
    assert doc["earned"]["experience"] == 1936                 # 累加（本局增量 936）
    assert doc["earned"]["inventory_amounts"]["3608481516"] == 4434
    assert doc["earned"]["inventory_amounts"]["897894480"] == 7
    assert doc["earned"]["package_progress"]["277818845"] == {"level": 5, "progress": 459}
    missions = doc["earned"]["missions"]
    assert missions["count"] == 1 and len(missions["recent_ids"]) == 1
    assert missions["last"]["experience"] == 936
    assert mgr.session_dirty is True
    assert any(e["kind"] == "mission" for e in mgr.status()["events"])
    mgr.close()


def test_record_mission_end_dedupes_same_mission(tmp_path):
    """客户端重试同一份结算响应 → 只入账一次（宁可少记也不能双计）。"""
    sid = make_save(tmp_path, experience=0)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    assert mgr.record_mission_end(MISSION_END_BODY)["ok"] is True
    dup = mgr.record_mission_end(MISSION_END_BODY)
    assert dup["ok"] is True and dup["duplicate"] is True
    doc = saves.SaveStore(sid, root=tmp_path).load()
    assert doc["earned"]["experience"] == 936
    assert doc["earned"]["missions"]["count"] == 1
    assert doc["earned"]["inventory_amounts"]["3608481516"] == 4434
    mgr.close()


def test_record_mission_end_different_missions_both_count(tmp_path):
    sid = make_save(tmp_path, experience=0)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_mission_end(MISSION_END_BODY)
    other = json.loads(MISSION_END_BODY.decode("utf-8"))
    other["missionId"] = "another-mission"
    mgr.record_mission_end(json.dumps(other).encode())
    doc = saves.SaveStore(sid, root=tmp_path).load()
    assert doc["earned"]["experience"] == 936 * 2
    assert doc["earned"]["missions"]["count"] == 2
    assert len(doc["earned"]["missions"]["recent_ids"]) == 2
    mgr.close()


def test_record_mission_end_packages_never_lower(tmp_path):
    """progressionPackageUpdates 是服务端当前值 → max 合并，不累加、不降级。"""
    sid = make_save(tmp_path, experience=0)
    st = saves.SaveStore(sid, root=tmp_path)
    doc = st.load()
    doc["earned"]["package_progress"]["277818845"] = {"level": 6, "progress": 900}
    st.save(doc)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    mgr.record_mission_end(MISSION_END_BODY)
    got = saves.SaveStore(sid, root=tmp_path).load()["earned"]["package_progress"]["277818845"]
    assert got == {"level": 6, "progress": 900}
    mgr.close()


def test_record_mission_end_requires_mission_id(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_mission_end(json.dumps({"experience": 5}).encode())
    assert out["ok"] is False and out["reason"] == "no-mission-id"
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 1000
    assert mgr.session_dirty is False
    mgr.close()


def test_record_mission_end_bad_body(tmp_path):
    mgr = active_save.ActiveSave(root=tmp_path, run_id="r1")
    mgr.start()
    out = mgr.record_mission_end(b"not json")
    assert out["ok"] is False and out["reason"] == "bad-json"
    assert mgr.record_mission_end(b"")["ok"] is False
    assert mgr.session_dirty is False
    mgr.close()


def test_record_mission_end_strict_refused_before_verification(tmp_path):
    sid = make_save(tmp_path, experience=1000)
    mgr = active_save.ActiveSave(root=tmp_path, strict=True, run_id="r1")
    mgr.start()
    mgr.record_mission_end(MISSION_END_BODY)
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 1000
    assert mgr.session_dirty is False
    mgr.on_getmotd(STEAM_A)
    mgr.record_mission_end(MISSION_END_BODY)
    assert saves.SaveStore(sid, root=tmp_path).load()["earned"]["experience"] == 1936
    mgr.close()


def test_pending_of_other_save_is_not_reused(tmp_path):
    """研究线建议：pending 复用必须校验 saveId —— 上一个号的基准不能拿来给这个号。"""
    sid_a = make_save(tmp_path, experience=1000)
    st_a = saves.SaveStore(sid_a, root=tmp_path)
    saves.begin_session(st_a, run_id="old")        # A 的旧基准（exp=1000）
    st_a.add_experience(1000)                      # 之后 A 档被写脏（当前 exp=2000）
    data = json.loads((tmp_path / "_last.json").read_text(encoding="utf-8"))
    data["last_save_id"] = sid_a
    data["pending"] = {"save_id": saves.save_id_for(STEAM_B), "run_id": "old",
                       "since": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (tmp_path / "_last.json").write_text(json.dumps(data), encoding="utf-8")

    mgr = active_save.ActiveSave(root=tmp_path, run_id="r2")
    mgr.start()
    assert mgr._snapshot["action"] != "reused"     # 没拿"属于 B 的 pending"去复用 A 的旧基准
    snap = saves.read_session_snapshot(sid_a, root=tmp_path)
    assert snap["doc"]["earned"]["experience"] == 2000      # 基准 = 当前状态，不是旧快照
    mgr.close()
