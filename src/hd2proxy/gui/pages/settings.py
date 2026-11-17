"""设置页：profile 表单（proxy / cert）+ 路径与版本信息。"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

from ...engine import config as cfgmod
from ...engine import paths
from .. import theme
from . import Page


class SettingsPage(Page):
    title = "设置"

    def build(self):
        self.header("设置", "profile 就是引擎的全部输入（schema v2）；保存后「应用配置」热更新")

        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 16))
        body.columnconfigure(0, weight=3, uniform="c")
        body.columnconfigure(1, weight=2, uniform="c")

        left = tk.Frame(body, bg=theme.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = tk.Frame(body, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew")

        # ---- profile ---------------------------------------------------
        wrap, f = theme.section(left, "Profile", "保存位置与名称")
        wrap.pack(fill="x", pady=(0, 12))
        self.var_name = tk.StringVar()
        self._row(f, 0, "名称", ttk.Entry(f, textvariable=self.var_name, width=26))
        self.path_lbl = tk.Label(f, text="", bg=theme.BG, fg=theme.DIM, font=theme.F_S,
                                 anchor="w", justify="left", wraplength=520)
        self.path_lbl.grid(row=1, column=0, columnspan=3, sticky="w", padx=(92, 0), pady=(0, 6))
        btnbar = tk.Frame(f, bg=theme.BG)
        btnbar.grid(row=2, column=0, columnspan=3, sticky="w", padx=(92, 0))
        theme.button(btnbar, "保存配置", command=lambda: self.app.save_profile(False)).pack(
            side="left", padx=(0, 8))
        theme.button(btnbar, "应用配置（热更新）", primary=True,
                     command=lambda: self.app.save_profile(True)).pack(side="left", padx=(0, 8))
        theme.button(btnbar, "另存为", command=self._save_as).pack(side="left")

        # ---- proxy -----------------------------------------------------
        wrap, f = theme.section(left, "代理", "监听与上游；listen_ip 不能是回环（新版客户端拒绝）")
        wrap.pack(fill="x", pady=(0, 12))
        self.var_host = tk.StringVar()
        self.var_listen = tk.StringVar()
        self.var_port = tk.StringVar()
        self.var_crl = tk.StringVar()
        self.var_control = tk.StringVar()
        self.var_passthrough = tk.BooleanVar()
        self.var_verbose = tk.BooleanVar()
        self._row(f, 0, "目标域名", ttk.Entry(f, textvariable=self.var_host, width=34))
        self._row(f, 1, "监听 IP", ttk.Entry(f, textvariable=self.var_listen, width=26))
        theme.button(f, "换监听地址…", command=self._choose_listen).grid(
            row=1, column=2, sticky="w", padx=(8, 0))
        tk.Label(f, text="auto = 自动选主网卡；也可填本机非回环 IP", bg=theme.BG,
                 fg=theme.DIM, font=theme.F_S).grid(row=2, column=1, columnspan=2,
                                                    sticky="w", padx=(8, 0), pady=(0, 4))
        self._row(f, 3, "监听端口", ttk.Entry(f, textvariable=self.var_port, width=12))
        self._row(f, 4, "CRL 端口", ttk.Entry(f, textvariable=self.var_crl, width=12))
        self._row(f, 5, "控制面端口", ttk.Entry(f, textvariable=self.var_control, width=12))
        chk = tk.Frame(f, bg=theme.BG)
        chk.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=2)
        for text, var in (("直通模式（不改写）", self.var_passthrough),
                          ("详细日志", self.var_verbose)):
            tk.Checkbutton(chk, text=text, variable=var, bg=theme.BG, fg=theme.FG,
                           selectcolor=theme.PANEL2, activebackground=theme.BG,
                           activeforeground=theme.FG,
                           font=theme.F_S).pack(side="left", padx=(0, 12))

        # ---- cert ------------------------------------------------------
        wrap, f = theme.section(left, "证书", "ca 模式；有效期硬上限 2 天；签完即删 CA 私钥")
        wrap.pack(fill="x", pady=(0, 12))
        self.var_days = tk.StringVar()
        self.var_minrem = tk.StringVar()
        self.var_autorenew = tk.BooleanVar()
        self._row(f, 0, "有效期（天）", ttk.Combobox(f, textvariable=self.var_days,
                                                    values=["1", "2"], width=6, state="readonly"))
        self._row(f, 1, "剩余<（小时）续期", ttk.Entry(f, textvariable=self.var_minrem, width=6))
        tk.Checkbutton(f, text="启动前自动续期", variable=self.var_autorenew, bg=theme.BG,
                       fg=theme.FG, selectcolor=theme.PANEL2, activebackground=theme.BG,
                       activeforeground=theme.FG,
                       font=theme.F_S).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=2)

        # ---- 右侧：环境信息 --------------------------------------------
        wrap, info = theme.section(right, "环境", "只读")
        wrap.pack(fill="both", expand=True)
        self.info_text = theme.ScrollText(info, height=21, mono=True, wrap="word")
        self.info_text.pack(fill="both", expand=True)
        btns = tk.Frame(info, bg=theme.BG)
        btns.pack(fill="x", pady=(8, 0))
        theme.button(btns, "打开状态目录",
                     command=lambda: self._open(paths.state_dir())).pack(side="left", padx=(0, 8))
        theme.button(btns, "打开日志",
                     command=lambda: self._open(paths.LOGDIR)).pack(side="left")

    # ---- 小工具 -------------------------------------------------------
    def _row(self, parent, row, label, widget):
        tk.Label(parent, text=label, bg=theme.BG, fg=theme.MUTED, font=theme.F_S,
                 anchor="e", width=13).grid(row=row, column=0, sticky="e", pady=2)
        widget.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=2)

    def _open(self, path, label="目录", hint="引擎运行过之后才会有内容"):
        from ..openutil import open_path
        if not open_path(path, self.app.toast, label=label, hint=hint):
            return
        return True

    def _choose_listen(self):
        """「换监听地址」对话框：候选只列真实网卡 IP，并标出每个 IP 上 443 的占用状态。"""
        from .. import listen_ip as listen_ip_ui
        ip = listen_ip_ui.choose_listen_ip(self, self.app)
        if ip:
            self.var_listen.set(ip)
            proxy = self.app.profile.setdefault("proxy", {})
            proxy["listen_ip"] = ip          # 与对话框保持一致；保存时以表单为准
            self.app.mark_dirty()

    def _save_as(self):
        name = self.var_name.get().strip() or "新配置"
        try:
            normalized, errors, _ = cfgmod.validate(self._collect())
            if errors:
                messagebox.showerror("校验失败", "\n".join(errors))
                return
            target = cfgmod.profile_path(name)
            cfgmod.save_profile_file(target, normalized)
            self.app.profile_path = target
            self.path_lbl.configure(text="已另存：%s" % target)
            self.app.toast("已另存 profile：%s" % name)
        except Exception as e:          # noqa: BLE001
            messagebox.showerror("另存失败", repr(e))

    # ---- 表单 <-> profile --------------------------------------------
    def refresh(self):
        p = self.app.profile
        self.var_name.set(p.get("name") or "")
        proxy = p.get("proxy") or {}
        self.var_host.set(proxy.get("host") or "")
        self.var_listen.set(proxy.get("listen_ip") or "auto")
        self.var_port.set(str(proxy.get("port") or 443))
        self.var_crl.set(str(proxy.get("crl_port") or 8080))
        self.var_control.set(str(proxy.get("control_port") or 17897))
        self.var_passthrough.set(bool(proxy.get("passthrough")))
        self.var_verbose.set(bool(proxy.get("verbose")))
        cert = p.get("cert") or {}
        self.var_days.set(str(cert.get("days") or 2))
        self.var_minrem.set(str(cert.get("min_remaining_hours") or 12))
        self.var_autorenew.set(bool(cert.get("auto_renew", True)))
        self.path_lbl.configure(text="当前 profile：%s" % self.app.profile_path)
        self.info_text.set_text(self._env_text())

    def _collect(self):
        p = json_clone(self.app.profile)
        p["name"] = self.var_name.get().strip() or "默认"
        proxy = p.setdefault("proxy", {})
        proxy["host"] = self.var_host.get().strip()
        proxy["listen_ip"] = self.var_listen.get().strip() or "auto"
        proxy["port"] = _int(self.var_port.get(), 443)
        proxy["crl_port"] = _int(self.var_crl.get(), 8080)
        proxy["control_port"] = _int(self.var_control.get(), 17897)
        proxy["passthrough"] = bool(self.var_passthrough.get())
        proxy["verbose"] = bool(self.var_verbose.get())
        cert = p.setdefault("cert", {})
        cert["days"] = _int(self.var_days.get(), 2)
        cert["min_remaining_hours"] = _float(self.var_minrem.get(), 12.0)
        cert["auto_renew"] = bool(self.var_autorenew.get())
        return p

    def _env_text(self):
        import hd2proxy
        build = self.app.catalogs.build or {}
        cat = self.app.catalogs.summary()
        lines = [
            "hd2-proxy-toolkit %s" % hd2proxy.__version__,
            "仓库        : %s" % paths.REPO_ROOT,
            "数据目录    : %s" % paths.DATA_DIR,
            "状态目录    : %s" % paths.state_dir(),
            "证书目录    : %s" % self.app.cert_dir(),
            "日志        : %s" % paths.PROXY_LOG,
            "profile     : %s" % self.app.profile_path,
            "",
            "游戏 build  : %s" % build.get("game_build", "?"),
            "warId       : %s" % build.get("war_id", "?"),
            "",
            "catalogs    : 变种 %d / 战备 %d / 效果 %d / 星球 %d / 物品 %d"
            % (cat["variants"], cat["stratagems"], cat["effects"],
               cat["planets"], cat["items"]),
            "引擎        : %s" % ("运行中" if self.app.client.running() else "未运行"),
        ]
        warnings = (self.app.profile.get("_warnings") or []) + (cat.get("warnings") or [])
        if warnings:
            lines += ["", "提示："] + ["  · " + w for w in warnings]
        return "\n".join(lines)


def json_clone(obj):
    import json
    return json.loads(json.dumps(obj))


def _int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value, default):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default
