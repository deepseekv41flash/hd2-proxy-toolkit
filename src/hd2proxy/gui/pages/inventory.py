"""本地账号页（原名「物品与战备」）：武器 / 附件 / 外观 / 战备 / 目录追加 / 目录总览 / 存档 七个 tab。

2026-11-23 改名 + 加「存档（本机账本）」tab：本页改的东西**全部只在本机生效**（库存行 / 目录上架 /
本机 earned 账本），不回传服务器；服务端仍是事实源。页头固定三条边界提示。

前四个 tab 写 `profile["inventory"][key]`（行格式 {"mixId","amount","isDiscovered"}）；
目录追加 tab 写 `profile["items"]`（template + add）；目录总览是**只读**查询页
（2026-11-18 起把服务端目录 3020 行全量做进来：名字/类别/空号默认标记）。
全部只改内存 profile，由右上角「应用配置」热更新到引擎。
"""

import tkinter as tk
from tkinter import messagebox, ttk

from .. import theme
from ..catalogs import CATALOG_SCOPES, ITEM_CATEGORY_LABELS
from ..widgets import RowEditor, SearchList
from . import Page

# key -> 中文名（与 profile.inventory 的键一一对应）
EDIT_TABS = (("weapons", "武器"), ("attachments", "附件"),
             ("cosmetics", "外观"), ("stratagems", "战备"))
TAB_NAMES = dict(EDIT_TABS)
# key -> items.json 的 `category` 值（每个 tab 的列表只显示这一类；2026-11-17 用户报「外观里冒出附件」）
TAB_CATEGORY = {"weapons": "weapon", "attachments": "attachment",
                "cosmetics": "cosmetic", "stratagems": "stratagem"}


def _catalog_add_id(entry):
    """目录追加列表条目 -> itemId（dict 取 id/mixId，纯整数原样）；解析不了返回 None。"""
    raw = entry.get("id", entry.get("mixId")) if isinstance(entry, dict) else entry
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# 三条边界（页头固定展示 + 存档 tab 里再展开一次，避免用户误以为"改账号数据"）
BOUNDARY_SHORT = ("仅本机视图", "不回传服务器", "服务端仍是事实源")
BOUNDARY_LINES = (
    "只在本机生效：改的是客户端收到的响应，不写服务端任何数据",
    "不回传服务器：本机账本不会同步到任何服务器，也不会影响同账号的其它机器",
    "服务端仍是事实源：服务端给得更多就听它的，本机账本只在服务端给得更少时兜底",
)


