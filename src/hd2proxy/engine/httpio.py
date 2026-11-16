"""HTTP/1.1 最小读写工具（M1 从 legacy_proxy.py 抽出，行为一致）。

只处理本项目会遇到的情况：Connection: close、Content-Length 或 chunked、可选 gzip。
"""

import gzip


def read_head(conn):
    buf = b""
    while b"\r\n\r\n" not in buf:
        try:
            chunk = conn.recv(4096)
        except Exception:
            return b"", b""
        if not chunk:
            return b"", buf
        buf += chunk
        if len(buf) > 1 << 20:
            return b"", b""
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def parse_headers(head):
    lines = head.split(b"\r\n")
    first = lines[0].decode("latin-1") if lines else ""
    hdrs = {}
    for line in lines[1:]:
        if b":" in line:
            k, v = line.split(b":", 1)
            hdrs[k.strip().decode("latin-1").lower()] = v.strip().decode("latin-1")
    return first, hdrs


def dechunk(data):
    out = b""
    while True:
        idx = data.find(b"\r\n")
        if idx < 0:
            return out or data
        try:
            size = int(data[:idx].split(b";")[0], 16)
        except ValueError:
            return out or data
        if size == 0:
            return out
        out += data[idx + 2:idx + 2 + size]
        data = data[idx + 2 + size + 2:]


def maybe_gunzip(body, hdrs):
    if (hdrs.get("content-encoding", "") or "").lower().find("gzip") >= 0:
        try:
            return gzip.decompress(body), True
        except Exception:
            return body, False
    if body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body), True
        except Exception:
            return body, False
    return body, False
