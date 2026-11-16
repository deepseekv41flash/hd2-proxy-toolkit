"""GUI 核心单测：数据目录、控制面客户端、App 导入与基础冒烟。

页面测试在 tests/unit/test_gui_pages.py（战况/物品/抓包三页）。
"""

import json
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
