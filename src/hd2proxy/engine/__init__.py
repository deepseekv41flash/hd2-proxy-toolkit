"""代理引擎。

M0：`legacy_proxy` 直接可运行（`python src/hd2proxy/engine/legacy_proxy.py --help`）。
M1 起按 `server / upstream / pipeline / hooks / certs / hosts / config / control` 拆分，
拆分以本文件为基线做等价性回归（5 个离线自检 + 快照对比）。
"""
