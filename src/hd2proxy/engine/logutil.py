"""日志（M1 从 legacy_proxy.py 抽出，行为一致）。

- 同时写 proxy.log、可选 audit.log、并 print 到 stdout；
- `log_throttled` 同类日志限流（证书没装好时客户端每 9 秒重试，不限流会刷屏）；
- `rotate_logs` 启动时把超过 512KB 的日志挪成 .log.1（只留一份）。
"""

import contextlib
import sys
import threading
import time

from .paths import AUDIT_LOG, LOGDIR, PROXY_LOG

_lock = threading.Lock()

# 1.04 起默认只留“必要日志”：启动/计划/改写/错误。
# 每条请求的 REQ/RESP 只有 --verbose（或 config.verbose=true）时才写。
VERBOSE = False
# 离线预演等「纯计算」场景要完全静音：不 print、不写 proxy.log。
# 为什么不做成参数：钩子内部是 `log(...)` 直接调用，参数传不进去；进程级开关最省事
# （预演跑在 GUI/CLI 进程里，和引擎不同进程，不存在跨线程污染）。
SILENT = False
_THROTTLE = {}          # key -> (last_logged_ts, count)


@contextlib.contextmanager
def quiet():
    """临时静音所有日志（离线预演用）。"""
    global SILENT
    old = SILENT
    SILENT = True
    try:
        yield
    finally:
        SILENT = old


def ensure_utf8_console() -> bool:
    """把 stdout/stderr 切到 UTF-8（errors=replace），避免中文/符号在 GBK 控制台崩进程。

    为什么必须做：中文 Windows 的控制台默认 cp936（GBK），而日志里有 `⚠`（U+26A0）等
    GBK 编码不出的字符 —— `print` 会抛 UnicodeEncodeError，**把整个引擎进程带走**
    （0.5.4-alpha.1 打包版启动即崩，现场只有一行 pyinstaller traceback）。
    返回是否至少成功切换了一个流。
    """
    ok = False
    for stream in (sys.stdout, sys.stderr):
        if stream is None:                 # windowed exe（console=False）没有控制台
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            ok = True
        except Exception:                  # noqa: BLE001 - 非 TextIOWrapper / 已关闭
            pass
    return ok


def _safe_print(line):
    """打印到控制台：编码不支持就降级写 bytes，**绝不抛异常**（日志文件已经写过了）。"""
    stream = sys.stdout
    if stream is None:
        return
    try:
        print(line, flush=True)
        return
    except (UnicodeEncodeError, OSError):
        pass
    try:
        buf = getattr(stream, "buffer", None)
        if buf is None:
            return
        enc = getattr(stream, "encoding", None) or "utf-8"
        buf.write((line + "\n").encode(enc, "replace"))
        buf.flush()
    except Exception:                      # noqa: BLE001 - 控制台彻底不可用也不影响引擎
        pass


def log(msg, audit=False):
    if SILENT:
        return
    line = time.strftime("%H:%M:%S ") + msg
    with _lock:
        try:
            LOGDIR.mkdir(parents=True, exist_ok=True)
            with PROXY_LOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            if audit:
                with AUDIT_LOG.open("a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + msg + "\n")
        except Exception:
            pass
        _safe_print(line)


def log_throttled(key, msg, every=60.0):
    """同类日志限流：第一次立刻写，之后每 every 秒最多一条，并带上累计次数。

    为什么需要：证书没装好时游戏每 9 秒重试一次，局域网里的扫描器也会来敲门 ——
    不限流的话 proxy.log 会被同一行刷满（以前一次会话几 KB，现在压在几十行）。
    """
    now = time.time()
    last, n = _THROTTLE.get(key, (0.0, 0))
    n += 1
    if last == 0.0 or now - last >= every:
        _THROTTLE[key] = (now, n)
        log(msg + ("" if n == 1 else "  （同类累计 %d 次）" % n))
    else:
        _THROTTLE[key] = (last, n)


def rotate_logs(max_bytes=512 * 1024):
    """启动时把过大的 proxy.log 挪成 proxy.log.1（只留一份），日志永远不涨到 MB 级。"""
    try:
        if PROXY_LOG.exists() and PROXY_LOG.stat().st_size > max_bytes:
            old = PROXY_LOG.with_suffix(".log.1")
            if old.exists():
                old.unlink()
            PROXY_LOG.rename(old)
    except Exception:
        pass
