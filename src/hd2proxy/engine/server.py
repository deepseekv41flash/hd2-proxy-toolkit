"""TLS MITM 代理服务（M1：从 legacy_proxy.py 拆出 + 控制面接入）。

三个动作（与原实现一致）：

    游戏 --TLS--> 本机 listen_ip:443（自签 CA 签发叶子）
                    │ ① 按路径命中钩子 → 解析 JSON → 增改字段 → 重发（去掉 Content-Length/Encoding）
                    │ ② 其余原样透传（passthrough 模式两个都跳过）
                    └--TLS--> 官方 API（DNS-over-HTTPS 解析上游，绕开 hosts）

M1 新增：
  * `spec=`：schema v2 profile 归一化后的显式配置；None = 退回研究线旧行为（读 env / runtime/*.json）；
  * 控制 API（control.py）：127.0.0.1 + token，供 GUI/CLI 读状态、热改配置；
  * 启动前自动续证（certs.ensure_session）。
"""

import argparse
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
from pathlib import Path

from . import (certs, diagnostics, hosts as hosts_mod, httpio, logutil, model, paths,
                 unlock_all, upstream)
from .active_save import ActiveSave
from .hooks import achievements as achievements_hook
from .hooks import capture, inventory, items, progression, stats as stats_hook, warinfo
from .hooks import consume as consume_hook
from .hooks import purchase as purchase_hook
from .logutil import log, log_throttled, rotate_logs
from .model import Mod, resolve_plan, rewrite_status


# ==== Proxy 类（自 M0 legacy_proxy.py 逐字抽取；仅钩子调用点与控制面接入处改动） ====
def _log_unlock_all(spec):
    """「一键解锁全部物品」的规格日志（启动 / 热重载各打一次，不随请求刷屏）。"""
    inv = getattr(spec, "inventory", None) or {}
    st = inv.get("unlockAll")
    if not isinstance(st, dict) or not st.get("enabled"):
        return
    scope = ",".join(st.get("scope") or [])
    _lv = st.get("level")
    _xp = st.get("xp")
    log("一键解锁全部物品（仅本机视图）：运行时按客户端目录展开 + 舰船模块 6 条包等级置满"
        " + 可改装武器补空槽改装条目 + 战团条目全按已领取"
        + (" + 账号等级补到 %s 级（%s 经验；武器改装在 10 级解锁）"
           % (_lv, _xp) if _xp else "") + "%s"
        % (("；范围 " + scope) if scope else ""), audit=True)
    try:
        from . import unlock_all as _ua
        n = len(_ua.seasonpass_items())
    except Exception:
        n = 0
    if n:
        log("一键解锁：战团领取名单 %d 条（军械库解锁态看这份名单；"
            "客户端本次会话从 /api/SeasonPass 学到的新战团会落盘，下次会话生效）" % n,
            audit=True)


def stamp_identity_header(lines, ident, has_account=False):
    """v0.7.0：给上游请求补身份头（自建服按玩家分档用）。

    ``ident`` = ``ActiveSave.identity_header()`` 的 ``(value, source)`` 或 None。
    客户端自己的 lobby 请求已带 ``X-HD2-Account`` 时 ``has_account=True`` → 不重复加（多值头会让服务端取错）。
    纯函数：不改入参，返回新列表。
    """
    if not ident or has_account:
        return lines
    value, source = ident
    lines = list(lines)
    if value:
        lines.append(("X-HD2-Account: %s" % value).encode("ascii", "ignore"))
    # value 为空（source=uncertain）时**只发 Source**：让自建服跳过 IP/唯一玩家兜底、直接回落公共数据。
    lines.append(("X-HD2-Account-Source: %s" % source).encode("ascii", "ignore"))
    return lines


