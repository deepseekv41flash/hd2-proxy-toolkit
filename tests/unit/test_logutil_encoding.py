"""控制台编码安全回归测试（0.5.4-alpha.1 打包版在中文 Windows 启动即崩的 bug）。

现场：`hd2proxy.exe engine` 在中文字符控制台（cp936/GBK）打印 `⚠ 证书未受信任…` 时，
`print` 抛 `UnicodeEncodeError: 'gbk' codec can't encode character U+26A0`，
把整个引擎进程带走（只有一行 pyinstaller traceback）。

这里用假控制台复现两条防线：
  1. `ensure_utf8_console()`：启动时把 stdout/stderr 切 UTF-8（errors=replace）；
  2. `log()` 里的 `_safe_print()`：任何原因导致 print 失败时降级写 bytes，绝不让日志杀死引擎。
"""

import sys

import pytest

from hd2proxy.__main__ import main as cli_main
from hd2proxy.engine import logutil, server


class _Buf:
    """模拟 TextIOWrapper.buffer（降级写 bytes 用）。"""

    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    def flush(self):
        pass


class GbkConsole:
    """模拟 cp936 控制台：GBK 编不出的字符（如 ⚠）抛 UnicodeEncodeError。"""

    encoding = "gbk"

    def __init__(self):
        self.lines = []
        self.buffer = _Buf()

    def write(self, text):
        text.encode("gbk")          # ⚠ → UnicodeEncodeError，与真实 TextIOWrapper 一致
        self.lines.append(text)

    def flush(self):
        pass


class Utf8Console:
    encoding = "utf-8"

    def __init__(self):
        self.lines = []
        self.buffer = _Buf()

    def write(self, text):
        self.lines.append(text)

    def flush(self):
        pass


class ReconfiguredConsole(Utf8Console):
    """记录 reconfigure 调用（ensure_utf8_console 的验证用）。"""

    def __init__(self):
        super().__init__()
        self.reconfigured = []

    def reconfigure(self, **kwargs):
        self.reconfigured.append(kwargs)
        self.encoding = kwargs.get("encoding", self.encoding)


@pytest.fixture()
def log_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(logutil, "LOGDIR", tmp_path)
    monkeypatch.setattr(logutil, "PROXY_LOG", tmp_path / "proxy.log")
    monkeypatch.setattr(logutil, "AUDIT_LOG", tmp_path / "audit.log")
    return tmp_path


# ---------------------------------------------------------------- 防线 2：log() 永不崩


def test_log_survives_gbk_console(log_paths, monkeypatch):
    console = GbkConsole()
    monkeypatch.setattr(sys, "stdout", console)
    logutil.log("⚠ 证书未受信任：当前 CA 不在受信任根存储")      # 不该抛
    # 文件里是完整 UTF-8 原文
    text = (log_paths / "proxy.log").read_text(encoding="utf-8")
    assert "⚠ 证书未受信任" in text
    # 控制台降级写 bytes（⚠ 被 replace 成 ?），且带换行
    assert console.buffer.data.endswith(b"\n")
    assert b"?" in console.buffer.data


def test_log_normal_utf8_console(log_paths, monkeypatch):
    console = Utf8Console()
    monkeypatch.setattr(sys, "stdout", console)
    logutil.log("⚠ 普通控制台")
    assert any("⚠ 普通控制台" in line for line in console.lines)


def test_log_when_stdout_missing(log_paths, monkeypatch):
    """windowed exe（console=False）里 sys.stdout 可能是 None。"""
    monkeypatch.setattr(sys, "stdout", None)
    logutil.log("⚠ 没有控制台也不该崩")
    assert "⚠ 没有控制台" in (log_paths / "proxy.log").read_text(encoding="utf-8")


def test_log_when_console_raises_oserror(log_paths, monkeypatch):
    class Broken:
        encoding = "utf-8"
        buffer = None

        def write(self, text):
            raise OSError("console gone")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", Broken())
    logutil.log("⚠ 控制台彻底不可用")            # 不抛即可
    assert "⚠ 控制台彻底不可用" in (log_paths / "proxy.log").read_text(encoding="utf-8")


def test_log_throttled_survives_gbk(log_paths, monkeypatch):
    monkeypatch.setattr(sys, "stdout", GbkConsole())
    monkeypatch.setattr(logutil, "_THROTTLE", {})
    logutil.log_throttled("k", "⚠ 限流日志")     # 不抛
    assert "⚠ 限流日志" in (log_paths / "proxy.log").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 防线 1：启动时切 UTF-8


def test_ensure_utf8_console_reconfigures(monkeypatch):
    out, err = ReconfiguredConsole(), ReconfiguredConsole()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    assert logutil.ensure_utf8_console() is True
    assert out.reconfigured == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.reconfigured == [{"encoding": "utf-8", "errors": "replace"}]


def test_ensure_utf8_console_tolerates_missing_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert logutil.ensure_utf8_console() is False


def test_ensure_utf8_console_tolerates_plain_object(monkeypatch):
    class NoReconfigure:
        encoding = "gbk"

        def write(self, text):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", NoReconfigure())
    monkeypatch.setattr(sys, "stderr", NoReconfigure())
    assert logutil.ensure_utf8_console() is False      # 没有 reconfigure 也不抛


# ---------------------------------------------------------------- 接线：入口真的会调用


def test_server_main_installs_utf8_console(monkeypatch):
    called = []
    monkeypatch.setattr(server.logutil, "ensure_utf8_console", lambda: called.append(1))
    with pytest.raises(SystemExit):
        server.main(["--help"])
    assert called, "engine 入口必须先切 UTF-8 控制台"


def test_cli_main_installs_utf8_console(monkeypatch):
    called = []
    monkeypatch.setattr("hd2proxy.__main__.logutil_mod.ensure_utf8_console",
                        lambda: called.append(1))
    assert cli_main(["--help"]) == 0          # CLI 的 --help 是正常返回（不 raise）
    assert called, "CLI 入口必须先切 UTF-8 控制台"
