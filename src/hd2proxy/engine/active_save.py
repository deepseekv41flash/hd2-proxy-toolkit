"""引擎侧 activeSave：首屏乐观预绑定 + 身份校验 + 会话基准回滚（G2）。

为什么需要这一层（研究线 2026-11-23 实测，真实会话 + mock 8 次启动一致）：

  * 时序：items +13/+15 s → **Progression +16/+19 s** → inventory +18 s → … →
    **GetMotd +24/+42 s**（身份 SteamID64 在这里才出现）；
  * 客户端**一次会话只拉一次** ``/api/Progression``。

⇒ 若等身份到达再选档，老玩家整局看空档（首屏已经渲染完且不会重取）。所以：
启动时按 ``runtime/saves/_last.json`` **乐观预绑定** → 首屏先按它渲染 →
GetMotd 到达后校验；不一致按研究线口径分流（local 合并 / 已识别档不混档）。

回滚粒度（研究线 2026-11-23 反馈：``.bak`` 单槽回滚不到「会话前」）：

  * 会话基准快照 ``_session-start/<saveId>.json`` 在 ``_bind()`` 时留；
  * 本局写入（``update_earned``）只把 ``session_dirty`` 置真；
  * 身份不一致且本局写过 → **整档回滚**到基准 + 脏档全文留 ``_orphan``；
  * 身份一致 → 基准**重建**为当前状态（= 最后一次已验证点）并清 ``pending``；
  * 没写过 → **不动档**（研究线选项 3：没快照/没写入就没什么可回滚）。

职责边界：本模块只管「哪份档在生效 / 身份对不对 / 本局有没有写过」；
具体响应怎么改在 ``hooks/progression.py``（G2）与后续 G3–G5 钩子；
落盘一律走 ``saves.SaveStore``（原子写 / 损坏隔离 / ``.bak``）。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from . import paths, saves
from .logutil import log, log_throttled

ORIGIN_LAST = "last"       # 预绑定来源：_last.json（老玩家首屏按它渲染）
ORIGIN_LOCAL = "local"     # 没有任何历史：先按 local 渲染，等身份到达再迁移


def _clean(value) -> str | None:
    """身份字段归一化：空串 → None（避免 "" 被当成已识别）。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ActiveSave:
    """一局游戏一个实例（引擎进程级）：activeSave + 会话快照 + 身份状态机。

    线程安全：代理是「一条连接一个线程」，GetMotd / Progression / items 可能并发到达，
    所有状态读写都在 ``self._lock`` 下；等身份时**不持锁**（否则 GetMotd 线程进不来）。
    """

    def __init__(self, root=None, *, wait_seconds=1.2, strict=False, run_id=None):
        self.root = Path(root) if root else Path(paths.SAVES_DIR)
        self.wait_seconds = max(0.0, float(wait_seconds or 0))
        self.strict = bool(strict)
        self.run_id = str(run_id or uuid.uuid4().hex[:12])
        self._lock = threading.RLock()
        self._identity_known = threading.Event()
        self._store = saves.SaveStore(saves.DEFAULT_SAVE_ID, root=self.root)
        self.save_id = saves.DEFAULT_SAVE_ID
        self.steam_id = None
        self.hd2_account = None
        self.origin = ORIGIN_LOCAL
        self.verified = False          # 本局身份是否已校验通过（strict 写入的前置条件）
        self.session_dirty = False     # 本局是否写过 activeSave（决定要不要回滚）
        self.client_version = None     # 登录请求体里的 clientVersion（catalog_build 辅字段）
        self.wait_took = None          # 首屏等身份实际耗时（排障用）
        self.events = []               # 最近事件（控制面/GUI 读）
        self.warnings = []             # 需要用户看见的告警（换号回滚等）
        self._snapshot = {}
        self._first_progression = False
        self._last_catalog = None
        self._ident_recorded = (None, None)    # 已落盘的身份（避免每发 GetMotd 都写盘）

    # ------------------------------------------------------------ 生命周期
    def start(self) -> dict:
        """引擎启动：按 ``_last.json`` 预绑定 activeSave + 取会话基准快照。"""
        with self._lock:
            last = saves.read_last(self.root)
            raw_id = _clean(last.get("last_save_id"))
            sid = saves.normal_save_id(raw_id) if raw_id else saves.DEFAULT_SAVE_ID
            # `last_save_id: local` 不算预绑定（上一局也没认出身份）：
            # 此时没有"上次那位玩家"可参照，首屏等身份的逻辑照常生效。
            prebound = sid != saves.DEFAULT_SAVE_ID
            self.origin = ORIGIN_LAST if prebound else ORIGIN_LOCAL
            self.steam_id = _clean(last.get("last_steam_id"))
            self.hd2_account = _clean(last.get("last_hd2_account_id"))
            pending = saves.read_pending(self.root)
            # 上局没校验完就崩/关（pending 新鲜且同一档）→ 沿用最早基准，跨重启也能回滚
            reuse = (saves.pending_reusable(pending)
                     and str(pending.get("save_id") or "") == sid)
            self._bind(sid, reuse=reuse, mark=True)
            log("存档：activeSave=%s（%s%s），会话基准=%s"
                % (self.save_id, self.origin,
                   "，复用上局基准" if reuse else "", self._snapshot.get("action")),
                audit=True)
            return self.status()

    def close(self):
        """引擎退出：身份已校验的收摊清快照；未校验则**保留**（下次启动还能回滚）。"""
        with self._lock:
            try:
                if self.verified:
                    saves.clear_session_snapshot(self.save_id, self.root)
                    saves.clear_pending(root=self.root)
                    self._event("close", "身份已校验：清理会话基准")
                else:
                    self._event("close", "身份未校验：保留会话基准供下次启动回滚")
            except Exception as e:            # noqa: BLE001 - 收摊失败不能影响退出
                log("存档收摊失败：%r" % e)

    def _bind(self, save_id, *, reuse=False, mark=False):
        """切换 activeSave 并为它取会话基准快照。"""
        old_sid = self.save_id
        self._store = saves.SaveStore(save_id, root=self.root)
        self.save_id = self._store.save_id
        snap = saves.begin_session(self._store, run_id=self.run_id, reuse=reuse)
        self._snapshot = snap
        self.session_dirty = False
        if mark:
            pending = saves.read_pending(self.root) if reuse else {}
            since = (pending.get("since")
                     if str(pending.get("save_id") or "") == self.save_id else None)
            # 复用旧基准时**保留原始 since**，否则每次启动都刷新新鲜度、永不过期
            saves.mark_pending(self.save_id, run_id=self.run_id, root=self.root, since=since)
        self._event("bind", "activeSave=%s ← %s（基准 %s，hash %s）"
                    % (self.save_id, old_sid if old_sid != self.save_id else "启动",
                       snap.get("action"), snap.get("sha") or "-"))

    # ------------------------------------------------------------ 响应入口
    def apply_progression(self, body):
        """``/api/Progression`` 根响应：必要时等身份 → 合并 earned。返回 (body, 改动数)。"""
        if body is None:
            return body, 0
        self._maybe_wait_identity()
        with self._lock:
            try:
                doc = self._store.load()
            except Exception as e:            # noqa: BLE001 - 存档异常不能打断首屏
                log("存档读取失败（Progression 合并跳过）：%r" % e)
                return body, 0
            new_body, changed = saves.apply_to_progression(body, doc)
            if not self._first_progression:
                self._first_progression = True
                self._event("progression", "首屏按 %s 渲染（来源 %s，earned 改动 %d 字段）"
                            % (self.save_id, self.origin, changed))
            return new_body, changed

    def record_items(self, body, client_version=None):
        """``/api/Progression/items``（**注入前**响应）→ 记录 catalog_build。"""
        if not body:
            return None
        with self._lock:
            try:
                info = self._store.record_catalog(body, client_version or self.client_version)
            except Exception as e:            # noqa: BLE001
                log("catalog_build 记录失败：%r" % e)
                return None
            if info.get("sha8") and info.get("value") != self._last_catalog:
                self._last_catalog = info.get("value")
                self._event("catalog", "目录 %s" % info.get("value"))
            return info

    def note_login(self, body):
        """``/api/Account/Login`` **请求体**里的 clientVersion（catalog_build 辅字段）。"""
        doc = None
        try:
            if isinstance(body, (bytes, bytearray)):
                doc = json.loads(bytes(body).decode("utf-8", "replace"))
            elif isinstance(body, str):
                doc = json.loads(body)
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        version = _clean(doc.get("clientVersion"))
        if version:
            with self._lock:
                self.client_version = version
        return version

    def on_getmotd(self, account_id):
        """``Pes/GetMotd`` 响应 ``accountId`` = SteamID64（主键来源）。"""
        return self._observe_identity(steam_id=account_id, source="getmotd")

    def on_getmessages(self, account_id):
        """``Pes/GetMessages`` 响应 ``accountId`` = HD2 20 位账号 id（**只作别名**）。"""
        return self._observe_identity(hd2_account=account_id, source="getmessages")

    # ------------------------------------------------------------ 写入入口
    def update_earned(self, mutate, *, reason="earned") -> dict:
        """G3+ 的写回入口：就地改 earned 并落盘，自动计 ``session_dirty``。

        ``identity_strict``（默认关）时身份未校验 → **拒绝写入**：宁可丢这一局的窗口
        写入，也不写进可能属于别人的档（研究线口径：跨玩家污染比丢窗口严重得多）。
        """
        with self._lock:
            if self.strict and not self.verified:
                self._event("strict", "身份未校验，拒绝写入（%s）" % reason)
                log("⚠ identity_strict：身份未校验，已拒绝写入存档 %s（%s）"
                    % (self.save_id, reason), audit=True)
                return self._store.load()
            doc = self._store.load()
            earned = doc.setdefault("earned", {})
            mutate(earned, doc)
            out = self._store.save(doc)
            self.session_dirty = True
            self._event("write", "earned 已写盘（%s）" % reason)
            return out

    # ------------------------------------------------------------ 身份状态机
    def _maybe_wait_identity(self):
        """无 ``_last`` 预绑定时，首屏最多等 ``wait_seconds`` 秒身份（等不到就按 local 渲染）。

        有预绑定就**不等**：那正是预绑定的意义（首屏立刻出内容）。
        """
        if self._first_progression or self._identity_known.is_set():
            return
        if self.origin == ORIGIN_LAST or self.wait_seconds <= 0:
            return
        started = time.monotonic()
        got = self._identity_known.wait(self.wait_seconds)
        self.wait_took = round(time.monotonic() - started, 2)
        if got:
            self._event("wait", "首屏等身份 %.2fs 后到达" % self.wait_took)
        else:
            log_throttled("save-wait-timeout",
                          "首屏等身份 %.2fs 超时 → 先按 %s 渲染（身份到达后按口径切档）"
                          % (self.wait_took, self.save_id), every=300)
            self._event("wait", "首屏等身份 %.2fs 超时 → 按 %s 渲染"
                        % (self.wait_took, self.save_id))

    def _observe_identity(self, *, steam_id=None, hd2_account=None, source="getmotd") -> dict:
        """观测到身份 → 校验 / 切档（研究线 2026-11-23 分流口径）。"""
        steam = _clean(steam_id)
        hd2 = _clean(hd2_account)
        if not (steam or hd2):
            return {"ok": False, "action": "no-id", "save_id": self.save_id}
        with self._lock:
            if steam:
                self.steam_id = steam
            if hd2:
                self.hd2_account = hd2
            self._identity_known.set()
            target_id = saves.save_id_for_identity(self.steam_id, self.hd2_account,
                                                   root=self.root)
            if target_id == self.save_id:
                # 真实会话里 GetMotd 会重复出现（46 分钟 7 次）：只在「首次校验」或
                # 「别名变了」时落盘，避免每发都写档 + 刷 .bak
                changed = (not self.verified) or (self.steam_id, self.hd2_account) != self._ident_recorded
                self.verified = True
                if changed:
                    self._store.set_identity(self.hd2_account, self.steam_id, source=source)
                    # 校验通过 = 当前状态可以信任：把基准重建到这里（最后一次已验证点）
                    self._snapshot = saves.rebase_session(self._store, run_id=self.run_id)
                    saves.clear_pending(root=self.root)
                    self._ident_recorded = (self.steam_id, self.hd2_account)
                    self._event(source, "身份校验一致 → %s" % self.save_id)
                return {"ok": True, "action": "same", "save_id": self.save_id,
                        "target_id": target_id, "steam_id": self.steam_id,
                        "hd2_account_id": self.hd2_account}
            return self._switch_to_identity(target_id, source=source)

    def _switch_to_identity(self, target_id, *, source="getmotd") -> dict:
        """身份与 activeSave 不一致：local 合并 / 已识别档不混档（回滚 + orphan）。"""
        old_id = self.save_id
        old_identified = saves.is_identified(self._store.load())
        info = {"ok": True, "action": "merged" if not old_identified else "switched",
                "save_id": target_id, "old_save_id": old_id, "target_id": target_id,
                "old_identified": bool(old_identified),
                "session_dirty": bool(self.session_dirty),
                "rollback": "none", "orphan": "", "dirty_sha": "", "restored_sha": ""}
        if not old_identified:
            # 旧档 local/未识别：不会混进别人的进度 → 合并 + 归档（绝不静默丢）
            target = self._store.adopt_identity(hd2_account=self.hd2_account,
                                                steam_id=self.steam_id, root=self.root)
            info["save_id"] = target.save_id
        else:
            # 两个已识别档之间绝不合并：本局写入整档回滚到会话基准，脏档留 orphan
            info.update(self._rollback_session())
            target = saves.SaveStore(target_id, root=self.root)
            target.set_identity(self.hd2_account, self.steam_id, source=source)
        self._bind(target.save_id, reuse=False, mark=False)
        self.verified = True
        saves.clear_pending(root=self.root)
        saves.write_last(self.save_id, self.steam_id, self.hd2_account, root=self.root)
        self._event("switch", "%s → %s（%s，回滚=%s，orphan=%s）"
                    % (old_id, self.save_id, info["action"], info["rollback"],
                       info["orphan"] or "-"))
        if info["action"] == "switched":
            self._warn("⚠ 身份切换：%s（已识别）→ %s；**不合并**（避免跨玩家混档）。"
                       "本局写入=%s，回滚=%s%s"
                       % (old_id, self.save_id, "有" if info["session_dirty"] else "无",
                          info["rollback"],
                          "，脏档另存 " + info["orphan"] if info["orphan"] else ""))
        else:
            log("身份确认：%s（local/未识别）已合并进 %s 并归档"
                % (old_id, self.save_id), audit=True)
        return info

    def _rollback_session(self) -> dict:
        """本局写过 → 整档回滚到会话基准；脏档全文 + 双方 hash + 丢弃摘要留 orphan。"""
        out = {"rollback": "none", "orphan": "", "dirty_sha": "", "restored_sha": ""}
        if not self.session_dirty:
            return out                       # 本局没写过 → 不动档（研究线选项 3）
        dirty_doc = self._store.load()
        res = saves.restore_session_snapshot(self._store)
        out["rollback"] = res.get("mode") or "none"
        out["dirty_sha"] = saves.doc_sha(dirty_doc)
        if res.get("ok"):
            restored_doc = self._store.load()
            out["restored_sha"] = saves.doc_sha(restored_doc)
            out["orphan"] = saves.write_orphan(
                self.save_id, dirty_doc, root=self.root, reason="identity-switch",
                extra={"rollback_mode": out["rollback"],
                       "restored_doc_sha": out["restored_sha"],
                       "restored_doc": restored_doc,
                       "discarded": saves.earned_diff(dirty_doc.get("earned"),
                                                      restored_doc.get("earned"))})
            saves.clear_session_snapshot(self.save_id, self.root)
            self.session_dirty = False
            log("⚠ 会话回滚：%s 已整档恢复到会话基准（%s；脏档 %s → 恢复后 %s），脏档另存 %s"
                % (self.save_id, out["rollback"], out["dirty_sha"], out["restored_sha"],
                   out["orphan"] or "（写入失败）"), audit=True)
        else:
            # 回滚失败/无基准：保留脏档并喊出来，绝不假装成功
            out["orphan"] = saves.write_orphan(
                self.save_id, dirty_doc, root=self.root, reason="rollback-failed",
                extra={"rollback_mode": out["rollback"]})
            log("⚠ 会话回滚未完成（%s）：%s 仍是脏档，全文已另存 %s —— 请人工核对"
                % (out["rollback"], self.save_id, out["orphan"] or "（写入失败）"), audit=True)
        return out

    # ------------------------------------------------------------ 状态 / 事件
    def status(self) -> dict:
        """控制面 / GUI 读的状态快照（不触发任何写盘）。"""
        with self._lock:
            catalog = None
            try:
                catalog = self._store.load().get("catalog_build")
            except Exception:                 # noqa: BLE001 - 状态查询不能抛
                catalog = None
            return {
                "enabled": True,
                "save_id": self.save_id,
                "origin": self.origin,
                "verified": bool(self.verified),
                "session_dirty": bool(self.session_dirty),
                "strict": bool(self.strict),
                "wait_seconds": self.wait_seconds,
                "wait_took": self.wait_took,
                "steam_id": self.steam_id,
                "hd2_account_id": self.hd2_account,
                "client_version": self.client_version,
                "catalog_build": catalog,
                "snapshot": dict(self._snapshot or {}),
                "events": list(self.events[-12:]),
                "warnings": list(self.warnings[-10:]),
            }

    def _event(self, kind, detail):
        try:
            self.events.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "kind": str(kind), "detail": str(detail)[:300]})
            if len(self.events) > 50:
                del self.events[:-50]
        except Exception:                     # noqa: BLE001
            pass

    def _warn(self, message):
        try:
            self.warnings.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  "message": str(message)[:400]})
            if len(self.warnings) > 20:
                del self.warnings[:-20]
        except Exception:                     # noqa: BLE001
            pass
        log(message, audit=True)
