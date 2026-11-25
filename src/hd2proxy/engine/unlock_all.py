"""一键解锁全部物品（v0.10.1-alpha.2/4）：运行时按**客户端目录**展开 + 包进度 + 改装条目。

2026-11-25 实机反馈（空白号）：护甲/头盔/披风只出 3 件、舰船模块 0 件。根因两条：

1. **目录来源错了**：alpha.1 用离线 `data/catalogs/items.json`（商店/护甲表子集，pc3 只有 46 个 id），
   而客户端真实目录里 pc3 有 441 个。⇒ 改为**运行时 live 目录**（引擎看到的 `/api/Progression/items`
   响应），由 :func:`set_catalog` 缓存；拿不到时才退回离线目录。
2. **舰船模块不是库存行**：它们是 6 条 `progression package`（type=1，每条 5 级）的**等级进度**，
   客户端按 `/api/Progression.packageProgress[].level` 显示；另外 6 个 `requiredItems`（pc0）必须在库存里，
   否则 Ship Module 页显示"under construction"。
   （来源：HellForge `ProfileStore.cs:530` + 11-20 真机抓包 `ProgressionPackages`。）

授予行 `isDiscovered`：**默认 false** —— 2026-11-25 实证：真实库存（主号 970 + 空白号 60 行）**全部 false**；
alpha.2 改成 true 后出现"所有武器缺改装按钮"，故回退为 false（可用 profile `inventory.unlock_discovered` 改）。

3. **改装（L2）条目**（alpha.4）：`/api/Progression/Items/Customize/v2` 是**按武器**的改装槽快照，客户端
   启动后只拉一次（+19~22 s，见 `docs/HANDOFF-SAVE-SYSTEM-TO-MITM-2026-11-23.md` §10.7）。主号这份是
   **74 条**、空白号 **0 条**（`544b4168_*` vs `eef46741_*`）；两个号在同一代理/同样注入下唯一仍不同的
   「改装」相关数据就是它 ⇒ 空白号「所有可改装武器缺改装按钮」的头号原因。
   这里给目录里**有子项（附件）的 pc1 武器**补一条空槽模板条目（形状取自客户端自己 PUT 过的
   `f71b1f23_*`：`{mixId32, modes:[], activeIndex:0, customizations:[{index:0, slots:[0]*8}]}`）。
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
# 客户端硬上限（HellForge `RegisteredItems.cs:119`：CatalogueCap=InventoryCap=4096；
# 注释明确："past that the game ignores the rest, and a weapon would be held without its attachments"
# —— 2026-11-25 主号症状（970 行 + 注入 3042 ≈ 4012，贴上限；全武器缺"改装"按钮）与之吻合）。
INVENTORY_CAP = 4096
INVENTORY_SAFE_MARGIN = 64          # 给客户端自己的补充留余量


# 武器精通包（progression package type=2，50 条 × 25 级）——2026-11-25 用户提示 + HellForge 证据：
# 武器改装/升级入口需要该武器在 packageProgress 里有条目（同 ship module 机制）。
# 来源：2026-11-20 真机 `/api/Progression/ProgressionPackages` 抓包。
WEAPON_PACKAGES = (
    1949876251, 3439606727, 2221505542, 2659105163, 1334452973,
    4111972552, 883379673, 4090978686, 2373460877, 1973516948,
    1437213432, 2875976550, 1681710644, 3499835822, 1059686006,
    287968734, 1445043045, 3988417885, 3479006272, 1414744964,
    2679158493, 2750223772, 2941409959, 2093204274, 652555970,
    2031945469, 297733241, 1240353314, 1125762146, 3350514626,
    3247913466, 3391943729, 1691930195, 1084659860, 9042909,
    1535490275, 3400574762, 3115977081, 359248235, 2797172057,
    4286173191, 872226585, 1350237306, 934119933, 674723509,
    1715358342, 277818845, 2541413995, 67627790, 4246017227,
)
WEAPON_LEVEL_DEFAULT = 1     # 最小侵入：只让条目存在（等级 1），不动武器升级进度显示

# 改装槽模板（客户端自己的空槽形状，见 `f71b1f23_*`/`bf3a4053_*`）
CUSTOMIZE_SLOT_COUNT = 8

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


def inject_inventory(items, scope=None, discovered=False):
    """把可拥有物品补进 inventory.items[]（原地修改），返回 ``(added, skipped)``。

    ``discovered``：授予行 `isDiscovered`（默认 false —— 真实数据里所有库存行都是 false；
    2026-11-25 发现改成 true 会导致"所有武器缺改装按钮"，见模块注释）。

    **上限保护**：客户端只认前 4096 条库存（见 INVENTORY_CAP 注释）；这里留 64 条余量，
    超出部分不再追加（skipped 计数进日志）。注入顺序保证武器/附件优先（见 ownable_ids）。
    """
    if not isinstance(items, list):
        return 0, 0
    have = _have_mix_ids(items)
    room = INVENTORY_CAP - INVENTORY_SAFE_MARGIN - len(items)
    added = skipped = 0
    for mid in ownable_ids(scope):
        if mid in have:
            continue
        if room <= 0:
            skipped += 1
            continue
        items.append({"mixId": mid, "amount": 1, "isDiscovered": bool(discovered)})
        have.add(mid)
        added += 1
        room -= 1
    return added, skipped


def customizable_weapons() -> list:
    """目录里**有子项（附件）**的 pc1 武器 mixId 列表（保留目录顺序，去重）。

    「改装」界面对每把武器要重算子项（附件）id（HellForge `RegisteredItems.cs:14-17`）：
    `mixId = WeaponChild(attachment.itemId, weapon.mixId)`；没有子项的武器在该界面里没有可选项。
    ⇒ 只给有子项的武器补条目，避免把非可改装武器塞进这份数据。
    """
    rows = catalog_rows()
    parents = set()
    for r in rows:
        try:
            pid = int(r.get("parentId") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid > 0:
            parents.add(pid)
    out, seen = [], set()
    for r in rows:
        if r.get("progressionCategory") != 1:
            continue
        try:
            mid = int(r.get("mixId"))
        except (TypeError, ValueError):
            continue
        if mid > 0 and mid in parents and mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def inject_customizations(doc):
    """给所有可改装武器补一条**空槽**改装条目（原地改 `doc["items"]`），返回新增条数。

    形状取自客户端自己 PUT 过的真实空槽（`f71b1f23_api_Progression_Items_Customize_v2.json`）：
    ``{"mixId32": <武器>, "modes": [], "activeIndex": 0,
       "customizations": [{"index": 0, "slots": [0]*8}]}``。
    已有条目一律不动（玩家的真实预设优先）。
    """
    if not isinstance(doc, dict):
        return 0
    items = doc.get("items")
    if not isinstance(items, list):
        return 0
    have = set()
    for it in items:
        if isinstance(it, dict):
            try:
                have.add(int(it.get("mixId32", it.get("mixId", 0)) or 0))
            except (TypeError, ValueError):
                pass
    added = 0
    for mid in customizable_weapons():
        if mid in have:
            continue
        items.append({"mixId32": mid,
                      "modes": [],
                      "activeIndex": 0,
                      "customizations": [{"index": 0,
                                          "slots": [0] * CUSTOMIZE_SLOT_COUNT}]})
        have.add(mid)
        added += 1
    return added


def inject_inventory_customizations(doc):
    """同上的**扁平**版本：`/api/Progression/inventory` 的 `customization[]`
    （主号 149 条 / 空白号 1 条；形状 `{mixId32, index, activeIndex, slots, modes}`）。

    客户端启动时先拉 inventory（+18 s）再拉 `Items/Customize/v2`（+19 s），两处都喂一遍最稳。
    没有 `customization` 数组时补一个（客户端自己也会发这个键）。返回新增条数。
    """
    if not isinstance(doc, dict):
        return 0
    entries = doc.get("customization")
    if entries is None:
        entries = doc["customization"] = []
    if not isinstance(entries, list):
        return 0
    have = set()
    for it in entries:
        if isinstance(it, dict):
            try:
                have.add((int(it.get("mixId32", 0) or 0), int(it.get("index", 0) or 0)))
            except (TypeError, ValueError):
                pass
    added = 0
    for mid in customizable_weapons():
        if (mid, 0) in have:
            continue
        entries.append({"mixId32": mid,
                        "index": 0,
                        "activeIndex": 0,
                        "slots": [0] * CUSTOMIZE_SLOT_COUNT,
                        "modes": []})
        have.add((mid, 0))
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
    for pid in WEAPON_PACKAGES:
        entry = by_id.get(pid)
        if entry is None:
            progress.append({"id32": pid, "level": WEAPON_LEVEL_DEFAULT,
                             "progress": 0, "sortOrder": 0, "claimedLevels": []})
            changed += 1
        else:
            try:
                level = int(entry.get("level") or 0)
            except (TypeError, ValueError):
                level = 0
            if level < WEAPON_LEVEL_DEFAULT:
                entry["level"] = WEAPON_LEVEL_DEFAULT
                changed += 1
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
