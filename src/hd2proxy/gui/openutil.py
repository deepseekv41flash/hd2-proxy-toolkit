"""在系统默认程序里打开文件/目录（统一「文件还不存在」的友好提示）。

为什么单独抽出来：三个页面都有「打开日志 / 打开状态目录」按钮，之前各自直接
os.startfile(路径)，文件还没生成时会把原始异常呛给用户 ——
实测冻结版新建 profile 后点「打开日志」弹 FileNotFoundError(2) 原文，
既看不懂也像是坏了。这里统一成一句人话 ✓
"""

import os
from pathlib import Path


def open_path(path, toast, label="文件", hint="引擎运行后才会生成"):
    """打开路径；不存在时给友好提示。返回是否真的打开了。"""
    p = Path(path)
    if not p.exists():
        toast("%s还不存在：%s（%s）" % (label, p, hint), error=True)
        return False
    try:
        os.startfile(str(p))          # noqa: S606 - Windows 用默认程序打开
        return True
    except Exception as e:            # noqa: BLE001
        toast("打开%s失败：%r" % (label, e), error=True)
        return False
