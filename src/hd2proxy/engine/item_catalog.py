"""物品目录（`data/catalogs/items.json`）读取 + 「一键解锁全部物品」展开。

目录来源：`/api/Progression/items` **全量行**的离线归档（2026-11-18 起，3020 行在架），字段已规范化：

    mix_id / item_id / option_id / parent_id / parent_name
    category / catalog_category / name / name_source
    default_owned（空号默认就拥有）/ in_catalog（客户端目录里确实有这一行）

「一键解锁全部物品」= 把**在架且可拥有**的行展开成库存行（`mixId` / `amount=1` / `isDiscovered=false`），
由引擎在 `/api/Progression/inventory` 响应里注入 —— **仅本机视图**，不写服务端任何数据。

排除规则（profile 可用 `inventory.unlock_scope` 收窄到指定类别）：

* `in_catalog=false`：不在客户端目录里，注入了也看不到（42 行）
* `category=currency`：货币不是"物品"（15 行）
* `default_owned=true`：空号默认就拥有，注入纯属冗余（55 行）

本模块只读文件、纯函数（除一个按 mtime/size 失效的缓存），不依赖网络/引擎状态。
"""

import json
import threading
from pathlib import Path

from . import paths

CATALOG_PATH = paths.CATALOGS_DIR / "items.json"

# profile `inventory.unlock_scope` 允许的类别（来自目录 `category` 字段）
VALID_SCOPES = ("weapon", "attachment", "cosmetic", "stratagem",
                "banner", "booster", "unknown")
# 不是"物品"的类别：货币（信用点等由其它字段/端点管理）
EXCLUDED_CATEGORIES = frozenset({"currency"})

_cache = {"key": None, "rows": []}
_lock = threading.Lock()


def load_rows(path=None) -> list:
    """读目录行（按 (路径, mtime, size) 缓存；文件变了一次重读）。读不到返回 []。"""
    p = Path(path or CATALOG_PATH)
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["rows"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = doc.get("items") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        rows = []
    rows = [r for r in rows if isinstance(r, dict)]
    with _lock:
        _cache["key"] = key
        _cache["rows"] = rows
    return rows


def unlock_all_ids(scope=None, path=None) -> tuple[list[int], dict]:
    """展开「一键解锁全部物品」要注入的 mixId 列表。

    ``scope``：空/None = 全部可拥有类别；否则只保留这些类别（见 :data:`VALID_SCOPES`）。
    返回 ``(ids, stats)``；ids 去重且保序（按目录顺序），stats 供日志/GUI 展示。
    """
    scope_set = {str(s).strip().lower() for s in (scope or []) if str(s).strip()}
    rows = load_rows(path)
    stats = {"catalogRows": len(rows), "skippedNotInCatalog": 0,
             "skippedCurrency": 0, "skippedDefaultOwned": 0,
             "skippedNoMixId": 0, "skippedScope": 0, "rows": 0,
             "scope": sorted(scope_set)}
    ids, seen = [], set()
    for row in rows:
        if row.get("in_catalog") is False:
            stats["skippedNotInCatalog"] += 1
            continue
        cat = str(row.get("category") or "unknown").strip().lower()
        if cat in EXCLUDED_CATEGORIES:
            stats["skippedCurrency"] += 1
            continue
        if scope_set and cat not in scope_set:
            stats["skippedScope"] += 1
            continue
        if row.get("default_owned"):
            stats["skippedDefaultOwned"] += 1
            continue
        try:
            mid = int(row.get("mix_id"))
        except (TypeError, ValueError):
            stats["skippedNoMixId"] += 1
            continue
        if mid <= 0 or mid in seen:
            stats["skippedNoMixId"] += 1
            continue
        seen.add(mid)
        ids.append(mid)
    stats["rows"] = len(ids)
    return ids, stats


def unlock_all_summary(scope=None, path=None) -> dict:
    """给 GUI 用的摘要（不返回完整 ids，避免一次拉几千个数字）。"""
    ids, stats = unlock_all_ids(scope=scope, path=path)
    out = dict(stats)
    out["count"] = len(ids)
    return out
