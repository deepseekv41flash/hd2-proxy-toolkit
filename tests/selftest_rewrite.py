"""改写逻辑的离线自检：起一个本地假上游，验证代理真的改了 /Status。

不需要游戏、不需要联网、不需要管理员。

  py tools\\selftest_rewrite.py
"""

import gzip
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 绝不碰正在用的 runtime/、logs/：面板的“一键自检”会给子进程设 VMOD_DATA=<临时目录>
BASE = Path(os.environ["VMOD_DATA"]) if os.environ.get("VMOD_DATA") else ROOT
CERT_DIR = Path(os.environ.get("HD2PROXY_TEST_CERTS") or (ROOT / "certs"))
PROXY = ROOT / "src" / "hd2proxy" / "engine" / "legacy_proxy.py"
CATALOG = ROOT / "data" / "legacy" / "variant_catalog.json"
HOST = "api.live.prod.thehelldiversgame.com"
TEST_PORT = 8444
UP_PORT = 9099

STATUS_JSON = {
    "warId": 801,
    "planetStatus": [{"index": 100, "owner": 2}],
    "planetActiveEffects": [{"index": 100, "galacticEffectId": 1195}],
}

calls = []


def fake_upstream():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", UP_PORT))
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                c = conn.recv(4096)
                if not c:
                    break
                buf += c
            first = buf.split(b"\r\n")[0].decode("latin-1")
            calls.append(first)
            body = gzip.compress(json.dumps(STATUS_JSON).encode())  # 模拟真实的 gzip 响应
            head = ("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    "Content-Encoding: gzip\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                    % len(body))
            conn.sendall(head.encode() + body)
        finally:
            conn.close()


def client_get(port, path, cafile):
    ctx = ssl.create_default_context(cafile=str(cafile))
    raw = socket.create_connection(("127.0.0.1", port), timeout=15)
    tls = ctx.wrap_socket(raw, server_hostname=HOST)
    tls.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
                 % (path, HOST)).encode())
    buf, need = b"", None
    while True:
        c = tls.recv(65536)
        if not c:
            break
        buf += c
        if need is None and b"\r\n\r\n" in buf:
            head, _, body = buf.partition(b"\r\n\r\n")
            for line in head.decode("latin-1", "replace").lower().split("\r\n"):
                if line.startswith("content-length:"):
                    need = len(body) + int(line.split(":", 1)[1].strip())
            if need is None:
                need = len(body)
        if need is not None and len(buf) >= need:
            break
    tls.close()
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1", "replace"), body


def main():
    anchor = CERT_DIR / "anchor.pem"
    if not anchor.exists():
        print("FAIL: certs 目录里没有 anchor.pem（先跑 gen_session_certs.py）")
        return 1

    threading.Thread(target=fake_upstream, daemon=True).start()
    time.sleep(0.3)

    cfg = {
        "host": HOST, "listenIp": "127.0.0.1", "allowLoopback": True,
        "port": TEST_PORT,
        "upstreamTest": "127.0.0.1:%d" % UP_PORT,
        "passthrough": False,
        "allowDevFlags": False, "crlPort": 0,
        "targets": [{"planet": 100, "variant": "掠食"}],
    }
    cfg_path = BASE / "logs" / "selftest_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    runtime = BASE / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "selection.json").write_text(json.dumps({
        "enabled": True, "variants": ["掠食变种"]
    }, ensure_ascii=False), encoding="utf-8")
    (runtime / "stratagems.json").write_text(json.dumps({
        # The fourth id proves the proxy applies the same three-item cap as the panel.
        "enabled": True, "ids": [1227, 1263, 1254, 1152]
    }), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(PROXY),
         "--port", str(TEST_PORT), "--config", str(cfg_path),
         "--catalog", str(CATALOG),
         "--cert-dir", str(CERT_DIR)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    ok = 0
    try:
        head, body = client_get(TEST_PORT, "/api/WarSeason/801/Status", anchor)
        status = head.splitlines()[0] if head else "(no response)"
        print("  状态行:", status)
        plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        doc = json.loads(plain.decode("utf-8", "replace"))
        ids = [e["galacticEffectId"] for e in doc["planetActiveEffects"] if e["index"] == 100]
        print("  planet 100 的效果 id:", ids)
        trials = [1227, 1263, 1254]
        if 1243 in ids and 1245 in ids and all(i in ids for i in trials) and 1152 not in ids:
            print("  [OK  ] 改写生效（tag+玩法+前3个战备试用 都注入了）")
            ok += 1
        else:
            print("  [FAIL] 改写或三战备上限未生效")
        if 1195 in ids:
            print("  [OK  ] 原有条目没有被破坏")
            ok += 1
        else:
            print("  [FAIL] 原有条目丢失")
        if calls and "/api/WarSeason/801/Status" in calls[-1]:
            print("  [OK  ] 上游收到的路径正确:", calls[-1])
            ok += 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print("RESULT=%s" % ("PASS" if ok == 3 else "FAIL(%d/3)" % ok))
    return 0 if ok == 3 else 2


if __name__ == "__main__":
    sys.exit(main())
