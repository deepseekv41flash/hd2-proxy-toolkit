"""抓包与日志页：抓包设置（写 profile.capture）+ 引擎子进程日志 + 最近改写事件。

日志来自 `EngineClient.log_lines`（app 每轮轮询把最近 40 行推给 `on_logs`）：
这里做增量追加（避免整段重画），显示上限 400 行。
"""

import os
import tkinter as tk
from collections import deque

from ...engine import paths
from .. import theme
from . import Page

LOG_LIMIT = 400               # 界面最多保留的日志行数
TAIL_WINDOW = 40              # app 每轮推过来的行数（增量比较用）


class CapturePage(Page):
    title = "抓包与日志"

    # ---------------------------------------------------------------- 构图
    def build(self):
        self.header("抓包与日志",
                    "抓包只读落盘（白名单路径 + 体积上限）；日志来自引擎子进程 stdout")
        self._log_buf = deque(maxlen=LOG_LIMIT)
        self._log_seen = []               # 上一轮的日志尾窗口（算增量用）

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        body.columnconfigure(0, weight=2, uniform="col")
        body.columnconfigure(1, weight=3, uniform="col")
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=theme.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = tk.Frame(body, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew")

        # ---- 抓包设置 --------------------------------------------------
        wrap, form = theme.section(left, "抓包设置", "写 profile.capture")
        wrap.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)      # 输入框/提示随列宽伸缩
        self.var_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text="启用抓包（enabled）", variable=self.var_enabled,
                       command=self._sync_capture, bg=theme.BG, fg=theme.FG,
                       selectcolor=theme.PANEL2, activebackground=theme.BG,
                       activeforeground=theme.FG,
                       font=theme.F_B).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)

        self.var_dir = tk.StringVar()
        self._row(form, 1, "目录", theme.entry(form, self.var_dir, width=18))
        tk.Label(form, text="留空 = 引擎默认（状态目录下 captures）",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, justify="left",
                 wraplength=200).grid(row=2, column=1, sticky="ew", padx=(8, 0),
                                      pady=(0, 6))

        self.var_paths = tk.StringVar()
        self._row(form, 3, "响应白名单", theme.entry(form, self.var_paths, width=18))
        tk.Label(form, text="逗号分隔（默认 api/）", bg=theme.BG, fg=theme.DIM,
                 font=theme.F_S, justify="left", wraplength=200).grid(
            row=4, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))

        self.var_req_paths = tk.StringVar()
        self._row(form, 5, "请求白名单", theme.entry(form, self.var_req_paths, width=18))
        tk.Label(form, text="留空 = 不抓请求体", bg=theme.BG, fg=theme.DIM,
                 font=theme.F_S, justify="left", wraplength=200).grid(
            row=6, column=1, sticky="ew", padx=(8, 0), pady=(0, 6))

        self.var_planet = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text="记录 planetInfos.settingsHash",
                       variable=self.var_planet, command=self._sync_capture,
                       bg=theme.BG, fg=theme.FG, selectcolor=theme.PANEL2,
                       activebackground=theme.BG, activeforeground=theme.FG,
                       font=theme.F_B).grid(row=7, column=0, columnspan=2, sticky="w", pady=3)
        tk.Label(form, text="生态借用要用的源值（抓一次 live warinfo）",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, justify="left",
                 wraplength=200).grid(row=8, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))

        btns = tk.Frame(form, bg=theme.BG)
        btns.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        theme.button(btns, "写回 profile", command=self._sync_capture).pack(
            side="left", padx=(0, 8))
        theme.button(btns, "应用到引擎", primary=True,
                     command=self._apply_capture).pack(side="left")
        self.engine_lbl = tk.Label(form, text="引擎 未运行", bg=theme.BG, fg=theme.DIM,
                                   font=theme.F_S, anchor="w")
        self.engine_lbl.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ---- 运行日志 --------------------------------------------------
        wrap, logbox = theme.section(right, "运行日志", "引擎子进程 stdout · 最多 400 行")
        wrap.pack(fill="both", expand=True)
        self.log_text = theme.ScrollText(logbox, height=9, mono=True)
        self.log_text.pack(fill="both", expand=True)
        log_bar = tk.Frame(logbox, bg=theme.BG)
        log_bar.pack(fill="x", pady=(8, 0))
        theme.button(log_bar, "清空显示", command=self._clear_log).pack(side="left",
                                                                       padx=(0, 8))
        theme.button(log_bar, "打开日志文件", command=self._open_log).pack(side="left")
        self.log_hint = tk.Label(log_bar, text="0 行", bg=theme.BG, fg=theme.DIM,
                                 font=theme.F_S)
        self.log_hint.pack(side="right")

        # ---- 最近改写事件 ----------------------------------------------
        head = tk.Frame(body, bg=theme.BG)
        head.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        tk.Label(head, text="最近改写事件", bg=theme.BG, fg=theme.FG,
                 font=theme.F_H).pack(anchor="w")
        wrap, self.events = theme.table(
            head, [("时间", 150), ("钩子", 150), ("内容", 620)], height=3)
        wrap.pack(fill="both", expand=True, pady=(6, 0))

    def _row(self, parent, row, label, widget):
        tk.Label(parent, text=label, bg=theme.BG, fg=theme.MUTED, font=theme.F_S,
                 anchor="e", width=8).grid(row=row, column=0, sticky="e", pady=3)
        widget.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=3)

    # ---------------------------------------------------------------- 设置
    @staticmethod
    def _split_list(text):
        """逗号分隔 -> 去重列表（中英文逗号都认）。"""
        out = []
        for part in str(text or "").replace("，", ",").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
        return out

    def _sync_capture(self, silent=False):
        """把表单写进 profile.capture（只改内存 + mark_dirty，不动引擎）。"""
        cap = self.app.profile.get("capture")
        if not isinstance(cap, dict):
            cap = {}
            self.app.profile["capture"] = cap
        cap["enabled"] = bool(self.var_enabled.get())
        cap["dir"] = self.var_dir.get().strip()
        cap["paths"] = self._split_list(self.var_paths.get()) or ["api/"]
        cap["req_paths"] = self._split_list(self.var_req_paths.get())
        cap["planet_settings"] = bool(self.var_planet.get())
        cap.setdefault("max_bytes", 8 << 20)
        self.app.mark_dirty()
        if not silent:
            self.app.toast("抓包设置已写入 profile（点右上角「应用配置」热更新）")
        return cap

    def _apply_capture(self):
        if not self.app.client.running():
            self.app.toast("引擎未运行 —— 先启动引擎再把抓包设置推下去", error=True)
            return
        cap = self._sync_capture(silent=True)
        enabled = bool(cap.get("enabled"))
        directory = cap.get("dir") or None

        def done(result):
            if isinstance(result, Exception):
                self.app.toast("应用抓包设置失败：%r" % (result,), error=True)
                return
            self.app.toast("已应用到引擎：抓包%s" % ("开" if enabled else "关"))

        self.app.run_bg(lambda: self.app.client.set_capture(enabled, directory), done,
                        busy="应用抓包设置…")

    # ---------------------------------------------------------------- 日志
    def on_logs(self, lines):
        """增量追加：`lines` 是最近 N 行的尾窗口，按「上一轮窗口的后缀 = 本轮窗口的前缀」找重叠。"""
        lines = [str(x) for x in (lines or [])]
        if not lines:
            return
        prev = self._log_seen
        overlap = 0
        for n in range(min(len(prev), len(lines)), 0, -1):
            if prev[-n:] == lines[:n]:
                overlap = n
                break
        self._log_seen = lines[-TAIL_WINDOW:]
        fresh = lines[overlap:]
        if not fresh:
            return
        for line in fresh:
            self._log_buf.append(line)
            self.log_text.append(line)
        self._trim_log()
        self.log_hint.configure(text="%d 行" % len(self._log_buf))

    def _trim_log(self):
        """超出 400 行就删最旧的几行（Tk Text 末尾自带一行空行，行号要减 1）。"""
        widget = self.log_text.text
        visible = int(widget.index("end-1c").split(".")[0]) - 1
        if visible <= LOG_LIMIT:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "%d.0" % (visible - LOG_LIMIT + 1))
        widget.configure(state="disabled")

    def _clear_log(self):
        self._log_buf.clear()
        self._log_seen = []
        self.log_text.set_text("")
        self.log_hint.configure(text="0 行")
        self.app.toast("日志显示已清空（引擎日志文件未动）")

    def _open_log(self):
        from ..openutil import open_path
        open_path(paths.PROXY_LOG, self.app.toast, label="日志文件")

    # ---------------------------------------------------------------- 状态
    def refresh(self):
        cap = self.app.profile.get("capture")
        cap = cap if isinstance(cap, dict) else {}
        self.var_enabled.set(bool(cap.get("enabled")))
        self.var_dir.set(str(cap.get("dir") or
                             (self.app.cert_dir().parent / "captures")))
        self.var_paths.set(", ".join(cap.get("paths") or ["api/"]))
        self.var_req_paths.set(", ".join(cap.get("req_paths") or []))
        self.var_planet.set(bool(cap.get("planet_settings")))
        self.log_hint.configure(text="%d 行" % len(self._log_buf))
        self.on_status(self.app.last_status)

    def on_status(self, status):
        if not status:
            self.engine_lbl.configure(text="引擎 未运行", fg=theme.DIM)
            theme.fill_table(self.events, [])
            return
        cap = status.get("capture")
        if isinstance(cap, dict):
            cap_text = "抓包 开" if cap.get("enabled") else "抓包 关"
        else:
            cap_text = "抓包 开" if cap else "抓包 关"
        self.engine_lbl.configure(text="引擎 运行中 · %s" % cap_text, fg=theme.GREEN)
        rows = []
        for ev in reversed(status.get("rewrites") or []):
            rows.append((str(ev.get("ts") or "")[-8:], ev.get("kind") or "",
                         ev.get("detail") or ""))
        theme.fill_table(self.events, rows)
