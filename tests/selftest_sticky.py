"""粘性星球自检：切星球不会把已经注入的星球弄丢。

场景重现（这正是之前担心的 bug）：
  1. 玩家选了 A（lobby planetId=100），Status 里有 A；
  2. 玩家切到 B（planetId=268），再拉 Status —— A 不应该消失；
  3. 玩家再回 A，A 仍然有变种。

跑法：py tools\\selftest_sticky.py
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
TEST_PORT = 8445
UP_PORT = 9098
SELECTION = BASE / "runtime" / "selection.json"

STATUS_JSON = {
    "warId": 801,
    "planetStatus": [{"index": i, "owner": 2} for i in (1, 100, 268, 300, 301)],
    "planetActiveEffects": [{"index": 1, "galacticEffectId": 1195}],
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
            head, _, rest = buf.partition(b"\r\n\r\n")
            text = head.decode("latin-1")
            first = text.split("\r\n")[0]
            calls.append(first)
            need = 0
            for line in text.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    need = int(line.split(":", 1)[1].strip())
            while len(rest) < need:
                c = conn.recv(4096)
                if not c:
                    break
                rest += c
            if first.startswith("POST") or first.startswith("PUT"):
                body = b'{"ok":true}'
                conn.sendall(("HTTP/1.1 202 Accepted\r\nContent-Length: %d\r\n"
                              "Connection: close\r\n\r\n" % len(body)).encode() + body)
            else:
                body = gzip.compress(json.dumps(STATUS_JSON).encode())
                conn.sendall(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                              "Content-Encoding: gzip\r\nContent-Length: %d\r\n"
                              "Connection: close\r\n\r\n" % len(body)).encode() + body)
        finally:
            conn.close()


def call(port, method, path, cafile, body=None):
    ctx = ssl.create_default_context(cafile=str(cafile))
    raw = socket.create_connection(("127.0.0.1", port), timeout=15)
    tls = ctx.wrap_socket(raw, server_hostname=HOST)
    head = "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n" % (method, path, HOST)
    data = b""
    if body is not None:
        data = json.dumps(body).encode()
        head += "Content-Type: application/json\r\nContent-Length: %d\r\n" % len(data)
    tls.sendall(head.encode() + b"\r\n" + data)
    buf, need = b"", None
    while True:
        c = tls.recv(65536)
        if not c:
            break
        buf += c
        if need is None and b"\r\n\r\n" in buf:
            h, _, b = buf.partition(b"\r\n\r\n")
            for line in h.decode("latin-1").lower().split("\r\n"):
                if line.startswith("content-length:"):
                    need = len(b) + int(line.split(":", 1)[1].strip())
            if need is None:
                need = len(b)
        if need is not None and len(buf) >= need:
            break
    tls.close()
    h, _, b = buf.partition(b"\r\n\r\n")
    return h.decode("latin-1"), b


def planets_in(body):
    plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    doc = json.loads(plain.decode("utf-8", "replace"))
    return sorted({e["index"] for e in doc["planetActiveEffects"] if e["galacticEffectId"] in (1243, 1245, 1306, 1309)})


def main():
    anchor = CERT_DIR / "anchor.pem"
    if not anchor.exists():
        print("FAIL: 没有 certs/anchor.pem，先跑 gen_session_certs.py")
        return 1
    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    SELECTION.write_text(json.dumps({"enabled": True, "variants": ["掠食变种"]},
                                    ensure_ascii=False), encoding="utf-8")

    threading.Thread(target=fake_upstream, daemon=True).start()
    time.sleep(0.3)

    cfg = {"host": HOST, "port": TEST_PORT, "upstreamTest": "127.0.0.1:%d" % UP_PORT,
           "passthrough": False, "allowDevFlags": False, "crlPort": 0, "targets": []}
    cfg_path = BASE / "logs" / "selftest_sticky_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(PROXY), "--port", str(TEST_PORT),
         "--config", str(cfg_path), "--catalog", str(CATALOG),
         "--cert-dir", str(CERT_DIR)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    ok = 0
    try:
        call(TEST_PORT, "PUT", "/api/lobby", anchor, body={"planetId": 100})
        time.sleep(0.3)
        _, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        p1 = planets_in(body)
        print("  选 A(100) 后注入星球:", p1)
        if 100 in p1:
            print("  [OK  ] A 有变种")
            ok += 1
        else:
            print("  [FAIL] A 没有变种")

        call(TEST_PORT, "PUT", "/api/lobby", anchor, body={"planetId": 268})
        time.sleep(0.3)
        _, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        p2 = planets_in(body)
        print("  切到 B(268) 后注入星球:", p2)
        if 100 in p2 and 268 in p2:
            print("  [OK  ] 切走后 A 仍在（粘性生效）")
            ok += 1
        else:
            print("  [FAIL] 切走后 A 丢了")

        call(TEST_PORT, "POST", "/api/Operation/Mission/Start", anchor,
             body={"planetIndex": 100})
        time.sleep(0.3)
        _, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        p3 = planets_in(body)
        print("  进 A 任务后注入星球:", p3)
        if 100 in p3:
            print("  [OK  ] 想进的那颗始终有变种")
            ok += 1
        else:
            print("  [FAIL] 想进的星球没有变种")

        # 上限 3：再摸两颗，最早的应被挤掉
        for pi in (300, 301):
            call(TEST_PORT, "PUT", "/api/lobby", anchor, body={"planetId": pi})
            time.sleep(0.25)
        _, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        p4 = planets_in(body)
        print("  上限检查（摸过 100/268/300/301）:", p4)
        if len(p4) <= 3 and 100 not in p4 and 301 in p4:
            print("  [OK  ] 上限 3 生效（最早的被挤掉，最新保留）")
            ok += 1
        else:
            print("  [FAIL] 上限不符合预期")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            SELECTION.write_text(json.dumps({"enabled": False, "variants": []}), encoding="utf-8")
        except Exception:
            pass

    print("RESULT=%s" % ("PASS" if ok == 4 else "FAIL(%d/4)" % ok))
    return 0 if ok == 4 else 2


if __name__ == "__main__":
    sys.exit(main())
