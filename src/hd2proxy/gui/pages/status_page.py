"""战况改写页：6 张能力卡（变种词条 / 全局效果 / 星球词条 / 休眠星 / 生态借用 / 归属翻转）。

页面只读写 `app.profile`（schema v2）并调 `app.mark_dirty()`；**不直接调引擎** ——
引擎由右上角「应用配置」热更新（GUI 只是控制面客户端）。

M3 在顶部加「能力模板」条（一键写入研究线已验证的组合）与「离线预演」按钮
（把 profile 套到 data/samples 上，不开游戏就能看会改什么）；底部是「扩展 / 实验」折叠区，
放引擎已实现但 v0.1 界面不主推的延后项，并显式标注验证状态。

版式：2 列卡片网格放在纵向滚动画布里；卡片内部一律「控件铺满宽度、纵向排」，不写死像素宽
（1180x780 + Windows DPI 缩放下也不会把右侧控件裁掉）。窗口窄于 SINGLE_COL_BELOW 时退成单列。
"""

import copy
import tkinter as tk
from tkinter import ttk

from ...engine import preview as preview_mod
from .. import templates, theme
from ..widgets import PlanetPicker, RowEditor, SearchList
from . import Page

MAX_HEALTH = 1000000
REGEN_PER_SECOND = 4.1666665
SECTOR = 20
OWNER_CHOICES = ("0 · 无主", "1 · 人类", "2 · 虫族", "3 · 机器人", "4 · 光能者")
DICT_KEYS = ("globalEffects", "owner")
PICK_WIDTH = 14          # 星球下拉宽度（字符）：卡片内宽度有限，别用默认 34
HINT_WRAP = 380          # 卡片内提示文字换行宽度（卡片整宽，够用）
SINGLE_COL_BELOW = 820   # 画布窄于此宽度时卡片改单列（App 最小 980 宽也不裁）


