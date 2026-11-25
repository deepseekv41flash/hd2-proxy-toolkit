"""一键解锁全部物品（v0.10.1-alpha.2）：运行时按**客户端目录**展开 + 舰船模块包进度。

2026-11-25 实机反馈（空白号）：护甲/头盔/披风只出 3 件、舰船模块 0 件。根因两条：

1. **目录来源错了**：alpha.1 用离线 `data/catalogs/items.json`（商店/护甲表子集，pc3 只有 46 个 id），
   而客户端真实目录里 pc3 有 441 个。⇒ 改为**运行时 live 目录**（引擎看到的 `/api/Progression/items`
   响应），由 :func:`set_catalog` 缓存；拿不到时才退回离线目录。
2. **舰船模块不是库存行**：它们是 6 条 `progression package`（type=1，每条 5 级）的**等级进度**，
   客户端按 `/api/Progression.packageProgress[].level` 显示；另外 6 个 `requiredItems`（pc0）必须在库存里，
   否则 Ship Module 页显示"under construction"。
   （来源：HellForge `ProfileStore.cs:530` + 11-20 真机抓包 `ProgressionPackages`。）

授予行统一 `isDiscovered=true`（HellForge 对"授予物品"的写法；空白号此前用 false 时护甲/披风不显示）。
"""

import json
import threading

# ---- 舰船模块：6 条 type=1 进度包（第 7 条 1555987791 不在活动账号上，忽略） ----------
SHIP_MODULE_PACKAGES = (
    131213678, 4202868518, 2822932719, 792686718, 1831255310, 2636037703)
SHIP_MODULE_MAX_LEVEL = 5
# 6 条包的 requiredItems（必须在库存里，Ship Module 页才出现）
SHIP_MODULE_REQUIRED_ITEMS = (
    3440915970, 3421210661, 2070435954, 1402181160, 3822450566, 3764534604)
# 货币不是"物品"：库存里不需要注入（信用点/奖章/样本走其它字段）
EXCLUDED_CATEGORIES = frozenset({18})

_lock = threading.Lock()
_catalog = {"key": None, "rows": []}


def reset():
    """清缓存（测试用）。"""
    with _lock:
        _catalog["key"] = None
        _catalog["rows"] = []


def set_catalog(rows, key=None) -> int:
    """缓存客户端目录行（`/api/Progression/items` 响应的 items 数组）。返回行数。"""
    clean = [r for r in rows if isinstance(r, dict) and r.get("mixId")]
    with _lock:
        _catalog["key"] = key
        _catalog["rows"] = clean
    return len(clean)


def catalog_rows() -> list:
    with _lock:
        return list(_catalog["rows"])


def ownable_ids(scope=None) -> list:
    """要注入库存的 mixId 列表（去重保序）。

    优先用运行时缓存的客户端目录；没有时退回离线目录（`item_catalog.unlock_all_ids`），
    这样离线 preview / 未收到 items 响应前也有兜底。
    `scope` 目前只对离线兜底生效（live 目录按 progressionCategory 过滤）。
    """
    rows = catalog_rows()
    ids, seen = [], set()
    if rows:
        for r in rows:
            if r.get("progressionCategory") in EXCLUDED_CATEGORIES:
                continue
            try:
                mid = int(r.get("mixId"))
            except (TypeError, ValueError):
                continue
            if mid > 0 and mid not in seen:
                seen.add(mid)
                ids.append(mid)
        for mid in SHIP_MODULE_REQUIRED_ITEMS:
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)
        return ids
    from . import item_catalog
    ids, _stats = item_catalog.unlock_all_ids(scope=scope or [])
    for mid in SHIP_MODULE_REQUIRED_ITEMS:
        if mid not in ids:
            ids.append(mid)
    return ids


def _have_mix_ids(items) -> set:
    have = set()
    for it in items or []:
        if isinstance(it, dict):
            try:
                have.add(int(it.get("mixId", 0)))
            except (TypeError, ValueError):
                pass
    return have


def inject_inventory(items, scope=None) -> int:
    """把可拥有物品补进 inventory.items[]（原地修改），返回新增行数。"""
    if not isinstance(items, list):
        return 0
    have = _have_mix_ids(items)
    added = 0
    for mid in ownable_ids(scope):
        if mid in have:
            continue
        items.append({"mixId": mid, "amount": 1, "isDiscovered": True})
        have.add(mid)
        added += 1
    return added


def patch_progression(body):
    """把 6 条舰船模块包的 `packageProgress` 等级置满（原地/返回 bytes）。

    返回 ``(new_body 或 None, 改动数)``；没有 `packageProgress` 数组时也不报错，
    只在有变化时返回新 body。
    """
    if body is None:
        return None, 0
    try:
        doc = json.loads(body) if isinstance(body, (bytes, str)) else body
    except Exception:
        return None, 0
    if not isinstance(doc, dict):
        return None, 0
    progress = doc.get("packageProgress")
    if not isinstance(progress, list):
        return None, 0
    by_id = {}
    for entry in progress:
        if isinstance(entry, dict):
            try:
                by_id[int(entry.get("id32", 0))] = entry
            except (TypeError, ValueError):
                pass
    changed = 0
    for pid in SHIP_MODULE_PACKAGES:
        entry = by_id.get(pid)
        if entry is None:
            progress.append({"id32": pid, "level": SHIP_MODULE_MAX_LEVEL,
                             "progress": 0, "sortOrder": 0, "claimedLevels": []})
            changed += 1
            continue
        try:
            level = int(entry.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        if level != SHIP_MODULE_MAX_LEVEL:
            entry["level"] = SHIP_MODULE_MAX_LEVEL
            entry["progress"] = 0
            changed += 1
    if not changed:
        return None, 0
    return json.dumps(doc, separators=(",", ":")).encode("utf-8"), changed
