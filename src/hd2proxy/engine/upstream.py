"""上游解析：DoH 绕 hosts + 地址选择（M1 从 legacy_proxy.py 抽出）。

为什么用 DoH：hosts 里正是我们把这个域名指到本机的，系统解析会自环。
任何回环结果都丢弃 —— 否则会变成「自己连自己」的死循环。
"""

import json
import socket

from .logutil import log


def doh_resolve(host):
    """解析白名单域名，**绕过 hosts**（hosts 里正是我们把它指到 127.0.0.1 的）。

    先问固定 IP 的 DoH 服务，再退系统解析；任何回环结果都丢弃，避免自环。
    """
    import urllib.request
    for url in ("https://223.5.5.5/resolve?name=%s&type=A" % host,
                "https://cloudflare-dns.com/dns-query?name=%s&type=A" % host):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=6) as r:
                doc = json.loads(r.read().decode("utf-8", "replace"))
            for a in doc.get("Answer") or []:
                if a.get("type") == 1 and a.get("data"):
                    ip = str(a["data"])
                    if not ip.startswith(("127.", "0.")):
                        return ip
        except Exception as e:
            log("  doh %s failed: %r" % (url.split("/")[2], e))
    try:
        ip = socket.gethostbyname(host)
        if not ip.startswith(("127.", "0.")):
            return ip
    except Exception:
        pass
    return None


def upstream_addr(mod, host):
    if mod.upstream_test:
        h, p = mod.upstream_test.rsplit(":", 1)
        return h, int(p)
    if mod.upstream_ip:
        ip = mod.upstream_ip
    else:
        ip = doh_resolve(host)
    if not ip or ip.startswith(("127.", "0.")):
        raise RuntimeError("refuse upstream %r -> %r (loopback/unknown)" % (host, ip))
    return ip, 443

