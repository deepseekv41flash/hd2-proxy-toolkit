"""GUI 通用控件：可搜索列表、星球选择器、行编辑表。"""

import tkinter as tk
from tkinter import ttk

from . import theme


class SearchList(tk.Frame):
    """搜索框 + 列表：用于变种/效果/战备/物品选择。

    items: [(key, label), ...]；get_selected() 返回 key（无选中返回 None）。
    """

    def __init__(self, parent, items=None, height=7, on_pick=None):
        super().__init__(parent, bg=theme.PANEL)
        self._items = list(items or [])
        self._filtered = list(self._items)
        self.on_pick = on_pick

        top = tk.Frame(self, bg=theme.PANEL)
        top.pack(fill="x", padx=6, pady=(6, 2))
        self.var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.var, width=18)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<KeyRelease>", lambda _e: self._apply_filter())
        self.count = tk.Label(top, text="", bg=theme.PANEL, fg=theme.DIM, font=theme.F_S)
        self.count.pack(side="right", padx=(6, 0))

        body = tk.Frame(self, bg=theme.PANEL)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.listbox = tk.Listbox(body, height=height, bg=theme.PANEL2, fg=theme.FG,
                                  selectbackground="#2a3b50", selectforeground=theme.FG,
                                  bd=0, highlightthickness=0, font=theme.F_S,
                                  activestyle="none")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", self._on_double)
        self.set_items(self._items)

    # ---- 数据 ---------------------------------------------------------
    def set_items(self, items):
        self._items = list(items or [])
        self._apply_filter()

    def _apply_filter(self):
        q = self.var.get().strip().lower()
        self._filtered = [(k, lbl) for k, lbl in self._items
                          if not q or q in str(lbl).lower() or q in str(k).lower()]
        self.listbox.delete(0, "end")
        for _k, lbl in self._filtered:
            self.listbox.insert("end", lbl)
        self.count.configure(text="%d/%d" % (len(self._filtered), len(self._items)))

    def _on_select(self, _e=None):
        if self.on_pick:
            key = self.get_selected()
            if key is not None:
                self.on_pick(key)

    def _on_double(self, _e=None):
        self._on_select()

    def get_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self._filtered):
            return self._filtered[idx][0]
        return None

    def get_selected_label(self):
        sel = self.listbox.curselection()
        if not sel:
            return None
        return self.listbox.get(sel[0])


class PlanetPicker(tk.Frame):
    """星球选择器：下拉 + 可选文本过滤（catalogs.planets 为空时退化为手填 index）。

    下拉值 = **游戏索引**（引擎/Status 用的编号），不是 planet_data 行号 —— 两者偏移不是常数。
    旧目录没有 game_index 时退回行号（并在标签里保持一致，避免半新半旧）。
    """

    def __init__(self, parent, catalogs, width=34):
        super().__init__(parent, bg=theme.PANEL)
        self.catalogs = catalogs
        self._labels = []
        self._index_of = {}
        rows = getattr(catalogs, "game_planets", None) or catalogs.planets
        for p in rows:
            idx = p.get("game_index")
            if idx is None:
                idx = p.get("index")
            if idx is None:
                continue
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            name = p.get("name") or "?"
            biome = p.get("biome") or "?"
            label = "%d · %s (%s)" % (idx, name, biome)
            self._labels.append(label)
            self._index_of[label] = idx
        self.var = tk.StringVar()
        self.box = ttk.Combobox(self, textvariable=self.var, values=self._labels,
                                width=width, state="readonly", font=theme.F_B)
        self.box.pack(fill="x")
        if self._labels:
            self.box.current(0)

    def get(self):
        label = self.var.get()
        if label in self._index_of:
            return self._index_of[label]
        return None

    def set(self, index):
        for label, idx in self._index_of.items():
            if idx == index:
                self.var.set(label)
                return True
        self.var.set(str(index))
        return False


