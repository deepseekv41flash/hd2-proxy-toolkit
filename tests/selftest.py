"""基础自检（不需要游戏、不需要联网、不需要管理员）：起代理 + 假上游，验证四件事。

  1. 白名单域名握手成功（信任锚 = certs/anchor.pem），上游可达并有响应体；
  2. **非白名单 SNI 被拒绝** —— 证明这不是一个开放代理；
  3. 改写生效：`/api/WarSeason/801/Status` 里目标星球出现配置的 id 对；
  4. 原有条目不被破坏。

与旧版（variant_mod\\tools\\selftest.py）的区别：旧版要求「代理已经在 8443 上跑着」，
    这里自己起代理与假上游，clone 下来直接可跑（M0 门禁要求 5 个自检零外部依赖）。

跑法：python tests/selftest.py
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
BASE = Path(os.environ["VMOD_DATA"]) if os.environ.get("VMOD_DATA") else ROOT
CERT_DIR = Path(os.environ.get("HD2PROXY_TEST_CERTS") or (ROOT / "certs"))
PROXY = ROOT / "src" / "hd2proxy" / "engine" / "legacy_proxy.py"
CATALOG = ROOT / "data" / "legacy" / "variant_catalog.json"

HOST = "api.live.prod.thehelldiversgame.com"
TEST_PORT = 8446
UP_PORT = 9097

STATUS_JSON = {
    "warId": 801,
    "planetStatus": [{"index": 100, "owner": 2}],
    "planetActiveEffects": [{"index": 100, "galacticEffectId": 1195}],
}
REQUESTS = []


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
            REQUESTS.append(buf.split(b"\r\n")[0].decode("latin-1", "replace"))
            body = gzip.compress(json.dumps(STATUS_JSON).encode())
            conn.sendall(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                          "Content-Encoding: gzip\r\nContent-Length: %d\r\n"
                          "Connection: close\r\n\r\n" % len(body)).encode() + body)
        finally:
            conn.close()


def request(port, hostname, path, cafile, timeout=20):
    ctx = ssl.create_default_context(cafile=str(cafile))
    raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    tls = ctx.wrap_socket(raw, server_hostname=hostname)
    req = ("GET %s HTTP/1.1\r\nHost: %s\r\nAccept: */*\r\n"
           "User-Agent: hd2-proxy-toolkit-selftest\r\nConnection: close\r\n\r\n" % (path, HOST))
    tls.sendall(req.encode())
    buf = b""
    need = None
    while True:
        c = tls.recv(65536)
        if not c:
            break
        buf += c
        if need is None and b"\r\n\r\n" in buf:
            head, _, body = buf.partition(b"\r\n\r\n")
            text = head.decode("latin-1", "replace").lower()
            for line in text.split("\r\n"):
                if line.startswith("content-length:"):
                    need = len(body) + int(line.split(":", 1)[1].strip())
                    break
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
        print("FAIL: 没有测试证书（先跑 tools/run_selftests.py，或手工 gen_session_certs.py）")
        return 1

    threading.Thread(target=fake_upstream, daemon=True).start()
    time.sleep(0.3)

    cfg = {
        "host": HOST, "port": TEST_PORT, "upstreamTest": "127.0.0.1:%d" % UP_PORT,
        "passthrough": False, "allowDevFlags": False, "crlPort": 0,
        "targets": [{"planet": 100, "variant": "掠食"}],
    }
    cfg_path = BASE / "logs" / "selftest_basic_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(PROXY), "--port", str(TEST_PORT),
         "--config", str(cfg_path), "--catalog", str(CATALOG),
         "--cert-dir", str(CERT_DIR)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)

    results = []
    try:
        # 3. 非白名单 SNI 必须先被拒绝（先测，避免误判）
        try:
            request(TEST_PORT, "example.com", "/", anchor, timeout=8)
            results.append(("非白名单 SNI 被拒绝", "FAIL", "居然握手成功 —— 可能是开放代理"))
        except Exception as e:
            results.append(("非白名单 SNI 被拒绝", "OK", type(e).__name__))

        # 1+2. 白名单域名握手 + 上游可达
        try:
            head, body = request(TEST_PORT, HOST, "/api/WarSeason/current/WarId", anchor)
            ok = head.startswith("HTTP/1.1 200") or head.startswith("HTTP/1.0 200")
            results.append(("白名单握手", "OK" if ok else "FAIL",
                            head.splitlines()[0] if head else "no response"))
            results.append(("上游可达", "OK" if body else "WARN", "%d B" % len(body)))
        except Exception as e:
            results.append(("白名单握手", "FAIL", repr(e)))
            head, body = "", b""

        # 4. 改写生效 + 原有条目保留
        try:
            head, body = request(TEST_PORT, HOST, "/api/WarSeason/801/Status", anchor, timeout=40)
            plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
            doc = json.loads(plain.decode("utf-8", "replace"))
            ids = [e.get("galacticEffectId") for e in (doc.get("planetActiveEffects") or [])
                   if e.get("index") == 100]
            if 1243 in ids and 1245 in ids:
                results.append(("改写生效", "OK", "planet 100 -> 1243,1245"))
            else:
                results.append(("改写生效", "FAIL", "planet 100 实际 ids=%r" % (ids,)))
            if 1195 in ids:
                results.append(("原有条目保留", "OK", "1195 仍在"))
            else:
                results.append(("原有条目保留", "FAIL", "原有 1195 丢失"))
        except Exception as e:
            results.append(("改写检查", "FAIL", repr(e)))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print("\n== hd2-proxy-toolkit selftest ==")
    bad = 0
    for name, status, detail in results:
        if status == "FAIL":
            bad += 1
        print("  [%-4s] %-22s %s" % (status, name, detail))
    print("RESULT=%s" % ("PASS" if bad == 0 else "FAIL(%d)" % bad))
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
