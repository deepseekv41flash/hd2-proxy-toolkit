"""实时战况页：不启动游戏 / 引擎也能拉官方战况，主要给**排查**用。

数据来自 `engine/live.py`（DoH 解析真实 IP → SNI 直连官方公共只读端点，免登录）：
  * 顶部工具条：拉取 / 保存快照 / 打开快照目录 / 自动刷新（默认关）；
  * 摘要卡：战局、星球/战役、星球效果、GWE 条数；
  * 左表「靶星」：有战役的星球（**卡面可点**，前线优先）——选错靶星是「卡面看不到」的头号原因；
  * 右表「星球效果」：`planetActiveEffects` 按星球聚合（可按星球名 / 索引 / effect id 过滤），
    选中一行会在下方列出该星球每个 effect 的 id + 名称。

排查口诀：卡面看不到 → 先确认「这颗星有战役（左表有它）」→ 再看右表里它到底挂了哪些 effect。
"""

import os
import tkinter as tk
from datetime import datetime

from ...engine import live as live_mod
from ...engine import paths
from .. import theme
from . import Page

DEFAULT_INTERVAL = 60          # 秒
MAX_EFFECT_CELL = 220          # 右表 effect ids 单元格最多显示的字符数


class LivePage(Page):
    title = "实时战况"

    # ---------------------------------------------------------------- 构图
    def build(self):
        self.snapshot = None
        self._loading = False
        self._auto_job = None
        self._effect_rows = []          # [(planet_index, [effect ids])]，供选中联动

        self.header("实时战况",
                    "官方公共只读 API · 无需启动游戏/引擎 —— 排查「卡面为什么没显示」")
        self._build_toolbar()
        self._build_cards()
        self._build_tables()
        self._hint = tk.Label(
            self, text="提示：只有「有战役」的星球卡面可点（左表）；0 号 SUPER EARTH 母星永远不显示。"
                       "点「拉取战况」开始。",
            bg=theme.BG, fg=theme.DIM, font=theme.F_S, justify="left", anchor="w",
            wraplength=1100)
        self._hint.pack(fill="x", padx=22, pady=(6, 12))

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=theme.BG)
        bar.pack(fill="x", padx=22, pady=(4, 0))
        theme.button(bar, "拉取战况", command=self.fetch_now, primary=True).pack(side="left")
        theme.button(bar, "保存快照", command=self.save_snapshot).pack(side="left",
                                                                     padx=(8, 0))
        theme.button(bar, "打开快照目录", command=self.open_dir).pack(side="left",
                                                                   padx=(8, 0))
        self.var_auto = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="自动刷新（秒）", variable=self.var_auto,
                       command=self._toggle_auto, bg=theme.BG, fg=theme.FG,
                       selectcolor=theme.PANEL2, activebackground=theme.BG,
                       activeforeground=theme.FG,
                       font=theme.F_S).pack(side="left", padx=(16, 4))
        self.var_interval = tk.StringVar(value=str(DEFAULT_INTERVAL))
        theme.entry(bar, self.var_interval, width=6).pack(side="left")
        self.state_lbl = tk.Label(bar, text="尚未拉取", bg=theme.BG, fg=theme.DIM,
                                  font=theme.F_S, anchor="e")
        self.state_lbl.pack(side="right")

    def _build_cards(self):
        cards = tk.Frame(self, bg=theme.BG)
        cards.pack(fill="x", padx=22, pady=(10, 0))
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="c")
        self.card_war = theme.card(cards, "战局", "—", "warId · status time")
        self.card_war[0].grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.card_planets = theme.card(cards, "星球 / 战役", "—", "planetStatus · campaigns")
        self.card_planets[0].grid(row=0, column=1, sticky="nsew", padx=10)
        self.card_effects = theme.card(cards, "星球效果", "—", "planetActiveEffects",
                                       accent=theme.GOLD)
        self.card_effects[0].grid(row=0, column=2, sticky="nsew", padx=10)
        self.card_gwe = theme.card(cards, "GWE 目录", "—", "GalacticWarEffects 条数")
        self.card_gwe[0].grid(row=0, column=3, sticky="nsew", padx=(10, 0))

    def _build_tables(self):
        body = tk.Frame(self, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=22, pady=(10, 0))
        body.columnconfigure(0, weight=2, uniform="col")
        body.columnconfigure(1, weight=3, uniform="col")
        body.rowconfigure(0, weight=1)

        # 左：靶星（有战役的星球）
        left, lbody = theme.section(body, "靶星（有战役 = 卡面可点）", "前线优先")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        wrap, self.targets = theme.table(
            lbody, [("阵营", 70), ("星球", 150), ("索引", 60), ("战役", 90)], height=10)
        wrap.pack(fill="both", expand=True)

        # 右：星球效果（可按星球/effect 过滤）
        right, rbody = theme.section(body, "星球效果（planetActiveEffects）",
                                     "选中一行看 effect 名称")
        right.grid(row=0, column=1, sticky="nsew")
        filt = tk.Frame(rbody, bg=theme.BG)
        filt.pack(fill="x", pady=(0, 6))
        tk.Label(filt, text="过滤", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self.var_filter = tk.StringVar()
        e = theme.entry(filt, self.var_filter, width=22)
        e.pack(side="left", padx=(6, 6))
        e.bind("<Return>", lambda _e: self._render_effects())
        theme.button(filt, "应用", command=self._render_effects).pack(side="left")
        tk.Label(filt, text="星球名 / 索引 / effect id", bg=theme.BG, fg=theme.DIM,
                 font=theme.F_S).pack(side="left", padx=(8, 0))
        wrap, self.effects = theme.table(
            rbody, [("星球", 200), ("effect ids", 290), ("数量", 46)], height=8)
        wrap.pack(fill="both", expand=True)
        self.effects.bind("<<TreeviewSelect>>", lambda _e: self._show_effect_detail())
        self.effect_detail = tk.Label(rbody, text="尚未拉取 —— 点「拉取战况」", bg=theme.BG, fg=theme.DIM,
                                      font=theme.F_S, justify="left", anchor="w",
                                      wraplength=560)
        self.effect_detail.pack(fill="x", pady=(6, 0))

    # ---------------------------------------------------------------- 拉取
    def fetch_now(self):
        if self._loading:
            return
        self._loading = True
        self.state_lbl.configure(text="拉取中…", fg=theme.GOLD)

        def work():
            snap = live_mod.fetch()
            saved = live_mod.save_snapshot(snap, self._last_dir())
            return {"snap": snap, "saved": saved}

        def done(result):
            self._loading = False
            if isinstance(result, Exception):
                self.state_lbl.configure(text="拉取失败：%s" % (result,), fg=theme.RED)
                self.app.toast("拉取实时战况失败", error=True)
                return
            self._render(result["snap"])
            self.state_lbl.configure(
                text="%s · 出口 %s · 用时 %ss · 快照 %s"
                     % (result["snap"].get("fetched_at"), result["snap"].get("ip"),
                        result["snap"].get("elapsed"),
                        os.path.dirname(result["saved"]["files"]["meta.json"])),
                fg=theme.MUTED)
            self.app.toast("实时战况已更新")

        self.app.run_bg(work, done, busy="拉取实时战况（无需游戏）…")

    @staticmethod
    def _last_dir():
        return paths.state_dir() / "live" / "last"

    def save_snapshot(self):
        if not self.snapshot:
            self.app.toast("还没有战况数据 —— 先点「拉取战况」", error=True)
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = paths.state_dir() / "live" / stamp
        saved = live_mod.save_snapshot(self.snapshot, target)
        self.app.toast("已保存快照：%s" % saved["out_dir"])
        self.app.show_text("快照已保存", "目录：%s\n\n文件：\n%s"
                           % (saved["out_dir"],
                              "\n".join("· %s" % p for p in saved["files"].values())))

    def open_dir(self):
        base = paths.state_dir() / "live"
        base.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(base))         # noqa: S606 - Windows 资源管理器
        except (AttributeError, OSError) as e:
            self.app.toast("打不开目录：%r" % (e,), error=True)

    # ---------------------------------------------------------------- 自动刷新
    def _toggle_auto(self):
        if self.var_auto.get():
            self._schedule_auto()
        elif self._auto_job is not None:
            try:
                self.app.root.after_cancel(self._auto_job)
            except (tk.TclError, AttributeError):
                pass
            self._auto_job = None

    def _interval(self):
        try:
            return max(15, min(600, int(self.var_interval.get())))
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL

    def _schedule_auto(self):
        if not self.var_auto.get():
            return
        self._auto_job = self.app.root.after(self._interval() * 1000, self._auto_tick)

    def _auto_tick(self):
        self._auto_job = None
        if not self.var_auto.get():
            return
        if getattr(self.app, "current_page", None) == "live":
            self.fetch_now()
        self._schedule_auto()

    # ---------------------------------------------------------------- 渲染
    def _render(self, snap):
        self.snapshot = snap
        s = snap.get("summary") or {}
        self.card_war[1].configure(text="war %s" % (s.get("war_id") or "?"))
        self.card_war[2].configure(text="status time %s" % (s.get("status_time") or "?"))
        self.card_planets[1].configure(
            text="%s / %s" % (s.get("planets") or 0, s.get("campaigns") or 0))
        self.card_planets[2].configure(
            text="攻击边 %s · 事件 %s" % (s.get("attacks") or 0, s.get("events") or 0))
        self.card_effects[1].configure(text=str(s.get("planet_effects") or 0))
        self.card_effects[2].configure(text="按星球聚合见右下表")
        self.card_gwe[1].configure(text=str(s.get("gwe_effects") or 0))
        self.card_gwe[2].configure(text="%s · %s" % (snap.get("host"), snap.get("ip")))
        self._render_targets()
        self._render_effects()
        self._hint.configure(
            fg=theme.DIM,
            text="提示：只有「有战役」的星球卡面可点（左表）；0 号 SUPER EARTH 母星永远不显示。"
                 "若目标星不在左表：它没有战役 → 换一颗有战役的星（推荐前线虫族/机器人/光能者星）。")

    def _render_targets(self):
        rows = live_mod.annotate(live_mod.suggest_targets(self.snapshot.get("status") or {}),
                                 self._name_map())
        theme.fill_table(self.targets, [
            (r.get("faction") or "?", (r.get("name") or "?")[:24], r.get("index"),
             r.get("campaign_id")) for r in rows])

    def _render_effects(self):
        status = (self.snapshot or {}).get("status") or {}
        text = (self.var_filter.get() or "").strip().lower()
        names = self._name_map()
        by_planet: dict[int, list[int]] = {}
        for e in status.get("planetActiveEffects") or []:
            if not isinstance(e, dict):
                continue
            try:
                idx = int(e.get("index"))
            except (TypeError, ValueError):
                continue
            try:
                eid = int(e.get("galacticEffectId"))
            except (TypeError, ValueError):
                continue
            by_planet.setdefault(idx, []).append(eid)
        rows, self._effect_rows = [], []
        for idx in sorted(by_planet):
            ids = sorted(by_planet[idx])
            label = "%s · %s" % (idx, names.get(idx) or "?")
            hay = (label + " " + " ".join(str(i) for i in ids)).lower()
            if text and text not in hay:
                continue
            cell = ", ".join(str(i) for i in ids)
            if len(cell) > MAX_EFFECT_CELL:
                cell = cell[:MAX_EFFECT_CELL] + "…"
            rows.append((label, cell, len(ids)))
            self._effect_rows.append((idx, ids))
        theme.fill_table(self.effects, rows)
        self.effect_detail.configure(text="共 %d 颗星球有生效效果" % len(rows))

    def _show_effect_detail(self):
        sel = self.effects.selection()
        if not sel:
            return
        try:
            pos = int(self.effects.index(sel[0]))
        except (ValueError, tk.TclError):
            return
        if not (0 <= pos < len(self._effect_rows)):
            return
        idx, ids = self._effect_rows[pos]
        label = "%s · %s" % (idx, self._name_map().get(idx) or "?")
        self.effect_detail.configure(
            text="%s → %s" % (label, "、".join(self._effect_label(i) for i in ids)))

    # ---------------------------------------------------------------- 名称
    def _name_map(self) -> dict[int, str]:
        rows = {}
        cats = getattr(self.app, "catalogs", None)
        if cats is None:
            return rows
        for idx, _label in (cats.planet_entries() or []):
            row = cats.planet_row(idx) or {}
            rows[int(idx)] = row.get("name") or "?"
        return rows

    def _effect_label(self, eid) -> str:
        cats = getattr(self.app, "catalogs", None)
        if cats is None:
            return str(eid)
        return cats.effect_label(eid)
