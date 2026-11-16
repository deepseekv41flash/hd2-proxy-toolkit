"""GUI（Tkinter）：本机控制面客户端 + 5 个页面。

入口：`python -m hd2proxy gui [--profile <path>]`。
GUI 不直接碰 hosts/证书/游戏 —— 安装/还原走 CLI 子进程（需 UAC），
引擎走独立进程（控制面 HTTP），所以关窗不会打断游戏会话。
"""

from .app import App

__all__ = ["App"]
