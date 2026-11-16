"""GUI 冒烟 + 截图：起一个真引擎（假上游）→ 打开 GUI → 逐页截图 → 退出清理。

既当 M2 的验收证据（5 页绑定真实引擎状态），也当日常看观感的快速工具。

用法：
  python tools/gui_smoke.py                      # 全部页面，截到 research/screenshots/
  python tools/gui_smoke.py --pages overview,status
  python tools/gui_smoke.py --out <dir> --keep   # 保留临时 profile 便于复现

产物：`gui-<page>.png` + `gui-status.json`（当时的 /status 快照）。
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PAGES = ["overview", "status", "inventory", "capture", "settings"]

STATUS_DOC = {
    "warId": 801, "time": 1700000000,
    "planetStatus": [{"index": 100, "owner": 2}, {"index": 200, "owner": 3}],
    "planetActiveEffects": [{"index": 100, "galacticEffectId": 1195}],
    "campaigns": [], "planetAttacks": [], "planetEvents": [], "jointOperations": [],
    "globalEvents": [{"eventId": 1501113, "effectIds": [1]}], "planetRegions": [],
}


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Upstream:
    def __init__(self, port):
        import gzip
        doc = STATUS_DOC

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if "/api/WarSeason/801/Status" in self.path:
                    body = gzip.compress(json.dumps(doc).encode())
                    self.send_response(200)
                    self.send_header("Content-Encoding", "gzip")
                else:
                    body = json.dumps({"id": 801}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def build_profile(tmp: Path, port, crl, control, up_port) -> Path:
    from hd2proxy.engine import certs, config
    prof = config.default_profile(name="演示配置")
    prof["proxy"].update({"listen_ip": "auto", "port": port, "crl_port": crl,
                          "control_port": control, "passthrough": False, "verbose": False})
    prof["cert"].update({"days": 1, "auto_renew": False})
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [100]}]
    prof["status"]["planet_effects"] = [{"index": 76, "ids": [1243, 1245]}]
    prof["status"]["globalEffects"] = {"1501113": [1346]}
    prof["status"]["owner"] = {"158": 1}
    prof["inventory"]["weapons"] = [{"mixId": 2112173638}]
    prof["items"]["add"] = [2112173638]
    prof["capture"].update({"enabled": True, "dir": str(tmp / "captures"),
                            "paths": ["api/"], "planet_settings": True})
    path = tmp / "profile.json"
    config.save_profile_file(path, prof)
    certs.generate_session(tmp / "certs", host=certs.DEFAULT_HOST, days=1, force=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "research" / "screenshots"))
    ap.add_argument("--pages", default=",".join(PAGES))
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    pages = [p.strip() for p in a.pages.split(",") if p.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="hd2proxy-gui-"))
    os.environ["HD2PROXY_STATE"] = str(tmp / "state")
    from hd2proxy.gui import App
    from hd2proxy.gui.client import EngineClient

    up_port, port, crl, control = (free_port() for _ in range(4))
    profile_path = build_profile(tmp, port, crl, control, up_port)
    client = EngineClient()
    cfg_path = tmp / "legacy_cfg.json"
    cfg_path.write_text(json.dumps({"host": "api.live.prod.thehelldiversgame.com",
                                    "upstreamTest": "127.0.0.1:%d" % up_port}),
                        encoding="utf-8")
    import tkinter as tk
    root = tk.Tk()
    root.attributes("-topmost", True)       # 截图时保证窗口在最前（不被 IDE/DSH 挡住）
    shots = []
    with Upstream(up_port):
        client.start_engine(profile_path, tmp / "certs", control_port=control,
                            extra=("--config", str(cfg_path), "--no-auto-renew"))
        if not client.wait_ready(30):
            print("引擎未就绪，日志：")
            print("\n".join(list(client.log_lines)[-20:]))
            client.shutdown()
            root.destroy()
            return 2
        app = App(root, profile_path=profile_path, client=client)
        status_snapshot = {}
        try:
            for page in pages:
                app.show_page(page)
                root.update_idletasks()
                root.lift()
                root.focus_force()
                root.update()
                time.sleep(0.5)
                root.update()
                try:
                    from PIL import ImageGrab
                    x, y = root.winfo_rootx(), root.winfo_rooty()
                    w, h = root.winfo_width(), root.winfo_height()
                    png = out / ("gui-%s.png" % page)
                    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(png)
                    shots.append(str(png))
                    print("screenshot -> %s (%dx%d)" % (png, w, h))
                except Exception as e:      # noqa: BLE001
                    print("screenshot 失败（%s）：%r" % (page, e))
                if not status_snapshot:
                    try:
                        status_snapshot = client.status()
                    except Exception as e:      # noqa: BLE001
                        status_snapshot = {"error": repr(e)}
        finally:
            (out / "gui-status.json").write_text(
                json.dumps(status_snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
            client.shutdown()
            root.destroy()
            if not a.keep:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                print("临时 profile 保留在：%s" % tmp)
    print("shots:", len(shots))
    return 0 if len(shots) == len(pages) else 2


if __name__ == "__main__":
    sys.exit(main())