class Proxy:
    def __init__(self, mod, cert_dir, send_chain=False, spec=None):
        self.mod = mod
        self.spec = spec                      # EngineSpec | None（None = 研究线旧行为）
        self.save = None                      # ActiveSave | None（G2 存档层，main() 里挂）
        self.started_at = time.time()
        self.rewrites = []                    # 最近改写事件（控制面/GUI 读）
        self.cert_dir = Path(cert_dir)
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        leaf = "server.chain.pem" if send_chain else "server.pem"
        self.ctx.load_cert_chain(str(self.cert_dir / leaf), str(self.cert_dir / "server.key"))
        self.ctx.options |= ssl.OP_NO_TICKET
        self.ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        self.ctx.set_servername_callback(self.on_sni)
        # 用于拒绝非白名单 SNI：一个没装证书的上下文，握手会自然失败（不发 alert 之外的任何东西）
        self.empty_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.stats = {"tls": 0, "req": 0, "deny": 0, "rewrite": 0}
        # v0.10.1-alpha.5：战团条目缓存的「上次报过的条数」（避免每个 SeasonPass 请求都刷日志）
        self._warbond_seen = 0
        # 只放行本机来源（回环 + 本机各网卡 IP）。算一次就够，别每条连接都解析一遍。
        self.local_ips = {"127.0.0.1", self.mod.listen_ip}
        try:
            for addrinfo in socket.getaddrinfo(socket.gethostname(), None):
                self.local_ips.add(addrinfo[4][0])
        except Exception:
            pass

    # ---- M1：spec 取用与控制面事件 -------------------------------------------
    def _spec_part(self, name):
        return getattr(self.spec, name, None) if self.spec is not None else None

    def _capture_spec(self):
        return self._spec_part("capture")

    def _status_spec(self):
        return self._spec_part("status_extra")

    def _warinfo_spec(self):
        return self._spec_part("warinfo")

    def _inventory_spec(self):
        return self._spec_part("inventory")

    def _items_spec(self):
        return self._spec_part("items")

    def _customize_spec(self):
        return self._spec_part("customize")

    def _unlock_all_cfg(self) -> dict:
        """「一键解锁全部物品」的规格（未开启返回空 dict）。"""
        cfg = self._inventory_spec()
        ua = (cfg or {}).get("unlockAll") if isinstance(cfg, dict) else None
        if isinstance(ua, dict):
            return ua if ua.get("enabled") else {}
        return {"enabled": True} if ua else {}

    def _unlock_all_enabled(self) -> bool:
        """「一键解锁全部物品」是否开启（v0.10.1-alpha.2：请求期按运行时目录展开）。"""
        return bool(self._unlock_all_cfg().get("enabled"))

    def _note(self, kind, detail):
        """记一条改写事件（控制面/GUI 实时展示；只保留最近 200 条）。"""
        try:
            self.rewrites.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
                                  "detail": str(detail)[:400]})
            if len(self.rewrites) > 200:
                del self.rewrites[:-200]
        except Exception:
            pass

    def _save_observe(self, path, body, hdrs, reqbody=None):
        """G2/G3 存档层：从**上游原始响应**里记身份、目录与结算奖励（不改写，失败只记日志）。

        为什么用原始 body：``items`` 的 catalog_build 必须取**注入前**响应，否则会随
        profile 配置漂移、失去跨版本可比性（研究线 2026-11-23 口径）。
        """
        save = self.save
        if save is None:
            return
        if paths.GETMOTD_MARK in path or paths.GETMESSAGES_MARK in path:
            plain, _ = httpio.maybe_gunzip(body, hdrs)
            try:
                doc = json.loads(plain)
            except (ValueError, TypeError):
                return
            account = doc.get("accountId") if isinstance(doc, dict) else None
            if not account:
                return
            if paths.GETMOTD_MARK in path:
                save.on_getmotd(account)      # SteamID64（主键）
            else:
                save.on_getmessages(account)  # HD2 20 位 id（只作别名）
        elif paths.ITEMS_PATH in path:
            plain, _ = httpio.maybe_gunzip(body, hdrs)
            save.record_items(plain)
        elif paths.MISSION_END_MARK in path:
            # G3：结算响应 = 本局奖励增量（经验/物品/包进度）→ 累加进 earned
            plain, _ = httpio.maybe_gunzip(body, hdrs)
            save.record_mission_end(plain)
        elif stats_hook.is_stats_path(path):
            # G4：终身统计（单调计数器）→ 记录进 earned.stats.profile
            plain, _ = httpio.maybe_gunzip(body, hdrs)
            save.record_stats(plain)
        else:
            kind = purchase_hook.kind_of(path)
            if kind:
                # G5+：购买/解锁响应 → 扣钱 + 授予（负=扣、正=授予；10s 窗口去重）
                plain, _ = httpio.maybe_gunzip(body, hdrs)
                save.record_purchase(plain, kind, request_body=reqbody)

    def on_sni(self, sslsock, servername, ctx):
        # 单域名白名单：别的 SNI 一律拒绝（不是开放代理）
        if servername != self.mod.host:
            self.stats["deny"] += 1
            log_throttled("sni-deny", "SNI DENY %r (allowlist=%s)" % (servername, self.mod.host))
            return self.empty_ctx
        return None

    def handle(self, conn, addr):
        # 先按来源过滤、再谈 TLS：局域网里的其它设备和扫描器连握手机会都不给，
        # 也不会拿到我们的证书（1.04 之前是先握手、拿到证书之后才 PEER DENY）。
        if addr[0] not in self.local_ips:
            self.stats["deny"] += 1
            log_throttled("peer-deny",
                          "PEER DENY %s:%d (only local connections allowed)" % (addr[0], addr[1]))
            try:
                conn.close()
            except Exception:
                pass
            return
        try:
            conn.settimeout(30)
            tls = self.ctx.wrap_socket(conn, server_side=True)
        except Exception as e:
            self.stats["deny"] += 1
            # 客户端在握手阶段断开，绝大多数是「不信任本机 CA」（其余是扫描器/探测）：
            # 这种失败在客户端只会显示通用网络错误，所以日志必须给出可操作提示。
            hint = ""
            if isinstance(e, ssl.SSLError) or "SSL" in type(e).__name__:
                hint = ("（多为客户端不信任本机 CA：点 GUI「安装 / 修复」或运行 "
                        "hd2proxy.exe install 重新导入信任）")
            log_throttled("tls-reject",
                          "TLS REJECTED %s:%d %r%s" % (addr[0], addr[1], e, hint))
            try:
                conn.close()
            except Exception:
                pass
            return
        self.stats["tls"] += 1
        try:
            tls.settimeout(60)
            while True:
                head, rest = httpio.read_head(tls)
                if not head:
                    break
                first, hdrs = httpio.parse_headers(head)
                body = rest
                if "chunked" in hdrs.get("transfer-encoding", "").lower():
                    body = httpio.dechunk(body)
                else:
                    need = int(hdrs.get("content-length", "0") or 0)
                    while len(body) < need:
                        c = tls.recv(65536)
                        if not c:
                            break
                        body += c
                self.stats["req"] += 1
                path = first.split(" ")[1] if len(first.split(" ")) > 1 else ""
                # 必要日志里只留“改写/错误”；逐条 REQ/RESP 只在 --verbose 时写。
                if logutil.VERBOSE:
                    log("REQ %s %s %dB" % (first.split(" ")[0], path[:80], len(body)))
                capture.capture_request(
                    path, body, hdrs,
                    method=first.split(" ")[0] if " " in first else "",
                    spec=self._capture_spec())
                # G2：登录**请求体**里的 clientVersion（catalog_build 的第三段，不是必需字段）
                if self.save is not None and body and paths.LOGIN_PATH in path:
                    try:
                        self.save.note_login(body)
                    except Exception as e:        # noqa: BLE001
                        log("clientVersion 记录失败：%r" % e)
                # G5：局内消耗（请求体）→ inventory_amounts 扣减（下限 0、保留行）
                if (self.save is not None and not self.mod.passthrough and body
                        and consume_hook.is_path(path)):
                    try:
                        self.save.record_consume(body)
                    except Exception as e:        # noqa: BLE001
                        log("消耗扣减记录失败：%r" % e)
                # G5：成就上报（请求体）→ earned.achievements（per-key max）
                if (self.save is not None and not self.mod.passthrough and body
                        and achievements_hook.is_path(path)):
                    try:
                        self.save.record_achievements(body)
                    except Exception as e:        # noqa: BLE001
                        log("成就上报记录失败：%r" % e)
                try:
                    ip, port = upstream.upstream_addr(self.mod, self.mod.host)
                    raw = socket.create_connection((ip, port), timeout=20)
                    if self.mod.upstream_test:
                        up = raw                     # 测试上游是明文 HTTP，不做 TLS
                    else:
                        up = ssl.create_default_context().wrap_socket(
                            raw, server_hostname=self.mod.host)
                except Exception as e:
                    log("upstream error %r" % e)
                    break
                lines = [head.split(b"\r\n")[0]]
                _conditional = (b"if-none-match:", b"if-modified-since:", b"if-match:",
                                b"if-unmodified-since:", b"if-range:")
                _stripped = False
                _has_account = False
                for line in head.split(b"\r\n")[1:]:
                    low = line.lower()
                    if low.startswith(b"connection:"):
                        continue
                    if low.startswith(b"x-hd2-account:"):
                        _has_account = True       # 客户端 lobby 请求自带：保留，不重复加
                    # 1.15：Status 是我们要改写的那一个响应。如果客户端带条件请求头
                    # （If-None-Match / If-Modified-Since 等），上游会回 304 且**没有响应体** ——
                    # 我们就没东西可改，客户端继续用自己缓存的旧战况（现场表现：游戏在走代理、
                    # player planet 一行行地出，却一条 REWRITE 都没有）。
                    # 所以对这一个路径剥掉条件头，让上游总是回 200 + 完整 body。
                    if paths.ALLOWED_PATH in path and low.startswith(_conditional):
                        _stripped = True
                        continue
                    lines.append(line)
                if _stripped:
                    log_throttled("status-conditional",
                                  "Status 条件请求头已剥离（否则上游 304 无响应体，就没法改写）",
                                  every=3600)
                # v0.7.0：自建服身份分档 —— 给上游补 X-HD2-Account（+ 来源标注）。
                # 客户端登录体里没有账号 id、首屏读档也早于身份出现，所以这一层必须由引擎盖章；
                # 身份未校验时用 _last 预绑定值并标 source=prebind，服务端可自行决定信不信。
                _ident = self.save.identity_header() if self.save is not None else None
                lines = stamp_identity_header(lines, _ident, _has_account)
                lines.append(b"Connection: close")
                up.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
                resp = b""
                while True:
                    c = up.recv(65536)
                    if not c:
                        break
                    resp += c
                up.close()
                rhead, _, rbody = resp.partition(b"\r\n\r\n")
                rfirst, rhdrs = httpio.parse_headers(rhead)
                client_close = "close" in (hdrs.get("connection", "") or "").lower()
                dechunked = False
                if "chunked" in rhdrs.get("transfer-encoding", "").lower():
                    rbody = httpio.dechunk(rbody)
                    dechunked = True
                capture.capture_response(path, rbody, rhdrs, spec=self._capture_spec())
                if logutil.VERBOSE:
                    log("RESP %s %dB"
                        % (rfirst.split(" ")[1] if " " in rfirst else rfirst, len(rbody)))
                elif paths.ALLOWED_PATH in path:
                    # 非 verbose 也留一行 Status 回执：这是“游戏有没有来拉战况”的唯一证据。
                    # 排查时它能把“没来拉”和“拉了但没改写”分开（两种现场都遇到过）。
                    log("STATUS %s %dB" % (rfirst.split(" ")[1] if " " in rfirst else "?", len(rbody)))
                if paths.ALLOWED_PATH in path and " 304 " in (" " + rfirst + " "):
                    log_throttled("status-304",
                                  "WARN: Status 返回 304 且没有响应体 —— 这次无法改写（条件头已剥离，下次应恢复）",
                                  every=300)

                # 跟踪玩家触碰过的星球：lobby 的 planetId，以及 Operation/Mission 的 planetIndex
                if body and any(k in path for k in ("/api/lobby", "/api/Operation",
                                                    "/api/Account/ReportPosition")):
                    try:
                        m = re.search(rb'"planetIndex"\s*:\s*(-?\d+)', body)
                        why = "mission"
                        if not m:
                            m = re.search(rb'"planetId"\s*:\s*(-?\d+)', body)
                            why = "lobby"
                        if m:
                            pi = int(m.group(1))
                            if pi >= 0:
                                self.mod.note_planet(pi, why)
                    except Exception:
                        pass

                out_body = rbody
                rewrite_added = 0
                dropped_encoding = False
                # DSH-WARINFO-SETTINGS-V1：生态借用的实际落点
                if (not self.mod.passthrough) and paths.WARINFO_MARK in path and rbody:
                    plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                    try:
                        wi_body, wi_n = warinfo.apply(plain, spec=self._warinfo_spec())
                    except Exception as e:
                        log("warinfo rewrite skipped: %r" % e)
                        wi_body, wi_n = plain, 0
                    if wi_n:
                        self.stats["rewrite"] = self.stats.get("rewrite", 0) + 1
                        out_body = wi_body
                        dropped_encoding = was_gz
                        log("REWRITE-WARINFO %d planet(s) settingsHash 已改%s"
                            % (wi_n, " [from gzip]" if was_gz else ""), audit=True)
                        self._note("warinfo", "%d planet(s)" % wi_n)
                if (not self.mod.passthrough) and paths.ALLOWED_PATH in path and rbody:
                    plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                    plan = {}
                    try:
                        candidate_plan = (self.spec.status_plan
                                          if self.spec is not None
                                          and self.spec.status_plan is not None
                                          else self.mod.effective_plan())
                        status_doc = json.loads(plain)
                        plan, filtered = resolve_plan(status_doc, candidate_plan)
                        if filtered:
                            detail = ", ".join(
                                "planet %d %s(%s) != owner(%s)" %
                                (p, name, faction, owner or "unknown")
                                for p, name, faction, owner in filtered)
                            log("FACTION FILTER: " + detail)
                        new_body, rewrite_added = rewrite_status(plain, plan, self._status_spec())
                    except Exception as e:
                        log("rewrite skipped: %r" % e)
                        new_body, rewrite_added = plain, 0
                    if rewrite_added:
                        self.stats["rewrite"] += 1
                        out_body = new_body
                        dropped_encoding = was_gz
                        summary = ", ".join("planet %d -> %s" % (p, ids)
                                            for p, ids in sorted(plan.items())) or "extra: campaigns/owner"
                        active = self.mod.active_names()
                        trials = self.mod.active_stratagem_names()
                        label = "+".join(active) if active else "(none)"
                        trial_label = "、".join(x["name"] for x in trials) or "(none)"
                        log("REWRITE +%d entries (%s) 变种=%s 战备试用=%s%s"
                            % (rewrite_added, summary, label, trial_label,
                               " [from gzip]" if was_gz else ""), audit=True)
                        self._write_status(plan, label, trials)
                        self._note("status", "+%d entries %s" % (rewrite_added, summary))
                    else:
                        # 200 有响应体但没加任何条目：最常见是"游戏在报告星球之前就拉了 Status"，
                        # 属于正常时序（下一发就会改）；也可能是没选变种。措辞按这两种情况写。
                        _pl = {str(k): v for k, v in plan.items()}
                        if not _pl:
                            log_throttled("status-noplan",
                                          "Status 200 但还没有可注入的星球 —— 游戏报告星球位置后会改写"
                                          "（如果一直不生效：重启一次游戏，或在星图里等 Status 刷新）",
                                          every=300)
                        else:
                            log_throttled("status-nochange",
                                          "Status 200 但没有新增条目（plan=%s）—— 这些 id 可能已经在响应里了"
                                          % json.dumps(_pl, ensure_ascii=False), every=300)

                elif (not self.mod.passthrough) and paths.INV_PATH in path and rbody:
                    # DSH_GWE_INV_V1：拥有的物品清单注入/移除（见 _gwe_inventory_rewrite）
                    plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                    try:
                        new_body, inv_added, inv_removed = inventory.inventory_rewrite(
                            plain, spec=self._inventory_spec())
                    except Exception as e:
                        log("inventory rewrite failed: %r" % e)
                        new_body, inv_added, inv_removed = None, 0, 0
                    if new_body is not None and (inv_added or inv_removed):
                        out_body = new_body
                        rewrite_added = inv_added + inv_removed
                        dropped_encoding = was_gz
                        self.stats["rewrite"] += 1
                        log("INV REWRITE +%d -%d 行%s"
                            % (inv_added, inv_removed, " [from gzip]" if was_gz else ""),
                            audit=True)
                        self._note("inventory", "+%d -%d 行" % (inv_added, inv_removed))

                elif (not self.mod.passthrough) and paths.ITEMS_PATH in path and rbody:
                    # DSH_GWE_ITEMS_V1：往服务端物品目录里补一条（克隆同族记录，改 itemId/mixId）
                    plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                    # 一键解锁：缓存**运行时客户端目录**（离线目录是子集，不能用于"解锁全部"）
                    if self._unlock_all_enabled():
                        try:
                            _cat = json.loads(plain)
                            if isinstance(_cat, list):
                                n = unlock_all.set_catalog(_cat)
                                log("UNLOCK 运行期目录已缓存 %d 行" % n)
                        except Exception as e:      # noqa: BLE001 - 目录解析失败不影响代理
                            log("UNLOCK 目录解析失败（本次不缓存）: %r" % e)
                    try:
                        new_body, items_added = items.items_rewrite(plain, spec=self._items_spec())
                    except Exception as e:
                        log("items rewrite failed: %r" % e)
                        new_body, items_added = None, 0
                    if new_body is not None and items_added:
                        out_body = new_body
                        rewrite_added = items_added
                        dropped_encoding = was_gz
                        self.stats["rewrite"] += 1
                        log("ITEMS REWRITE +%d entries%s"
                            % (items_added, " [from gzip]" if was_gz else ""), audit=True)
                        self._note("items", "+%d entries" % items_added)

                elif (not self.mod.passthrough) and paths.SEASONPASS_PATH in path and rbody \
                        and paths.SEASONPASS_BUY_PATH not in path:
                    # v0.10.1-alpha.5：缓存战团条目表（26 个战团的 itemIds 并集）—— 军械库解锁态看这份名单。
                    # 客户端 +16 s 先拉 /api/Progression、+19 s 才拉 /api/SeasonPass ⇒ 本次只学到、落盘，
                    # 下一次会话起生效（内置兜底 data/catalogs/warbond_items.json 让首跑就有效）。
                    if self._unlock_all_enabled():
                        try:
                            plain, _was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                            n = unlock_all.set_seasonpass(json.loads(plain))
                            if n and self._warbond_seen != n:
                                self._warbond_seen = n
                                log("UNLOCK 战团条目已缓存 %d 条（全部按「已领取」下发）" % n)
                        except Exception as e:      # noqa: BLE001 - 缓存失败不影响代理
                            log("UNLOCK 战团列表解析失败（本次不缓存）: %r" % e)

                elif (not self.mod.passthrough) and paths.CUSTOMIZE_PATH in path and rbody:
                    # DSH-GWE-CUSTOMIZE-V1：L2 改装槽快照改写（见 _gwe_customize_rewrite）
                    # v0.10.1-alpha.4：一键解锁时给所有可改装武器补空槽条目（空白号该响应是空数组）
                    plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                    try:
                        new_body, cz_hits = inventory.customize_rewrite(
                            plain, spec=self._customize_spec(),
                            unlock_all_enabled=self._unlock_all_enabled())
                    except Exception as e:
                        log("customize rewrite failed: %r" % e)
                        new_body, cz_hits = None, 0
                    if new_body is not None and cz_hits:
                        out_body = new_body
                        rewrite_added = cz_hits
                        dropped_encoding = was_gz
                        self.stats["rewrite"] += 1
                        log("CUSTOMIZE REWRITE +%d entry/slot(s)%s"
                            % (cz_hits, " [from gzip]" if was_gz else ""), audit=True)
                        self._note("customize", "+%d entry/slot(s)" % cz_hits)

                # G2 存档层：身份/目录记录 + Progression 根响应合并
                # 与上面的「配置驱动改写链」正交：只认精确根路径 `/api/Progression`，
                # 身份与目录取**上游原始响应**（items 必须注入前，否则 catalog_build 漂移）。
                _ua_on = self._unlock_all_enabled()
                if (self.save is not None or _ua_on) and not self.mod.passthrough and rbody:
                    try:
                        if self.save is not None:
                            self._save_observe(path, rbody, rhdrs, reqbody=body)
                        if progression.is_root_path(path):
                            plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                            _ua_cfg = self._unlock_all_cfg() if _ua_on else {}
                            new_body, save_n = progression.apply(
                                plain, self.save, unlock_all_enabled=_ua_on,
                                forge_flags=int(_ua_cfg.get("flags") or 0),
                                forge_xp=int(_ua_cfg.get("xp") or 0))
                            if save_n:
                                out_body = new_body
                                rewrite_added = save_n
                                dropped_encoding = was_gz
                                self.stats["rewrite"] += 1
                                log("SAVE REWRITE +%d field(s)（存档 %s）%s"
                                    % (save_n, self.save.save_id,
                                       " [from gzip]" if was_gz else ""), audit=True)
                                self._note("save", "+%d field(s)" % save_n)
                        elif stats_hook.is_stats_path(path):
                            # G4：终身统计逐 key 取 max（只抬不降；新号返回 0 也不抹掉本地战绩）
                            plain, was_gz = httpio.maybe_gunzip(rbody, rhdrs)
                            new_body, stats_n = stats_hook.apply(plain, self.save)
                            if stats_n:
                                out_body = new_body
                                rewrite_added = stats_n
                                dropped_encoding = was_gz
                                self.stats["rewrite"] += 1
                                log("SAVE STATS +%d field(s)（存档 %s）%s"
                                    % (stats_n, self.save.save_id,
                                       " [from gzip]" if was_gz else ""), audit=True)
                                self._note("save-stats", "+%d field(s)" % stats_n)
                        elif paths.INV_PATH in path:
                            # G5：库存数量只抬不降 —— 上游给得少（离线/私服/回滚）时用本机账本兜底。
                            # 若上面的配置注入已经改过 body，就在**注入后的视图**上合并，避免互相覆盖。
                            _src = out_body if rewrite_added else rbody
                            plain, was_gz = httpio.maybe_gunzip(_src, rhdrs)
                            new_body, inv_n = self.save.apply_inventory(plain)
                            if inv_n:
                                out_body = new_body
                                rewrite_added += inv_n
                                if _src is rbody:
                                    dropped_encoding = was_gz
                                self.stats["rewrite"] += 1
                                log("SAVE INV +%d 行（存档 %s，只抬不降）%s"
                                    % (inv_n, self.save.save_id,
                                       " [from gzip]" if was_gz else ""), audit=True)
                                self._note("save-inv", "+%d rows" % inv_n)
                    except Exception as e:    # noqa: BLE001 - 存档层异常绝不打断游戏
                        log("存档层处理失败（本次跳过）：%r" % e)

                # 只要动过 body（去 chunk / 解 gzip / 改写）就必须重写响应头，
                # 否则客户端仍按 chunked 或旧长度解析 → 直接失败
                # （curl 表现为 HTTP 200 + 0 字节 + exit 56）。
                if dechunked or rewrite_added:
                    rhead = self._fix_headers(rhead, len(out_body),
                                              keep_encoding=not dropped_encoding)

                tls.sendall(rhead + b"\r\n\r\n" + out_body)
                if client_close:
                    break
        except Exception as e:
            log("handler error: %r" % e)
        finally:
            try:
                tls.close()
            except Exception:
                pass

    @staticmethod
    def _write_status(plan, active, stratagems=None):
        """给面板看的运行时状态（原子写）。"""
        try:
            paths.RUNTIME.mkdir(parents=True, exist_ok=True)
            doc = {
                "planet": next(iter(plan), None),
                "planets": sorted(plan.keys()),
                "plan": {str(k): v for k, v in plan.items()},
                "variant": active,
                "stratagems": stratagems or [],
                "rewritten_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "pid": os.getpid(),
            }
            tmp = paths.STATUS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            tmp.replace(paths.STATUS_FILE)
        except Exception as e:
            log("status write failed: %r" % e)

    @staticmethod
    def _fix_headers(rhead, new_len, keep_encoding=True):
        kept = [rhead.split(b"\r\n")[0]]
        for line in rhead.split(b"\r\n")[1:]:
            low = line.lower()
            if low.startswith((b"content-length:", b"transfer-encoding:", b"connection:")):
                continue
            if not keep_encoding and low.startswith(b"content-encoding:"):
                continue
            kept.append(line)
        kept.append(b"Content-Length: %d" % new_len)
        kept.append(b"Connection: close")
        return b"\r\n".join(kept)




