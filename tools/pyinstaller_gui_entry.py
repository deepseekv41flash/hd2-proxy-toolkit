"""GUI 入口（windowed exe，双击用）：直接打开图形界面，不弹控制台。

构建为 `hd2proxy-gui.exe`（console=False）；CLI 仍由 `hd2proxy.exe` 提供。
"""
import sys

from hd2proxy.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["gui"]))
