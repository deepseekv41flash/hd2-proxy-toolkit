"""改写 + 热重载 + 跟随星球的离线自检（不需要游戏/联网/管理员）。

流程：
  1. 起本地假上游（明文 HTTP），返回 gzip 的 Status；
  2. 起代理（测试端口），config 里写死 planet 100 -> 掠食；
  3. 客户端发 POST /api/lobby（body 带 planetId=100），让代理记住"玩家在哪颗星球"；
  4. GET Status：应注入 config 的掠食（1243,1245），原有条目保留；
  5. 面板等价操作：写 runtime/selection.json = 蟑龙；
  6. 再 GET Status：应改成蟑龙（1306,1309），说明**热重载**生效（代理没重启）。
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
SELECTION = BASE / "runtime" / "selection.json"

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
            if first.startswith("POST"):
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


def ids_for(body):
    plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    doc = json.loads(plain.decode("utf-8", "replace"))
    return [e["galacticEffectId"] for e in doc["planetActiveEffects"] if e["index"] == 100]


def main():
    anchor = CERT_DIR / "anchor.pem"
    if not anchor.exists():
        print("FAIL: 没有 certs/anchor.pem，先跑 gen_session_certs.py")
        return 1

    SELECTION.parent.mkdir(parents=True, exist_ok=True)
    if SELECTION.exists():
        SELECTION.unlink()

    threading.Thread(target=fake_upstream, daemon=True).start()
    time.sleep(0.3)

    cfg = {
        "host": HOST, "port": TEST_PORT, "upstreamTest": "127.0.0.1:%d" % UP_PORT,
        "passthrough": False, "allowDevFlags": False, "crlPort": 0,
        "targets": [{"planet": 100, "variant": "掠食"}],
    }
    cfg_path = BASE / "logs" / "selftest_config.json"
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
        # 3. 让代理记住玩家星球
        head, _ = call(TEST_PORT, "POST", "/api/lobby", anchor, body={"planetId": 100})
        print("  lobby POST ->", head.splitlines()[0] if head else "?")
        time.sleep(0.3)

        # 4. config 的掠食
        head, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        ids = ids_for(body)
        print("  第一次 Status（config=掠食）:", ids)
        if 1243 in ids and 1245 in ids and 1195 in ids:
            print("  [OK  ] config 变种注入 + 原有条目保留")
            ok += 1
        else:
            print("  [FAIL] config 注入不正确")

        # 5. 面板选择：多选（掠食 + 蟑龙 同时挂）
        SELECTION.write_text(json.dumps({"enabled": True, "variants": ["掠食变种", "蟑龙"]},
                                        ensure_ascii=False), encoding="utf-8")
        time.sleep(1.2)          # 让代理看到 mtime 变化（同一秒内可能读不到，留足时间）
        head, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        ids = ids_for(body)
        print("  第二次 Status（多选 掠食变种+蟑龙）:", ids)
        if 1243 in ids and 1245 in ids and 1306 in ids and 1309 in ids:
            print("  [OK  ] 热重载 + 多选叠加生效（两套变种同挂一颗星球）")
            ok += 1
        else:
            print("  [FAIL] 多选未生效")

        # 6. 清空选择 -> 回到 config 的默认项
        SELECTION.write_text(json.dumps({"enabled": False, "variants": []},
                                        ensure_ascii=False), encoding="utf-8")
        time.sleep(1.2)
        head, body = call(TEST_PORT, "GET", "/api/WarSeason/801/Status", anchor)
        ids = ids_for(body)
        print("  第三次 Status（清空选择）:", ids)
        if 1306 not in ids and 1309 not in ids and 1243 in ids and 1245 in ids:
            print("  [OK  ] 清空后回落到 config 默认，且不会叠加")
            ok += 1
        else:
            print("  [FAIL] 清空行为不正确")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            SELECTION.unlink()
        except Exception:
            pass

    print("RESULT=%s" % ("PASS" if ok == 3 else "FAIL(%d/3)" % ok))
    return 0 if ok == 3 else 2

if __name__ == "__main__":
    sys.exit(main())