def port_owner_report(port):
    """谁在监听这个端口：返回 ["python.exe (PID 1234)", ...]。

    1.16 加它是因为现场日志里只有一行 "端口被占了"，看不出是旧代理还是加速器 ——
    而这两种处理方式完全不同（杀旧进程 / 关加速器）。

    走 ``sysprobe.port_listeners``（一条 ``netstat -ano`` + Toolhelp 快照 + 缓存），
    不再自己 spawn netstat/tasklist：这里以前最多要跑 1+N 个控制台子进程，
    引擎被 GUI 拉起时这些子进程会各自闪一个控制台窗口。
    """
    from . import sysprobe

    owners, seen = [], set()
    try:
        listeners = sysprobe.port_listeners(port)
    except Exception as e:                            # noqa: BLE001 - 诊断失败不能影响退出码
        return ["（查询端口占用失败：%r）" % (e,)]
    for item in listeners:
        pid = int(item.get("pid") or 0)
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        owners.append("%s (PID %d)" % (item.get("name") or "?", pid))
    return owners or ["（netstat 没列出监听者 —— 可能是系统保留/WinNAT/端口代理）"]



# ==== M1：引擎上下文 + 启动入口 ===============================================



def _capture_state(proxy) -> dict:
    """抓包状态快照（控制面 /status 用）：enabled/dir/paths。"""
    cap = {}
    if proxy.spec is not None and isinstance(proxy.spec.capture, dict):
        cap = proxy.spec.capture
    return {"enabled": bool(cap.get("enabled")), "dir": cap.get("dir") or "",
            "paths": list(cap.get("paths") or [])}


