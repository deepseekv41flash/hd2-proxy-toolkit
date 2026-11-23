"""GUI 入口（windowed exe，双击用）：直接打开图形界面，不弹控制台。

构建为 `hd2proxy-gui.exe`（console=False）；CLI 仍由 `hd2proxy.exe` 提供。
"""
import sys

from hd2proxy.engine.logutil import ensure_utf8_console

# 中文 Windows 控制台默认 GBK：日志里的 ⚠ 会抛 UnicodeEncodeError 把进程带走
ensure_utf8_console()

from hd2proxy.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["gui"]))
