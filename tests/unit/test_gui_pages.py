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
from hd2proxy.gui.pages.inventory import InventoryPage  # noqa: E402
from hd2proxy.gui.pages.status_page import StatusPage  # noqa: E402


# ---------------------------------------------------------------- fake app


class FakeClient:
    """只实现页面用到的引擎客户端面：running / set_capture。"""

    def __init__(self):
        self.running_flag = False
        self.calls = []

    def running(self):
        return self.running_flag

    def set_capture(self, enabled, directory=None):
        self.calls.append((enabled, directory))
        return {"ok": True, "enabled": enabled}


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
    page.variant_list.listbox.selection_set(0)
    name = page.variant_list.get_selected()
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
    page.variant_list.listbox.selection_clear(0, "end")
    page._add_variant()
    assert app.last_toast()[1] is True
    assert app.profile["status"]["variants"] == []


def test_status_effects_dedup_and_merge(root, app):
    page = _make(StatusPage, root, app)
    page.global_list.listbox.selection_set(0)
    effect = page.global_list.get_selected()
    page._add_global()
    assert app.profile["status"]["globalEffects"] == {"1501113": [effect]}
    page._add_global()                        # 同事件同 effect：去重
    assert app.profile["status"]["globalEffects"] == {"1501113": [effect]}
    page.pe_pick.set(100)
    page.pe_list.listbox.selection_set(1)
    effect2 = page.pe_list.get_selected()
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
    assert app.profile["status"]["variants"] == [{"name": "掠食变种", "planets": [76]}]
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