class EngineContext:
    """控制面 / GUI 需要的运行期上下文（单实例）。"""

    def __init__(self, proxy, mod, spec, *, cert_dir, host, listen_ip, port, crl_port,
                 profile_path=None, profile_name=None):
        self.proxy = proxy
        self.mod = mod
        self.spec = spec
        self.cert_dir = Path(cert_dir)
        self.host = host
        self.listen_ip = listen_ip
        self.port = port
        self.crl_port = crl_port
        self.profile_path = Path(profile_path) if profile_path else None
        self.profile_name = profile_name
        self.started_at = time.time()
        self.shutdown = threading.Event()
        self.reload_cb = None          # (profile_dict) -> dict  由 main 注入
        self.verify_cb = None          # () -> dict
        self.capture_cb = None         # (bool, dir|None) -> dict
        self.set_passthrough_cb = None  # (bool) -> dict
        self.control = None            # control.ControlServer

    # ---- 状态快照（/status） -------------------------------------------------
    def status(self) -> dict:
        import hd2proxy
        from . import certs as _certs
        proxy = self.proxy
        return {
            "version": hd2proxy.__version__,
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "host": self.host,
            "listen_ip": self.listen_ip,
            "port": self.port,
            "crl_port": self.crl_port,
            "mode": "passthrough" if (proxy.spec.passthrough if proxy.spec is not None
                                      else self.mod.passthrough) else "rewrite",
            "profile": self.profile_name,
            "profile_path": str(self.profile_path) if self.profile_path else None,
            "control_port": getattr(self.control, "port", None),
            "stats": dict(proxy.stats),
            "cert": _certs.cert_status(self.cert_dir),
            "planets": self.mod.target_planets(),
            "capture": _capture_state(proxy),
            "save": (proxy.save.status() if proxy.save is not None else None),
            "rewrites": list(proxy.rewrites)[-50:],
            "log": str(paths.PROXY_LOG),
        }

    def note(self, message):
        log(message)


