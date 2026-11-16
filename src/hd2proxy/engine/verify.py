"""证书链 / CRL / Status 回执的「三连验证」（产品化的 §7.4 验收）。

三个检查各自独立，任何一项 FAIL 都能单独定位问题：
  1. **TLS 握手**：用本机 CA（certs/anchor.pem）当信任锚，经代理请求 WarId，期望 200 + JSON；
  2. **CRL 服务**：Schannel 必须取到 CRL 才会继续握手，所以本地 8080 必须回 200；
  3. **Status 回执**：经代理拉一次 Status，期望 200 且有响应体（证明链路与改写路径都在工作）。
"""

import json
import socket
import ssl
import time
import urllib.request

from .logutil import log


def local_opener():
    """访问本机 HTTP 服务的 opener：**显式禁用系统代理**。

    为什么必须：Windows 的 WinINET 代理设置会被 urllib 读到，Clash/加速器把
    127.0.0.1 也送进代理时，本机控制面/CRL 请求就会失败（研究线踩过同一类坑：
    curl 必须加 `--noproxy '*'`）。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _tls_get(listen_ip, port, host, path, cafile, timeout=15.0):
    """经代理发一个最小 HTTP/1.1 GET，返回 (状态行, body)。"""
    ctx = ssl.create_default_context(cafile=str(cafile))
    raw = socket.create_connection((listen_ip, port), timeout=timeout)
    tls = ctx.wrap_socket(raw, server_hostname=host)
    try:
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nAccept: */*\r\n"
               "User-Agent: hd2proxy-verify\r\nConnection: close\r\n\r\n" % (path, host))
        tls.sendall(req.encode())
        buf = b""
        need = None
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            buf += chunk
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
    finally:
        try:
            tls.close()
        except Exception:
            pass
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1", "replace"), body


def _check_tls(listen_ip, port, host, cert_dir):
    anchor = cert_dir / "anchor.pem"
    name = "TLS 握手 + 白名单域名"
    if not anchor.exists():
        return {"name": name, "ok": False, "detail": "缺少 %s（先安装/续证）" % anchor}
    try:
        head, body = _tls_get(listen_ip, port, host, "/api/WarSeason/current/WarId", anchor)
    except Exception as e:      # noqa: BLE001
        return {"name": name, "ok": False, "detail": "握手/请求失败: %r" % (e,)}
    status = head.splitlines()[0] if head else "(无响应)"
    ok = " 200 " in (" " + status.split(" ", 1)[-1] + " ") or status.startswith("HTTP/1.1 200")
    detail = "%s · %d B" % (status, len(body))
    if ok and body:
        try:
            doc = json.loads(body.decode("utf-8", "replace"))
            if isinstance(doc, dict) and "id" in doc:
                detail += " · WarId=%s" % doc.get("id")
        except Exception:
            pass
    return {"name": name, "ok": bool(ok), "detail": detail}


def _check_crl(crl_port):
    name = "CRL 服务（Schannel 必需）"
    url = "http://127.0.0.1:%d/ca.crl" % int(crl_port)
    try:
        req = urllib.request.Request(url, method="GET")
        with local_opener().open(req, timeout=5) as r:
            data = r.read()
            code = r.status
        return {"name": name, "ok": code == 200 and len(data) > 0,
                "detail": "%s · %d B" % (url, len(data))}
    except Exception as e:      # noqa: BLE001
        return {"name": name, "ok": False, "detail": "%s -> %r" % (url, e)}


def _check_status(listen_ip, port, host, cert_dir):
    name = "Status 回执（链路 + 改写路径）"
    anchor = cert_dir / "anchor.pem"
    if not anchor.exists():
        return {"name": name, "ok": False, "detail": "缺少 anchor.pem"}
    try:
        head, body = _tls_get(listen_ip, port, host,
                              "/api/WarSeason/801/Status", anchor, timeout=40.0)
    except Exception as e:      # noqa: BLE001
        return {"name": name, "ok": False, "detail": "请求失败: %r" % (e,)}
    status = head.splitlines()[0] if head else "(无响应)"
    ok = (" 200 " in (" " + status + " ")) and len(body) > 0
    detail = "%s · %d B" % (status, len(body))
    if ok:
        detail += " · 改写后的响应已收到"
    return {"name": name, "ok": bool(ok), "detail": detail}


def verify_all(ctx) -> dict:
    """对运行中的引擎做三连验证。ctx 需有 listen_ip/port/host/cert_dir/crl_port。"""
    cert_dir = ctx.cert_dir
    results = [
        _check_tls(ctx.listen_ip, ctx.port, ctx.host, cert_dir),
        _check_crl(ctx.crl_port),
        _check_status(ctx.listen_ip, ctx.port, ctx.host, cert_dir),
    ]
    ok = all(r["ok"] for r in results)
    log("verify: %s" % ("PASS" if ok else "FAIL"), audit=True)
    for r in results:
        log("  [%s] %s —— %s" % ("OK" if r["ok"] else "FAIL", r["name"], r["detail"]))
    return {"ok": ok, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": results}
