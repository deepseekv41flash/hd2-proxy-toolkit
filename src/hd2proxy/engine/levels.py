"""等级表（`data/catalogs/levels.json`）：等级 ↔ 累计经验。

来源：真机 `GET /api/Progression/levelspec`（2026-11-20 抓包 `0a1bf61e`）——本 build 共 **300 级**，
10 级 = **7,100** 累计经验（与 wiki Levels 页 Unlocks 表 "Level 10 = Weapon Attachments" 一致）。

用途：
  * `engine/unlock_all.py`：账号等级下限补丁（<10 级补到 7,100）；
  * GUI「存档（本机账本）」tab：把"目标等级"换算成经验写进本机账本（等级编辑）。

模块只读文件、纯函数 + 一个按文件指纹失效的缓存。
"""

import json
import threading

from . import paths

LEVELS_FILE = paths.CATALOGS_DIR / "levels.json"
# 武器改装在 10 级解锁（wiki Levels：Level 10 奖励含 Weapon Attachments；本 build 同级 7,100 经验）
CUSTOMIZE_UNLOCK_LEVEL = 10

_cache = {"key": None, "rows": []}
_lock = threading.Lock()


def reset():
    """清缓存（测试用）。"""
    with _lock:
        _cache["key"] = None
        _cache["rows"] = []


def rows(path=None) -> list:
    """等级表 ``[{level, requiredExperience}]``（按 (路径, mtime, size) 缓存）。读不到返回 []。"""
    from pathlib import Path
    p = Path(path or LEVELS_FILE)
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return list(_cache["rows"])
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = doc.get("levels") if isinstance(doc, dict) else doc
    clean = []
    for r in raw or []:
        if isinstance(r, dict):
            try:
                clean.append({"level": int(r["level"]),
                              "requiredExperience": int(r["requiredExperience"])})
            except (KeyError, TypeError, ValueError):
                continue
    clean.sort(key=lambda e: e["level"])
    with _lock:
        _cache["key"] = key
        _cache["rows"] = list(clean)
    return clean


def max_level() -> int:
    """表里最高一级（读不到 = 1）。"""
    rs = rows()
    return rs[-1]["level"] if rs else 1


def xp_for_level(level) -> int:
    """该等级所需的**累计经验**阈值；表里没有该级时取不超过它的最大一级（找不到=0）。"""
    try:
        want = int(level)
    except (TypeError, ValueError):
        return 0
    if want <= 0:
        return 0
    best = 0
    for r in rows():
        if r["level"] <= want:
            best = r["requiredExperience"]
        else:
            break
    return best


def level_for_xp(xp) -> int:
    """累计经验对应的**等级**（找不到/负数 = 0）。"""
    try:
        cur = int(xp)
    except (TypeError, ValueError):
        return 0
    lv = 0
    for r in rows():
        if cur >= r["requiredExperience"]:
            lv = r["level"]
        else:
            break
    return lv


def describe(xp) -> str:
    """一行中文描述：``2 级（208 经验，距 3 级还差 142）``。"""
    lv = level_for_xp(xp)
    try:
        cur = int(xp)
    except (TypeError, ValueError):
        cur = 0
    nxt = lv + 1
    need = xp_for_level(nxt)
    if lv and need > cur:
        return "%d 级（%d 经验，距 %d 级还差 %d）" % (lv, cur, nxt, need - cur)
    return "%d 级（%d 经验）" % (lv, cur)