class PickDropdown(tk.Frame):
    """一行高的可搜索下拉选择器（替代 3 行小列表，2026-11-17 用户要求）。

    为什么要有：变种词条 / 全局效果 / 星球词条这类「条目多、但要选一个」的地方，原来用
    3 行高的 SearchList —— 只能看到 3 条、还占版面。改成和星球选择一样的下拉：收起时一行，
    点开是原生 ttk::Combobox 弹窗（带滚动条），输入关键词实时过滤候选。

    items: [(key, label), ...]；`get()` 返回选中 key；`select_index()` / `set_key()` 供测试与回填。
    """

    def __init__(self, parent, items=None, width=40, on_pick=None, popup_rows=12):
        super().__init__(parent, bg=theme.PANEL)
        self.on_pick = on_pick
        self._items = []
        self._labels = []
        self._key_of = {}
        self._key = None
        self.var = tk.StringVar()
        self.box = ttk.Combobox(self, textvariable=self.var, values=[],
                                width=width, state="normal", height=popup_rows,
                                font=theme.F_B)
        self.box.pack(side="left", fill="x", expand=True)
        self.count = tk.Label(self, text="", bg=theme.PANEL, fg=theme.DIM, font=theme.F_S)
        self.count.pack(side="left", padx=(6, 0))
        self.box.bind("<KeyRelease>", self._on_key)
        self.box.bind("<<ComboboxSelected>>", self._on_selected)
        self.box.bind("<Return>", self._on_return)
        self.set_items(items or [])

    # ---- 数据 ---------------------------------------------------------
    def set_items(self, items):
        self._items = list(items or [])
        self._labels, self._key_of = [], {}
        for key, label in self._items:
            label = str(label)
            self._labels.append(label)
            self._key_of.setdefault(label, key)
        self._key = None
        self.var.set("")
        self.box.configure(values=self._labels)
        self._update_count(len(self._labels))

    def _update_count(self, shown):
        total = len(self._labels)
        self.count.configure(text="共 %d 条" % total if shown == total
                             else "%d/%d" % (shown, total))

    def _filtered_labels(self, query):
        query = (query or "").strip().lower()
        if not query:
            return list(self._labels)
        return [label for label in self._labels if query in label.lower()]

    # ---- 交互 ---------------------------------------------------------
    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Left", "Right",
                            "Home", "End", "Prior", "Next", "Shift_L", "Shift_R",
                            "Control_L", "Control_R"):
            return
        hits = self._filtered_labels(self.var.get())
        self.box.configure(values=hits)
        self._update_count(len(hits))

    def _open(self):
        try:
            self.box.tk.call("ttk::combobox::Post", self.box)
        except tk.TclError:
            pass

    def _on_selected(self, _event=None):
        key = self._key_of.get(self.var.get())
        if key is None:
            return
        self._key = key
        self.box.configure(values=self._labels)      # 选完恢复全量候选
        self._update_count(len(self._labels))
        if self.on_pick:
            self.on_pick(key)

    def _on_return(self, _event=None):
        label = self.var.get()
        if label in self._key_of:
            self._on_selected()
        else:
            hits = self._filtered_labels(label)
            if len(hits) == 1:
                self.var.set(hits[0])
                self._on_selected()
            else:
                self._open()
        return "break"

    # ---- 读写 ---------------------------------------------------------
    def get(self):
        return self._key

    def select_index(self, index):
        """按下标选中（测试 / 键盘回车用）：等价于在下拉里点第 index 项。"""
        if 0 <= index < len(self._items):
            self.var.set(self._labels[index])
            self._on_selected()
            return self._key
        self._key = None
        return None

    def set_key(self, key):
        for label, known in self._key_of.items():
            if known == key:
                self.var.set(label)
                self._key = key
                return True
        return False


class RowEditor(tk.Frame):
    """可删行的只读表（配合“添加/删除”按钮）。"""

    def __init__(self, parent, columns, height=4, on_change=None, autosize=False):
        super().__init__(parent, bg=theme.PANEL)
        self.on_change = on_change
        self.autosize = autosize
        f, self.tv = theme.table(self, columns, height=height)
        f.pack(fill="both", expand=True)
        bar = tk.Frame(self, bg=theme.PANEL)
        bar.pack(fill="x", pady=(4, 0))
        theme.button(bar, "删除选中", command=self.remove_selected).pack(side="left")
        self.hint = tk.Label(bar, text="", bg=theme.PANEL, fg=theme.DIM, font=theme.F_S)
        self.hint.pack(side="right")

    def set_rows(self, rows, hint=""):
        theme.fill_table(self.tv, rows)
        if self.autosize:
            # 至少 2 行、最多 8 行；5 个变种就显示 5 行（原来固定 2 行只能看到 2 条）
            self.tv.configure(height=max(2, min(len(rows), 8)))
        self.hint.configure(text=hint or "%d 条" % len(rows))

    def remove_selected(self):
        sel = self.tv.selection()
        if not sel:
            return
        idx = self.tv.index(sel[0])
        if self.on_change:
            self.on_change(idx)
