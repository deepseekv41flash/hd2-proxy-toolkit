"""GUI 三页单测：战况改写 / 物品与战备 / 抓包与日志。

不依赖引擎进程：App 用轻量 fake（只提供页面用到的接口：profile / catalogs /
mark_dirty / toast / cert_dir / client / run_bg），页面代码与真实 App 走同一套接口。
无图形环境（tk.Tk() 抛 TclError）时整文件跳过。
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

import tkinter as tk                                   # noqa: E402

from hd2proxy.engine import config                     # noqa: E402
from hd2proxy.gui import templates                     # noqa: E402
from hd2proxy.gui import theme                         # noqa: E402
from hd2proxy.gui.catalogs import Catalogs             # noqa: E402
from hd2proxy.gui.pages.capture import CapturePage     # noqa: E402
from hd2proxy.gui.pages.overview import OverviewPage   # noqa: E402
from hd2proxy.gui.pages.settings import SettingsPage   # noqa: E402
from hd2proxy.gui.pages.inventory import InventoryPage  # noqa: E402
from hd2proxy.gui.pages.live_page import LivePage        # noqa: E402
from hd2proxy.gui.pages.status_page import StatusPage  # noqa: E402


# ---------------------------------------------------------------- fake app


class FakeClient:
    """只实现页面用到的引擎客户端面：running / set_capture / run_cli。"""

    def __init__(self):
        self.running_flag = False
        self.calls = []

    def running(self):
        return self.running_flag

    def set_capture(self, enabled, directory=None):
        self.calls.append((enabled, directory))
        return {"ok": True, "enabled": enabled}

    def run_cli(self, args, timeout=180):
        self.calls.append(list(args))
        return 0, ""


class FakeApp:
    def __init__(self, tmp_path, catalogs):
        self.profile = config.default_profile(name="测试")
        self.profile_path = tmp_path / "profile.json"
        self.catalogs = catalogs
        self.last_status = None
        self.client = FakeClient()
        self.toasts = []
        self.texts = []
        self.dirty = 0
        self._cert_dir = tmp_path / "state" / "certs"
        self._cert_dir.mkdir(parents=True, exist_ok=True)

    def mark_dirty(self):
        self.dirty += 1

    def toast(self, text, error=False):
        self.toasts.append((text, error))

    def cert_dir(self):
        return self._cert_dir

    def run_bg(self, fn, on_done, busy=""):
        try:
            result = fn()
        except Exception as e:            # noqa: BLE001 - 与 App 一样把异常交给 on_done
            result = e
        on_done(result)

    def show_text(self, title, content):
        self.texts.append((title, content))

    def last_toast(self):
        return self.toasts[-1] if self.toasts else (None, False)

    # 总览页按钮/Navigation 只要求这些动作存在（页面测试不真正启动引擎）
    def start_engine(self):
        self.calls_started = getattr(self, "calls_started", 0) + 1

    def stop_engine(self):
        self.calls_stopped = getattr(self, "calls_stopped", 0) + 1

    def verify(self):
        pass

    def install_dry(self):
        pass

    def uninstall_dry(self):
        pass

    def save_profile(self, apply=False):
        return True


MINIMAL_STATUS = {
    "mode": "rewrite",
    "cert": {"usable": True, "remaining_hours": 5},
    "stats": {"req": 3, "rewrite": 2},
    "capture": {"enabled": False, "dir": "", "paths": ["api/"]},
    "rewrites": [{"ts": "2026-11-16T19:00:00", "kind": "status", "detail": "planet 76 +2"}],
}


# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def catalogs():
    return Catalogs()


def _ensure_tcl_env():
    """补回 TCL_LIBRARY/TK_LIBRARY。

    Python 首次初始化 Tcl 时会写这两个环境变量；同一进程里前序测试销毁过 Tk 解释器后
    它们可能被清掉，再调 `tk.Tk()` 就会报「Can't find a usable tk.tcl」。
    目录从 sys.prefix 推导（不写死盘符路径）。
    """
    tcl_root = Path(sys.prefix) / "tcl"
    for name, pattern in (("TCL_LIBRARY", "tcl8.*"), ("TK_LIBRARY", "tk8.*")):
        dirs = sorted(p for p in tcl_root.glob(pattern) if p.is_dir())
        if dirs:
            os.environ[name] = str(dirs[-1])


def _anchor_root():
    """在**收集阶段**（早于任何用例执行）先建一个常驻 Tk 根。

    Windows 上同一个进程里「先建后毁」Tk 解释器后，再调 `tk.Tk()` 有机会初始化失败
    （找不到 tk.tcl）。tests/unit/test_gui_core.py 的 App 冒烟会建了又毁 Tk，所以这里
    先把解释器常驻住，全程复用它 —— 也顺便让整个模块少建/毁解释器。
    """
    _ensure_tcl_env()
    try:
        r = tk.Tk()
    except tk.TclError:                    # pragma: no cover - 无图形环境
        return None
    r.withdraw()
    theme.apply_theme(r)
    return r


_ANCHOR = {"root": _anchor_root()}          # 故意不 destroy：留到进程退出


@pytest.fixture(scope="module")
def root():
    r = _ANCHOR["root"]
    if r is None:
        pytest.skip("无图形环境")
    r.withdraw()
    return r


@pytest.fixture()
def app(tmp_path, catalogs):
    return FakeApp(tmp_path, catalogs)


def _make(page_cls, root, app):
    page = page_cls(root, app)
    page.pack(fill="both", expand=True)
    root.update_idletasks()
    return page


# ---------------------------------------------------------------- 三页共性


def test_all_pages_build_refresh_and_status(root, app):
    for page_cls in (StatusPage, InventoryPage, CapturePage):
        page = _make(page_cls, root, app)
        page.refresh()
        page.on_status(None)
        page.on_status(MINIMAL_STATUS)
        assert app.profile["name"] == "测试"


# ---------------------------------------------------------------- StatusPage


def test_status_page_refresh_and_status(root, app):
    page = _make(StatusPage, root, app)
    page.refresh()
    page.on_status(None)
    assert "未运行" in page.engine_lbl.cget("text")
    page.on_status(MINIMAL_STATUS)
    assert "运行中" in page.engine_lbl.cget("text")
    assert "当前 profile" in page.profile_lbl.cget("text")
    assert app.profile["status"]["variants"] == []


def test_status_add_variant_and_dedup(root, app):
    page = _make(StatusPage, root, app)
    page.variant_dd.select_index(0)
    name = page.variant_dd.get()
    page.variant_pick.set(76)
    page._add_variant()
    assert app.profile["status"]["variants"] == [{"name": name, "planets": [76]}]
    assert app.dirty == 1
    page._add_variant()                       # 同变种同星球：拒绝重复
    assert app.profile["status"]["variants"][0]["planets"] == [76]
    assert app.last_toast()[1] is True
    assert len(page.variant_editor.tv.get_children()) == 1
    page._del_variant(0)
    assert app.profile["status"]["variants"] == []


def test_status_empty_selection_toasts(root, app):
    page = _make(StatusPage, root, app)
    page._add_variant()                        # 下拉没选中任何变种
    assert app.last_toast()[1] is True
    assert app.profile["status"]["variants"] == []


def test_status_effects_dedup_and_merge(root, app):
    page = _make(StatusPage, root, app)
    page.global_dd.select_index(0)
    effect = page.global_dd.get()
    page._add_global()
    assert app.profile["status"]["globalEffects"] == {"1501113": [effect]}
    page._add_global()                        # 同事件同 effect：去重
    assert app.profile["status"]["globalEffects"] == {"1501113": [effect]}
    page.pe_pick.set(100)
    page.pe_dd.select_index(1)
    effect2 = page.pe_dd.get()
    page._add_planet_effect()
    page._add_planet_effect()                 # 同星球同 effect：去重
    assert app.profile["status"]["planet_effects"] == [{"index": 100, "ids": [effect2]}]
    page.pe_pick.set(101)
    page._add_planet_effect()                 # 另一颗星：新增一行
    assert len(app.profile["status"]["planet_effects"]) == 2


def test_status_make_dormant_writes_four_pieces(root, app):
    page = _make(StatusPage, root, app)
    page.var_star.set("300")
    page.var_hash.set("694418289")
    page.var_pos.set("0.3,-0.55")
    page.var_owner.set("1 · 人类")
    page.var_camp.set("51999")
    page._make_dormant()
    prof = app.profile
    assert prof["warinfo"]["planet_infos"] == [
        {"index": 300, "settingsHash": 694418289, "position": {"x": 0.3, "y": -0.55},
         "maxHealth": 1000000, "initialOwner": 1, "sector": 20, "waypoints": []}]
    assert prof["status"]["planet_nodes"] == [
        {"index": 300, "owner": 1, "health": 1000000, "regenPerSecond": 4.1666665,
         "players": 0, "position": {"x": 0.3, "y": -0.55}}]
    assert prof["status"]["campaigns"] == [
        {"planet": 300, "id": 51999, "type": 0, "count": 1, "race": 1}]
    assert prof["status"]["owner"] == {"300": 1}
    rows = [page.dormant_tv.item(i)["values"] for i in page.dormant_tv.get_children()]
    assert len(rows) == 4 and all(row[2] == "OK" for row in rows)
    # 再生成一次：同 index 的条目要替换，不能重复
    page._make_dormant()
    assert len(prof["warinfo"]["planet_infos"]) == 1
    assert len(prof["status"]["planet_nodes"]) == 1
    assert len(prof["status"]["campaigns"]) == 1
    assert prof["status"]["owner"] == {"300": 1}


def test_status_borrow_and_owner_flip(root, app):
    page = _make(StatusPage, root, app)
    page.borrow_src.set(100)
    page.borrow_dst.set(76)
    page.var_borrow_hash.set("2995599666")
    page._borrow_ecosystem()
    assert app.profile["warinfo"]["settings_hash"] == {"76": 2995599666}
    # 留空且源星球没有缓存 hash -> 报错提示，不写坏数据
    page.var_borrow_hash.set("")
    page.borrow_dst.set(101)
    page._borrow_ecosystem()
    assert app.last_toast()[1] is True
    assert "101" not in app.profile["warinfo"]["settings_hash"]
    # 归属翻转
    page.owner_pick.set(76)
    page.var_owner_pick.set("3 · 机器人")
    page._flip_owner()
    assert app.profile["status"]["owner"] == {"76": 3}
    page._del_owner(0)
    assert app.profile["status"]["owner"] == {}


# ---------------------------------------------------------------- M3：模板 / 预演 / 折叠区


def test_status_template_bar_applies_first_core_template(root, app):
    page = _make(StatusPage, root, app)
    assert page.tpl_box.current() == 0            # 默认选中第一个核心模板
    assert "变种词条试用" == page.tpl_var.get()
    page.tpl_planet.set(76)
    page._apply_template_pick()
    # M4 后模板改走 planet_effects 原始通道（不按 owner 过滤）
    assert app.profile["status"]["planet_effects"] == [{"index": 76, "ids": [1243, 1245]}]
    assert app.dirty == 1
    assert app.texts and "模板已应用" in app.texts[-1][0]
    assert "星球 76" in app.texts[-1][1]


def test_status_template_without_planet_toasts_error(root, app):
    page = _make(StatusPage, root, app)
    page.tpl_planet.var.set("")                   # 模拟没选星球
    page.tpl_box.current(2)                       # 战备试用：需要星球
    page._apply_template_pick()
    assert app.last_toast()[1] is True
    assert app.profile["status"]["trials"] == []
    assert app.profile["status"]["variants"] == []
    assert app.dirty == 0


def test_status_deferred_fold_and_apply(root, app):
    page = _make(StatusPage, root, app)
    assert page._deferred_open is False
    page._toggle_deferred()
    assert page._deferred_open is True
    assert page._deferred_body.winfo_manager() == "pack"
    page.tpl_planet.set(158)
    page._apply_template(templates.DEFERRED_TEMPLATES[0])   # 防守战役
    assert app.profile["status"]["campaigns"][0]["type"] == 4
    assert app.dirty == 1
    page._toggle_deferred()
    assert page._deferred_open is False


def test_status_preview_calls_engine_preview(root, app):
    page = _make(StatusPage, root, app)
    page.tpl_planet.set(100)
    page.tpl_box.current(0)
    page._apply_template_pick()                   # 先加一个变种，预演才有增量
    page._preview_profile()
    assert app.texts and "离线预演" in app.texts[-1][0]
    body = app.texts[-1][1]
    assert "战况 Status" in body and "合计" in body
    assert "增量" in app.last_toast()[0]


# ---------------------------------------------------------------- InventoryPage


@pytest.fixture()
def inv_page(root, app):
    page = _make(InventoryPage, root, app)
    page.refresh()
    return page


def test_inventory_add_remove_and_summary(inv_page, app):
    page = inv_page
    page._lists["weapons"].listbox.selection_set(0)
    mix = page._lists["weapons"].get_selected()
    page._amounts["weapons"].set("3")
    page._add_item("weapons")
    assert app.profile["inventory"]["weapons"] == [
        {"mixId": mix, "amount": 3, "isDiscovered": False}]
    page._add_item("weapons")                  # 同 mixId：拒绝重复
    assert len(app.profile["inventory"]["weapons"]) == 1
    assert "武器 1" in page.sum_lbl.cget("text")
    page._remove_row("weapons", 0)
    assert app.profile["inventory"]["weapons"] == []
    assert "武器 0" in page.sum_lbl.cget("text")


def test_inventory_tabs_only_show_their_own_category(inv_page):
    """四个 tab 是筛选器：外观里不能出现附件；附件 tab 是一级武器 / 二级配件。

    判定用物品内部名当指纹：`TUBE REDDOT` / `Vertical Grip` 一定属于附件；
    `Shear` / `Veto` 一定属于武器。
    """
    page = inv_page
    labels = {key: list(page._lists[key].listbox.get(0, "end"))
              for key in ("weapons", "cosmetics", "stratagems")}
    assert labels["cosmetics"] and not any("TUBE REDDOT" in x or "Vertical Grip" in x
                                           for x in labels["cosmetics"])
    assert any("Shear" in x for x in labels["weapons"])
    assert not any("Shear" in x for x in labels["cosmetics"])
    # 战备（cat 11）2026-11-18 起可由战备目录 hash 匹配命名（部分行有名字）：这里只守类别不串味
    assert labels["stratagems"]
    assert not any("TUBE REDDOT" in x or "Vertical Grip" in x or "Shear" in x
                   for x in labels["stratagems"])
    # 一级：武器列表 = 目录里所有「有配件」的武器（57 把）；二级初始为空
    groups = page.app.catalogs.attachment_groups()
    assert len(groups) == 57
    assert page._weapon_lists["attachments"].listbox.size() == len(groups)
    assert page._lists["attachments"].listbox.size() == 0
    # 选一把武器 -> 二级 = 该武器全部配件（含 TUBE REDDOT / Vertical Grip 这类附件名）
    pid, name, items = groups[0]
    page._pick_attachment_weapon("attachments", str(pid))
    labels2 = list(page._lists["attachments"].listbox.get(0, "end"))
    assert len(labels2) == len(items) and len(items) > 0
    assert page._lists["attachments"].listbox.size() == len(items)
    # 列表不截断：武器 / 外观 / 战备 tab 的条目数 = 该类别的全部条目
    for key, category in (("weapons", "weapon"), ("cosmetics", "cosmetic"),
                          ("stratagems", "stratagem")):
        total = len(page.app.catalogs.search_items("", category=category))
        assert len(labels[key]) == total, (key, len(labels[key]), total)
        assert total > 0


def test_attachment_tab_bulk_unlock_all_and_dedupe(inv_page, app):
    """一级选武器 + 点「添加到库存」= 解锁该武器全部配件；重复点只提示、不重复加。"""
    page = inv_page
    gallery = page.app.catalogs.attachment_groups()
    pid, name, items = gallery[0]
    page._weapon_lists["attachments"].listbox.selection_set(0)
    page._add_item("attachments")
    rows = app.profile["inventory"]["attachments"]
    assert len(rows) == len(items)
    assert {r["mixId"] for r in rows} == {mix for mix, _label in items}
    # 再来一次：全部已存在 -> 不新增，提示里含「已在」
    before = len(app.profile["inventory"]["attachments"])
    page._add_item("attachments")
    assert len(app.profile["inventory"]["attachments"]) == before
    text, error = app.last_toast()
    assert error and "已在" in text


def test_attachment_tab_single_add_from_second_level(inv_page, app):
    """二级选中具体配件时，只加那一条（不是整把武器）。"""
    page = inv_page
    gallery = page.app.catalogs.attachment_groups()
    pid, name, items = gallery[0]
    page._pick_attachment_weapon("attachments", str(pid))
    page._lists["attachments"].listbox.selection_set(0)
    page._lists["attachments"]._on_select()
    page._add_item("attachments")
    rows = app.profile["inventory"]["attachments"]
    assert len(rows) == 1 and rows[0]["mixId"] == items[0][0]


def test_attachment_tab_global_search(inv_page):
    """附件 tab 的关键词搜索跨武器：搜附件名命中二级列表，清空后回到按武器浏览。"""
    page = inv_page
    page._keywords["attachments"].set("TUBE REDDOT")
    page._search_items("attachments")
    hits = list(page._lists["attachments"].listbox.get(0, "end"))
    assert hits and all("TUBE REDDOT" in x for x in hits)
    assert "/" in hits[0]                       # 标签带武器名
    page._keywords["attachments"].set("")
    page._search_items("attachments")
    assert page._lists["attachments"].listbox.size() == 0
    assert page._weapon_lists["attachments"].listbox.size() == 57


def test_inventory_lists_are_not_truncated(inv_page):
    """回归：列表必须装下整类（原来是 search_items 默认 limit=80，附件 1176 条只显示 80）。"""
    page = inv_page
    catalog = page.app.catalogs
    assert len(catalog.search_items("", category="attachment")) == 1455
    # 武器 / 外观 / 战备 tab 直接装全量
    for key, category in (("weapons", "weapon"), ("cosmetics", "cosmetic"),
                          ("stratagems", "stratagem")):
        assert page._lists[key].listbox.size() == len(catalog.search_items("", category=category))
    # 附件 tab：一级装全部武器；选中后二级装该武器全部配件
    groups = catalog.attachment_groups()
    assert page._weapon_lists["attachments"].listbox.size() == len(groups)
    pid, name, items = groups[0]
    page._pick_attachment_weapon("attachments", str(pid))
    assert page._lists["attachments"].listbox.size() == len(items)
    # 目录追加 tab 也不截断
    assert page.catalog_list.listbox.size() == len(catalog.search_items("", limit=None))


def test_inventory_catalog_overview_is_read_only_and_filters(inv_page, app):
    """0.4.0「目录总览」只读页：全量目录 + 类别筛选 + 汇总，切 tab 不写 profile。

    断言是数据驱动的（目录行数随 build 变），具体数值由 test_catalogs_data.py 守。
    """
    page = inv_page
    catalog = page.app.catalogs
    tabs = [page.nb.tab(i, "text") for i in range(len(page.nb.tabs()))]
    assert tabs == ["武器", "附件", "外观", "战备", "目录追加", "目录总览"]
    summary = catalog.catalog_summary()
    assert page.catalog_overview_list.listbox.size() == len(catalog.search_items("", limit=None))
    text = page.catalog_summary_lbl.cget("text")
    assert ("服务端目录 %d 行" % summary["rows"]) in text
    assert ("界面条目 %d" % summary["items"]) in text
    assert ("空号默认拥有 %d" % summary["default_owned"]) in text
    # 类别筛选与编辑 tab 同口径
    page.var_catalog_scope.set("附件")
    page._fill_catalog_list()
    assert page.catalog_overview_list.listbox.size() == len(
        catalog.search_items("", category="attachment"))
    assert "当前「附件」" in page.catalog_count.cget("text")
    page.var_catalog_scope.set("仅空号默认拥有")
    page._fill_catalog_list()
    assert page.catalog_overview_list.listbox.size() == summary["default_owned"]
    assert page.catalog_overview_list.listbox.size() > 0
    assert all("默认已有" in label
               for label in page.catalog_overview_list.listbox.get(0, "end"))
    page.var_catalog_scope.set("仅目录外（可追加）")
    page._fill_catalog_list()
    extra_labels = list(page.catalog_overview_list.listbox.get(0, "end"))
    assert extra_labels and all("目录缺" in label for label in extra_labels)
    assert any("Shear" in label for label in extra_labels)     # 研究线未上架武器
    # 只读：切 tab / 重填列表不产生 profile 改动
    page.var_catalog_scope.set("全部")
    page._fill_catalog_list()
    dirty_before = app.dirty
    add_before = len((app.profile.get("items") or {}).get("add") or [])
    page.nb.select(5)
    page._on_tab_changed()
    page.nb.select(4)
    page._on_tab_changed()
    assert app.dirty == dirty_before
    assert len((app.profile.get("items") or {}).get("add") or []) == add_before


def test_inventory_search_keeps_category_filter(inv_page):
    """关键词搜索也不能越界：附件 tab 搜 grip 有结果，外观 tab 搜 grip 必须为空。"""
    page = inv_page
    page._keywords["attachments"].set("grip")
    page._search_items("attachments")
    assert page._lists["attachments"].listbox.size() > 0
    page._keywords["cosmetics"].set("grip")
    page._search_items("cosmetics")
    assert page._lists["cosmetics"].listbox.size() == 0


def test_inventory_add_rejects_cross_category(inv_page, app):
    """兜底：万一列表被塞进异类条目，也不许写进错类别的 profile 列表。"""
    page = inv_page
    attachment_mix, attachment_label = page.app.catalogs.search_items(
        "", limit=1, category="attachment")[0]
    page._lists["cosmetics"].set_items([(attachment_mix, attachment_label)])
    page._lists["cosmetics"].listbox.selection_set(0)
    page._add_item("cosmetics")
    assert app.profile["inventory"].get("cosmetics") in (None, [])
    text, error = app.last_toast()
    assert error and "附件" in text


def test_inventory_catalog_add_dedup(inv_page, app):
    page = inv_page
    page.catalog_list.listbox.selection_set(0)
    mix = page.catalog_list.get_selected()
    page.var_template.set("2797466032")
    page._add_catalog_item()
    assert app.profile["items"]["template"] == 2797466032
    assert app.profile["items"]["add"] == [mix]
    page._add_catalog_item()                   # int 不重复
    assert app.profile["items"]["add"] == [mix]
    page._del_catalog_item(0)
    assert app.profile["items"]["add"] == []


def test_inventory_clear_all_added_removes_everything(inv_page, app, monkeypatch):
    """一键清空：四类库存行 + 目录追加全撤（附件批量加整把武器后不必逐条删）。

    附件是「武器 × 附件」粒度：一把枪批量添加一次几十条，最多 1455 条。本按钮是
    「全部撤回」语义 —— 库存四类清空 + 目录追加清空，template 这类标量设置保留。
    """
    page = inv_page
    gallery = page.app.catalogs.attachment_groups()
    _pid, _name, items = gallery[0]
    page._weapon_lists["attachments"].listbox.selection_set(0)
    page._weapon_lists["attachments"]._on_select()
    page._add_item("attachments")                       # 批量加整把武器的配件
    assert len(app.profile["inventory"]["attachments"]) == len(items) > 0
    weapon_mix = page.app.catalogs.search_items("", category="weapon")[0][0]
    page._append_inventory_row("weapons", weapon_mix, 1)
    page.catalog_list.listbox.selection_set(0)
    page.var_template.set("2797466032")
    page._add_catalog_item()                            # 目录追一条
    assert app.profile["inventory"]["weapons"] and app.profile["items"]["add"]
    # 取消：一条也不改
    monkeypatch.setattr("hd2proxy.gui.pages.inventory.messagebox.askyesno",
                        lambda *a, **k: False)
    page._clear_all_added()
    assert app.profile["inventory"]["weapons"]
    assert app.profile["inventory"]["attachments"]
    assert app.profile["items"]["add"]
    # 确认：库存四类 + 目录追加全部清空
    monkeypatch.setattr("hd2proxy.gui.pages.inventory.messagebox.askyesno",
                        lambda *a, **k: True)
    dirty_before = app.dirty
    page._clear_all_added()
    for key, _label in (("weapons", "武器"), ("attachments", "附件"),
                        ("cosmetics", "外观"), ("stratagems", "战备")):
        assert app.profile["inventory"][key] == [], key
    assert app.profile["items"]["add"] == []
    assert app.profile["items"]["template"] == 2797466032       # 标量设置保留
    assert app.dirty > dirty_before
    text, error = app.last_toast()
    assert not error and "已清空全部已添加项" in text
    assert "武器 0" in page.sum_lbl.cget("text")


def test_inventory_clear_all_added_when_empty_toasts_error(inv_page, app):
    """没有已添加项时点按钮：明确提示，不弹确认框、不标脏。"""
    page = inv_page
    app.profile["inventory"] = {}
    app.profile.setdefault("items", {})["add"] = []
    dirty_before = app.dirty
    page._clear_all_added()
    text, error = app.last_toast()
    assert error and "没有已添加项" in text
    assert app.dirty == dirty_before


# ---------------------------------------------------------------- CapturePage


@pytest.fixture()
def cap_page(root, app):
    page = _make(CapturePage, root, app)
    page.refresh()
    return page


def test_capture_sync_and_apply(cap_page, app):
    page = cap_page
    assert page.var_paths.get() == "api/"     # 默认响应白名单
    page.var_enabled.set(True)
    page.var_paths.set("api/, api/WarSeason/801/Status")
    page.var_planet.set(True)
    cap = page._sync_capture()
    assert cap["enabled"] is True and cap["planet_settings"] is True
    assert app.profile["capture"]["paths"] == ["api/", "api/WarSeason/801/Status"]
    assert app.dirty >= 1
    page._apply_capture()                     # 引擎未运行：只提示，不炸
    assert app.last_toast()[1] is True
    assert app.client.calls == []
    app.client.running_flag = True
    page._apply_capture()                     # 引擎运行：推给控制面
    assert app.client.calls and app.client.calls[0][0] is True


def test_capture_on_logs_incremental_and_capped(cap_page):
    page = cap_page
    page.on_logs(["a", "b"])
    page.on_logs(["a", "b", "c"])              # 尾窗口变长：只追加 c
    assert page.log_text.text.get("1.0", "end-1c") == "a\nb\nc\n"
    page.on_logs(["b", "c"])                   # 旧窗口：不重复追加
    assert page.log_text.text.get("1.0", "end-1c") == "a\nb\nc\n"
    page.on_logs(["l%d" % i for i in range(500)])
    visible = int(page.log_text.text.index("end-1c").split(".")[0]) - 1
    assert visible == 400                      # 最多保留 400 行
    assert page.log_text.text.get("1.0", "1.end") == "l100"
    assert page.log_text.text.get("%d.0" % visible, "%d.end" % visible) == "l499"
    page._clear_log()
    assert page.log_text.text.get("1.0", "end-1c") == ""


def test_capture_status_rewrites_table(cap_page):
    page = cap_page
    page.on_status(MINIMAL_STATUS)
    rows = [page.events.item(i)["values"] for i in page.events.get_children()]
    assert rows == [["19:00:00", "status", "planet 76 +2"]]
    page.on_status(None)
    assert page.events.get_children() == ()
    assert "未运行" in page.engine_lbl.cget("text")


# ---- 目录缺失物品：库存行必须与目录行成对（2026-11-17 用户报「Shear 解锁不生效」）--------
SHEAR_MIX = 2112173638          # LAS-22 Shear：服务端目录里没有
SHEAR_TEMPLATE = 3866352840     # 研究线 M4 实机验证过的同族模板 itemId
BOLT_PISTOL_MIX = 3271863995    # 目录里本来就有：只注库存行即可


def _select_only(page, key, mix):
    page._lists[key].set_items([(mix, page.app.catalogs.item_label(mix))])
    page._lists[key].listbox.selection_set(0)


def test_inventory_add_catalog_missing_weapon_pairs_catalog_row(inv_page, app):
    page = inv_page
    _select_only(page, "weapons", SHEAR_MIX)
    page._add_item("weapons")
    assert app.profile["inventory"]["weapons"] == [
        {"mixId": SHEAR_MIX, "amount": 1, "isDiscovered": False}]
    # 关键断言：目录行自动配对（之前只写库存行 → 游戏里不显示）
    assert app.profile["items"]["add"] == [{"id": SHEAR_MIX, "template": SHEAR_TEMPLATE}]
    text, error = app.last_toast()
    assert not error and "模板" in text


def test_inventory_add_released_weapon_does_not_add_catalog_row(inv_page, app):
    page = inv_page
    _select_only(page, "weapons", BOLT_PISTOL_MIX)
    page._add_item("weapons")
    assert app.profile["inventory"]["weapons"][0]["mixId"] == BOLT_PISTOL_MIX
    assert app.profile["items"]["add"] == []       # 目录已有 → 不写多余目录行


def test_inventory_remove_catalog_missing_weapon_drops_paired_row(inv_page, app):
    page = inv_page
    _select_only(page, "weapons", SHEAR_MIX)
    page._add_item("weapons")
    assert app.profile["items"]["add"] == [{"id": SHEAR_MIX, "template": SHEAR_TEMPLATE}]
    page._remove_row("weapons", 0)
    assert app.profile["inventory"]["weapons"] == []
    assert app.profile["items"]["add"] == []       # 与添加对称：移除库存行时撤掉配对的目录行


def test_catalog_add_tab_uses_unlock_template(inv_page, app):
    page = inv_page
    page.catalog_list.set_items([(SHEAR_MIX, page.app.catalogs.item_label(SHEAR_MIX))])
    page.catalog_list.listbox.selection_set(0)
    page._add_catalog_item()                       # 不设全局模板，也应带上配对模板
    assert app.profile["items"]["add"] == [{"id": SHEAR_MIX, "template": SHEAR_TEMPLATE}]


def test_inventory_refresh_heals_old_profile_without_catalog_row(inv_page, app):
    """升级前的老 profile：库存里有 Shear 但 items.add 为空 —— 打开本页应自动补齐目录行。"""
    page = inv_page
    app.profile.setdefault("inventory", {})["weapons"] = [
        {"mixId": SHEAR_MIX, "amount": 1, "isDiscovered": False}]
    app.profile.pop("items", None)
    page.refresh()
    assert app.profile["items"]["add"] == [{"id": SHEAR_MIX, "template": SHEAR_TEMPLATE}]
    page.refresh()                                  # 幂等：不会重复补
    assert app.profile["items"]["add"] == [{"id": SHEAR_MIX, "template": SHEAR_TEMPLATE}]


# ---- 变种词条 / 全局效果 / 星球词条：3 行小列表 -> 下拉选择器（2026-11-17 用户要求）--------
def _key_event(keysym="a"):
    from types import SimpleNamespace
    return SimpleNamespace(keysym=keysym)


def test_status_dropdowns_list_all_entries(root, app):
    page = _make(StatusPage, root, app)
    assert page.variant_dd._labels == [label for _k, label in app.catalogs.variant_entries()]
    assert len(page.global_dd._labels) == len(app.catalogs.effect_entries()) > 50
    assert page.pe_dd._labels == page.global_dd._labels
    assert "共 %d 条" % len(page.variant_dd._labels) in page.variant_dd.count.cget("text")


def test_status_dropdown_filters_on_typing(root, app):
    page = _make(StatusPage, root, app)
    dd = page.variant_dd
    total = len(dd._labels)
    dd.var.set("掠食")
    dd._on_key(_key_event())
    shown = list(dd.box.cget("values"))
    assert 0 < len(shown) < total and all("掠食" in v for v in shown)
    assert "共" not in dd.count.cget("text") or "/" in dd.count.cget("text")
    dd.var.set("")                              # 清空关键词 -> 恢复全量
    dd._on_key(_key_event("BackSpace"))
    assert len(dd.box.cget("values")) == total


def test_status_dropdown_pick_sets_ids_hint(root, app):
    page = _make(StatusPage, root, app)
    page.variant_dd.select_index(0)
    name = page.variant_dd.get()
    assert name and page._sel_variant == name
    assert "ids" in page.variant_ids_lbl.cget("text")


def test_status_editors_grow_with_rows(root, app):
    """5 个变种/效果时表要显示 5 行（原来固定 2 行 → 用户只看到 2 条）。"""
    page = _make(StatusPage, root, app)
    names = [name for name, _label in app.catalogs.variant_entries()][:5]
    app.profile["status"]["variants"] = [{"name": n, "planets": [100]} for n in names]
    page._render_variants()
    assert len(page.variant_editor.tv.get_children()) == 5
    assert int(page.variant_editor.tv.cget("height")) == 5
    app.profile["status"]["globalEffects"] = {"1501113": [1243, 1245, 1276, 1400, 1401]}
    page._render_global()
    assert int(page.global_editor.tv.cget("height")) == 5
    app.profile["status"]["planet_effects"] = [{"index": 100 + i, "ids": [1243]} for i in range(5)]
    page._render_planet_effects()
    assert int(page.pe_editor.tv.cget("height")) == 5


def test_status_editors_shrink_back_to_two_rows(root, app):
    page = _make(StatusPage, root, app)
    app.profile["status"]["variants"] = []
    page._render_variants()
    assert int(page.variant_editor.tv.cget("height")) == 2


# ---------------------------------------------------------------- P0：端口诊断 / 系统自检
def _diag_snapshot(**over):
    snap = {"listen_setting": "auto", "listen_ip": "100.67.169.17", "listen_error": None,
            "primary_ip": "100.67.169.17", "ports": [], "engine_running": True,
            "engine_pids": [1], "hosts": {"state": "ok", "line": "x", "ip": "100.67.169.17",
                                          "commented": False, "expected_ip": "100.67.169.17"},
            "cert": {"usable": True, "remaining_hours": 40.0, "thumbprint": "AB", "warnings": []},
            "game_running": False, "admin": False}
    snap.update(over)
    return snap


def test_overview_shows_diag_warning_and_hides_when_clean(root, app, monkeypatch):
    from hd2proxy.engine import diagnostics as diag_mod

    errors = {"ok": False, "errors": [{"level": "error", "text": "hosts 那一行被注释掉了"}],
              "warnings": [{"level": "error", "text": "hosts 那一行被注释掉了"}]}
    monkeypatch.setattr(diag_mod, "collect", lambda *a, **k: _diag_snapshot())
    monkeypatch.setattr(diag_mod, "evaluate", lambda snap: errors)
    page = _make(OverviewPage, root, app)
    page.refresh()
    assert page._warn_shown is True
    assert "hosts 那一行被注释掉了" in page.warn_lbl.cget("text")

    clean = {"ok": True, "errors": [], "warnings": []}
    monkeypatch.setattr(diag_mod, "evaluate", lambda snap: clean)
    page._diag_at = 0.0                    # 模拟已过节流窗口（真实切页间隔 >2.5s）
    page.refresh()
    assert page._warn_shown is False


def test_overview_diag_throttles_repeated_refresh(root, app, monkeypatch):
    """切页/切标签会连着 refresh：2.5 秒内只算一次，否则每次切「总览」都卡一下。"""
    from hd2proxy.engine import diagnostics as diag_mod

    calls = []

    def fake_collect(*args, **kwargs):
        calls.append(1)
        return _diag_snapshot()

    monkeypatch.setattr(diag_mod, "collect", fake_collect)
    monkeypatch.setattr(diag_mod, "evaluate", lambda snap: {"ok": True, "errors": [],
                                                            "warnings": []})
    page = _make(OverviewPage, root, app)
    page.refresh()
    page.refresh()
    page.refresh()
    assert len(calls) == 1
    page._diag_at = 0.0                    # 过了节流窗口 -> 重新算
    page.refresh()
    assert len(calls) == 2


# ---------------------------------------------------------------- 证书信任修复（alpha.3）
def _patch_text_dialog(monkeypatch):
    """断言不弹真窗口：_TextDialog 换成记录器。"""
    from hd2proxy.gui.pages import overview as overview_mod

    shown = []
    monkeypatch.setattr(overview_mod, "_TextDialog",
                        lambda parent, title, content: shown.append((title, content)))
    return shown


def test_overview_install_real_runs_cli(root, app, monkeypatch):
    from tkinter import messagebox

    from hd2proxy.engine import diagnostics as diag_mod
    _patch_text_dialog(monkeypatch)
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[0]) or True)
    calls = []
    monkeypatch.setattr(app.client, "run_cli",
                        lambda args: calls.append(list(args)) or (0, "INSTALL-OUT"))
    monkeypatch.setattr(diag_mod, "collect", lambda *a, **k: _diag_snapshot())
    monkeypatch.setattr(diag_mod, "evaluate",
                        lambda snap: {"ok": True, "errors": [], "warnings": []})
    page = _make(OverviewPage, root, app)
    page._install_real()
    assert asked == ["安装 / 修复"]
    assert calls and calls[0][:2] == ["install", "--profile"]
    assert "--cert-dir" in calls[0]
    assert page._diag_at > 0            # 安装后强制重算现场检查


def test_overview_install_real_cancel_does_nothing(root, app, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(app.client, "run_cli", lambda args: calls.append(list(args)) or (0, ""))
    page = _make(OverviewPage, root, app)
    page._install_real()
    assert calls == []


def test_overview_renew_offers_install_trust_once(root, app, monkeypatch):
    """续期换了 CA 且未受信 → 只弹一次确认（不要连问两遍），随后调用 install。"""
    from tkinter import messagebox

    from hd2proxy.engine import certs as certs_mod
    _patch_text_dialog(monkeypatch)
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[0]) or True)
    monkeypatch.setattr(certs_mod, "cert_status",
                        lambda *a, **k: {"exists": True, "trusted": False})
    calls = []
    monkeypatch.setattr(app.client, "run_cli",
                        lambda args: calls.append(list(args)) or (0, "OUT"))
    page = _make(OverviewPage, root, app)
    page._offer_install_trust()
    assert asked == ["新证书还没安装信任"]
    assert calls and calls[0][:2] == ["install", "--profile"]


def test_overview_renew_skips_install_when_trusted(root, app, monkeypatch):
    from tkinter import messagebox

    from hd2proxy.engine import certs as certs_mod
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[0]) or True)
    monkeypatch.setattr(certs_mod, "cert_status",
                        lambda *a, **k: {"exists": True, "trusted": True})
    calls = []
    monkeypatch.setattr(app.client, "run_cli", lambda args: calls.append(list(args)) or (0, ""))
    page = _make(OverviewPage, root, app)
    page._offer_install_trust()
    assert asked == [] and calls == []


def test_overview_renew_then_installs_trust(root, app, monkeypatch):
    """完整链路：certs renew 成功 → 发现未受信 → 自动走 install。"""
    from tkinter import messagebox

    from hd2proxy.engine import certs as certs_mod
    _patch_text_dialog(monkeypatch)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(certs_mod, "cert_status",
                        lambda *a, **k: {"exists": True, "trusted": False})
    calls = []
    monkeypatch.setattr(app.client, "run_cli",
                        lambda args: calls.append(list(args)) or (0, "OK"))
    page = _make(OverviewPage, root, app)
    page._renew_cert()
    assert calls[0][:2] == ["certs", "renew"]
    assert calls[1][:2] == ["install", "--profile"]


def test_overview_selfcheck_opens_text_dialog(root, app, monkeypatch):
    from hd2proxy.engine import diagnostics as diag_mod
    monkeypatch.setattr(diag_mod, "collect", lambda *a, **k: _diag_snapshot())
    monkeypatch.setattr(diag_mod, "evaluate", lambda snap: {"ok": True, "errors": [],
                                                            "warnings": []})
    monkeypatch.setattr(diag_mod, "format_text", lambda snap, ev=None: "SELFCHECK-TEXT")
    page = _make(OverviewPage, root, app)
    page._selfcheck()
    assert app.texts and app.texts[-1][0] == "系统自检"
    assert "SELFCHECK-TEXT" in app.texts[-1][1]


def test_settings_choose_listen_ip_updates_profile(root, app, monkeypatch):
    from hd2proxy.gui import listen_ip as listen_ip_ui
    monkeypatch.setattr(listen_ip_ui, "choose_listen_ip",
                        lambda parent, a: "192.168.1.5")
    page = _make(SettingsPage, root, app)
    page.refresh()
    page._choose_listen()
    assert page.var_listen.get() == "192.168.1.5"
    assert app.profile["proxy"]["listen_ip"] == "192.168.1.5"
    assert app.dirty >= 1


def test_port_conflict_dialog_builds_and_returns(root, app):
    """回归：对话框必须真能显示（曾因 tk.Label 用元组 pady 抛 TclError → 只剩空壳窗口）。"""
    from hd2proxy.gui import listen_ip as listen_ip_ui
    pre = {"listen_ip": "100.67.169.17", "conflicts": [{
        "role": "代理", "port": 443, "state": "conflict", "wildcard": False,
        "owners": [{"pid": 14920, "name": "python.exe", "addr": "100.67.169.17:443",
                    "path": "x", "wildcard": False}]}]}

    def close():
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.title() == "端口被占用":
                child.destroy()

    root.after(300, close)
    assert listen_ip_ui.port_conflict_dialog(root, app, pre) == "cancel"


def test_choose_listen_ip_dialog_builds(root, app, monkeypatch):
    """回归：换监听地址对话框同样要能显示；取消时返回 None 且不改 profile。"""
    from hd2proxy.engine import diagnostics as diag_mod
    from hd2proxy.gui import listen_ip as listen_ip_ui
    monkeypatch.setattr(diag_mod, "listen_candidates", lambda profile: [
        {"ip": "100.67.169.17", "interface": "以太网", "is_virtual": False,
         "is_primary": True, "state": "free", "wildcard": False, "owners": [],
         "recommended": True}])

    def close():
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.title() == "换监听地址":
                child.destroy()

    root.after(300, close)
    assert listen_ip_ui.choose_listen_ip(root, app) is None
    assert app.profile["proxy"]["listen_ip"] == "auto"


# ---------------------------------------------------------------- 实时战况页（0.4.3）

def test_live_page_registered():
    from hd2proxy.gui.app import PAGE_DEFS
    rows = {key: (icon, label) for key, icon, label in PAGE_DEFS}
    assert "live" in rows
    assert rows["live"][1] == "实时战况"


def _live_snapshot():
    import json
    from pathlib import Path
    from hd2proxy.engine import live
    sample = Path(__file__).resolve().parents[2] / "data" / "samples" / "status.json"
    status = json.loads(sample.read_text(encoding="utf-8"))
    gwe = [{"id": 1}]
    return {
        "schema": 1, "host": "api.example", "ip": "1.2.3.4", "war_id": 801,
        "fetched_at": "2026-11-20T13:00:00+08:00", "elapsed": 0.1,
        "status": status, "gwe": gwe,
        "summary": live.summarize(status, gwe),
        "targets": live.campaign_targets(status),
    }


def test_live_page_renders_snapshot(root, app):
    page = _make(LivePage, root, app)
    snap = _live_snapshot()
    page._render(snap)
    assert page.card_war[1].cget("text") == "war 801"
    assert page.card_gwe[1].cget("text") == "1"
    assert len(page.targets.get_children()) == len(snap["status"]["campaigns"])
    # 星球效果表：sample 里有 planetActiveEffects，按星球聚合后至少 1 行
    assert len(page.effects.get_children()) >= 1
    assert page._effect_rows
    # 过滤不命中 -> 空表，但重绘不抛异常
    page.var_filter.set("no-such-planet-xyz")
    page._render_effects()
    assert page.effects.get_children() == ()
    page.var_filter.set("")
    page._render_effects()
    assert len(page.effects.get_children()) >= 1


def test_live_page_save_without_snapshot_warns(root, app):
    page = _make(LivePage, root, app)
    page.save_snapshot()
    assert app.last_toast()[1] is True          # error=True
