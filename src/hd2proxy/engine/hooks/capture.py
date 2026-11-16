"""DSH_GWE_CAPTURE_V1：只读抓包（响应体 / 请求体落盘）。

设计约束（沿用研究线）：
  * 默认关闭；只有设置抓包目录才写盘；
  * 只写 body，不写 header/token；
  * 白名单路径过滤（`HD2_GWE_PATHS` / `HD2_GWE_REQ_PATHS`）。
"""

import gzip
import hashlib
import json
import os
import re
import time

from ..logutil import log


# ---- DSH_GWE_CAPTURE_V1 : read-only response dump (added by DSH tools/gwe_capture.py) ----
def load_capture_spec(spec=None, req=False):
    """抓包配置：spec 显式传入优先；否则退回研究线的环境变量行为。

    spec（schema v2 / 测试）: {"enabled": bool, "dir": str, "paths": [...],
                             "req_paths": [...], "max_bytes": int}
    环境变量（旧行为）: HD2_GWE_DUMP / HD2_GWE_PATHS / HD2_GWE_REQ_PATHS / HD2_GWE_MAX
    """
    if spec is not None:
        return spec if isinstance(spec, dict) else {}
    outdir = os.environ.get("HD2_GWE_DUMP", "")
    default_pats = ("/api/Operation,/api/lobby,/api/Progression/Items/Customize" if req
                    else "/api/WarSeason/GalacticWarEffects")
    return {
        "enabled": bool(outdir),
        "dir": outdir,
        "paths": [p.strip() for p in os.environ.get("HD2_GWE_PATHS", default_pats).split(",")
                  if p.strip()],
        "req_paths": [p.strip() for p in os.environ.get("HD2_GWE_REQ_PATHS", default_pats).split(",")
                      if p.strip()],
        "max_bytes": int(os.environ.get("HD2_GWE_MAX", str(8 << 20)) or (8 << 20)),
    }


def capture_response(path, body, hdrs, spec=None):
    """把匹配路径的响应体原样落盘，供离线分析。绝不写 header/token，异常一律吞掉。"""
    import gzip, hashlib, json as _json, os, re as _re, time as _time
    try:
        cfg = load_capture_spec(spec, req=False)
        outdir = cfg.get("dir") or ""
        if not cfg.get("enabled", True) or not outdir or not body:
            return
        pats = cfg.get("paths") or []
        if not any(p in path for p in pats):
            return
        cap = int(cfg.get("max_bytes") or (8 << 20))
        raw = body
        if body[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(body)
            except Exception:
                raw = body
        if len(raw) > cap:
            log("gwe-dump skipped: %d B > cap %d" % (len(raw), cap))
            return
        os.makedirs(outdir, exist_ok=True)
        digest = hashlib.sha256(raw).hexdigest()
        slug = _re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")[-60:] or "body"
        stamp = _time.strftime("%Y%m%dT%H%M%SZ", _time.gmtime())
        # 按内容哈希命名 => 同一份响应被轮询多次也只落一个文件
        fp = os.path.join(outdir, "%s_%s.json" % (digest[:8], slug))
        if os.path.exists(fp):
            return
        with open(fp, "wb") as fh:
            fh.write(raw)
        try:
            _json.loads(raw.decode("utf-8", "replace"))
            kind = "json"
        except Exception:
            kind = "not-json"
        # 只记：时间 / 路径 / 字节数 / sha256 / 是否合法 JSON。不记 header。
        with open(os.path.join(outdir, "index.txt"), "a", encoding="utf-8") as ix:
            ix.write("%s\t%s\t%d\t%s\t%s\n" % (stamp, path, len(raw), digest, kind))
        log("gwe-dump %s %d B -> %s" % (path.split("?")[0], len(raw), fp))
    except Exception as e:
        try:
            log("gwe-dump failed (ignored): %r" % e)
        except Exception:
            pass
# ---- /DSH_GWE_CAPTURE_V1 ----

def capture_request(path, body, hdrs, method="", spec=None):
    """请求体落盘：给“客户端提案”类请求用（Operation* / lobby / 改装保存）。绝不写 header/token。"""
    import gzip, hashlib, os, re as _re, time as _time
    try:
        cfg = load_capture_spec(spec, req=True)
        outdir = cfg.get("dir") or ""
        if not cfg.get("enabled", True) or not outdir or not body:
            return
        pats = cfg.get("req_paths") or []
        if not any(p in path for p in pats):
            return
        cap = int(cfg.get("max_bytes") or (8 << 20))
        raw = body
        if body[:2] == b"\x1f\x8b":
            try:
                raw = gzip.decompress(body)
            except Exception:
                raw = body
        if len(raw) > cap:
            log("gwe-req skipped: %d B > cap %d" % (len(raw), cap))
            return
        os.makedirs(outdir, exist_ok=True)
        digest = hashlib.sha256((method + "\x00").encode() + path.encode("utf-8", "replace")
                                + b"\x00" + raw).hexdigest()
        slug = _re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")[-60:] or "req"
        stamp = _time.strftime("%Y%m%dT%H%M%SZ", _time.gmtime())
        tag = (method or "REQ").upper()[:6]
        fp = os.path.join(outdir, "req_%s_%s_%s.json" % (tag, digest[:8], slug))
        if os.path.exists(fp):
            return
        with open(fp, "wb") as fh:
            fh.write(raw)
        with open(os.path.join(outdir, "index.txt"), "a", encoding="utf-8") as ix:
            ix.write("%s\tREQ %s\t%s\t%d\t%s\n" % (stamp, tag, path, len(raw), digest))
        log("gwe-req %s %s %d B -> %s" % (tag, path.split("?")[0], len(raw), fp))
    except Exception as e:
        try:
            log("gwe-req failed (ignored): %r" % e)
        except Exception:
            pass
# ---- /DSH_GWE_CAPTURE_V1_END ----

