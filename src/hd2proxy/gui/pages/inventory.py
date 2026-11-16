"""物品与战备页：武器 / 附件 / 外观 / 战备 / 目录追加 五个 tab。

前四个 tab 写 `profile["inventory"][key]`（行格式 {"mixId","amount","isDiscovered"}），
目录追加 tab 写 `profile["items"]`（template + add）。全部只改内存 profile，
由右上角「应用配置」热更新到引擎。
"""

import tkinter as tk
from tkinter import ttk

from .. import theme
from ..widgets import RowEditor, SearchList
from . import Page

# key -> 中文名（与 profile.inventory 的键一一对应）
EDIT_TABS = (("weapons", "武器"), ("attachments", "附件"),
             ("cosmetics", "外观"), ("stratagems", "战备"))
TAB_NAMES = dict(EDIT_TABS)


class InventoryPage(Page):
    title = "物品与战备"

    # ---------------------------------------------------------------- 构图
    def build(self):
        self.header("物品与战备",
                    "库存行 / 目录上架都只是 profile 改写；改完点右上角「应用配置」热更新")
        self._lists = {}
        self._amounts = {}
        self._keywords = {}
        self._editors = {}
        self._counts = {}
        self._filled = {}              # tab 的列表是否已填过（切 tab 时补一次）

        bar = tk.Frame(self, bg=theme.BG)
        bar.pack(fill="x", padx=22, pady=(0, 8))
        self.sum_lbl = tk.Label(bar, text="", bg=theme.BG, fg=theme.MUTED, font=theme.F_S)
        self.sum_lbl.pack(side="left")
        tk.Label(bar, text="库存行 = 解锁/试用；目录追加 = 让物品出现在列表里",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=22, pady=(0, 16))
        for key, label in EDIT_TABS:
            self._build_edit_tab(key, label)
        self._build_items_tab()
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ---- 前四个 tab ----------------------------------------------------
    def _build_edit_tab(self, key, label):
        tab = tk.Frame(self.nb, bg=theme.BG)
        self.nb.add(tab, text=label)

        bar = tk.Frame(tab, bg=theme.BG)
        bar.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(bar, text="关键词", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self._keywords[key] = tk.StringVar()
        kw = theme.entry(bar, self._keywords[key], width=16)
        kw.pack(side="left", padx=(6, 6))
        kw.bind("<Return>", lambda _e, k=key: self._search_items(k))
        theme.button(bar, "搜索", command=lambda k=key: self._search_items(k)).pack(
            side="left", padx=(0, 12))
        tk.Label(bar, text="数量", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self._amounts[key] = tk.StringVar(value="1")
        theme.entry(bar, self._amounts[key], width=6).pack(side="left", padx=(6, 12))
        theme.button(bar, "添加到库存", primary=True,
                     command=lambda k=key: self._add_item(k)).pack(side="left")
        self._counts[key] = tk.Label(bar, text="", bg=theme.BG, fg=theme.DIM, font=theme.F_S)
        self._counts[key].pack(side="right")

        body = tk.Frame(tab, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        left = tk.Frame(body, bg=theme.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(body, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew")
        items = self.app.catalogs.search_items("")
        lst = SearchList(left, items=items, height=12)
        lst.pack(fill="both", expand=True)
        self._lists[key] = lst
        self._filled[key] = bool(items)
        tk.Label(left, text="列表内搜索框只在当前结果里过滤；换关键词点「搜索」",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, anchor="w").pack(
            fill="x", pady=(4, 0))
        editor = RowEditor(right, [("mixId", 108), ("名称", 210), ("数量", 54)], height=12,
                           on_change=lambda i, k=key: self._remove_row(k, i))
        editor.pack(fill="both", expand=True)
        self._editors[key] = editor

    def _search_items(self, key):
        """关键词 -> catalogs.search_items（全量目录里查，limit 200）。"""
        kw = self._keywords[key].get().strip()
        items = self.app.catalogs.search_items(kw, limit=200)
        self._lists[key].set_items(items)
        self._filled[key] = bool(items)
        self.app.toast("%s：命中 %d 条" % (TAB_NAMES.get(key, key), len(items)))

    def _add_item(self, key):
        mix = self._lists[key].get_selected()
        if mix is None:
            self.app.toast("先在左侧列表里选一件物品", error=True)
            return
        raw = str(self._amounts[key].get()).strip() or "1"
        try:
            amount = int(raw)
        except ValueError:
            self.app.toast("数量要填整数", error=True)
            return
        if amount < 1:
            self.app.toast("数量必须 >= 1", error=True)
            return
        rows = self._inventory().setdefault(key, [])
        if any(isinstance(r, dict) and int(r.get("mixId") or 0) == int(mix) for r in rows):
            self.app.toast("mixId %d 已在%s列表里（改数量请先删除再加）" % (mix, TAB_NAMES[key]),
                           error=True)
            return
        rows.append({"mixId": int(mix), "amount": int(amount), "isDiscovered": False})
        self.app.mark_dirty()
        self._render_tab(key)
        self.app.toast("已加入%s：%s" % (TAB_NAMES[key], self.app.catalogs.item_label(mix)))

    def _remove_row(self, key, index):
        rows = self._inventory(create=False).get(key) or []
        if 0 <= index < len(rows):
            row = rows.pop(index)
            mix = row.get("mixId") if isinstance(row, dict) else row
            self.app.mark_dirty()
            self._render_tab(key)
            self.app.toast("已从%s移除 mixId %s" % (TAB_NAMES[key], mix))

    def _render_tab(self, key):
        rows = []
        for row in self._inventory(create=False).get(key) or []:
            if not isinstance(row, dict):
                continue
            mix = row.get("mixId")
            rows.append((mix, self.app.catalogs.item_label(mix), row.get("amount", 1)))
        self._editors[key].set_rows(rows, "%d 件" % len(rows))
        self._counts[key].configure(text="已加入 %d 件" % len(rows))
        self._render_summary()

    # ---- 第五个 tab：目录追加 ------------------------------------------
    def _build_items_tab(self):
        tab = tk.Frame(self.nb, bg=theme.BG)
        self.nb.add(tab, text="目录追加")

        bar = tk.Frame(tab, bg=theme.BG)
        bar.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(bar, text="模板 itemId", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self.var_template = tk.StringVar()
        theme.entry(bar, self.var_template, width=12).pack(side="left", padx=(6, 6))
        theme.button(bar, "设为模板", command=self._set_template).pack(side="left", padx=(0, 14))
        tk.Label(bar, text="关键词", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self.var_items_kw = tk.StringVar()
        kw = theme.entry(bar, self.var_items_kw, width=14)
        kw.pack(side="left", padx=(6, 6))
        kw.bind("<Return>", lambda _e: self._search_catalog_items())
        theme.button(bar, "搜索", command=self._search_catalog_items).pack(
            side="left", padx=(0, 10))
        theme.button(bar, "追加到目录", primary=True,
                     command=self._add_catalog_item).pack(side="left")
        self.items_count = tk.Label(bar, text="", bg=theme.BG, fg=theme.DIM, font=theme.F_S)
        self.items_count.pack(side="right")

        body = tk.Frame(tab, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=1, uniform="col")
        body.columnconfigure(1, weight=1, uniform="col")
        left = tk.Frame(body, bg=theme.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = tk.Frame(body, bg=theme.BG)
        right.grid(row=0, column=1, sticky="nsew")
        items = self.app.catalogs.search_items("")
        self.catalog_list = SearchList(left, items=items, height=12)
        self.catalog_list.pack(fill="both", expand=True)
        self._filled_items = bool(items)
        tk.Label(left, text="追加的对象是 catalog 里的 mixId/itemId；模板 itemId 决定克隆哪一行",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, anchor="w").pack(
            fill="x", pady=(4, 0))
        self.items_editor = RowEditor(right, [("itemId", 108), ("名称", 250)], height=12,
                                      on_change=self._del_catalog_item)
        self.items_editor.pack(fill="both", expand=True)

    def _set_template(self):
        raw = str(self.var_template.get()).strip()
        if not raw:
            self._items()["template"] = None
            self.app.mark_dirty()
            self.app.toast("已清空目录模板 itemId")
            return
        try:
            tmpl = int(raw)
        except ValueError:
            self.app.toast("模板 itemId 要填整数", error=True)
            return
        self._items()["template"] = tmpl
        self.app.mark_dirty()
        self.app.toast("目录模板 itemId = %d" % tmpl)

    def _search_catalog_items(self):
        kw = self.var_items_kw.get().strip()
        items = self.app.catalogs.search_items(kw, limit=200)
        self.catalog_list.set_items(items)
        self._filled_items = bool(items)
        self.app.toast("目录搜索结果：%d 条" % len(items))

    def _add_catalog_item(self):
        tmpl_raw = str(self.var_template.get()).strip()
        if tmpl_raw:
            try:
                self._items()["template"] = int(tmpl_raw)
            except ValueError:
                self.app.toast("模板 itemId 要填整数", error=True)
                return
        mix = self.catalog_list.get_selected()
        if mix is None:
            self.app.toast("先在左侧列表里选一个物品", error=True)
            return
        add = self._items().setdefault("add", [])
        if int(mix) in add:
            self.app.toast("itemId %d 已在追加列表里" % mix, error=True)
            return
        add.append(int(mix))
        self.app.mark_dirty()
        self._render_items()
        self.app.toast("已追加到目录：%s" % self.app.catalogs.item_label(mix))

    def _del_catalog_item(self, index):
        add = self._items(create=False).get("add") or []
        if 0 <= index < len(add):
            item = add.pop(index)
            self.app.mark_dirty()
            self._render_items()
            self.app.toast("已从目录追加里移除 itemId %s" % item)

    def _render_items(self):
        rows = []
        for item in self._items(create=False).get("add") or []:
            rows.append((item, self.app.catalogs.item_label(item)))
        self.items_editor.set_rows(rows, "%d 条" % len(rows))
        self.items_count.configure(text="目录追加 %d 条" % len(rows))
        self._render_summary()

    def _on_tab_changed(self, _event=None):
        """切 tab 时校验当前 tab 的列表是否为空（空了就按关键词重查一遍）。"""
        try:
            current = self.nb.index(self.nb.select())
        except tk.TclError:
            return
        keys = [k for k, _label in EDIT_TABS]
        if current < len(keys):
            key = keys[current]
            if not self._filled.get(key):
                self._search_items(key)
        elif not self._filled_items:
            self._search_catalog_items()

    # ---------------------------------------------------------------- 数据
    def _inventory(self, create=True):
        inv = self.app.profile.get("inventory")
        if not isinstance(inv, dict):
            if not create:
                return {}
            inv = {}
            self.app.profile["inventory"] = inv
        return inv

    def _items(self, create=True):
        doc = self.app.profile.get("items")
        if not isinstance(doc, dict):
            if not create:
                return {}
            doc = {}
            self.app.profile["items"] = doc
        return doc

    # ---------------------------------------------------------------- 刷新
    def _render_summary(self):
        inv = self._inventory(create=False)
        parts = []
        for key, label in EDIT_TABS:
            rows = inv.get(key) or []
            parts.append("%s %d" % (label, len(rows) if isinstance(rows, list) else 0))
        add = self._items(create=False).get("add") or []
        parts.append("目录追加 %d" % (len(add) if isinstance(add, list) else 0))
        self.sum_lbl.configure(text="已加入：" + " · ".join(parts))

    def refresh(self):
        for key, _label in EDIT_TABS:
            self._render_tab(key)
        self._render_items()
        tmpl = self._items(create=False).get("template")
        self.var_template.set("" if tmpl is None else str(tmpl))
        self._render_summary()

    def on_status(self, status):
        # 本页数据全在 profile 里，引擎状态不影响编辑；只在顶部提示里留个记号
        if status:
            self.sum_lbl.configure(fg=theme.MUTED)
        return
