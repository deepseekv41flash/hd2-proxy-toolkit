"""GUI 壳：顶部状态条 + 左侧 5 页导航 + 内容区 + 底部状态行。

设计约束（M2 门禁）：GUI 只是控制面客户端 ——
  * 页面只读写 `app.profile`（schema v2 dict）与 `app.client`（引擎控制面）；
  * 轮询在后台线程，Tk 主线程只渲染；
  * 引擎未运行时所有页面仍可编辑配置（保存为 profile 文件），不报错。
"""

import json
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from ..engine import config as cfgmod
from ..engine import diagnostics, paths, sysprobe
from . import catalogs as catalogs_mod
from . import theme
from .client import EngineClient, EngineError, REPO

PAGE_DEFS = [
    ("overview", "◈", "总览"),
    ("status", "◍", "战况改写"),
    ("inventory", "▤", "物品与战备"),
    ("capture", "◫", "抓包与日志"),
    ("settings", "⚙", "设置"),
]


class App:
    def __init__(self, root: tk.Tk, profile_path=None, client=None, catalogs=None):
        self.root = root
        self.client = client or EngineClient()
        self.catalogs = catalogs or catalogs_mod.Catalogs()
        self.profile_path = profile_path or (cfgmod.profile_path("default"))
        self.profile = self._load_profile()
        self.pages = {}
        self.current_page = None
        self.dirty = False
        self.last_status = None
        self._queue = queue.Queue()
        self._stop_poll = threading.Event()

        root.title("HD2 战况代理工坊")
        root.geometry("1180x780")
        root.minsize(980, 660)
        root.configure(bg=theme.BG)
        theme.apply_theme(root)

        self._build()
        self._start_poll()
        self.show_page("overview")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Destroy>", self._on_root_destroy, add="+")

    # ---------------------------------------------------------------- 配置
    def _load_profile(self):
        if self.client.running():
            try:
                doc = self.client.config()
                if doc.get("mode") == "profile" and isinstance(doc.get("profile"), dict):
                    self.profile_path = doc.get("path") or self.profile_path
                    return doc["profile"]
            except EngineError:
                pass
        try:
            return cfgmod.load_profile_file(self.profile_path)
        except Exception:
            prof = cfgmod.default_profile(name="默认")
            prof["_warnings"] = ["尚未创建 profile（首次点“保存配置”会写入 %s）"
                                 % self.profile_path]
            return prof

    def mark_dirty(self):
        self.dirty = True
        self._refresh_topbar()

    def save_profile(self, apply=False):
        prof = {k: v for k, v in self.profile.items() if not k.startswith("_")}
        normalized, errors, warnings = cfgmod.validate(prof)
        if errors:
            messagebox.showerror("配置校验失败", "\n".join("· " + e for e in errors))
            return False
        try:
            if apply and self.client.running():
                result = self.client.put_config(normalized)
                self.profile = normalized
                self.dirty = False
                self.toast("已应用到引擎（热更新，无需重启）")
                self._after_profile_change()
                return True
            cfgmod.save_profile_file(self.profile_path, normalized)
            self.profile = normalized
            self.dirty = False
            self.toast("已保存：%s" % self.profile_path)
            if apply:
                self.toast("已保存；引擎未运行 —— 启动引擎后即生效")
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("保存失败", repr(e))
            return False
        self._after_profile_change()
        return True

    def _after_profile_change(self):
        self._refresh_topbar()
        page = self.pages.get(self.current_page)
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    # ---------------------------------------------------------------- 构图
    def _build(self):
        self.top = tk.Frame(self.root, bg=theme.PANEL, height=46)
        self.top.pack(fill="x")
        tk.Frame(self.top, bg=theme.BORDER, height=1).pack(side="bottom", fill="x")
        left = tk.Frame(self.top, bg=theme.PANEL)
        left.pack(side="left", padx=14)
        tk.Label(left, text="HD2 战况代理工坊", bg=theme.PANEL, fg=theme.FG,
                 font=(theme.FONT, 12, "bold")).pack(side="left")
        build = self.catalogs.build or {}
        tk.Label(left, text="  build %s · warId %s"
                 % (build.get("game_build", "?"), build.get("war_id", "?")),
                 bg=theme.PANEL, fg=theme.DIM, font=theme.F_S).pack(side="left")

        right = tk.Frame(self.top, bg=theme.PANEL)
        right.pack(side="right", padx=12)
        self.pills = {}
        for key, text in (("engine", "● 引擎"), ("cert", "证书"), ("capture", "抓包"),
                          ("profile", "配置")):
            lbl = theme.pill(right, text)
            lbl.pack(side="right", padx=3)
            self.pills[key] = lbl
        theme.button(right, "应用配置", command=lambda: self.save_profile(True),
                     primary=True).pack(side="right", padx=(0, 8))
        theme.button(right, "保存配置",
                     command=lambda: self.save_profile(False)).pack(side="right", padx=(0, 4))

        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(fill="both", expand=True)

        self.nav = tk.Frame(body, bg=theme.PANEL, width=188)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        tk.Frame(body, bg=theme.BORDER, width=1).pack(side="left", fill="y")
        self.nav_rows = {}
        for key, icon, label in PAGE_DEFS:
            self._make_nav_row(key, icon, label)
        foot = tk.Frame(self.nav, bg=theme.PANEL)
        foot.pack(side="bottom", fill="x", padx=12, pady=12)
        tk.Label(foot, text="GUI 只是控制面客户端", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.F_S).pack(anchor="w")
        tk.Label(foot, text="引擎独立进程 · 关窗不打断游戏",
                 bg=theme.PANEL, fg=theme.DIM, font=theme.F_S,
                 wraplength=160, justify="left").pack(anchor="w")

        self.content = tk.Frame(body, bg=theme.BG)
        self.content.pack(side="left", fill="both", expand=True)

        bottom = tk.Frame(self.root, bg=theme.PANEL, height=26)
        bottom.pack(fill="x", side="bottom")
        tk.Frame(bottom, bg=theme.BORDER, height=1).pack(side="top", fill="x")
        self.status_msg = tk.Label(bottom, text="就绪", bg=theme.PANEL, fg=theme.DIM,
                                   font=theme.F_S)
        self.status_msg.pack(side="left", padx=12)
        self.status_engine = tk.Label(bottom, text="引擎 未运行", bg=theme.PANEL,
                                      fg=theme.MUTED, font=theme.F_S)
        self.status_engine.pack(side="right", padx=12)

    def _make_nav_row(self, key, icon, label):
        row = tk.Frame(self.nav, bg=theme.PANEL)
        row.pack(fill="x", padx=10, pady=2)
        bar = tk.Frame(row, bg=theme.PANEL, width=3)
        bar.pack(side="left", fill="y")
        ic = tk.Label(row, text=icon, bg=theme.PANEL, fg=theme.MUTED, font=(theme.FONT, 12))
        ic.pack(side="left", padx=(10, 8), pady=9)
        tx = tk.Label(row, text=label, bg=theme.PANEL, fg=theme.MUTED, font=theme.F_B)
        tx.pack(side="left")
        self.nav_rows[key] = (row, bar, ic, tx)
        for w in (row, ic, tx):
            w.bind("<Button-1>", lambda _e, k=key: self.show_page(k))

    # ---------------------------------------------------------------- 页面
    def show_page(self, key):
        if key not in dict((p[0], p) for p in PAGE_DEFS):
            return
        for k, (row, bar, ic, tx) in self.nav_rows.items():
            active = k == key
            row.configure(bg=theme.PANEL2 if active else theme.PANEL)
            bar.configure(bg=theme.GOLD if active else theme.PANEL)
            ic.configure(bg=theme.PANEL2 if active else theme.PANEL,
                         fg=theme.GOLD if active else theme.MUTED)
            tx.configure(bg=theme.PANEL2 if active else theme.PANEL,
                         fg=theme.FG if active else theme.MUTED,
                         font=theme.F_H if active else theme.F_B)
        if self.current_page and self.current_page != key:
            self.pages[self.current_page].pack_forget()
        page = self.pages.get(key)
        if page is None:
            page = self._make_page(key)
            if page is None:
                return
            self.pages[key] = page
        page.pack(fill="both", expand=True)
        self.current_page = key
        if hasattr(page, "refresh"):
            page.refresh()
        if hasattr(page, "on_status"):
            page.on_status(self.last_status)

    def _make_page(self, key):
        try:
            if key == "overview":
                from .pages.overview import OverviewPage
                return OverviewPage(self.content, self)
            if key == "status":
                from .pages.status_page import StatusPage
                return StatusPage(self.content, self)
            if key == "inventory":
                from .pages.inventory import InventoryPage
                return InventoryPage(self.content, self)
            if key == "capture":
                from .pages.capture import CapturePage
                return CapturePage(self.content, self)
            if key == "settings":
                from .pages.settings import SettingsPage
                return SettingsPage(self.content, self)
        except Exception as e:      # noqa: BLE001
            tk.Label(self.content, text="页面加载失败：%r" % (e,), bg=theme.BG,
                     fg=theme.RED, font=theme.F_B).pack(padx=20, pady=20)
            return None
        return None

    # ---------------------------------------------------------------- 轮询
    def _start_poll(self):
        def loop():
            while not self._stop_poll.is_set():
                status = None
                if self.client.state() is not None:
                    try:
                        status = self.client.status()
                    except Exception:
                        status = None
                self._queue.put((status, list(self.client.log_lines)[-40:]))
                time.sleep(0.6)

        threading.Thread(target=loop, daemon=True).start()
        self.root.after(120, self._drain)

    def _drain(self):
        latest = None
        while True:
            try:
                latest = self._queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            status, logs = latest
            self.last_status = status
            self._apply_status(status)
            page = self.pages.get(self.current_page)
            if page is not None and hasattr(page, "on_status"):
                page.on_status(status)
            cap = self.pages.get("capture")
            if cap is not None and hasattr(cap, "on_logs"):
                cap.on_logs(logs)
            self.status_engine.configure(
                text="引擎 运行中 · %s" % (self.client.state() or {}).get("url", ""),
                fg=theme.GREEN if status else theme.MUTED)
        if not self._stop_poll.is_set():
            try:
                self.root.after(150, self._drain)
            except tk.TclError:
                self._stop_poll.set()

    def _apply_status(self, status):
        running = status is not None
        self.pills["engine"].configure(
            text="● 引擎 运行中" if running else "● 引擎 未运行",
            fg=theme.GREEN if running else theme.DIM,
            bg="#1a2b20" if running else theme.PANEL2)
        if running:
            cert = status.get("cert") or {}
            hours = cert.get("remaining_hours")
            warn = not cert.get("usable")
            self.pills["cert"].configure(
                text="证书 %s" % (("剩 %.1f 小时" % hours) if hours else "—"),
                fg=theme.RED if warn else (theme.GOLD if (hours or 99) < 12 else theme.GREEN),
                bg="#3a1f22" if warn else (theme.PANEL2 if not hours else "#2c2716"))
            cap = status.get("capture") or {}
            self.pills["capture"].configure(
                text="抓包 %s" % ("开" if cap.get("enabled") else "关"),
                fg=theme.GREEN if cap.get("enabled") else theme.MUTED)
            self.pills["profile"].configure(
                text="配置 %s" % (status.get("profile") or "legacy"), fg=theme.MUTED)
        else:
            self.pills["cert"].configure(text="证书 —", fg=theme.DIM, bg=theme.PANEL2)
            self.pills["capture"].configure(text="抓包 —", fg=theme.DIM)
            self.pills["profile"].configure(text="配置 未连接", fg=theme.DIM)
        self._refresh_topbar()

    def _refresh_topbar(self):
        name = self.profile.get("name") or "?"
        mark = " *未保存" if self.dirty else ""
        self.pills["profile"].configure(text="配置 %s%s" % (name, mark))

    # ---------------------------------------------------------------- 动作
    def toast(self, text, error=False):
        self.status_msg.configure(text=text, fg=theme.RED if error else theme.MUTED)

    def run_bg(self, fn, on_done, busy="执行中…"):
        self.toast(busy)

        def work():
            try:
                result = fn()
            except Exception as e:      # noqa: BLE001
                result = e
            self.root.after(0, lambda: on_done(result))

        threading.Thread(target=work, daemon=True).start()

    # ---- 引擎 ---------------------------------------------------------
    def cert_dir(self):
        d = paths.state_dir() / "certs"
        if (d / "session.json").exists():
            return d
        return paths.CERT_DIR

    def start_engine(self):
        if self.client.running():
            self.toast("引擎已在运行")
            return
        if not self._guard_game_running("启动引擎"):
            return
        if not self._preflight_ports():
            return
        prof = {k: v for k, v in self.profile.items() if not k.startswith("_")}
        normalized, errors, _ = cfgmod.validate(prof)
        if errors:
            messagebox.showerror("配置校验失败", "\n".join(errors))
            return
        self.profile = normalized
        cert_dir = self.cert_dir()
        if not (cert_dir / "session.json").exists():
            if not messagebox.askyesno("缺少会话证书",
                                       "还没有会话证书（%s）。\n要现在签发一张吗（ca 模式 1 天）？"
                                       % cert_dir):
                return
            code, out = self.client.run_cli(["certs", "renew", "--cert-dir", str(cert_dir),
                                             "--days", str(normalized["cert"]["days"])])
            self.toast("证书签发%s" % ("成功" if code == 0 else "失败"), error=code != 0)
            if code != 0:
                messagebox.showerror("签发失败", out[-1500:])
                return
        try:
            cfgmod.save_profile_file(self.profile_path, normalized)
            self.dirty = False
        except Exception as e:      # noqa: BLE001
            messagebox.showerror("保存 profile 失败", repr(e))
            return
        proxy = normalized["proxy"]
        self.run_bg(
            lambda: (self.client.start_engine(
                self.profile_path, cert_dir,
                listen_ip=(None if proxy.get("listen_ip") == "auto" else proxy["listen_ip"]),
                control_port=proxy.get("control_port"),
                extra=("--no-auto-renew",) if not normalized["cert"]["auto_renew"] else ()),
                self.client.wait_ready(30)),
            lambda r: self._after_start(r), busy="启动引擎…")

    def _after_start(self, result):
        if isinstance(result, Exception):
            messagebox.showerror("启动失败", repr(result))
            return
        proc, ready = result
        if ready:
            self.toast("引擎已启动 —— 游戏里切一次星球即可生效")
            self._after_profile_change()
        else:
            tail = "\n".join(list(self.client.log_lines)[-25:])
            messagebox.showerror("引擎启动失败",
                                 "进程退出或 30 秒内未就绪。\n\n最近日志：\n" + tail[-1800:])
            self.toast("引擎启动失败", error=True)

    def stop_engine(self):
        if not self.client.running() and not self.client.engine_alive():
            self.toast("引擎未运行")
            return
        if not self._guard_game_running("停止引擎"):
            return
        self.run_bg(lambda: self.client.shutdown(), lambda _r: self.toast("引擎已停止"),
                    busy="停止引擎…")

    # ---- 端口 / 游戏守卫（P0：来自第三方工具 1.26 的现场经验） ----------
    def _guard_game_running(self, action: str) -> bool:
        """游戏在跑时启停代理会掐断会话（卡登录/通讯出错）—— 默认拦下，用户确认才继续。"""
        if not sysprobe.game_running():
            return True
        message = ("检测到《Helldivers 2》正在运行。" + chr(10) + chr(10)
                   + "%s可能掐断当前会话（表现为卡登录 / 与服务器通讯时出错）。" % action
                   + chr(10) + "建议先退出游戏再操作。" + chr(10) + chr(10) + "仍然继续吗？")
        ok = messagebox.askyesno("游戏正在运行", message, icon="warning")
        if not ok:
            self.toast("已取消：游戏运行中，先退出游戏再%s" % action)
        return ok

    def _preflight_ports(self) -> bool:
        """启动前端口预检（443 / CRL / 控制面）：冲突时让用户换监听 IP、仍然启动或取消。"""
        from . import listen_ip as listen_ip_ui

        for _attempt in range(3):
            pre = diagnostics.port_preflight(self.profile)
            if pre.get("listen_error"):
                messagebox.showerror("监听地址不可用", pre["listen_error"])
                return False
            if not pre.get("conflicts"):
                return True
            choice = listen_ip_ui.port_conflict_dialog(self.root, self, pre)
            if choice == "switch":
                if not listen_ip_ui.choose_listen_ip(self.root, self):
                    return False
                continue                    # 换完再查一次（最多 3 轮）
            if choice == "start":
                self.toast("端口被占用，仍尝试启动 —— 失败请看日志里的 BIND FAIL 占用者")
                return True
            return False
        return True

    def selfcheck(self):
        """系统自检：端口占用 / hosts 状态 / 证书 / 游戏进程（只读，不需要管理员）。"""
        snapshot = diagnostics.collect(self.profile, cert_dir=self.cert_dir())
        self.show_text("系统自检", diagnostics.format_text(snapshot))
        return snapshot

    def verify(self):
        if not self.client.running():
            messagebox.showinfo("验证", "引擎未运行 —— 先启动引擎再验证。")
            return

        def done(result):
            if isinstance(result, Exception):
                messagebox.showerror("验证失败", repr(result))
                return
            lines = ["%s  %s —— %s" % ("[OK  ]" if c["ok"] else "[FAIL]",
                                       c["name"], c["detail"]) for c in result["checks"]]
            text = ("验证通过 ✓\n\n" if result.get("ok") else "验证未通过 ✗\n\n") + "\n".join(lines)
            self.toast("验证%s" % ("通过" if result.get("ok") else "未通过"),
                       error=not result.get("ok"))
            (messagebox.showinfo if result.get("ok") else messagebox.showwarning)("验证三连", text)

        self.run_bg(self.client.verify, done, busy="验证中…")

    def install_dry(self):
        prof = self.profile
        listen = prof["proxy"].get("listen_ip") or "auto"
        args = ["install", "--dry-run", "--cert-dir", str(self.cert_dir()),
                "--listen-ip", listen]
        self._run_cli_dialog(args, "安装计划（dry-run，不改系统）")

    def uninstall_dry(self):
        prof = self.profile
        listen = prof["proxy"].get("listen_ip") or "auto"
        args = ["uninstall", "--dry-run", "--cert-dir", str(self.cert_dir()),
                "--listen-ip", listen]
        self._run_cli_dialog(args, "还原计划（dry-run，不改系统）")

    def _run_cli_dialog(self, args, title):
        def done(result):
            if isinstance(result, Exception):
                messagebox.showerror(title, repr(result))
                return
            code, out = result
            self.toast("%s %s" % (title, "完成" if code == 0 else "失败"), error=code != 0)
            _TextDialog(self.root, title, out)
        self.run_bg(lambda: self.client.run_cli(args), done, busy=title)

    def show_text(self, title, content):
        """只读文本窗口（能力模板说明 / 离线预演结果等）。"""
        _TextDialog(self.root, title, content)

    # ---------------------------------------------------------------- 关闭
    def _on_root_destroy(self, event=None):
        """窗口被直接 destroy（测试/异常）时也要停轮询线程，避免之后 Tk 状态异常。"""
        if event is None or getattr(event, "widget", None) is self.root:
            self._stop_poll.set()

    def on_close(self):
        self._stop_poll.set()
        running = self.client.running()
        if running and not messagebox.askyesno(
                "退出 GUI", "引擎仍在运行，关窗不会停它（游戏不受影响）。\n要一起停止引擎吗？"):
            self.root.destroy()
            return
        if running:
            try:
                self.client.shutdown()
            except Exception:
                pass
        self.root.destroy()


class _TextDialog(tk.Toplevel):
    """只读输出窗口（安装/还原计划、CLI 输出、离线预演报告）。

    为什么用 wrap="word"：这些输出里有很长的一行（路径/指纹/JSON），wrap="none" 会被
    右边界裁掉且没有横向滚动条 —— 实测「离线预演」「安装计划」窗口左右看不全 ✓
    """

    def __init__(self, master, title, content):
        super().__init__(master)
        self.title(title)
        self.geometry("760x560")
        self.configure(bg=theme.BG)
        box = theme.ScrollText(self, height=26, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        box.set_text(content, see_end=False)
        theme.button(self, "关闭", command=self.destroy).pack(pady=(0, 12))
