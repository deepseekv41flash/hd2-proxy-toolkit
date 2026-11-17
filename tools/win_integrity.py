"""Windows 文件完整性标签（Mandatory Integrity Level）辅助。

为什么需要这个：**由低完整性（Low IL）进程创建的文件会继承 Low 标签**，而 Windows 启动 exe 时
进程完整性取「父进程 IL」与「映像文件 IL」的较小值。于是产物一旦被 Low 进程解压/生成，即使用户
在资源管理器里双击，进程也只有 Low IL —— 而 `%LOCALAPPDATA%` 是 Medium 标签，Low IL 写不进去。

实测（2026-11-17）：测试区 `current/` 是本项目用 DSH shell（Low 令牌）解压出来的，双击 GUI 后
进程 integrity RID = 4096（Low），「保存配置 / 证书签发 / 启动引擎」全部 `PermissionError(13)`；
把目录树标回 Medium 后，同样双击 → RID = 8192（Medium），全部恢复正常。

对策：产物落盘后把这些目录树标回 Medium（`icacls /setintegritylevel (OI)(CI)Medium /T`）。
非 Windows 平台直接返回 False（不影响跨平台开发/CI）。
"""

import os
import subprocess

LEVEL = "Medium"


def set_medium(path) -> bool:
    """把 path 整棵树（含子目录未来文件）的完整性标签设为 Medium。成功返回 True。

    为什么用 icacls 而不是 Python API：设置标签要 WRITE_OWNER/SeSecurityPrivilege 相关权限，
    icacls 是系统自带、行为稳定、无需管理员（对象属主即可改自己的标签）。
    """
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["icacls", str(path), "/setintegritylevel", "(OI)(CI)%s" % LEVEL, "/T", "/Q"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def describe(path) -> str:
    """返回一句给日志用的话（失败时调用方自己决定要不要提示）。"""
    ok = set_medium(path)
    return ("完整性标签已设为 %s：%s" % (LEVEL, path)) if ok else \
           ("完整性标签设置失败（可能非 Windows 或权限不足）：%s" % path)
