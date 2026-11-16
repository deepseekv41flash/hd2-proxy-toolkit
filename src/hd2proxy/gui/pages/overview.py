"""总览页：运行状态 / 证书 / 改写计数 / 抓包 + 主要动作 + 最近改写事件。"""

import tkinter as tk

from .. import theme
from ..app import _TextDialog
from . import Page


class OverviewPage(Page):
    title = "总览"

    def build(self):
        self.header("总览", "启动引擎 → 游戏里切一次星球即可生效；配置改动点「应用配置」热更新")

        # ---- 动作按钮（两行，避免窄窗裁切） ------------------------------
        bar = tk.Frame(self, bg=theme.BG)
        bar.pack(fill="x", padx=22, pady=(0, 10))
        row1 = tk.Frame(bar, bg=theme.BG)
        row1.pack(fill="x", pady=(0, 6))
        row2 = tk.Frame(bar, bg=theme.BG)
        row2.pack(fill="x")
        theme.button(row1, "启动引擎", command=self.app.start_engine, primary=True).pack(
            side="left", padx=(0, 8))
        theme.button(row1, "停止引擎", command=self.app.stop_engine).pack(side="left", padx=(0, 8))
        self.passthrough_btn = theme.button(row1, "切换直通", command=self._toggle_passthrough)
        self.passthrough_btn.pack(side="left", padx=(0, 8))
        theme.button(row1, "验证三连", command=self.app.verify).pack(side="left", padx=(0, 8))
        theme.button(row2, "签发 / 续期证书", command=self._renew_cert).pack(
            side="left", padx=(0, 8))
        theme.button(row2, "安装计划（dry-run）", command=self.app.install_dry).pack(
            side="left", padx=(0, 8))
        theme.button(row2, "还原计划（dry-run）", command=self.app.uninstall_dry).pack(
            side="left", padx=(0, 8))
        theme.button(row2, "打开日志", command=self._open_log).pack(side="left")

        # ---- 状态卡 ----------------------------------------------------
        cards = tk.Frame(self, bg=theme.BG)
        cards.pack(fill="x", padx=22)
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="c")
        self.card_engine = theme.card(cards, "运行状态", "未运行", "尚未启动引擎")
        self.card_engine[0].grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_cert = theme.card(cards, "证书有效期", "—", "会话证书 ca 模式（≤2 天）",
                                    accent=theme.GOLD)
        self.card_cert[0].grid(row=0, column=1, sticky="nsew", padx=10)
        self.card_stats = theme.card(cards, "本次改写", "0", "Status / 目录 / 库存")
        self.card_stats[0].grid(row=0, column=2, sticky="nsew", padx=10)
        self.card_capture = theme.card(cards, "抓包", "关", "白名单路径 · 只读落盘",
                                       accent=theme.MUTED)
        self.card_capture[0].grid(row=0, column=3, sticky="nsew", padx=(10, 0))

        # ---- 事件表 ----------------------------------------------------
        head = tk.Frame(self, bg=theme.BG)
        head.pack(fill="x", padx=22, pady=(16, 6))
        tk.Label(head, text="最近改写事件", bg=theme.BG, fg=theme.FG,
                 font=theme.F_H).pack(side="left")
        tk.Label(head, text="  来自引擎事件环（最多 200 条）", bg=theme.BG,
                 fg=theme.DIM, font=theme.F_S).pack(side="left")
        wrap, self.events = theme.table(
            self, [("时间", 140), ("钩子", 130), ("内容", 640)], height=9)
        wrap.pack(fill="both", expand=True, padx=22, pady=(0, 10))

        hint = tk.Frame(self, bg=theme.BG)
        hint.pack(fill="x", padx=22, pady=(0, 16))
        tk.Label(hint, text="提示：直通模式下不改写；验证三连 = TLS 握手 / CRL / Status 回执。"
                            "安装/还原的真操作需要一次 UAC，计划按钮只展示将改什么。",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, justify="left",
                 wraplength=1000).pack(anchor="w")

    # ---- 状态刷新 ------------------------------------------------------
    def on_status(self, status):
        if not status:
            self.card_engine[1].configure(text="未运行", fg=theme.MUTED)
            self.card_engine[2].configure(text="点「启动引擎」开始 · 关闭 GUI 不影响引擎")
            self.card_cert[1].configure(text="—", fg=theme.GOLD)
            self.card_stats[1].configure(text="0")
            self.card_capture[1].configure(text="关", fg=theme.MUTED)
            theme.fill_table(self.events, [])
            return
        mode = "直通" if status.get("mode") == "passthrough" else "改写"
        self.card_engine[1].configure(text=mode, fg=theme.FG if mode == "改写" else theme.GOLD)
        self.card_engine[2].configure(
            text="监听 %s:%s · 控制面 %s" % (status.get("listen_ip"), status.get("port"),
                                            status.get("control_port")))
        cert = status.get("cert") or {}
        hours = cert.get("remaining_hours")
        if cert.get("usable"):
            self.card_cert[1].configure(text="剩 %.1f 小时" % (hours or 0), fg=theme.GOLD)
            self.card_cert[2].configure(text="至 %s · 指纹 %s"
                                        % (cert.get("not_after", "?")[:16],
                                           (cert.get("thumbprint") or "")[:12]))
        else:
            self.card_cert[1].configure(text="不可用", fg=theme.RED)
            self.card_cert[2].configure(text="；".join(cert.get("warnings") or [])[:120])
        stats = status.get("stats") or {}
        self.card_stats[1].configure(text=str(stats.get("rewrite", 0)))
        self.card_stats[2].configure(text="请求 %s · 改写 %s · 拒绝 %s"
                                     % (stats.get("req", 0), stats.get("rewrite", 0),
                                        stats.get("deny", 0)))
        cap = status.get("capture") or {}
        on = bool(cap.get("enabled"))
        self.card_capture[1].configure(text="开" if on else "关",
                                       fg=theme.GREEN if on else theme.MUTED)
        self.card_capture[2].configure(
            text=("落盘目录 %s" % cap.get("dir")) if on else "在「抓包与日志」页开启")
        rows = []
        for ev in reversed(status.get("rewrites") or []):
            rows.append((ev.get("ts", "")[-8:], ev.get("kind", ""), ev.get("detail", "")))
        theme.fill_table(self.events, rows)

    def refresh(self):
        self.on_status(self.app.last_status)

    # ---- 动作 ----------------------------------------------------------
    def _toggle_passthrough(self):
        if not self.app.client.running():
            self.app.toast("引擎未运行", error=True)
            return
        current = (self.app.last_status or {}).get("mode")
        want = current != "passthrough"

        def done(result):
            if isinstance(result, Exception):
                self.app.toast("切换失败：%r" % (result,), error=True)
                return
            self.app.toast("已切到%s" % ("直通（不改写）" if want else "改写模式"))

        self.app.run_bg(lambda: self.app.client.set_passthrough(want), done,
                        busy="切换模式…")

    def _renew_cert(self):
        prof = self.app.profile
        args = ["certs", "renew", "--cert-dir", str(self.app.cert_dir()),
                "--days", str(prof["cert"]["days"])]

        def done(result):
            if isinstance(result, Exception):
                self.app.toast("签发失败：%r" % (result,), error=True)
                return
            code, out = result
            self.app.toast("证书签发%s" % ("成功" if code == 0 else "失败"), error=code != 0)
            _TextDialog(self.winfo_toplevel(), "证书签发", out)

        self.app.run_bg(lambda: self.app.client.run_cli(args), done, busy="签发证书…")

    def _open_log(self):
        from ..openutil import open_path
        from ...engine import paths
        open_path(paths.PROXY_LOG, self.app.toast, label="日志文件")