def _split_addr(value, default):
    """'ip:port' -> (ip, port)；空/invalid -> default。"""
    if not value:
        return default
    try:
        host, _, port = str(value).rpartition(":")
        return host or default[0], int(port)
    except Exception:
        return default


def build_parser():
    ap = argparse.ArgumentParser(description="HD2 本机 MITM 代理引擎（M1）")
    ap.add_argument("--config", default=str(paths.LEGACY_DIR / "config.example.json"),
                    help="旧式 config.json（无 profile 时使用）")
    ap.add_argument("--catalog", default=str(paths.LEGACY_DIR / "variant_catalog.json"))
    ap.add_argument("--cert-dir", default=str(paths.CERT_DIR))
    ap.add_argument("--cert-mode", choices=["leaf", "ca"], default="ca",
                    help="ca = 游戏唯一可用形态（默认）；leaf 仅离线实验")
    ap.add_argument("--passthrough", action="store_true", help="纯转发，不改写")
    ap.add_argument("--port", type=int, default=0, help="覆盖监听端口（默认取配置）")
    ap.add_argument("--listen-ip", default="", help="覆盖监听 IP（默认取配置）")
    ap.add_argument("--profile", default="", help="schema v2 profile 路径（产品模式）")
    ap.add_argument("--control-port", type=int, default=-1,
                    help="-1=按 profile/默认 17897；0=不启控制面")
    ap.add_argument("--no-control", action="store_true", help="不启控制面")
    ap.add_argument("--no-auto-renew", action="store_true", help="关闭启动前自动续证")
    ap.add_argument("--allow-loopback", action="store_true",
                    help="允许回环监听（仅离线测试/自检用；游戏客户端会拒绝回环）")
    ap.add_argument("--verbose", action="store_true", help="逐条 REQ/RESP 日志")
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--drop-def", default="")
    ap.add_argument("--add-def", default="")
    ap.add_argument("--inject", default="")
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    logutil.ensure_utf8_console()          # GBK 控制台打印 ⚠ 会崩进程
    a = build_parser().parse_args(argv)

    # ---- 1. 读配置：旧 config.json 打底；有 profile 则用 profile 覆盖 ----------
    cfg = {}
    try:
        cfg = json.loads(Path(a.config).read_text(encoding="utf-8-sig"))
    except Exception as e:
        log("config 读取失败（用默认值继续）: %r" % e)
    cfg.setdefault("host", certs.DEFAULT_HOST)
    cfg.setdefault("listenIp", "")
    cfg.setdefault("port", 443)

    profile = None
    spec = None
    profile_name = None
    profile_path = Path(a.profile) if a.profile else None
    if profile_path:
        from . import config as _config
        profile = _config.load_profile_file(profile_path)
        profile_name = profile.get("name") or profile_path.stem
        try:
            _catdoc_for_spec = json.loads(Path(a.catalog).read_text(encoding="utf-8"))
        except Exception as e:
            log("变种目录读取失败（变种计划可能为空）: %r" % e)
            _catdoc_for_spec = None
        spec = _config.to_engine_spec(profile, _catdoc_for_spec)
        _log_unlock_all(spec)
        cfg["host"] = spec.host or cfg["host"]
        if spec.listen_ip:
            cfg["listenIp"] = spec.listen_ip
        if spec.port:
            cfg["port"] = spec.port
        if spec.crl_port:
            cfg["crlPort"] = spec.crl_port
        cfg["passthrough"] = spec.passthrough
        cfg["verbose"] = spec.verbose
        log("profile: %s (%s)" % (profile_name, profile_path), audit=True)

    if a.allow_loopback:
        cfg["allowLoopback"] = True
    if a.listen_ip:
        cfg["listenIp"] = a.listen_ip
    if a.port:
        cfg["port"] = int(a.port)
    if a.passthrough:
        cfg["passthrough"] = True
    logutil.VERBOSE = bool(a.verbose or cfg.get("verbose"))

    host = cfg["host"]
    listen_ip = cfg.get("listenIp") or ""
    port = int(cfg.get("port", 443))
    crl_port = int(cfg.get("crlPort", 8080))

    # ---- 2. 监听 IP：不能是回环（19411 之后客户端拒绝回环连接） ---------------
    if not listen_ip or str(listen_ip).strip().lower() == "auto":
        try:
            from . import sysprobe
            listen_ip = sysprobe.resolve_listen_ip("auto")
        except Exception as e:      # 模块缺失或探测失败：用 UDP 出口地址兜底
            try:
                _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                _s.connect(("223.5.5.5", 80))
                listen_ip = _s.getsockname()[0]
                _s.close()
            except Exception:
                log("PREFLIGHT FAIL: 无法确定监听 IP（%r）；用 --listen-ip 指定非回环网卡 IP" % e)
                return 4
        cfg["listenIp"] = listen_ip
    elif listen_ip.startswith(("127.", "0.")) and not cfg.get("allowLoopback"):
        log("PREFLIGHT FAIL: listenIp=%r 是回环地址 —— 新版客户端会拒绝连接。"
            "请换成本机非回环网卡 IP（ipconfig 查看）" % listen_ip)
        return 4

    # ---- 3. 证书：按需自动续期 + preflight -----------------------------------
    cert_dir = Path(a.cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    auto_renew = (spec.cert_auto_renew if spec is not None else False) and not a.no_auto_renew
    if auto_renew:
        try:
            _days = (spec.cert_days if spec is not None else certs.MAX_DAYS_DEFAULT)
            r = certs.ensure_session(cert_dir, host=host, days=_days, max_days=_days,
                                     min_remaining_hours=(spec.cert_min_remaining_hours
                                                          if spec is not None else 12.0))
            log("证书 %s（剩余 %s 小时）"
                % (r["action"], round(r.get("remaining_hours") or 0, 1)), audit=True)
        except Exception as e:
            log("证书自动续期失败: %r（继续用现有证书尝试）" % e)

    # ---- 3b. 证书信任自检：CA 不在根存储时，游戏会在 TLS 握手阶段直接断开 --------
    # 这个坑很隐蔽：证书文件、CRL、CRL 服务全正常，只是「CA 没装进受信任根存储」，
    # 客户端只会显示「与服务器通讯时出错」，日志里也只有 TLS REJECTED —— 所以启动时就喊出来。
    try:
        _cert = certs.cert_status(cert_dir, check_trust=True)
        if _cert.get("exists") and _cert.get("trusted") is False:
            log("⚠ 证书未受信任：当前 CA 不在受信任根存储（指纹 %s）"
                % ((_cert.get("trust_thumbprint") or "?")[:12],), audit=True)
            log("   → 游戏会报「与服务器通讯时出错」；修复：hd2proxy.exe install "
                "或 GUI「安装 / 修复」（一次 UAC 即可）")
    except Exception as e:                       # noqa: BLE001 - 自检失败不影响启动
        log("证书信任自检失败: %r（继续启动）" % e)

    # ---- 4. 目录 + 计划 ------------------------------------------------------
    try:
        catdoc = json.loads(Path(a.catalog).read_text(encoding="utf-8"))
    except Exception as e:
        log("PREFLIGHT FAIL: 变种目录读取失败 %r" % e)
        return 2
    base = catdoc.get("variants") or {}
    aliases = catdoc.get("aliases") or {}
    catalog = dict(base)
    for alias, target in aliases.items():
        if target in base:
            catalog[alias] = base[target]
    cfg["_aliases"] = aliases
    meta = catdoc.get("meta") or {}
    cfg["_meta"] = meta

    mod = Mod(cfg, catalog, meta)
    problems = certs.preflight(host, cert_dir, mod.skipped)
    if problems:
        for p in problems:
            log("PREFLIGHT FAIL: " + p)
        log("拒绝启动（安全自检未通过）")
        return 2
    if not mod.plan and spec is None:
        log("提示：config.targets 为空 —— 注入内容完全由选择文件/profile 决定")

    # ---- 5. 起代理 ----------------------------------------------------------
    send_chain = (a.cert_mode == "ca" or certs._session_mode(cert_dir) == "ca")
    proxy = Proxy(mod, cert_dir, send_chain=send_chain, spec=spec)
    # ---- 5b. G2 存档层：profile 模式才启用；legacy 模式保持旧行为（不写盘） ----
    if spec is not None and (spec.saves or {}).get("enabled"):
        try:
            sv = spec.saves or {}
            # 身份未校验的首屏合并策略：默认 safe（防换号回声污染）；测试上游(mock/自建服)
            # 自动升到 full，保证「服务端给得少 ⇒ 存档层兜底」可验证。
            pv_mode = str(sv.get("preverify_merge") or "safe")
            if mod.upstream_test and pv_mode == "safe":
                pv_mode = "full"
            proxy.save = ActiveSave(wait_seconds=sv.get("wait_seconds", 1.2),
                                    strict=bool(sv.get("identity_strict", False)),
                                    preverify_merge=pv_mode)
            st = proxy.save.start()
            if st.get("origin") == "last":
                log("存档：首屏预绑定 %s（身份待 GetMotd 校验）" % st.get("save_id"), audit=True)
            else:
                log("存档：无历史档，先按 local 渲染（等身份到达后迁移）", audit=True)
        except Exception as e:                # noqa: BLE001 - 存档层失败不能挡住代理
            log("⚠ 存档层启动失败（继续以无存档模式运行）：%r" % e)
            proxy.save = None
    rotate_logs()
    srv = None
    last_err = None
    for attempt in range(1, 11):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 独占绑定：SO_REUSEADDR 在 Windows 上允许「抢占」正在监听的端口
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            s.bind((listen_ip, port))
            srv = s
            break
        except OSError as e:
            last_err = e
            s.close()
            if attempt == 1:
                log("bind %s:%d 失败（%r），重试最多 5 秒…" % (listen_ip, port, e))
            time.sleep(0.5)
    if srv is None:
        log("BIND FAIL %s:%d -> %r" % (listen_ip, port, last_err))
        for who in port_owner_report(port):
            log("  占用者: " + who)
        log("  端口被别的程序占了（旧代理/加速器/其它代理软件）。也可以换监听网卡。")
        return 3
    srv.listen(64)
    crl_srv = certs.serve_crl(cert_dir, crl_port)

    ctx = EngineContext(proxy, mod, spec, cert_dir=cert_dir, host=host,
                        listen_ip=listen_ip, port=port, crl_port=crl_port,
                        profile_path=profile_path, profile_name=profile_name)
    log("=" * 60)
    log("hd2proxy engine  host=%s  listen=%s:%d  passthrough=%s  mode=%s"
        % (host, listen_ip, port, mod.passthrough,
           "profile" if spec is not None else "legacy"), audit=True)
    # 启动自检：hosts 与当前监听 IP 不一致（缺失/被加速器注释/指向旧 IP）时**当场说清楚**，
    # 否则现场只会看到游戏报「与服务器通讯时出错」，看不出是 hosts 被注释了。
    try:
        advice = diagnostics.hosts_startup_advice(hosts_mod.read_hosts(), listen_ip)
    except Exception as exc:                    # noqa: BLE001 - 只读检查失败不影响启动
        advice = ["hosts 检查失败（%r）—— 请确认 hosts 指向 %s" % (exc, listen_ip)]
    for line in advice:
        log("⚠ " + line, audit=True)
    log("plan: %s" % json.dumps(mod.describe(), ensure_ascii=False), audit=True)
    if spec is not None and spec.status_plan is not None:
        log("profile plan: %s" % json.dumps(
            {str(k): v.get("variants") for k, v in spec.status_plan.items()},
            ensure_ascii=False), audit=True)

    # ---- 6. 控制面 ----------------------------------------------------------
    control_port = a.control_port
    if a.no_control:
        control_port = 0
    elif control_port < 0:
        control_port = (spec.control_port if spec is not None else 0) or 17897
    if control_port:
        try:
            from . import control as _control
            def _reload_profile(profile_doc):
                """控制面热重载：重建 spec 并替换指针（不重启、不断开游戏连接）。"""
                new_spec = _config.to_engine_spec(profile_doc, _catdoc_for_spec)
                _log_unlock_all(new_spec)
                proxy.spec = new_spec
                mod.passthrough = bool(new_spec.passthrough)
                logutil.VERBOSE = bool(new_spec.verbose or logutil.VERBOSE)
                # 存档层：wait_seconds / identity_strict 可热改；enabled 需要重启引擎
                if proxy.save is not None:
                    sv = new_spec.saves or {}
                    try:
                        proxy.save.wait_seconds = max(
                            0.0, float(sv.get("wait_seconds", proxy.save.wait_seconds)))
                        proxy.save.strict = bool(sv.get("identity_strict", proxy.save.strict))
                        _pv = str(sv.get("preverify_merge") or proxy.save.preverify_merge)
                        if mod.upstream_test and _pv == "safe":
                            _pv = "full"
                        proxy.save.preverify_merge = (
                            _pv if _pv in ("safe", "full", "off")
                            else proxy.save.preverify_merge)
                    except (TypeError, ValueError):
                        pass
                    if not sv.get("enabled", True):
                        log("⚠ profile 关闭了 saves.enabled：存档层需重启引擎才停用（本次继续生效）")
                active = [k for k, v in (
                    ("warinfo", new_spec.warinfo), ("status_extra", new_spec.status_extra),
                    ("status_plan", new_spec.status_plan), ("inventory", new_spec.inventory),
                    ("items", new_spec.items), ("customize", new_spec.customize),
                    ("saves", (new_spec.saves or {}).get("enabled")),
                    ("capture", (new_spec.capture or {}).get("enabled"))) if v]
                log("profile 热重载: %s · passthrough=%s · 生效钩子=%s"
                    % (profile_doc.get("name") or "?", new_spec.passthrough,
                       ",".join(active) or "(none)"), audit=True)
                return {"ok": True, "hot": True, "passthrough": new_spec.passthrough,
                        "active_hooks": active, "warnings": new_spec.warnings}

            ctx.reload_cb = _reload_profile
            ctx.control = _control.start(ctx, port=control_port)
            log("控制面 http://127.0.0.1:%d （token 在 %s）"
                % (ctx.control.port, paths.engine_state_file()), audit=True)
        except Exception as e:
            log("控制面启动失败（不影响代理）: %r" % e)

    # ---- 7. 运行 ------------------------------------------------------------
    try:
        paths.LOGDIR.mkdir(parents=True, exist_ok=True)
        paths.PROXY_PID.write_text(str(os.getpid()), encoding="utf-8")
    except Exception as e:
        log("pid file write failed: %r" % e)

    def _cleanup():
        try:
            if paths.PROXY_PID.read_text(encoding="utf-8").strip() == str(os.getpid()):
                paths.PROXY_PID.unlink()
        except Exception:
            pass
        try:
            if ctx.control is not None:
                ctx.control.stop()
        except Exception:
            pass
        try:
            if proxy.save is not None:
                proxy.save.close()
        except Exception:
            pass

    import atexit
    atexit.register(_cleanup)

    srv.settimeout(0.5)
    while not ctx.shutdown.is_set():
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        t = threading.Thread(target=proxy.handle, args=(conn, addr), daemon=True)
        t.start()
    log("engine 退出（pid %d）" % os.getpid(), audit=True)
    try:
        srv.close()
    except Exception:
        pass
    if crl_srv is not None:
        try:
            crl_srv.shutdown()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
