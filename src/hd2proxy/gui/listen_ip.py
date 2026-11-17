"""端口相关对话框：「换监听地址」与「端口被占用」（P0 端口诊断交互）。

为什么单独成模块：设置页（改 profile 的监听 IP）与总览页「启动引擎」前的端口预检都要用；
探测逻辑在 `engine/diagnostics.py`（可离线测试），这里只负责弹窗与写回 profile。

设计约束（对齐第三方工具的经验）：新版客户端拒绝回环地址，所以候选**只列真实网卡 IPv4**；
候选按「主网卡 > 物理网卡 > 虚拟网卡」排序，并直接标出每个 IP 上 443 的占用状态。
"""

import tkinter as tk

from ..engine import diagnostics
from . import theme


def _center(parent, win):
    try:
        win.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_width(), win.winfo_height()
        win.geometry("+%d+%d" % (max(0, px + (pw - w) // 2), max(0, py + (ph - h) // 2)))
    except tk.TclError:
        pass


def choose_listen_ip(parent, app) -> str | None:
    """「换监听地址」对话框：返回选中的 IP；取消返回 None。

    应用即写 `app.profile["proxy"]["listen_ip"]` 并 mark_dirty（不落盘 —— 由用户点保存/应用）。
    """
    root = parent.winfo_toplevel()
    proxy = app.profile.get("proxy") or {}
    try:
        port = int(proxy.get("port") or 443)
    except (TypeError, ValueError):
        port = 443
    rows = diagnostics.listen_candidates(app.profile)
    current = str(proxy.get("listen_ip") or "auto")

    win = tk.Toplevel(root)
    win.title("换监听地址")
    win.configure(bg=theme.BG)
    win.transient(root)
    win.attributes("-topmost", True)

    tk.Label(win, text=("游戏固定连 api.live.prod.thehelldiversgame.com:%d；hosts 只能改它解析到的 IP，"
                        "不能改端口。\n新版客户端拒绝回环地址（127.x 连上就断），所以这里只列本机网卡 IP。"
                        % port),
             bg=theme.BG, fg=theme.FG, font=theme.F_S, justify="left",
             padx=14, pady=10, wraplength=620).pack(anchor="w")

    wildcard = any(row.get("wildcard") for row in rows)
    if wildcard:
        tk.Label(win, text="⚠ 有程序绑定了 0.0.0.0 全体地址 —— 换任何监听 IP 都会被挡住，请先关掉它",
                 bg="#2a1f1f", fg=theme.RED, font=theme.F_S, justify="left",
                 padx=14, pady=4, wraplength=620).pack(anchor="w")
    if not rows:
        tk.Label(win, text="⚠ 没检测到任何可用的非回环网卡地址 —— 检查网络连接后再试",
                 bg="#2a1f1f", fg=theme.RED, font=theme.F_S, justify="left",
                 padx=14, pady=4, wraplength=620).pack(anchor="w")

    # 默认选中：推荐项；若当前配置是某个候选，也允许改回
    default_ip = current
    for row in rows:
        if row.get("recommended"):
            default_ip = row["ip"]
            break
    var = tk.StringVar(value=default_ip)

    body = tk.Frame(win, bg=theme.BG)
    body.pack(fill="both", expand=True, padx=14, pady=(4, 0))
    for row in rows:
        line = tk.Frame(body, bg=theme.BG)
        line.pack(fill="x", pady=1)
        tk.Radiobutton(line, text=row["ip"], variable=var, value=row["ip"],
                       bg=theme.BG, fg=theme.FG, selectcolor=theme.PANEL2,
                       activebackground=theme.BG, activeforeground=theme.GOLD,
                       font=theme.F_B).pack(side="left")
        label, color = {
            "free": ("空闲", theme.GREEN),
            "ours": ("本工具占用（正常）", theme.GREEN),
            "conflict": ("被占用", theme.RED),
        }.get(row.get("state"), ("未知", theme.MUTED))
        tk.Label(line, text=label, bg=theme.BG, fg=color, font=theme.F_S).pack(
            side="left", padx=(8, 0))
        if row.get("interface"):
            tk.Label(line, text="· %s" % row["interface"], bg=theme.BG, fg=theme.DIM,
                     font=theme.F_S).pack(side="left", padx=(6, 0))
        if row.get("is_virtual"):
            tk.Label(line, text="（虚拟网卡）", bg=theme.BG, fg=theme.DIM,
                     font=theme.F_S).pack(side="left", padx=(6, 0))
        if row.get("recommended"):
            tk.Label(line, text="推荐", bg=theme.BG, fg=theme.GOLD,
                     font=theme.F_S).pack(side="left", padx=(8, 0))
        if row["ip"] == current:
            tk.Label(line, text="（当前）", bg=theme.BG, fg=theme.MUTED,
                     font=theme.F_S).pack(side="left", padx=(6, 0))
        if row["ip"] == default_ip:
            pass

    hint = tk.Label(win, text="应用后请「保存配置 / 应用配置」，并重新安装一次（重写 hosts），否则游戏仍连旧 IP。",
                    bg=theme.BG, fg=theme.DIM, font=theme.F_S, justify="left",
                    padx=14, wraplength=620)
    hint.pack(fill="x", pady=(6, 0))

    picked = {"ip": None}

    def apply():
        ip = var.get().strip()
        if not ip:
            return
        target = app.profile.setdefault("proxy", {})
        target["listen_ip"] = ip
        app.mark_dirty()
        app.toast("监听地址已改为 %s —— 保存/应用配置后，记得重新安装以重写 hosts" % ip)
        picked["ip"] = ip
        win.destroy()

    btns = tk.Frame(win, bg=theme.BG)
    btns.pack(fill="x", padx=14, pady=10)
    theme.button(btns, "应用", command=apply, primary=True).pack(side="right")
    theme.button(btns, "取消", command=win.destroy).pack(side="right", padx=(0, 8))
    _center(root, win)
    win.grab_set()
    root.wait_window(win)
    return picked["ip"]


def port_conflict_dialog(parent, app, preflight: dict) -> str:
    """端口冲突确认框：返回 ``"switch"``（去换监听 IP）/ ``"start"``（仍然启动）/ ``"cancel"``。"""
    root = parent.winfo_toplevel()
    win = tk.Toplevel(root)
    win.title("端口被占用")
    win.configure(bg=theme.BG)
    win.transient(root)
    win.attributes("-topmost", True)

    tk.Label(win, text="启动引擎前检查发现端口被占用：", bg=theme.BG, fg=theme.FG,
             font=theme.F_B, padx=14, pady=(10, 4)).pack(anchor="w")
    body = tk.Frame(win, bg=theme.BG)
    body.pack(fill="both", expand=True, padx=14)
    for entry in preflight.get("conflicts") or []:
        tk.Label(body, text="· %s端口 %s：%s" % (
            entry.get("role"), entry.get("port"),
            "；".join("%s(PID %s)%s" % (o.get("name") or "?", o.get("pid") or "?",
                                       (" @ " + o["path"]) if o.get("path") else "")
                     for o in entry.get("owners") or []) or "查不到占用者"),
            bg=theme.BG, fg=theme.RED, font=theme.F_S, justify="left",
            wraplength=640).pack(anchor="w", pady=1)
        if entry.get("wildcard"):
            tk.Label(body, text="  ↑ 对方绑的是 0.0.0.0/:: 全体地址 —— 换监听 IP 无效，必须关掉它",
                     bg=theme.BG, fg=theme.GOLD, font=theme.F_S, justify="left",
                     wraplength=640).pack(anchor="w", pady=(0, 4))
    tk.Label(win, text="建议：关掉占用程序（旧代理/加速器/其它代理软件），或换一张网卡 IP。",
             bg=theme.BG, fg=theme.MUTED, font=theme.F_S, justify="left",
             padx=14, pady=(6, 10), wraplength=640).pack(anchor="w")

    picked = {"value": "cancel"}

    def choose(value):
        picked["value"] = value
        win.destroy()

    btns = tk.Frame(win, bg=theme.BG)
    btns.pack(fill="x", padx=14, pady=(0, 12))
    theme.button(btns, "换监听地址…", command=lambda: choose("switch")).pack(side="left")
    theme.button(btns, "仍然启动", command=lambda: choose("start")).pack(side="left", padx=(8, 0))
    theme.button(btns, "取消", command=lambda: choose("cancel")).pack(side="right")
    _center(root, win)
    win.grab_set()
    root.wait_window(win)
    return picked["value"]
