"""GUI 核心单测：数据目录、控制面客户端、App 导入与基础冒烟。

页面测试在 tests/unit/test_gui_pages.py（战况/物品/抓包三页）。
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hd2proxy.engine import config, paths
from hd2proxy.gui.catalogs import Catalogs
from hd2proxy.gui.client import EngineClient, EngineError

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- catalogs


def test_catalogs_load_and_query():
    cat = Catalogs()
    s = cat.summary()
    assert s["variants"] >= 20 and s["stratagems"] >= 50
    assert s["effects"] >= 300 and s["planets"] >= 400
    assert s["warnings"] == [], s["warnings"]
    assert cat.build.get("war_id") == 801
    # 变种：正式名与别名都能解析
    v = cat.resolve_variant("掠食变种")
    assert v and v["ids"] == [1243, 1245] and v["faction"] == "terminid"
    assert cat.resolve_variant("掠食") is not None
    assert cat.resolve_variant("不存在的变种") is None
    # 效果 / 星球 / 物品
    assert "1346" in cat.effect_label(1346)
    assert cat.planet_label(100).startswith("100 ·")
    # 行号 ≠ 游戏索引：planets.json 的 index 是 planet_data 行，选择器/写 profile 用 game_index
    assert len(cat.game_planets) >= 250
    assert cat.planet_row(76).get("name") == "TERREK"          # 行 79 的游戏索引是 76
    assert cat.planet_row(76).get("game_index") is None or int(cat.planet_row(76)["game_index"]) == 76
    names = dict(cat.planet_entries())
    assert 76 in names and "TERREK" in names[76]
    assert 100 in names and "TRANDOR" in names[100]
    hits = cat.search_items("everlasting")
    assert hits and "Everlasting" in hits[0][1]
    entries = cat.variant_entries()
    assert entries and all(isinstance(n, str) for n, _l in entries)


def test_catalogs_missing_dir_degrades(tmp_path):
    cat = Catalogs(tmp_path / "nope")
    assert cat.warnings and cat.summary()["variants"] == 0
    assert cat.resolve_variant("掠食变种") is None
    assert cat.search_items("x") == []


# ---------------------------------------------------------------- client


class _FakeEngine:
    """最小控制面：/healthz /status /config(GET/PUT)，带 token 校验。"""

    def __init__(self, token="tok"):
        self.token = token
        self.calls = []
        cfg = config.default_profile(name="fake")

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                return self.headers.get("X-HD2-Token") == token

            def do_GET(self):
                if self.path == "/healthz":
                    return self._send(200, {"ok": True})
                if not self._auth():
                    return self._send(401, {"error": "unauthorized"})
                if self.path == "/status":
                    return self._send(200, {"mode": "rewrite", "profile": "fake",
                                            "listen_ip": "127.0.0.1", "port": 443,
                                            "cert": {"usable": True, "remaining_hours": 5},
                                            "stats": {"req": 3, "rewrite": 2},
                                            "rewrites": [{"ts": "t", "kind": "status",
                                                          "detail": "+2"}]})
                if self.path == "/config":
                    return self._send(200, {"mode": "profile", "profile": cfg,
                                            "path": "x.json"})
                return self._send(404, {})

            def do_PUT(self):
                if not self._auth():
                    return self._send(401, {"error": "unauthorized"})
                n = int(self.headers.get("Content-Length") or 0)
                doc = json.loads(self.rfile.read(n).decode())
                return self._send(200, {"ok": True, "applied": {"hot": True},
                                        "warnings": [], "got": doc.get("name")})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def state(self):
        return {"url": "http://127.0.0.1:%d" % self.port, "token": self.token,
                "pid": 1, "port": self.port}

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_client_roundtrip(tmp_path):
    eng = _FakeEngine()
    try:
        state_file = tmp_path / "engine.json"
        state_file.write_text(json.dumps(eng.state()), encoding="utf-8")
        c = EngineClient(state_file)
        assert c.running() is True
        st = c.status()
        assert st["mode"] == "rewrite" and st["stats"]["rewrite"] == 2
        cfg = c.config()
        assert cfg["mode"] == "profile" and cfg["profile"]["name"] == "fake"
        r = c.put_config(cfg["profile"])
        assert r["ok"] and r["got"] == "fake"
    finally:
        eng.stop()


def test_client_errors(tmp_path):
    c = EngineClient(tmp_path / "missing.json")
    assert c.state() is None and c.running() is False
    with pytest.raises(EngineError):
        c.status()

    eng = _FakeEngine()
    try:
        state = dict(eng.state())
        state["token"] = "wrong"
        state_file = tmp_path / "engine.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        c = EngineClient(state_file)
        with pytest.raises(EngineError, match="401"):
            c.status()
    finally:
        eng.stop()


def test_client_engine_argv_and_cli():
    c = EngineClient()
    argv = c.engine_argv("p.json", "certs", listen_ip="127.0.0.1", control_port=17897,
                         extra=("--no-auto-renew",))
    assert "--profile" in argv and "--cert-dir" in argv
    assert argv[-1] == "--no-auto-renew"
    code, out = c.run_cli(["info"])
    assert code == 0 and '"repo"' in out


# ---------------------------------------------------------------- app


def test_app_importable():
    from hd2proxy.gui.app import PAGE_DEFS, App   # noqa: F401
    assert [p[0] for p in PAGE_DEFS] == ["overview", "status", "inventory",
                                         "capture", "settings"]


def test_app_smoke(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无图形环境")
    root.withdraw()
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path / "state"))
    prof = config.default_profile(name="冒烟")
    path = tmp_path / "profile.json"
    config.save_profile_file(path, prof)
    try:
        from hd2proxy.gui.app import App
        app = App(root, profile_path=path)
        assert app.profile["name"] == "冒烟"
        for page in ("overview", "settings"):
            app.show_page(page)
            root.update_idletasks()
            root.update()
        assert app.current_page == "settings"
    finally:
        root.destroy()


def test_cli_gui_subcommand_exists():
    """CLI 必须有 gui 子命令（--help 即可验证，不打开窗口）。"""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "hd2proxy", "gui", "--help"],
                       cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env={**__import__("os").environ,
                            "PYTHONPATH": str(REPO / "src")})
    assert r.returncode == 0, r.stderr
    assert "--profile" in r.stdout


# ---------------------------------------------------------------- 冻结模式的 CLI 桥

def test_cli_argv_frozen_uses_sibling_cli_exe(tmp_path, monkeypatch):
    """alpha.2 的 bug：冻结后 sys.executable 是 gui exe，直接拼 `[exe, legacy_proxy.py]`
    会弹第二个窗口/证书按钮失效。冻结模式必须改用同目录 hd2proxy.exe。"""
    from hd2proxy.gui import client as gc

    gui = tmp_path / "hd2proxy-gui.exe"
    cli = tmp_path / "hd2proxy.exe"
    gui.write_bytes(b"")
    cli.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert gc.cli_argv(["certs", "renew"]) == [str(cli), "certs", "renew"]
    argv = gc.EngineClient(state_file=tmp_path / "e.json").engine_argv(
        tmp_path / "p.json", tmp_path / "certs", control_port=17897)
    assert argv[0] == str(cli)
    assert argv[1] == "engine"
    assert "--profile" in argv and "--cert-dir" in argv and "--control-port" in argv
    assert str(gc.ENGINE_SCRIPT) not in argv          # 不能再出现源码路径


def test_cli_argv_frozen_without_sibling_falls_back(tmp_path, monkeypatch):
    from hd2proxy.gui import client as gc

    gui = tmp_path / "hd2proxy-gui.exe"
    gui.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(gui))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert gc.cli_argv(["info"]) == [str(gui), "info"]


def test_cli_argv_source_mode_keeps_python_m(monkeypatch):
    from hd2proxy.gui import client as gc

    monkeypatch.delattr(sys, "frozen", raising=False)
    argv = gc.cli_argv(["info"])
    assert argv[1:3] == ["-m", "hd2proxy"]
    assert argv[-1] == "info"


# ---------------------------------------------------------------- 子进程输出编码

def test_decode_output_utf8_bytes():
    from hd2proxy.gui.client import decode_output
    assert decode_output("安装计划".encode("utf-8")) == "安装计划"
    assert decode_output(b"") == ""
    assert decode_output(None) == ""
    assert decode_output("已经是文本") == "已经是文本"


def test_decode_output_gbk_bytes_falls_back():
    """冻结版 PyInstaller exe 的 stdout 是控制台代码页（中文 Windows = cp936），
    PYTHONUTF8/PYTHONIOENCODING 对冻结进程无效（实测四种组合字节相同）→ 必须回退 GBK，
    否则 GUI 里「安装计划」会显示成一串 ？。"""
    from hd2proxy.gui.client import decode_output

    text = "== 安装计划（dry-run，不改系统）==\n  1. 监听地址：100.67.169.17（可用）\n"
    assert decode_output(text.encode("gbk")) == text


def test_run_cli_decodes_gbk_output(monkeypatch, tmp_path):
    """run_cli 用原始字节 + decode_output，不能让 GBK 输出变成 U+FFFD。"""
    import subprocess as sp

    from hd2proxy.gui import client as gc

    fake = sp.CompletedProcess(args=["x"], returncode=0,
                               stdout="已保存：默认".encode("gbk"), stderr=b"")

    monkeypatch.setattr(gc.subprocess, "run", lambda *a, **k: fake)
    code, out = gc.EngineClient(state_file=tmp_path / "e.json").run_cli(["profiles", "list"])
    assert code == 0
    assert "已保存" in out and "\ufffd" not in out


# ---------------------------------------------------------------- 打开文件/目录

def test_open_path_missing_gives_friendly_toast(tmp_path):
    from hd2proxy.gui.openutil import open_path

    msgs = []
    ok = open_path(tmp_path / "nope.log", lambda m, error=False: msgs.append((m, error)),
                   label="日志文件")
    assert ok is False
    assert msgs and msgs[0][1] is True
    assert "还不存在" in msgs[0][0] and "日志文件" in msgs[0][0]


def test_open_path_existing_calls_startfile(tmp_path, monkeypatch):
    from hd2proxy.gui import openutil

    f = tmp_path / "ok.log"
    f.write_text("x", encoding="utf-8")
    called = []
    monkeypatch.setattr(openutil.os, "startfile", lambda p: called.append(p), raising=False)
    assert openutil.open_path(f, lambda *a, **k: None, label="日志文件") is True
    assert called == [str(f)]


# ---------------------------------------------------------------- 冻结版日志目录可写

def test_paths_frozen_puts_logs_under_state_dir(tmp_path, monkeypatch):
    """打包版 exe 可能被放到只读目录（Program Files / 只读盘）；logs/runtime 必须落在
    可写的状态目录，否则引擎日志静默丢失、GUI「打开日志」永远找不到文件。"""
    import importlib

    from hd2proxy.engine import paths as paths_mod

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("VMOD_DATA", raising=False)
    monkeypatch.delenv("HD2PROXY_STATE", raising=False)
    try:
        reloaded = importlib.reload(paths_mod)
        state = tmp_path / "LocalAppData" / "HD2ProxyStudio"
        assert reloaded.LOGDIR == state / "logs"
        assert reloaded.PROXY_LOG == state / "logs" / "proxy.log"
        assert reloaded.RUNTIME == state / "runtime"
    finally:
        monkeypatch.undo()
        importlib.reload(paths_mod)


def test_paths_source_mode_keeps_repo_logs():
    """源码模式不能跟着冻结版改：开发者要看仓库里的 logs/。"""
    from hd2proxy.engine import paths as paths_mod

    if getattr(sys, "frozen", False):
        pytest.skip("frozen")
    assert paths_mod.LOGDIR == paths_mod.REPO_ROOT / "logs"
