"""系统诊断：一次查清「游戏为什么连不上 / 引擎为什么起不来」的本机现场。

只读、不需要管理员、不改系统，给 GUI 总览页与命令行诊断共用。三层现场：

  1. **端口**：443（代理）/ 8080（CRL）/ 控制面 —— ``free`` / ``ours``（本工具引擎，正常）/
     ``conflict``（别人占用）。conflict 给占用者（进程名 / PID / 路径）；``0.0.0.0`` / ``::``
     通配绑定单独标记 —— 这种占用「换监听 IP」没用，必须关掉它。
  2. **hosts**：本工具那一行在不在、是否被注释（加速器 hosts 保护）、IP 是否等于要监听的 IP。
     如果 hosts 已指向本机但引擎没在跑 —— 进游戏就会报「与服务器通讯时出错」。
  3. **证书 / 游戏进程**：证书能否用、剩余小时；游戏是否在跑（改代理/重装前建议先退游戏）。

设计：``collect()`` 负责「跑探测」，``evaluate()`` 是**纯函数**（吃快照出告警），
离线测试直接喂快照即可，不依赖本机网卡 / 进程 / hosts。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import certs, hosts as hosts_mod, paths, sysprobe

# 端口角色：(profile 里的键, 默认端口, 中文名, 绑定地址)。
# 为什么三个都查：引擎要同时占这三个，任何一个被占都会启动失败；第三方工具只查 443/8080。
# 注意绑定地址：代理绑**监听网卡 IP**（游戏连过来），CRL 与控制面绑 **127.0.0.1**（只本机用）——
# 用监听 IP 去查 8080/17897 会永远显示「空闲」，从而误报「引擎在跑但端口空闲」。
PORT_DEFAULTS = (
    ("port", 443, "代理", "listen"),
    ("crl_port", 8080, "CRL", "127.0.0.1"),
    ("control_port", 17897, "控制面", "127.0.0.1"),
)


# --------------------------------------------------------------------------- #
# 采集
# --------------------------------------------------------------------------- #
def own_engine_pids(state_file: Path | None = None) -> set[int]:
    """本工具引擎的 PID（从 engine.json 读，且进程还活着才算）。

    端口预检必须排除它：引擎已在跑时 443 显示「被占用」是正常状态，不能报冲突。
    """
    path = Path(state_file) if state_file else paths.engine_state_file()
    pids: set[int] = set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return pids
    for key in ("pid", "control_pid"):
        try:
            pid = int(doc.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0 and sysprobe.pid_alive(pid):
            pids.add(pid)
    return pids


_COMMENT_PREFIX_RE = re.compile(r"^\s*#([A-Za-z_][A-Za-z0-9_]*?)(?=\d|\s|$)")


def hosts_diag(text: str, listen_ip: str) -> dict:
    """判定 hosts 里本工具那一行（纯函数）：ok / missing / commented / wrong-ip。

    被注释时额外给出 ``comment_prefix``（如加速器的 ``#uu_acc`` / ``#g_acc``）——
    现场排障要能一眼看出是哪个软件注释的，而不是只说「被注释」。
    """
    info = hosts_mod.find_marker(text or "")
    line = (info or {}).get("line") or ""
    ip = (info or {}).get("ip") or ""
    commented = bool((info or {}).get("commented"))
    if info is None:
        state = "missing"
    elif commented:
        state = "commented"
    elif listen_ip and ip != str(listen_ip):
        state = "wrong-ip"
    else:
        state = "ok"
    prefix = ""
    if commented:
        marker_pos = line.find(hosts_mod.MARKER)
        body = line[: marker_pos] if marker_pos >= 0 else line
        matched = _COMMENT_PREFIX_RE.match(body)
        if matched:
            prefix = "#" + matched.group(1)
    return {
        "state": state,
        "line": line,
        "ip": ip,
        "commented": commented,
        "comment_prefix": prefix,
        "expected_ip": str(listen_ip or ""),
    }


def hosts_startup_advice(text: str, listen_ip: str) -> list[str]:
    """引擎启动时的一句话建议（纯函数，便于单测）：hosts 与监听 IP 不一致就直说怎么修。"""
    diag = hosts_diag(text, listen_ip)
    state = diag["state"]
    if state == "ok":
        return []
    if state == "missing":
        return ["hosts 里没有本工具那一行 —— 游戏不会走代理；请执行 install / GUI「安装 / 修复」"]
    if state == "commented":
        prefix = diag.get("comment_prefix") or ""
        who = ("（前缀 %s，多为加速器 hosts 保护）" % prefix) if prefix else "（多为加速器 hosts 保护）"
        return ["hosts 那一行被注释掉了%s —— 游戏不会走代理；重写 hosts 后需重启引擎" % who]
    return ["hosts 指向 %s，但当前监听 %s —— 游戏连不到本引擎；请重写 hosts 或改监听 IP"
            % (diag.get("ip") or "?", listen_ip or "?")]


def collect(profile: dict, cert_dir=None, own_pids=None, state_file=None) -> dict:
    """跑一遍本机探测，返回快照（不抛异常：探测失败降级成空值 + 告警）。"""
    proxy = (profile or {}).get("proxy") or {}
    cert_cfg = (profile or {}).get("cert") or {}
    host = str(proxy.get("host") or "")

    # 监听地址：auto / 显式 -> 具体 IPv4；失败就记错误（不阻断其它检查）
    listen_setting = str(proxy.get("listen_ip") or "auto")
    listen_ip, listen_error = "", None
    try:
        listen_ip = sysprobe.resolve_listen_ip(listen_setting)
    except ValueError as exc:
        listen_error = str(exc)

    own = set(own_pids) if own_pids is not None else own_engine_pids(state_file)
    engine_running = bool(own)

    ports: list[dict] = []
    if listen_ip:
        for key, default, label, where in PORT_DEFAULTS:
            try:
                port = int(proxy.get(key) or default)
            except (TypeError, ValueError):
                port = default
            bind_ip = listen_ip if where == "listen" else where
            entry = sysprobe.port_state(bind_ip, port, own)
            entry.setdefault("ip", bind_ip)
            entry.setdefault("port", port)
            entry["role"] = label
            ports.append(entry)

    status = certs.cert_status(cert_dir or _default_cert_dir(), check_trust=True)
    hosts_text = ""
    try:
        hosts_text = hosts_mod.read_hosts()
    except OSError:
        hosts_text = ""
    hdiag = hosts_diag(hosts_text, listen_ip)

    return {
        "profile_name": str((profile or {}).get("name") or ""),
        "host": host,
        "listen_setting": listen_setting,
        "listen_ip": listen_ip,
        "listen_error": listen_error,
        "primary_ip": sysprobe.primary_ip(),
        "ports": ports,
        "engine_running": engine_running,
        "engine_pids": sorted(own),
        "hosts": hdiag,
        "cert": status,
        "game_running": sysprobe.game_running(),
        "admin": sysprobe.is_admin(),
        "cert_days": cert_cfg.get("days"),
    }


def _default_cert_dir() -> Path:
    d = paths.state_dir() / "certs"
    return d if (d / "session.json").exists() else paths.CERT_DIR


def port_preflight(profile: dict, own_pids=None, state_file=None) -> dict:
    """启动前端口预检（GUI「启动引擎」用）：只做「监听地址 + 三个端口三态」。

    返回 ``{"listen_ip", "listen_error", "ports", "conflicts", "wildcard"}``；
    ``conflicts`` 只装 state == conflict 的端口条目。
    """
    proxy = (profile or {}).get("proxy") or {}
    listen_setting = str(proxy.get("listen_ip") or "auto")
    try:
        listen_ip = sysprobe.resolve_listen_ip(listen_setting)
        listen_error = None
    except ValueError as exc:
        return {"listen_setting": listen_setting, "listen_ip": "", "listen_error": str(exc),
                "ports": [], "conflicts": [], "wildcard": False}
    own = set(own_pids) if own_pids is not None else own_engine_pids(state_file)
    ports = []
    for key, default, label, where in PORT_DEFAULTS:
        try:
            port = int(proxy.get(key) or default)
        except (TypeError, ValueError):
            port = default
        bind_ip = listen_ip if where == "listen" else where
        entry = sysprobe.port_state(bind_ip, port, own)
        entry.setdefault("ip", bind_ip)
        entry.setdefault("port", port)
        entry["role"] = label
        ports.append(entry)
    conflicts = [entry for entry in ports if entry.get("state") == "conflict"]
    return {
        "listen_setting": listen_setting,
        "listen_ip": listen_ip,
        "listen_error": listen_error,
        "ports": ports,
        "conflicts": conflicts,
        "wildcard": any(bool(entry.get("wildcard")) for entry in conflicts),
    }


def listen_candidates(profile: dict, own_pids=None, state_file=None) -> list[dict]:
    """「换监听地址」候选：本机非回环 IPv4 + 每个候选上的端口占用状态。

    推荐项（``recommended=True``）按顺序挑：默认路由出口 IP > 物理网卡 > 其它非回环；
    虚拟网卡（VMware/Hyper-V/TUN…）保留但标 ``is_virtual``，不推荐。
    """
    proxy = (profile or {}).get("proxy") or {}
    try:
        port = int(proxy.get("port") or 443)
    except (TypeError, ValueError):
        port = 443
    own = set(own_pids) if own_pids is not None else own_engine_pids(state_file)
    primary = sysprobe.primary_ip()
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in sysprobe.local_ipv4_addresses():
        ip = str(entry.get("ip") or "")
        if not ip or ip in seen or sysprobe.validate_listen_ip(ip) is not None:
            continue
        seen.add(ip)
        state = sysprobe.port_state(ip, port, own)
        rows.append({
            "ip": ip,
            "interface": entry.get("interface") or "",
            "is_virtual": bool(entry.get("is_virtual")),
            "is_primary": bool(primary and ip == primary),
            "state": state.get("state"),
            "wildcard": bool(state.get("wildcard")),
            "owners": state.get("owners") or [],
        })
    # 排序：主 IP 最前，其次物理网卡，最后虚拟；同组按 IP 数字序稳定
    def sort_key(row: dict):
        try:
            ip_key = tuple(int(part) for part in row["ip"].split("."))
        except ValueError:
            ip_key = (999, 999, 999, 999)
        return (0 if row["is_primary"] else 1,
                1 if row["is_virtual"] else 0,
                ip_key)
    rows.sort(key=sort_key)
    primary_row = next((row for row in rows if row["is_primary"]), None)
    if primary_row and primary_row["state"] in ("free", "ours"):
        recommended = primary_row["ip"]
    else:
        # 只推荐物理网卡；虚拟网卡（Hyper-V/VMware/TUN）即使空闲也不推荐 —— 游戏连它不可靠
        recommended = next((row["ip"] for row in rows
                            if not row["is_virtual"] and row["state"] in ("free", "ours")), None)
    for row in rows:
        row["recommended"] = bool(recommended and row["ip"] == recommended)
    return rows


# --------------------------------------------------------------------------- #
# 判定（纯函数：只吃快照，方便离线测试）
# --------------------------------------------------------------------------- #
def _owners_text(entry: dict) -> str:
    parts = []
    for owner in entry.get("owners") or []:
        brief = "%s(PID %s)" % (owner.get("name") or "?", owner.get("pid") or "?")
        if owner.get("path"):
            brief += " @ %s" % owner["path"]
        parts.append(brief)
    return "、".join(parts) or "（查不到占用者，可能是系统保留/WinNAT）"


def evaluate(snapshot: dict) -> dict:
    """快照 -> 结论：``warnings`` 里每项 ``{"level": error|warn|info, "text": str}``。"""
    warnings: list[dict] = []

    def add(level: str, text: str) -> None:
        warnings.append({"level": level, "text": text})

    if snapshot.get("listen_error"):
        add("error", "监听地址不可用：%s" % snapshot["listen_error"])

    for entry in snapshot.get("ports") or []:
        role = entry.get("role") or "端口"
        state = entry.get("state")
        if state == "conflict":
            if entry.get("wildcard"):
                add("error", "%s端口 %s 被 %s 占用（对方绑的是 0.0.0.0/:: 全体地址，"
                            "换监听 IP 无效，必须关掉它）"
                    % (role, entry.get("port"), _owners_text(entry)))
            else:
                add("error", "%s端口 %s 被 %s 占用 —— 关掉它，或在设置里换监听 IP"
                    % (role, entry.get("port"), _owners_text(entry)))
        elif state == "free" and snapshot.get("engine_running"):
            add("warn", "%s端口 %s 空闲，但引擎 PID %s 显示在运行 —— 可能绑定失败或刚启动"
                % (role, entry.get("port"), snapshot.get("engine_pids")))

    h = snapshot.get("hosts") or {}
    state = h.get("state")
    listen_ip = snapshot.get("listen_ip") or ""
    if state == "missing":
        add("error", "hosts 里没有本工具那一行 —— 游戏不会走代理；先点「安装 / 修复（管理员）」")
    elif state == "commented":
        prefix = h.get("comment_prefix") or ""
        who = ("（检测到 %s，多为加速器「hosts 保护」）" % prefix) if prefix else "（多为加速器「hosts 保护」）"
        add("error", "hosts 那一行被注释掉了%s —— 关闭保护后重新安装/修复"
                     "（TUN / 路由模式加速器切换后必须重写 hosts 并重启引擎）；"
                     "当前行：%s" % (who, h.get("line") or "?"))
    elif state == "wrong-ip":
        add("error", "hosts 指向 %s，但要监听的是 %s —— 本机 IP 变了，需重新安装/修复重写 hosts"
            % (h.get("ip") or "?", listen_ip or "?"))
    elif state == "ok" and not snapshot.get("engine_running"):
        add("error", "hosts 已把游戏指向本机（%s），但引擎没在运行 —— 现在进游戏会报"
                     "「与服务器通讯时出错」；先启动引擎" % (listen_ip or h.get("ip") or "?"))

    cert = snapshot.get("cert") or {}
    if not cert.get("usable"):
        detail = "；".join(cert.get("warnings") or []) or "（无证书信息）"
        add("warn", "会话证书不可用：%s" % detail)
    elif cert.get("trusted") is False:
        # 证书能签、但 CA 不在根存储：客户端在 TLS 握手阶段就被断开，
        # 游戏侧只报通用的 Error 60 / Status -1，引擎日志只有 TLS REJECTED —— 必须显式报出来
        add("error", "证书未受信任：当前 CA 不在受信任根存储（指纹 %s）→ 游戏 TLS 握手会被拒绝"
                     "（引擎日志 TLS REJECTED）。点「安装 / 修复」重新导入信任"
            % ((cert.get("trust_thumbprint") or "?")[:12],))
    elif (cert.get("remaining_hours") or 0) < 12:
        add("warn", "会话证书只剩 %.1f 小时，到期前游戏会连不上 —— 点「签发 / 续期证书」"
            % (cert.get("remaining_hours") or 0))

    if snapshot.get("game_running"):
        add("info", "游戏正在运行：改代理配置/重装/停引擎前建议先退游戏（会掐断当前会话）")

    errors = [w for w in warnings if w["level"] == "error"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 展示
# --------------------------------------------------------------------------- #
_STATE_LABELS = {"free": "空闲", "ours": "本工具占用（正常）", "conflict": "被占用"}


def format_text(snapshot: dict, evaluation: dict | None = None) -> str:
    """人读文本（GUI「系统自检」弹窗 / 未来 CLI 共用）。"""
    ev = evaluation or evaluate(snapshot)
    lines = ["==== 系统诊断 ===="]
    lines.append("监听配置 : %s -> %s%s"
                 % (snapshot.get("listen_setting"), snapshot.get("listen_ip") or "?",
                    "" if not snapshot.get("listen_error") else "（%s）" % snapshot["listen_error"]))
    lines.append("本机主 IP: %s" % (snapshot.get("primary_ip") or "?"))
    lines.append("引擎     : %s%s"
                 % ("运行中" if snapshot.get("engine_running") else "未运行",
                    "" if not snapshot.get("engine_pids")
                    else "（PID %s）" % "、".join(str(p) for p in snapshot["engine_pids"])))
    lines.append("游戏     : %s" % ("运行中" if snapshot.get("game_running") else "未运行"))
    lines.append("管理员   : %s" % ("是" if snapshot.get("admin") else "否"))
    lines.append("")
    lines.append("-- 端口 --")
    if not snapshot.get("ports"):
        lines.append("  （监听地址不可用，跳过端口检查）")
    for entry in snapshot.get("ports") or []:
        label = _STATE_LABELS.get(entry.get("state"), entry.get("state") or "?")
        extra = ""
        if entry.get("state") == "conflict":
            extra = " ：" + _owners_text(entry)
            if entry.get("wildcard"):
                extra += "（通配绑定，换 IP 无效）"
        elif entry.get("state") == "ours":
            extra = " ：" + _owners_text(entry)
        lines.append("  %s %s:%s -> %s%s"
                     % (entry.get("role"), entry.get("ip"), entry.get("port"), label, extra))
    lines.append("")
    lines.append("-- hosts --")
    h = snapshot.get("hosts") or {}
    hstate = {"ok": "已生效", "missing": "没有本工具的行",
              "commented": "被注释掉了", "wrong-ip": "IP 与监听不一致"}.get(
                  h.get("state"), h.get("state") or "?")
    lines.append("  状态: %s" % hstate)
    if h.get("line"):
        lines.append("  行  : %s" % h["line"])
    if h.get("state") == "wrong-ip":
        lines.append("  期望: %s（当前 hosts 是 %s）"
                     % (h.get("expected_ip") or "?", h.get("ip") or "?"))
    lines.append("")
    lines.append("-- 证书 --")
    cert = snapshot.get("cert") or {}
    lines.append("  可用: %s · 剩余 %s 小时 · 指纹 %s"
                 % ("是" if cert.get("usable") else "否",
                    cert.get("remaining_hours"),
                    (cert.get("thumbprint") or "—")[:12]))
    if cert.get("warnings"):
        for warning in cert["warnings"]:
            lines.append("  · %s" % warning)
    lines.append("")
    lines.append("-- 结论 --")
    if not ev["warnings"]:
        lines.append("  ✅ 没有发现阻塞项")
    for warning in ev["warnings"]:
        mark = {"error": "✗", "warn": "⚠", "info": "·"}.get(warning["level"], "·")
        lines.append("  %s %s" % (mark, warning["text"]))
    return "\n".join(lines)