class StatusPage(Page):
    title = "战况改写"

    # ---------------------------------------------------------------- 构图
    def build(self):
        self.header("战况改写",
                    "改完点右上角「应用配置」热更新；这里只改本机 profile，不直接动引擎")
        self._sel_variant = None          # 变种列表当前选中（on_pick 缓存）
        self._dormant_index = None        # 最近生成的休眠星（四件套核对表用）
        self._global_rows = []            # 全局效果表当前行 -> (事件 id, effect id)
        self._owner_rows = []             # 归属表当前行 -> 星球 index

        top = tk.Frame(self, bg=theme.BG)
        top.pack(fill="x", padx=22, pady=(0, 8))
        self.profile_lbl = tk.Label(top, text="", bg=theme.BG, fg=theme.MUTED, font=theme.F_S)
        self.profile_lbl.pack(side="left")
        self.engine_lbl = tk.Label(top, text="引擎 未运行", bg=theme.BG, fg=theme.DIM,
                                   font=theme.F_S)
        self.engine_lbl.pack(side="right")

        self._build_template_bar()
        self._cards = []
        self._single_col = None
        grid = self._scroll_body()
        for col in range(2):
            grid.columnconfigure(col, weight=1)

        self._build_variants(grid, 0, 0)
        self._build_global(grid, 0, 1)
        self._build_planet_effects(grid, 1, 0)
        self._build_dormant(grid, 1, 1)
        self._build_borrow(grid, 2, 0)
        self._build_owner(grid, 2, 1)
        self._build_deferred(grid)

    def _scroll_body(self):
        """纵向滚动区（只滚 Y，不出现横向滚动条）。返回内层 frame，卡片往它逐格 grid。"""
        outer = tk.Frame(self, bg=theme.BG)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=theme.BG)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", self._on_canvas_config)
        # 卡片是 canvas 的子窗口，Enter/Leave 会被子控件打断 —— 用全局绑定 + 命中判断
        canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self._canvas = canvas
        self._canvas_win = win
        self._grid = inner
        return inner

    def _on_canvas_config(self, event):
        # 注意：只给 canvas window item 设 width 不会重排内层 frame（实测无效），
        # 必须同时把 frame 自己的 -width 设成画布宽度，卡片列才会跟着画布伸缩。
        self._grid.configure(width=event.width)
        self._canvas.itemconfigure(self._canvas_win, width=event.width)
        self._relayout(event.width)

    def _on_wheel(self, event):
        try:
            canvas = self._canvas
            if not canvas.winfo_ismapped():
                return
            px, py = canvas.winfo_pointerxy()
            x0, y0 = canvas.winfo_rootx(), canvas.winfo_rooty()
            inside = (x0 <= px <= x0 + canvas.winfo_width()
                      and y0 <= py <= y0 + canvas.winfo_height())
            if inside:
                canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:          # 页面已销毁
            pass

    def _relayout(self, width=None):
        """宽度够就 2 列，窄窗口（App 最小 980 宽）退回 1 列 —— 任何情况下不横向溢出。"""
        if not self._cards or self._grid is None:
            return
        if width is None:
            width = self._canvas.winfo_width()
        single = width < SINGLE_COL_BELOW
        if single == self._single_col:
            return
        self._single_col = single
        self._grid.columnconfigure(0, weight=1)
        self._grid.columnconfigure(1, weight=0 if single else 1)
        for i, card in enumerate(self._cards):
            if single:
                card.grid_configure(row=i, column=0, padx=(22, 22))
            else:
                card.grid_configure(row=i // 2, column=i % 2,
                                    padx=(22, 8) if i % 2 == 0 else (8, 22))
        box = getattr(self, "_deferred_box", None)
        if box is not None:
            if single:
                box.grid_configure(row=len(self._cards), column=0, columnspan=1,
                                   padx=(22, 22))
            else:
                box.grid_configure(row=(len(self._cards) + 1) // 2, column=0,
                                   columnspan=2, padx=(22, 22))

    def _card(self, parent, row, col, title, sub=""):
        """自绘能力卡（PANEL 底 + BORDER 边），返回可放内容的 body。"""
        pad = (22, 8) if col == 0 else (8, 22)
        card = tk.Frame(parent, bg=theme.PANEL, highlightbackground=theme.BORDER,
                        highlightthickness=1, padx=12, pady=10)
        card.grid(row=row, column=col, sticky="nsew", padx=pad, pady=(0, 12))
        self._cards.append(card)
        head = tk.Frame(card, bg=theme.PANEL)
        head.pack(fill="x")
        tk.Label(head, text=title, bg=theme.PANEL, fg=theme.FG,
                 font=theme.F_H).pack(side="left")
        if sub:
            tk.Label(head, text="  " + sub, bg=theme.PANEL, fg=theme.DIM,
                     font=theme.F_S).pack(side="left")
        body = tk.Frame(card, bg=theme.PANEL)
        body.pack(fill="both", expand=True, pady=(6, 0))
        return body

    @staticmethod
    def _label(parent, text):
        return tk.Label(parent, text=text, bg=theme.PANEL, fg=theme.MUTED, font=theme.F_S)

    def _hint(self, parent, text):
        lbl = tk.Label(parent, text=text, bg=theme.PANEL, fg=theme.DIM, font=theme.F_S,
                       anchor="w", justify="left", wraplength=HINT_WRAP)
        lbl.pack(fill="x", pady=(4, 0))
        return lbl

    # ---- 顶部：能力模板 / 离线预演 -------------------------------------
    def _build_template_bar(self):
        bar = tk.Frame(self, bg=theme.PANEL, highlightbackground=theme.BORDER,
                       highlightthickness=1)
        bar.pack(fill="x", padx=22, pady=(0, 8))
        row = tk.Frame(bar, bg=theme.PANEL)
        row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(row, text="能力模板", bg=theme.PANEL, fg=theme.GOLD,
                 font=theme.F_H).pack(side="left")
        self.tpl_var = tk.StringVar()
        self.tpl_box = ttk.Combobox(row, textvariable=self.tpl_var, state="readonly",
                                    values=[t.title for t in templates.CORE_TEMPLATES],
                                    width=16)
        self.tpl_box.pack(side="left", padx=(8, 6))
        if templates.CORE_TEMPLATES:
            self.tpl_box.current(0)
        self.tpl_planet = PlanetPicker(row, self.app.catalogs, width=22)
        self.tpl_planet.pack(side="left", padx=(0, 6))
        theme.button(row, "应用模板", command=self._apply_template_pick).pack(side="left")
        theme.button(row, "离线预演", command=self._preview_profile).pack(side="right")
        self.tpl_hint = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.DIM,
                                 font=theme.F_S, anchor="w", justify="left")
        self.tpl_hint.pack(fill="x", padx=10, pady=(0, 6))
        # 说明文字随窗口宽度换行（不写死 wraplength，窗口窄了也不会被裁）
        bar.bind("<Configure>",
                 lambda e: self.tpl_hint.configure(wraplength=max(240, e.width - 24)))
        self.tpl_box.bind("<<ComboboxSelected>>", lambda _e: self._update_template_hint())
        self._update_template_hint()

    def _selected_template(self):
        tpls = templates.CORE_TEMPLATES
        if not tpls:
            return None
        idx = self.tpl_box.current()
        if 0 <= idx < len(tpls):
            return tpls[idx]
        return tpls[0]

    def _update_template_hint(self):
        tpl = self._selected_template()
        if tpl is None:
            return
        hint = tpl.desc
        if tpl.needs_planet:
            hint += "（需要右边的目标星球）"
        hint += "  ·  模板只改内存配置，点右上角「应用配置」才热更新"
        self.tpl_hint.configure(text=hint)

    def _apply_template_pick(self):
        tpl = self._selected_template()
        if tpl is not None:
            self._apply_template(tpl)

    def _apply_template(self, tpl):
        try:
            notes = tpl.apply(self.app.profile, self.tpl_planet.get())
        except ValueError as e:
            self.app.toast(str(e), error=True)
            return
        self.app.mark_dirty()
        self.refresh()
        self.app.toast("已应用模板「%s」—— 点「应用配置」热更新到引擎" % tpl.title)
        self.app.show_text("模板已应用 · %s" % tpl.title,
                           "\n".join("· " + n for n in notes)
                           + "\n\n下一步：右上角「应用配置」热更新；不进游戏可先点「离线预演」看增量。")

    def _preview_profile(self):
        profile = copy.deepcopy(self.app.profile)

        def done(result):
            if isinstance(result, Exception):
                self.app.toast("离线预演失败", error=True)
                self.app.show_text("离线预演失败", repr(result))
                return
            self.app.toast("离线预演：%d 处增量，%d 类响应会被改写"
                           % (result["totals"]["changes"], result["totals"]["applied"]))
            self.app.show_text("离线预演（不开游戏）", preview_mod.format_text(result))

        self.app.run_bg(lambda: preview_mod.preview(profile), done, busy="离线预演中…")

    # ---- 底部：扩展 / 实验（延后项折叠） --------------------------------
    def _build_deferred(self, parent):
        box = tk.Frame(parent, bg=theme.PANEL, highlightbackground=theme.BORDER,
                       highlightthickness=1, padx=12, pady=10)
        box.grid(row=3, column=0, columnspan=2, sticky="nsew",
                 padx=(22, 22), pady=(0, 12))
        self._deferred_box = box
        self._deferred_open = False
        head = tk.Frame(box, bg=theme.PANEL)
        head.pack(fill="x")
        self.deferred_btn = theme.button(
            head, "▸ 扩展 / 实验（%d 项延后能力）" % len(templates.DEFERRED_TEMPLATES),
            command=self._toggle_deferred)
        self.deferred_btn.pack(side="left")
        tk.Label(head, text="  引擎已实现，v0.1 不主推；每项都标了验证状态",
                 bg=theme.PANEL, fg=theme.DIM, font=theme.F_S).pack(side="left")
        self._deferred_body = tk.Frame(box, bg=theme.PANEL)
        for tpl in templates.DEFERRED_TEMPLATES:
            row = tk.Frame(self._deferred_body, bg=theme.PANEL2, padx=8, pady=6)
            row.pack(fill="x", pady=2)
            left = tk.Frame(row, bg=theme.PANEL2)
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=tpl.title, bg=theme.PANEL2, fg=theme.FG,
                     font=theme.F_B, anchor="w").pack(fill="x")
            tk.Label(left, text=tpl.desc, bg=theme.PANEL2, fg=theme.MUTED,
                     font=theme.F_S, anchor="w", justify="left",
                     wraplength=520).pack(fill="x")
            ok = "✓" in (tpl.evidence or "")
            tk.Label(left, text="验证状态：" + (tpl.evidence or "未标注"),
                     bg=theme.PANEL2, fg=theme.GOLD if ok else theme.RED,
                     font=theme.F_S, anchor="w", justify="left",
                     wraplength=520).pack(fill="x")
            theme.button(row, "应用", command=lambda t=tpl: self._apply_template(t)).pack(
                side="right", padx=(8, 0))

    def _toggle_deferred(self):
        self._deferred_open = not self._deferred_open
        if self._deferred_open:
            self._deferred_body.pack(fill="x", pady=(6, 0))
            self.deferred_btn.configure(text="▾ 扩展 / 实验（%d 项延后能力）"
                                        % len(templates.DEFERRED_TEMPLATES))
        else:
            self._deferred_body.pack_forget()
            self.deferred_btn.configure(text="▸ 扩展 / 实验（%d 项延后能力）"
                                        % len(templates.DEFERRED_TEMPLATES))

    # ---- 1. 变种词条 ---------------------------------------------------
    def _build_variants(self, parent, row, col):
        body = self._card(parent, row, col, "变种词条", "双 id 成对 · status.variants")
        self.variant_list = SearchList(body, items=self.app.catalogs.variant_entries(),
                                       height=3, on_pick=self._pick_variant)
        self.variant_list.pack(fill="x")
        bar = tk.Frame(body, bg=theme.PANEL)
        bar.pack(fill="x", pady=(6, 0))
        self.variant_pick = PlanetPicker(bar, self.app.catalogs, width=PICK_WIDTH)
        self.variant_pick.pack(side="left", fill="x", expand=True)
        theme.button(bar, "添加到方案", command=self._add_variant).pack(side="left",
                                                                       padx=(8, 0))
        self.variant_ids_lbl = self._hint(body, "选中变种后显示 dual ids")
        self.variant_editor = RowEditor(
            body, [("变种", 90), ("星球", 80), ("ids", 120)], height=2,
            on_change=self._del_variant)
        self.variant_editor.pack(fill="x", pady=(6, 0))

    def _pick_variant(self, name):
        self._sel_variant = name
        meta = self.app.catalogs.resolve_variant(name) or {}
        ids = ",".join(str(x) for x in (meta.get("ids") or [])) or "目录里查不到 ids"
        self.variant_ids_lbl.configure(text="%s → ids %s（%s）"
                                       % (name, ids, meta.get("faction") or "?"))

    def _add_variant(self):
        name = self._sel_variant or self.variant_list.get_selected()
        if not name:
            self.app.toast("先在变种列表里选一个变种", error=True)
            return
        info = self.app.catalogs.resolve_variant(name)
        if not info or not info.get("ids"):
            self.app.toast("目录里没有 %s 的 ids，先跑 tools/gen_catalogs.py" % name, error=True)
            return
        planet = self.variant_pick.get()
        if planet is None:
            self.app.toast("先选一颗星球（变种按星球挂）", error=True)
            return
        rows = self._status_lists("variants")
        target = next((r for r in rows if isinstance(r, dict) and r.get("name") == name), None)
        if target is None:
            target = {"name": name, "planets": []}
            rows.append(target)
        planets = target.setdefault("planets", [])
        if int(planet) in planets:
            self.app.toast("%s 已经挂在星球 %d 上了" % (name, planet), error=True)
            return
        planets.append(int(planet))
        self.app.mark_dirty()
        self._render_variants()
        self.app.toast("已加变种 %s → 星球 %d（点「应用配置」热更新）" % (name, planet))

    def _del_variant(self, index):
        rows = self._status_lists("variants", create=False)
        if 0 <= index < len(rows):
            name = rows[index].get("name") if isinstance(rows[index], dict) else rows[index]
            rows.pop(index)
            self.app.mark_dirty()
            self._render_variants()
            self.app.toast("已从方案移除变种 %s" % name)

    def _render_variants(self):
        rows = []
        for row in self._status_lists("variants", create=False):
            name = row.get("name") if isinstance(row, dict) else str(row)
            planets = (row.get("planets") if isinstance(row, dict) else []) or []
            meta = self.app.catalogs.resolve_variant(name) or {}
            rows.append((name, ",".join(str(p) for p in planets) or "—",
                         ",".join(str(x) for x in (meta.get("ids") or [])) or "—"))
        self.variant_editor.set_rows(rows, "%d 个变种" % len(rows))

    # ---- 2. 全局效果（GWE type94） -------------------------------------
    def _build_global(self, parent, row, col):
        body = self._card(parent, row, col, "全局效果", "type94 · globalEffects[事件 id]")
        bar = tk.Frame(body, bg=theme.PANEL)
        bar.pack(fill="x")
        self._label(bar, "事件 id").pack(side="left")
        self.var_event_id = tk.StringVar(value="1501113")
        theme.entry(bar, self.var_event_id, width=12).pack(side="left", padx=(6, 0))
        self.global_list = SearchList(body, items=self.app.catalogs.effect_entries(),
                                      height=3)
        self.global_list.pack(fill="x", pady=(6, 0))
        theme.button(body, "添加效果", command=self._add_global).pack(anchor="w", pady=(6, 0))
        self._hint(body, "同事件 id 去重；效果 id 见下表")
        self.global_editor = RowEditor(
            body, [("事件 id", 90), ("effect id", 130)], height=2,
            on_change=self._del_global)
        self.global_editor.pack(fill="x", pady=(6, 0))

    def _add_global(self):
        effect = self.global_list.get_selected()
        if effect is None:
            self.app.toast("先在效果列表里选一个 effect", error=True)
            return
        eid = self._as_int(self.var_event_id.get(), "事件 id")
        if eid is None:
            return
        ge = self._status_lists("globalEffects")
        ids = ge.setdefault(str(eid), [])
        if int(effect) in ids:
            self.app.toast("事件 %d 里已经有 effect %d" % (eid, effect), error=True)
            return
        ids.append(int(effect))
        self.app.mark_dirty()
        self._render_global()
        self.app.toast("已给全局事件 %d 加 effect %d" % (eid, effect))

    def _del_global(self, index):
        if 0 <= index < len(self._global_rows):
            eid, effect = self._global_rows[index]
            ge = self._status_lists("globalEffects", create=False)
            ids = ge.get(str(eid)) or []
            if effect in ids:
                ids.remove(effect)
            if not ids:
                ge.pop(str(eid), None)
            self.app.mark_dirty()
            self._render_global()
            self.app.toast("已移除全局事件 %d 的 effect %d" % (eid, effect))

    def _render_global(self):
        ge = self._status_lists("globalEffects", create=False)
        rows, pairs = [], []
        if isinstance(ge, dict):
            for eid in sorted(ge, key=lambda k: int(k) if str(k).isdigit() else 0):
                for effect in ge.get(eid) or []:
                    rows.append((eid, effect))
                    pairs.append((int(eid), int(effect)))
        self._global_rows = pairs
        self.global_editor.set_rows(rows, "%d 条" % len(rows))

    # ---- 3. 星球词条 ---------------------------------------------------
    def _build_planet_effects(self, parent, row, col):
        body = self._card(parent, row, col, "星球词条", "绕阵营过滤 · planet_effects")
        self.pe_pick = PlanetPicker(body, self.app.catalogs, width=PICK_WIDTH)
        self.pe_pick.pack(fill="x")
        self.pe_list = SearchList(body, items=self.app.catalogs.effect_entries(), height=3)
        self.pe_list.pack(fill="x", pady=(6, 0))
        theme.button(body, "添加词条", command=self._add_planet_effect).pack(
            anchor="w", pady=(6, 0))
        self._hint(body, "同星球合并去重（绕过阵营过滤，可挂到任意星）")
        self.pe_editor = RowEditor(
            body, [("星球", 90), ("effect ids", 160)], height=2,
            on_change=self._del_planet_effect)
        self.pe_editor.pack(fill="x", pady=(6, 0))

    def _pe_row(self, planet, create=True):
        rows = self._status_lists("planet_effects", create=create)
        for row in rows:
            if isinstance(row, dict) and int(row.get("index") or -1) == int(planet):
                return row
        return None

    def _add_planet_effect(self):
        planet = self.pe_pick.get()
        if planet is None:
            self.app.toast("先选一颗星球", error=True)
            return
        effect = self.pe_list.get_selected()
        if effect is None:
            self.app.toast("先在效果列表里选一个 effect", error=True)
            return
        row = self._pe_row(planet)
        if row is None:
            row = {"index": int(planet), "ids": []}
            self._status_lists("planet_effects").append(row)
        ids = row.setdefault("ids", [])
        if int(effect) in ids:
            self.app.toast("星球 %d 已经有 effect %d" % (planet, effect), error=True)
            return
        ids.append(int(effect))
        self.app.mark_dirty()
        self._render_planet_effects()
        self.app.toast("已给星球 %d 加 effect %d" % (planet, effect))

    def _del_planet_effect(self, index):
        rows = self._status_lists("planet_effects", create=False)
        if 0 <= index < len(rows):
            row = rows.pop(index)
            self.app.mark_dirty()
            self._render_planet_effects()
            self.app.toast("已移除星球 %s 的词条"
                           % (row.get("index") if isinstance(row, dict) else row))

    def _render_planet_effects(self):
        rows = []
        for row in self._status_lists("planet_effects", create=False):
            if not isinstance(row, dict):
                continue
            ids = ",".join(str(i) for i in (row.get("ids") or []))
            rows.append((row.get("index"), ids or "—"))
        self.pe_editor.set_rows(rows, "%d 颗星" % len(rows))

    # ---- 4. 休眠星（四件套） -------------------------------------------
    def _build_dormant(self, parent, row, col):
        body = self._card(parent, row, col, "休眠星（四件套）", "四件套 · warinfo + status")
        form = tk.Frame(body, bg=theme.PANEL)
        form.pack(fill="x")
        self.var_star = tk.StringVar(value="300")
        self.var_hash = tk.StringVar(value="")
        self.var_pos = tk.StringVar(value="0.0,0.0")
        self.var_camp = tk.StringVar(value="51999")
        self._field(form, 0, 0, "星号 index", theme.entry(form, self.var_star, width=7))
        self._field(form, 0, 1, "settingsHash", theme.entry(form, self.var_hash, width=9))
        self.var_owner = tk.StringVar(value=OWNER_CHOICES[1])
        owner_box = ttk.Combobox(form, textvariable=self.var_owner, values=list(OWNER_CHOICES),
                                 width=8, state="readonly")
        self._field(form, 1, 0, "owner", owner_box)
        self._field(form, 1, 1, "坐标 x,y", theme.entry(form, self.var_pos, width=9))
        self._field(form, 2, 0, "campaign id", theme.entry(form, self.var_camp, width=7))
        theme.button(form, "生成四件套", command=self._make_dormant,
                     primary=True).grid(row=2, column=1, sticky="w", padx=(6, 0), pady=3)
        wrap, self.dormant_tv = theme.table(
            body, [("要素", 200), ("星球", 90), ("状态", 50)], height=2)
        wrap.pack(fill="x", pady=(6, 0))
        self.dormant_tv.tag_configure("ok", foreground=theme.GREEN)
        self.dormant_tv.tag_configure("bad", foreground=theme.RED)
        self._hint(body, "settingsHash 留空按 0；坐标为 live warinfo 原值"
                         "（保存时引擎校验会把 planet_infos 坐标取整 —— 已知问题）")

    def _field(self, form, row, col, label, widget):
        tk.Label(form, text=label, bg=theme.PANEL, fg=theme.MUTED, font=theme.F_S,
                 anchor="e", width=10).grid(row=row, column=col * 2, sticky="e", pady=3)
        widget.grid(row=row, column=col * 2 + 1, sticky="w", padx=(6, 12), pady=3)

    def _make_dormant(self):
        index = self._as_int(self.var_star.get(), "星号 index", lo=0, hi=400)
        if index is None:
            return
        hash_raw = str(self.var_hash.get()).strip()
        hv = 0
        if hash_raw:
            try:
                hv = int(hash_raw, 0)
            except ValueError:
                self.app.toast("settingsHash 要填整数（可写 0x 十六进制）", error=True)
                return
        camp_id = self._as_int(self.var_camp.get(), "campaign id", lo=1)
        if camp_id is None:
            return
        pos = self._parse_pos(self.var_pos.get())
        if pos is None:
            self.app.toast("坐标要写成 x,y（例：0.3,-0.55）", error=True)
            return
        owner = OWNER_CHOICES.index(self.var_owner.get()) \
            if self.var_owner.get() in OWNER_CHOICES else 1
        # 坐标保持用户填的精度（0.3 不变成 0）；注意 config.validate 目前会把
        # warinfo.planet_infos[].position 取整 —— 属引擎侧已知问题，不在本页处理。
        pos_d = {"x": pos[0], "y": pos[1]}
        # 四条同 index 的条目：存在就替换，不存在才追加（四件套必须整组一致）
        infos = self._warinfo().setdefault("planet_infos", [])
        _replace_by(infos, {"index": index, "settingsHash": hv, "position": dict(pos_d),
                            "maxHealth": MAX_HEALTH, "initialOwner": owner,
                            "sector": SECTOR, "waypoints": []},
                    lambda r: _row_index(r) == index)
        st = self._status()
        _replace_by(st.setdefault("planet_nodes", []),
                    {"index": index, "owner": owner, "health": MAX_HEALTH,
                     "regenPerSecond": REGEN_PER_SECOND, "players": 0,
                     "position": dict(pos_d)},
                    lambda r: _row_index(r) == index)
        _replace_by(st.setdefault("campaigns", []),
                    {"planet": index, "id": camp_id, "type": 0, "count": 1, "race": 1},
                    lambda r: _row_index(r, "planet") == index)
        self._owner_map()[str(index)] = owner
        self._dormant_index = index
        self.app.mark_dirty()
        self._render_dormant()
        self._render_owner()
        self.app.toast("已生成星球 %d 的四件套（owner=%d；点「应用配置」热更新）"
                       % (index, owner))

    def _render_dormant(self):
        idx = self._dormant_index
        if idx is None:
            infos = [r for r in (self._warinfo().get("planet_infos") or [])
                     if isinstance(r, dict) and _row_index(r) is not None]
            idx = _row_index(infos[-1]) if infos else None
        tv = self.dormant_tv
        tv.delete(*tv.get_children())
        if idx is None:
            return
        st = self._status()
        checks = [
            ("warinfo.planet_infos", any(_row_index(r) == idx for r in
                                         (self._warinfo().get("planet_infos") or [])
                                         if isinstance(r, dict))),
            ("status.planet_nodes", any(_row_index(r) == idx for r in
                                        (st.get("planet_nodes") or [])
                                        if isinstance(r, dict))),
            ("status.campaigns", any(_row_index(r, "planet") == idx for r in
                                     (st.get("campaigns") or []) if isinstance(r, dict))),
            ("status.owner", str(idx) in (st.get("owner") or {})),
        ]
        for label, ok in checks:
            tv.insert("", "end", values=(label, "星球 %d" % idx, "OK" if ok else "缺"),
                      tags=("ok" if ok else "bad",))

    # ---- 5. 生态借用（settingsHash） -----------------------------------
    def _build_borrow(self, parent, row, col):
        body = self._card(parent, row, col, "生态借用", "warinfo.settings_hash[目标]")
        self._label(body, "源星球（借生态）").pack(anchor="w")
        self.borrow_src = PlanetPicker(body, self.app.catalogs, width=PICK_WIDTH)
        self.borrow_src.pack(fill="x")
        self._label(body, "目标星球（被改）").pack(anchor="w", pady=(6, 0))
        self.borrow_dst = PlanetPicker(body, self.app.catalogs, width=PICK_WIDTH)
        self.borrow_dst.pack(fill="x")
        bar = tk.Frame(body, bg=theme.PANEL)
        bar.pack(fill="x", pady=(6, 0))
        self._label(bar, "settingsHash").pack(side="left")
        self.var_borrow_hash = tk.StringVar(value="")
        theme.entry(bar, self.var_borrow_hash, width=12).pack(side="left", padx=(6, 0))
        theme.button(body, "写入目标星球", command=self._borrow_ecosystem).pack(
            anchor="w", pady=(6, 0))
        self._hint(body, "hash 可从 live warinfo 抓包抄；留空则复用 profile 里已有源的 hash")
        self.borrow_editor = RowEditor(
            body, [("目标星球", 110), ("settingsHash", 150)], height=2,
            on_change=self._del_borrow)
        self.borrow_editor.pack(fill="x", pady=(6, 0))

    def _borrow_ecosystem(self):
        dst = self.borrow_dst.get()
        if dst is None:
            self.app.toast("先选目标星球", error=True)
            return
        raw = str(self.var_borrow_hash.get()).strip()
        if not raw:
            src = self.borrow_src.get()
            cached = self._settings_hash().get(str(src)) if src else None
            if cached is None:
                self.app.toast("请填 settingsHash（先抓一次 live warinfo，或手填十进制/0x）",
                               error=True)
                return
            raw = str(cached)
        try:
            hv = int(raw, 0)
        except ValueError:
            self.app.toast("settingsHash 要填整数（可写 0x 十六进制）", error=True)
            return
        self._settings_hash()[str(dst)] = hv & 0xFFFFFFFF
        self.app.mark_dirty()
        self._render_borrow()
        self.app.toast("星球 %d 的 settingsHash 已设为 %d" % (dst, hv & 0xFFFFFFFF))

    def _owner_map(self):
        st = self._status()
        owners = st.get("owner")
        if not isinstance(owners, dict):
            owners = {}
            st["owner"] = owners
        return owners

    def _settings_hash(self):
        wi = self._warinfo()
        sh = wi.get("settings_hash")
        if not isinstance(sh, dict):
            sh = {}
            wi["settings_hash"] = sh
        return sh

    def _del_borrow(self, index):
        sh = self._settings_hash()
        keys = sorted(sh, key=lambda k: int(k) if str(k).isdigit() else 0)
        if 0 <= index < len(keys):
            key = keys[index]
            sh.pop(key, None)
            self.app.mark_dirty()
            self._render_borrow()
            self.app.toast("已移除星球 %s 的 settingsHash" % key)

    def _render_borrow(self):
        sh = self._warinfo().get("settings_hash")
        sh = sh if isinstance(sh, dict) else {}
        keys = sorted(sh, key=lambda k: int(k) if str(k).isdigit() else 0)
        self.borrow_editor.set_rows([(k, sh[k]) for k in keys], "%d 颗星" % len(keys))

    # ---- 6. 归属翻转 ---------------------------------------------------
    def _build_owner(self, parent, row, col):
        body = self._card(parent, row, col, "归属翻转", "status.owner[星球] = 0..4")
        self.owner_pick = PlanetPicker(body, self.app.catalogs, width=PICK_WIDTH)
        self.owner_pick.pack(fill="x")
        bar = tk.Frame(body, bg=theme.PANEL)
        bar.pack(fill="x", pady=(6, 0))
        self._label(bar, "新归属").pack(side="left")
        self.var_owner_pick = tk.StringVar(value=OWNER_CHOICES[1])
        ttk.Combobox(bar, textvariable=self.var_owner_pick, values=list(OWNER_CHOICES),
                     width=10, state="readonly").pack(side="left", padx=(6, 0))
        theme.button(body, "翻转归属", command=self._flip_owner).pack(anchor="w", pady=(6, 0))
        self._hint(body, "0 无主 / 1 人类 / 2 虫族 / 3 机器人 / 4 光能者")
        self.owner_editor = RowEditor(
            body, [("星球", 110), ("归属", 130)], height=2,
            on_change=self._del_owner)
        self.owner_editor.pack(fill="x", pady=(6, 0))

    def _flip_owner(self):
        planet = self.owner_pick.get()
        if planet is None:
            self.app.toast("先选一颗星球", error=True)
            return
        label = self.var_owner_pick.get()
        owner = OWNER_CHOICES.index(label) if label in OWNER_CHOICES else 1
        self._owner_map()[str(planet)] = int(owner)
        self.app.mark_dirty()
        self._render_owner()
        self.app.toast("星球 %d 归属改为 %s" % (planet, label))

    def _del_owner(self, index):
        if 0 <= index < len(self._owner_rows):
            key = str(self._owner_rows[index])
            self._owner_map().pop(key, None)
            self.app.mark_dirty()
            self._render_owner()
            self.app.toast("已移除星球 %s 的归属改写" % key)

    def _render_owner(self):
        owners = self._status_lists("owner", create=False) or {}
        keys = sorted(owners, key=lambda k: int(k) if str(k).isdigit() else 0)
        rows = []
        for key in keys:
            owner = owners[key]
            label = OWNER_CHOICES[owner] \
                if isinstance(owner, int) and 0 <= owner < len(OWNER_CHOICES) else str(owner)
            rows.append((key, label))
        self._owner_rows = [int(k) for k in keys if str(k).isdigit()]
        self.owner_editor.set_rows(rows, "%d 颗星" % len(rows))

    # ---------------------------------------------------------------- 数据
    def _status(self):
        """直接改 profile（schema v2）—— 页面与引擎之间只有这一份数据。"""
        st = self.app.profile.get("status")
        if not isinstance(st, dict):
            st = {}
            self.app.profile["status"] = st
        return st

    def _warinfo(self):
        wi = self.app.profile.get("warinfo")
        if not isinstance(wi, dict):
            wi = {}
            self.app.profile["warinfo"] = wi
        return wi

    def _status_lists(self, key, create=True):
        """取 status 下的列表/字典；create=False 时不写入（纯渲染用）。"""
        if create:
            st = self._status()
            val = st.get(key)
            if not isinstance(val, (list, dict)):
                val = {} if key in DICT_KEYS else []
                st[key] = val
            return val
        val = self._status().get(key)
        return val if isinstance(val, (list, dict)) else ({} if key in DICT_KEYS else [])

    @staticmethod
    def _parse_pos(text):
        parts = [p.strip() for p in str(text or "").split(",")]
        if len(parts) != 2:
            return None
        try:
            x, y = float(parts[0]), float(parts[1])
        except ValueError:
            return None
        return (int(x) if x.is_integer() else x, int(y) if y.is_integer() else y)

    def _as_int(self, text, name, lo=None, hi=None):
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            self.app.toast("%s 要填整数" % name, error=True)
            return None
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            self.app.toast("%s 超出范围" % name, error=True)
            return None
        return value

    # ---------------------------------------------------------------- 刷新
    def refresh(self):
        name = self.app.profile.get("name") or "?"
        self.profile_lbl.configure(text="当前 profile：%s · 改完点右上角「应用配置」热更新"
                                   % name)
        self._render_variants()
        self._render_global()
        self._render_planet_effects()
        self._render_dormant()
        self._render_borrow()
        self._render_owner()

    def on_status(self, status):
        if status:
            mode = "直通" if status.get("mode") == "passthrough" else "改写"
            self.engine_lbl.configure(text="引擎 运行中 · %s" % mode, fg=theme.GREEN)
        else:
            self.engine_lbl.configure(text="引擎 未运行（配置照常可改，保存到 profile）",
                                      fg=theme.DIM)


# ---------------------------------------------------------------- 小工具


def _row_index(row, key="index"):
    if not isinstance(row, dict):
        return None
    try:
        return int(row.get(key))
    except (TypeError, ValueError):
        return None


def _replace_by(rows, entry, match):
    """按 match 找到已有条目就地替换，找不到才 append（避免同 index 重复）。"""
    for i, row in enumerate(rows):
        if isinstance(row, dict) and match(row):
            rows[i] = entry
            return entry
    rows.append(entry)
    return entry
