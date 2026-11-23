"""DSH_SAVE_STATS_V1：`Stats/profile` 响应合并存档终身统计（G4）。

边界（有意为之）：

  * 只认两个 profile 汇总端点（`/api/Stats/profile/summary`、`/api/Stats/profile/801/summary`）；
    `/api/Stats/war/801/summary`（92 KB，战局内统计）语义未证，**不碰**；
  * 只合并**响应里已有**的数值键、逐 key 取 max —— 纯展示数据，只抬不降，
    换号/新号返回 0 时也不会把本地记录的战绩抹掉（研究线 2026-11-23 口径）；
  * 不新增字段（不在客户端凭空造统计项）；bool / 非数值一律跳过；
  * 等待/加锁/落盘在 `ActiveSave` 里（`apply_stats` / `record_stats`），本模块保持纯函数。
"""

from ..paths import STATS_PROFILE_MARKS


def is_stats_path(path: str) -> bool:
    """是否 profile 终身统计端点（去 query、去尾斜杠后精确匹配两个标记）。"""
    raw = str(path or "").split("?", 1)[0].rstrip("/")
    return any(raw.endswith(mark) for mark in STATS_PROFILE_MARKS)


def apply(body, save):
    """合并存档终身统计 → ``(new_body, 改动字段数)``；``save=None`` 时原样返回。"""
    if save is None:
        return body, 0
    return save.apply_stats(body)
