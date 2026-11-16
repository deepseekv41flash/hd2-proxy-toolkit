"""PyInstaller 入口（M5 打包用）：等价于 `python -m hd2proxy`。

为什么单独一个文件：PyInstaller 需要一个真实脚本入口；这里只做 sys.exit(main())，
保证源码运行与打包运行走同一条 CLI 路由（engine/selftest/gate 的转发短路径也一致）。
"""
import sys

from hd2proxy.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
