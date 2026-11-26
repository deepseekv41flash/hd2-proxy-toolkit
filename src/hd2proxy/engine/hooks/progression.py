"""DSH_SAVE_PROG_V1：``/api/Progression`` 根响应合并存档 earned（G2）。

为什么单独一个钩子：这是**首屏进度响应**，也是整个存档系统里唯一必须「先选档再渲染」的
一处 —— 客户端一次会话只拉它一次（时序见 `engine/active_save.py` 模块注释）。

边界（有意为之）：

  * **只认精确根路径** `/api/Progression`（去 query / 尾斜杠后比较）。它是
    `/api/Progression/inventory|items|levelspec|ProgressionPackages|ItemPackages` 的**前缀**，
    用子串匹配会把库存/目录/等级表一起改坏；
  * 纯函数式：``apply(body, save)`` 吃 bytes/str/dict + `ActiveSave`，返回 (body, 改动字段数)；
  * 等待身份 / 加锁 / 会话快照都在 `ActiveSave` 里，本模块不含状态，便于离线单测。
"""

from ..paths import PROG_PATH


def is_root_path(path: str) -> bool:
    """是否 `/api/Progression` 根路径（去 query / 尾斜杠后**精确**相等）。"""
    raw = str(path or "").split("?", 1)[0].rstrip("/")
    return raw == PROG_PATH


def apply(body, save, unlock_all_enabled=False, forge_flags=0, forge_xp=0):
    """把存档 earned 合并进 Progression 根响应；可选把舰船模块包等级置满。

    ``save`` 为 ``ActiveSave``（None = 存档层未启用 → 跳过合并）。
    ``forge_flags`` / ``forge_xp``：可选伪造账号级开关（教程位掩码 / 经验下限），默认 0 = 不动。
    ``unlock_all_enabled``：一键解锁开启时，把 6 条 ship module 包的 packageProgress 等级置满
    （模块不是库存行，客户端按包等级显示；见 ``engine/unlock_all.py``）。
    返回 ``(new_body, 改动字段数)``；无改动时 body 原样返回（引用相同，便于上层判等）。
    """
    new_body, changed = (body, 0)
    if save is not None:
        new_body, changed = save.apply_progression(body)
    if unlock_all_enabled:
        from .. import unlock_all as _ua
        patched, ua_n = _ua.patch_progression(
            new_body if new_body is not None else body,
            forge_flags=forge_flags, forge_xp=forge_xp)
        if ua_n:
            return patched, changed + ua_n
    return new_body, changed