class InventoryPage(Page):
    title = "本地账号"

    # ---------------------------------------------------------------- 构图
    def build(self):
        self.header("本地账号（仅本机视图）",
                    "库存 / 目录 / 存档都只改本机；改完点右上角「应用配置」热更新")
        self._build_boundary_bar()
        self._lists = {}
        self._amounts = {}
        self._keywords = {}
        self._editors = {}
        self._counts = {}
        self._list_hints = {}
        self._weapon_lists = {}        # 附件 tab 的一级列表：按武器筛选
        self._attachment_groups = {}   # 附件 tab：武器 key -> (parent_id, 武器名, [(mix, label), ...])
        self._sel_attachment_weapon = None
        self._filled = {}              # tab 的列表是否已填过（切 tab 时补一次）
        self._filled_catalog = False   # 目录总览列表是否已填（3062 行，切 tab 只补一次）

        bar = tk.Frame(self, bg=theme.BG)
        bar.pack(fill="x", padx=22, pady=(0, 8))
        self.sum_lbl = tk.Label(bar, text="", bg=theme.BG, fg=theme.MUTED, font=theme.F_S)
        self.sum_lbl.pack(side="left")
        # 一键解锁全部物品（v0.10.1）：按物品目录展开成库存行，只改本机响应
        self.unlock_btn = theme.button(bar, "一键解锁全部物品",
                                       command=self._toggle_unlock_all)
        self.unlock_btn.pack(side="left", padx=(14, 0))
        # 一键撤回本页所有改动：四类库存行 + 目录追加（附件这类成百上千条的库存没法手点删）
        theme.button(bar, "清空全部已添加", danger=True,
                     command=self._clear_all_added).pack(side="left", padx=(14, 0))
        tk.Label(bar, text="库存行 = 解锁/试用；目录追加 = 让物品出现在列表里",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=22, pady=(0, 16))
        for key, label in EDIT_TABS:
            if key == "attachments":
                self._build_attachment_tab(key, label)
            else:
                self._build_edit_tab(key, label)
        self._build_items_tab()
        self._build_catalog_tab()
        self._build_save_tab()
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ---- 页头三条边界 --------------------------------------------------
    def _build_boundary_bar(self):
        bar = tk.Frame(self, bg=theme.PANEL, highlightbackground=theme.BORDER,
                       highlightthickness=1)
        bar.pack(fill="x", padx=22, pady=(0, 8))
        self._boundary_labels = []
        for text in BOUNDARY_SHORT:
            lbl = tk.Label(bar, text="● " + text, bg=theme.PANEL, fg=theme.MUTED,
                           font=theme.F_S)
            lbl.pack(side="left", padx=(12, 0), pady=5)
            self._boundary_labels.append(lbl)
        tk.Label(bar, text="改名自「物品与战备」", bg=theme.PANEL, fg=theme.DIM,
                 font=theme.F_S).pack(side="right", padx=12, pady=5)

    # ---- 存档（本机账本）tab --------------------------------------------
    def _build_save_tab(self):
        tab = tk.Frame(self.nb, bg=theme.BG)
        self.nb.add(tab, text="存档（本机账本）")
        self._save_tab = tab

        top = tk.Frame(tab, bg=theme.BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        self.save_state_lbl = tk.Label(top, text="引擎未运行", bg=theme.BG,
                                       fg=theme.DIM, font=theme.F_S)
        self.save_state_lbl.pack(side="left")
        theme.button(top, "存档预演", command=self._preview_save,
                     primary=True).pack(side="right", padx=(8, 0))
        theme.button(top, "刷新摘要", command=self._refresh_save_summary).pack(
            side="right", padx=(8, 0))
        theme.button(top, "打开存档目录", command=self._open_save_dir).pack(side="right")

        self.save_summary_lbl = tk.Label(tab, text="", bg=theme.PANEL, fg=theme.FG,
                                         font=theme.F_S, justify="left", anchor="w",
                                         padx=12, pady=10)
        self.save_summary_lbl.pack(fill="x", padx=12, pady=(6, 8))

        box = tk.Frame(tab, bg=theme.PANEL, highlightbackground=theme.BORDER,
                       highlightthickness=1, padx=12, pady=8)
        box.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(box, text="边界（务必知道）", bg=theme.PANEL, fg=theme.FG,
                 font=theme.F_S).pack(anchor="w")
        for line in BOUNDARY_LINES:
            tk.Label(box, text="· " + line, bg=theme.PANEL, fg=theme.MUTED,
                     font=theme.F_S, anchor="w", justify="left").pack(fill="x")

        self.save_dir_lbl = tk.Label(tab, text="", bg=theme.BG, fg=theme.DIM,
                                     font=theme.F_S, anchor="w", justify="left")
        self.save_dir_lbl.pack(fill="x", padx=12, pady=(0, 10))
        self._refresh_save_summary()

    def _refresh_save_summary(self):
        """读本机账本 → 摘要（只读；引擎不跑也能看）。"""
        from ...engine import save_preview
        try:
            doc, source = save_preview.load_save()
            info = save_preview.summarize_save(doc)
        except Exception as e:      # noqa: BLE001 - 读不到只影响这一栏
            self.save_summary_lbl.configure(text="读取存档失败：%r" % (e,))
            return
        ident = info.get("identity") or {}
        who = ("steam %s（%s）" % (ident.get("steam_id"), ident.get("source"))
               if ident.get("steam_id") else "未识别（local 档）")
        lines = [
            "档：%s（%s）" % (info.get("save_id") or "?", source),
            "身份：%s" % who,
            "经验 %d · 成就 %d · 包进度 %d · 库存行 %d · 统计 %d 项 · 结算 %d 局"
            % (info.get("experience", 0), info.get("achievements", 0),
               info.get("package_progress", 0), info.get("inventory_amounts", 0),
               info.get("stats_fields", 0), info.get("missions_count", 0)),
        ]
        if info.get("catalog_build"):
            lines.append("目录：%s" % info["catalog_build"])
        self.save_summary_lbl.configure(text="\n".join(lines))
        self.save_dir_lbl.configure(
            text="存档目录：%s（点「存档预演」可在开游戏前看这份档会改什么 / 一局会加多少）"
                 % (self._save_root()))

    def _save_root(self):
        from ...engine import paths as engine_paths
        return engine_paths.SAVES_DIR

    def _open_save_dir(self):
        import os
        from pathlib import Path
        root = Path(self._save_root())
        try:
            root.mkdir(parents=True, exist_ok=True)
            os.startfile(str(root))         # noqa: S606 - Windows 资源管理器
        except Exception as e:              # noqa: BLE001
            self.app.toast("打开目录失败：%r" % (e,), error=True)

    def _preview_save(self):
        from ...engine import save_preview
        def done(result):
            if isinstance(result, Exception):
                self.app.toast("存档预演失败", error=True)
                self.app.show_text("存档预演失败", repr(result))
                return
            save = result.get("save") or {}
            self.app.toast("存档预演：经验 %d · 统计 %d 项 · %d 条结算样本"
                           % (save.get("experience", 0), save.get("stats_fields", 0),
                              len(result.get("missions") or [])))
            self.app.show_text("存档预演（不开游戏）", save_preview.format_text(result))
        self.app.run_bg(lambda: save_preview.preview(), done, busy="存档预演中…")

    def _render_save_state(self, status):
        """引擎状态 → 存档一行（live 身份校验态；与 status_page 顶部那行一致）。"""
        save = (status or {}).get("save") or {}
        lbl = getattr(self, "save_state_lbl", None)
        if lbl is None:
            return
        if not save.get("save_id"):
            lbl.configure(text="引擎未运行 / 存档层未启用", fg=theme.DIM)
            return
        if save.get("verified"):
            state = "已校验"
        elif save.get("origin") == "last":
            state = "预绑定·待校验"
        else:
            state = "待校验"
        if save.get("session_dirty"):
            state += " · 本局有写入"
        lbl.configure(text="引擎：存档 %s · %s" % (save.get("save_id"), state),
                      fg=theme.MUTED)

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
        items = self.app.catalogs.search_items("", category=TAB_CATEGORY[key], limit=None)
        lst = SearchList(left, items=items, height=12)
        lst.pack(fill="both", expand=True)
        self._lists[key] = lst
        self._filled[key] = bool(items)
        self._list_hints[key] = tk.Label(
            left, text="", bg=theme.BG, fg=theme.DIM, font=theme.F_S, anchor="w")
        self._list_hints[key].pack(fill="x", pady=(4, 0))
        self._update_list_hint(key, len(items))
        editor = RowEditor(right, [("mixId", 108), ("名称", 210), ("数量", 54)], height=12,
                           on_change=lambda i, k=key: self._remove_row(k, i))
        editor.pack(fill="both", expand=True)
        self._editors[key] = editor

    def _build_attachment_tab(self, key, label):
        """附件 tab：一级选武器、二级选该武器的具体配件。

        为什么是两级：附件解锁是「武器 × 附件」粒度（同一附件在不同枪上是不同 mixId，
        见 docs/UNLOCK-MAP-2026-11-06.md）。直接选中一级武器点「添加到库存」= 解锁该武器全部配件。
        """
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

        tk.Label(left, text="一级：选武器（共 %d 把；点「添加到库存」= 解锁该武器全部配件）"
                           % len(self.app.catalogs.attachment_groups()),
                 bg=theme.BG, fg=theme.MUTED, font=theme.F_S, anchor="w").pack(fill="x")
        self._weapon_lists[key] = SearchList(
            left, items=[], height=6,
            on_pick=lambda pid, k=key: self._pick_attachment_weapon(k, pid))
        self._weapon_lists[key].pack(fill="both", expand=True)

        tk.Label(left, text="二级：该武器的配件（选中则只加这一条）",
                 bg=theme.BG, fg=theme.MUTED, font=theme.F_S, anchor="w").pack(
            fill="x", pady=(6, 0))
        self._lists[key] = SearchList(left, items=[], height=6)
        self._lists[key].pack(fill="both", expand=True)
        self._list_hints[key] = tk.Label(left, text="", bg=theme.BG, fg=theme.DIM,
                                         font=theme.F_S, anchor="w", wraplength=520,
                                         justify="left")
        self._list_hints[key].pack(fill="x", pady=(4, 0))
        self._filled[key] = False

        editor = RowEditor(right, [("mixId", 108), ("名称", 210), ("数量", 54)], height=12,
                           on_change=lambda i, k=key: self._remove_row(k, i))
        editor.pack(fill="both", expand=True)
        self._editors[key] = editor
        self._fill_attachment_weapons()

    def _fill_attachment_weapons(self):
        """填一级武器列表（全部），并建立 key -> 分组 的映射。"""
        groups = self.app.catalogs.attachment_groups()
        self._attachment_groups = {str(pid): (pid, name, items)
                                   for pid, name, items in groups}
        items = [(str(pid), "%s · %d 件" % (name, len(sub)))
                 for pid, name, sub in groups]
        self._weapon_lists["attachments"].set_items(items)
        self._filled["attachments"] = True
        self._sel_attachment_weapon = None
        self._lists["attachments"].set_items([])
        self._update_attachment_hint()

    def _pick_attachment_weapon(self, key, parent_key):
        """选中一级武器 -> 填二级配件列表。"""
        group = self._attachment_groups.get(str(parent_key))
        if not group:
            return
        pid, name, items = group
        self._sel_attachment_weapon = (pid, name, items)
        self._lists["attachments"].set_items(list(items))
        self._update_attachment_hint()

    def _update_attachment_hint(self):
        sel = self._sel_attachment_weapon
        if not sel:
            text = ("未选武器：先在一级列表选武器，二级会列出该武器的全部配件；"
                    "选中一级武器直接点「添加到库存」= 一次解锁该武器全部配件")
        else:
            pid, name, items = sel
            text = ("当前武器：%s（0x%08X，%d 个配件）。直接点「添加到库存」= 解锁全部；"
                    "在二级列表选中某条则只加那一条" % (name, pid, len(items)))
        self._list_hints["attachments"].configure(text=text)

    def _search_items(self, key):
        """关键词查询。

        * 附件 tab：关键词在「全部配件」里跨武器搜（二级列表显示结果，标签带武器名）；
          清空关键词再点搜索 = 回到按武器浏览。
        * 其它 tab：只在本 tab 的类别里查，不截断。
        """
        kw = self._keywords[key].get().strip()
        if key == "attachments":
            if not kw:
                self._fill_attachment_weapons()
                self.app.toast("附件：已列出全部 %d 把武器" % len(self._attachment_groups))
                return
            needle = kw.lower()
            hits = []
            for pid, name, items in self._attachment_groups.values():
                for mix, label in items:
                    if needle in label.lower() or needle in name.lower():
                        hits.append((mix, "%s / %s" % (name, label)))
            self._lists[key].set_items(hits)
            self._list_hints[key].configure(
                text="搜索「%s」：命中 %d 个配件（跨全部武器；清空关键词再点搜索 = 回到按武器浏览）"
                     % (kw, len(hits)))
            self.app.toast("附件：命中 %d 个配件" % len(hits))
            return
        items = self.app.catalogs.search_items(kw, category=TAB_CATEGORY[key], limit=None)
        self._lists[key].set_items(items)
        self._filled[key] = bool(items)
        self._update_list_hint(key, len(items))
        self.app.toast("%s：命中 %d 条" % (TAB_NAMES.get(key, key), len(items)))

    def _update_list_hint(self, key, shown):
        """列表下方提示带上「本类共 N 条」——避免再出现「只显示 80 条」的错觉。"""
        label = self._list_hints.get(key)
        if label is not None:
            label.configure(text="本类共 %d 条；上方搜索框在全部条目里过滤，「关键词 + 搜索」"
                                 "走目录全量查询" % shown)

    def _amount_for(self, key):
        """读该 tab 的数量输入；非法返回 None（已 toast）。"""
        raw = str(self._amounts[key].get()).strip() or "1"
        try:
            amount = int(raw)
        except ValueError:
            self.app.toast("数量要填整数", error=True)
            return None
        if amount < 1:
            self.app.toast("数量必须 >= 1", error=True)
            return None
        return amount

    def _add_item(self, key):
        amount = self._amount_for(key)
        if amount is None:
            return
        if key == "attachments":
            self._add_attachment(key, amount)
            return
        mix = self._lists[key].get_selected()
        if mix is None:
            self.app.toast("先在左侧列表里选一件物品", error=True)
            return
        self._append_inventory_row(key, int(mix), amount)

    def _append_inventory_row(self, key, mix, amount):
        """把一条库存行加进 profile（类别校验 + 去重 + 渲染 + toast）。"""
        picked_category = self.app.catalogs.item_category(mix)
        if picked_category is not None and picked_category != TAB_CATEGORY[key]:
            self.app.toast("%s 属于「%s」，不能加到%s列表（四个 tab 各自只收同类物品）"
                           % (self.app.catalogs.item_label(mix),
                              {"weapon": "武器", "attachment": "附件", "cosmetic": "外观",
                               "stratagem": "战备"}.get(picked_category, picked_category),
                              TAB_NAMES[key]), error=True)
            return
        rows = self._inventory().setdefault(key, [])
        if any(isinstance(r, dict) and int(r.get("mixId") or 0) == int(mix) for r in rows):
            self.app.toast("mixId %d 已在%s列表里（改数量请先删除再加）" % (mix, TAB_NAMES[key]),
                           error=True)
            return
        rows.append({"mixId": int(mix), "amount": int(amount), "isDiscovered": False})
        self.app.mark_dirty()
        self._render_tab(key)
        template = self._ensure_catalog_row(int(mix))
        label = self.app.catalogs.item_label(mix)
        if template is None:
            self.app.toast("已加入%s：%s" % (TAB_NAMES[key], label))
        else:
            self.app.toast("已加入%s：%s（服务端目录里没有这条 → 已自动配对目录行，模板 %d；"
                           "重载引擎后游戏可见）" % (TAB_NAMES[key], label, template))

    def _ensure_catalog_row(self, mix):
        """目录里没有的物品：库存行必须配一条目录行，否则客户端不显示（M4 实机）。

        只对 items.json 带 `unlock_template` 的物品生效（= 服务端目录确实缺失、且有研究线
        验证过的同族模板）。已配对过就不重复加。返回模板 itemId；不需要时返回 None。
        """
        template = self.app.catalogs.unlock_template(mix)
        if template is None:
            return None
        add = self._items().setdefault("add", [])
        if not isinstance(add, list):
            add = self._items()["add"] = []
        if int(mix) not in {_catalog_add_id(entry) for entry in add}:
            add.append({"id": int(mix), "template": int(template)})
            self.app.mark_dirty()
            if getattr(self, "items_editor", None) is not None:
                self._render_items()
        return int(template)

    def _drop_catalog_row(self, mix):
        """移除库存行时撤掉配对的目录行（与 `_ensure_catalog_row` 对称）。返回模板或 None。"""
        template = self.app.catalogs.unlock_template(mix)
        if template is None:
            return None
        add = self._items(create=False).get("add") or []
        if not isinstance(add, list):
            return None
        kept = [entry for entry in add if _catalog_add_id(entry) != int(mix)]
        if len(kept) == len(add):
            return None
        self._items()["add"] = kept
        self.app.mark_dirty()
        if getattr(self, "items_editor", None) is not None:
            self._render_items()
        return int(template)

    def _add_attachment(self, key, amount):
        """附件：选中二级配件 -> 只加那一条；只选中一级武器 -> 解锁该武器全部配件。"""
        mix = self._lists[key].get_selected()
        if mix is not None:
            self._append_inventory_row(key, int(mix), amount)
            return
        weapon_key = self._weapon_lists[key].get_selected()
        if weapon_key is None:
            self.app.toast("先选一把武器（= 解锁该武器全部配件），或在二级列表选一个具体配件",
                           error=True)
            return
        group = self._attachment_groups.get(str(weapon_key))
        if not group:
            self.app.toast("武器列表已过期，点「搜索」刷新后再试", error=True)
            return
        pid, name, items = group
        rows = self._inventory().setdefault(key, [])
        existing = {int(r.get("mixId") or 0) for r in rows if isinstance(r, dict)}
        todo = [int(mix) for mix, _label in items if int(mix) not in existing]
        if not todo:
            self.app.toast("%s 的 %d 个配件都已在%s列表里"
                           % (name, len(items), TAB_NAMES[key]), error=True)
            return
        rows.extend({"mixId": mix, "amount": int(amount), "isDiscovered": False} for mix in todo)
        self.app.mark_dirty()
        self._render_tab(key)
        self.app.toast("已解锁 %s（0x%08X）的全部配件：%d 条（新增 %d，已存在 %d）"
                       % (name, pid, len(items), len(todo), len(items) - len(todo)))

    def _remove_row(self, key, index):
        rows = self._inventory(create=False).get(key) or []
        if 0 <= index < len(rows):
            row = rows.pop(index)
            mix = row.get("mixId") if isinstance(row, dict) else row
            template = self._drop_catalog_row(mix)
            self.app.mark_dirty()
            self._render_tab(key)
            if template is None:
                self.app.toast("已从%s移除 mixId %s" % (TAB_NAMES[key], mix))
            else:
                self.app.toast("已从%s移除 mixId %s，并撤掉配对的目录行（模板 %d）"
                               % (TAB_NAMES[key], mix, template))

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
        items = self.app.catalogs.search_items("", limit=None)
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
        items = self.app.catalogs.search_items(kw, limit=None)
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
        if int(mix) in {_catalog_add_id(entry) for entry in add}:
            self.app.toast("itemId %d 已在追加列表里" % mix, error=True)
            return
        template = self.app.catalogs.unlock_template(mix)
        add.append({"id": int(mix), "template": int(template)} if template else int(mix))
        self.app.mark_dirty()
        self._render_items()
        self.app.toast("已追加到目录：%s%s"
                       % (self.app.catalogs.item_label(mix),
                          "（模板 %d）" % template if template else ""))

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
            mix = _catalog_add_id(item)
            rows.append((mix, self.app.catalogs.item_label(mix)))
        self.items_editor.set_rows(rows, "%d 条" % len(rows))
        self.items_count.configure(text="目录追加 %d 条" % len(rows))
        self._render_summary()

    # ---- 第六个 tab：目录总览（只读） ----------------------------------
    def _build_catalog_tab(self):
        """服务端目录 3020 行的只读总览：汇总行 + 类别筛选 + 全量列表。

        为什么单独一页：目录补全后 items 有 3062 条（含 512 条类别语义未解的行），
        编辑 tab 只显示各自类别；这里回答「目录到底有什么、哪些还没名字、哪些空号就有」
        而不增加任何写入口（解锁仍在前四个 tab）。
        """
        tab = tk.Frame(self.nb, bg=theme.BG)
        self.nb.add(tab, text="目录总览")

        bar = tk.Frame(tab, bg=theme.BG)
        bar.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(bar, text="类别", bg=theme.BG, fg=theme.MUTED,
                 font=theme.F_S).pack(side="left")
        self.var_catalog_scope = tk.StringVar(value=CATALOG_SCOPES[0][1])
        self._catalog_scope_keys = {label: key for key, label in CATALOG_SCOPES}
        box = ttk.Combobox(bar, textvariable=self.var_catalog_scope,
                           values=[label for _key, label in CATALOG_SCOPES],
                           width=18, state="readonly", font=theme.F_S)
        box.pack(side="left", padx=(6, 10))
        box.bind("<<ComboboxSelected>>", lambda _e: self._fill_catalog_list())
        theme.button(bar, "刷新", command=self._fill_catalog_list).pack(side="left")
        self.catalog_count = tk.Label(bar, text="", bg=theme.BG, fg=theme.DIM, font=theme.F_S)
        self.catalog_count.pack(side="right")

        self.catalog_summary_lbl = tk.Label(
            tab, text="", bg=theme.BG, fg=theme.MUTED, font=theme.F_S,
            anchor="w", justify="left", wraplength=1000)
        self.catalog_summary_lbl.pack(fill="x", padx=12, pady=(0, 6))

        body = tk.Frame(tab, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.catalog_overview_list = SearchList(body, items=[], height=14)
        self.catalog_overview_list.pack(fill="both", expand=True)
        tk.Label(body, text="只读页：只查目录、不解锁任何东西；解锁/追加请用前五个 tab。"
                            "「默认已有」= 空号也拥有，「目录缺」= 服务端目录里没有（走目录追加）",
                 bg=theme.BG, fg=theme.DIM, font=theme.F_S, anchor="w",
                 justify="left", wraplength=1000).pack(fill="x", pady=(4, 0))
        self._render_catalog_summary()
        self._fill_catalog_list()

    def _render_catalog_summary(self):
        """汇总行：目录行数 / 界面条目 / 命名覆盖 / 空号默认 / 各语义类别行数。"""
        s = self.app.catalogs.catalog_summary()
        order = ("attachment", "cosmetic", "weapon", "stratagem",
                 "booster", "banner", "currency", "universal", "unknown")
        kind_parts = []
        for kind in order:
            stat = s["by_kind"].get(kind) or {}
            if stat.get("rows"):
                kind_parts.append("%s %d" % (ITEM_CATEGORY_LABELS.get(kind, kind),
                                             stat["rows"]))
        for kind, stat in s["by_kind"].items():     # 未登记中文名的类别也要显示
            if kind not in order and stat.get("rows"):
                kind_parts.append("%s %d" % (kind, stat["rows"]))
        line1 = ("服务端目录 %d 行（与账号无关）· 界面条目 %d（目录内 %d + 目录外 %d）"
                 % (s["rows"], s["items"], s["in_catalog"], s["extra"]))
        line2 = "已命名 %d · 未解 %d · 空号默认拥有 %d" % (
            s["named"], s["unnamed"], s["default_owned"])
        if kind_parts:
            line2 += " · 目录行类别：" + " · ".join(kind_parts)
        self.catalog_summary_lbl.configure(text=line1 + "\n" + line2)

    def _fill_catalog_list(self):
        scope = self._catalog_scope_keys.get(self.var_catalog_scope.get(), "all")
        items = self.app.catalogs.catalog_entries(scope=scope)
        self.catalog_overview_list.set_items(items)
        self._filled_catalog = bool(items)
        self.catalog_count.configure(
            text="当前「%s」%d 条" % (self.var_catalog_scope.get(), len(items)))

    def _on_tab_changed(self, _event=None):
        """切 tab 时补填当前 tab 的列表（只补一次；目录总览也是懒填）。"""
        try:
            current = self.nb.index(self.nb.select())
        except tk.TclError:
            return
        keys = [k for k, _label in EDIT_TABS]
        if current < len(keys):
            key = keys[current]
            if not self._filled.get(key):
                self._search_items(key)
        elif current == len(keys):
            if not self._filled_items:
                self._search_catalog_items()
        elif not self._filled_catalog:
            self._fill_catalog_list()

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

    # ---------------------------------------------------------------- 一键解锁全部
    def _toggle_unlock_all(self):
        """一键解锁/关闭「全部物品」（只改本机视图；点「应用配置」后引擎生效）。

        展开规则见 `engine/item_catalog.py`：在架 + 有 mixId + 非货币 + 非空号默认拥有。
        数据量大（约 2.5k 行），所以要确认框并显示实际条数。
        """
        from ...engine.item_catalog import unlock_all_ids

        inv = self._inventory()
        if inv.get("unlock_all"):
            inv["unlock_all"] = False
            self.app.mark_dirty()
            self._render_summary()
            self.app.toast("已关闭「一键解锁全部物品」（点应用配置后生效）")
            return
        ids, st = unlock_all_ids(inv.get("unlock_scope") or [])
        if not ids:
            # 2026-11-26 实机踩过：安装目录的 data/ 缺失 ⇒ 只报"读不到"没法自查，这里带上绝对路径
            from ...engine import paths as _paths
            _p = _paths.CATALOGS_DIR / "items.json"
            self.app.toast("没有可解锁的物品：目录文件读不到或为空 → %s（检查安装目录里的 data/ 是否完整）"
                           % _p, error=True)
            return
        scope = ",".join(st.get("scope") or []) or "全部类别"
        message = chr(10).join([
            "确定一键解锁全部物品？", "",
            "运行期按**客户端实际目录**展开（离线估算 %d 行，范围：%s）" % (len(ids), scope),
            "同时把 6 条舰船模块包的等级置满（模块不是库存行，靠 packageProgress 显示）",
            "并把**全部战团条目按「已领取」下发**（军械库的解锁态 —— 武器等级/改装按钮 —— 看这份名单）",
            "授予行 isDiscovered=false（与真实库存一致）", "",
            "只改客户端收到的响应，不写服务端任何数据；点「应用配置」后生效。",
            "物品很多时游戏内列表/商店可能加载变慢，这是预期副作用。",
        ])
        if not messagebox.askyesno("一键解锁全部物品", message):
            return
        inv["unlock_all"] = True
        self.app.mark_dirty()
        self._render_summary()
        self.app.toast("已开启一键解锁：%d 个物品（点「应用配置」生效）" % len(ids))

    # ---------------------------------------------------------------- 批量清空
    def _clear_all_added(self):
        """一键移除本页**所有已添加项**：四类库存行 + 目录追加行（只改本机 profile）。

        为什么需要：附件是「武器 × 附件」粒度，一把枪批量添加能一次进几十条，
        但没有批量移除时只能逐条点删除（附件最多 1455 条）。这里按「全部撤回」处理：
        四类库存行清空 + 目录追加清空（目录缺失物品自动配对的目录行随之消失），
        template 这类标量设置保留。确认框会先列出各类条数，取消不改任何东西。
        """
        inv = self._inventory(create=False)
        counts = {key: len(inv.get(key) or []) for key, _label in EDIT_TABS}
        add = self._items(create=False).get("add") or []
        add_count = len(add) if isinstance(add, list) else 0
        total = sum(counts.values()) + add_count
        if not total:
            self.app.toast("本页没有已添加项（库存与目录追加都是空的）", error=True)
            return
        detail = " · ".join("%s %d" % (label, counts[key]) for key, label in EDIT_TABS)
        if add_count:
            detail += " · 目录追加 %d" % add_count
        message = chr(10).join([
            "确定移除本页所有已添加项？", "", detail, "",
            "只改本机 profile；点「应用配置」后才影响引擎。",
        ])
        if not messagebox.askyesno("清空全部已添加", message):
            return
        for key, _label in EDIT_TABS:
            inv[key] = []
        if add_count:
            self._items()["add"] = []
        self.app.mark_dirty()
        for key, _label in EDIT_TABS:
            self._render_tab(key)
        self._render_items()
        self._render_summary()
        self.app.toast("已清空全部已添加项：库存 %d 条 · 目录追加 %d 条"
                       % (sum(counts.values()), add_count))

    # ---------------------------------------------------------------- 刷新
    def _render_summary(self):
        inv = self._inventory(create=False)
        parts = []
        for key, label in EDIT_TABS:
            rows = inv.get(key) or []
            parts.append("%s %d" % (label, len(rows) if isinstance(rows, list) else 0))
        add = self._items(create=False).get("add") or []
        parts.append("目录追加 %d" % (len(add) if isinstance(add, list) else 0))
        if inv.get("unlock_all"):
            from ...engine.item_catalog import unlock_all_summary
            st = unlock_all_summary(inv.get("unlock_scope") or [])
            parts.append("一键解锁 全开（离线估算 %d 行）" % st.get("count", 0))
        else:
            parts.append("一键解锁 关")
        line = "已加入：" + " · ".join(parts)
        cat = self.app.catalogs.catalog_summary()
        if cat["items"]:
            line += " ｜ 目录 %d 行 · 命名 %d · 空号默认 %d" % (
                cat["rows"], cat["named"], cat["default_owned"])
        self.sum_lbl.configure(text=line)

    def refresh(self):
        for key, _label in EDIT_TABS:
            self._render_tab(key)
        self._render_items()
        self._heal_catalog_rows()
        tmpl = self._items(create=False).get("template")
        self.var_template.set("" if tmpl is None else str(tmpl))
        self._render_catalog_summary()
        if getattr(self, "catalog_overview_list", None) is not None and not self._filled_catalog:
            self._fill_catalog_list()
        self._render_summary()
        self._refresh_save_summary()

    def _heal_catalog_rows(self):
        """老 profile 自愈：库存里已有「目录缺失物品」但没配目录行时补上（用户不必删了重加）。

        2026-11-17 之前手动加库存只写库存行 —— 升级后打开本页即把缺的目录行补齐；
        只对 items.json 带 unlock_template 的物品生效，重复调用无副作用。
        """
        for key, _label in EDIT_TABS:
            for row in self._inventory(create=False).get(key) or []:
                if not isinstance(row, dict):
                    continue
                mix = int(row.get("mixId") or 0)
                if mix:
                    self._ensure_catalog_row(mix)
        if getattr(self, "items_editor", None) is not None:
            self._render_items()

    def on_status(self, status):
        # 本页数据全在 profile 里，引擎状态不影响编辑；顶部提示 + 存档一行跟着更新
        if status:
            self.sum_lbl.configure(fg=theme.MUTED)
        self._render_save_state(status)
