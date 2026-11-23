"""DSH_SAVE_MISSION_V1：`POST /api/Operation/Mission/end` 响应 → 本局奖励增量（G3）。

为什么只读**响应**、不要请求体（研究线 2026-11-23 结论）：
服务端在响应里已经算好了本局该发的东西 —— `experience`（**本局获得值**，如 936）、
`badges[].itemRewards[{mixId,amount}]`、`lootedItemRewards`、`lootedHeavyItemRewards`、
`levelUpRewards`、`progressionPackageUpdates`。MITM 架构下直接**累加落盘**即可；
请求体只在「自己算奖励（离线 mock）」或「防篡改校验」时才需要。

关键取舍（研究线提醒 + 我们对着 5 份真实响应核过）：

  * **`rewards` 是最终入账清单，`badges[].itemRewards` 是明细**。5 份真实响应里恒有
    ``rewards[3608481516] == sum(badges.itemRewards[3608481516]) × 3``
    （1478→4434 / 346→1038 / 334→1002 / 1534→4602；倍数来自响应里的 ``multipliers.factor``），
    所以**默认取 `rewards` 入账**、badges/其它清单当交叉校验；`rewards` 缺失才退回明细求和。
    两条来源都写进日志/事件，实机对一次账就能定 —— 若要切回明细只改 ``ITEM_SOURCE`` 一处。
  * ``progressionPackageUpdates`` 形如 ``{platformAccountId, id32, level, progress}``，与
    `Progression.packageProgress` 同形，且实测**跨局递增（服务端当前值）** ⇒ 按 max 合并，**不累加**。
  * ``campaignWon`` / ``impact`` / ``othersImpact*`` 是战果展示：**不碰**（研究线红线：不伪造社区战果）。
  * 不认识的字段一律**原样忽略**（本模块不改写响应，只抽账）。
"""

from __future__ import annotations

import json

from ..paths import MISSION_END_MARK

# 物品入账来源：``rewards``（服务端最终入账，含 multipliers 倍率）/ ``badges``（明细求和）
ITEM_SOURCE = "rewards"

# 会被本模块消费的顶层字段；其余只记进 unknown_keys（便于以后补语义）
_KNOWN_KEYS = {
    "experience", "badges", "lootedItemRewards", "lootedHeavyItemRewards",
    "levelUpRewards", "rewards", "progressionPackageUpdates", "missionId",
    "missionIndex", "operationId",
}


def is_mission_end(path) -> bool:
    """是否结算端点（去 query 后按子串匹配：``/api/Operation/Mission/end``）。"""
    raw = str(path or "").split("?", 1)[0]
    return MISSION_END_MARK in raw


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _item_map(rows) -> dict[str, int]:
    """``[{"mixId","amount"}]`` → ``{str(mixId): amount}``（同 id 累加、忽略非法行）。"""
    out: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mix = _int(row.get("mixId"), -1)
        amount = _int(row.get("amount"), 0)
        if mix < 0 or amount <= 0:
            continue
        key = str(mix)
        out[key] = out.get(key, 0) + amount
    return out


def _badge_items(badges) -> dict[str, int]:
    """``badges[].itemRewards`` 明细求和。"""
    out: dict[str, int] = {}
    for badge in badges if isinstance(badges, list) else []:
        if not isinstance(badge, dict):
            continue
        for key, amount in _item_map(badge.get("itemRewards")).items():
            out[key] = out.get(key, 0) + amount
    return out


def _decode(body):
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(bytes(body).decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            return None
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return None
    return None


def extract_increments(body) -> dict:
    """从 `Mission/end` 响应体抽出本局增量（纯函数，离线可测）。

    返回::

        {"ok": bool, "has_increment": bool,
         "experience": int,                      # 本局增量（累加到存档 experience）
         "items": {str(mixId): amount},          # 入账物品/货币（来源见 item_source）
         "item_source": "rewards"|"badges"|"none",
         "badge_items": {...}, "other_items": {...}, "rewards_items": {...},   # 交叉校验
         "packages": {str(id32): {"level": int, "progress": int}},            # max 合并
         "mission": {"operation_id", "mission_index", "mission_id"},
         "unknown_keys": [...]}
    """
    doc = _decode(body)
    if not isinstance(doc, dict):
        return {"ok": False, "has_increment": False, "experience": 0, "items": {},
                "item_source": "none", "badge_items": {}, "other_items": {},
                "rewards_items": {}, "packages": {}, "mission": {}, "unknown_keys": []}

    experience = max(0, _int(doc.get("experience"), 0))
    badge_items = _badge_items(doc.get("badges"))
    other_items: dict[str, int] = {}
    for key in ("lootedItemRewards", "lootedHeavyItemRewards", "levelUpRewards"):
        for mix, amount in _item_map(doc.get(key)).items():
            other_items[mix] = other_items.get(mix, 0) + amount
    rewards_items = _item_map(doc.get("rewards"))

    if ITEM_SOURCE == "badges":
        items, source = badge_items, "badges"
    elif rewards_items:
        items, source = rewards_items, "rewards"
    elif badge_items or other_items:
        items, source = badge_items, "badges"       # rewards 缺失 → 退回明细
        for mix, amount in other_items.items():
            items[mix] = items.get(mix, 0) + amount
    else:
        items, source = {}, "none"

    packages = {}
    for row in doc.get("progressionPackageUpdates") or []:
        if not isinstance(row, dict):
            continue
        id32 = _int(row.get("id32"), -1)
        if id32 < 0:
            continue
        packages[str(id32)] = {"level": max(0, _int(row.get("level"), 0)),
                               "progress": max(0, _int(row.get("progress"), 0))}

    mission = {
        "operation_id": _int(doc.get("operationId"), 0) or None,
        "mission_index": _int(doc.get("missionIndex"), 0) or None,
        "mission_id": str(doc.get("missionId") or "").strip() or None,
    }
    return {
        "ok": True,
        "has_increment": bool(experience or items or packages),
        "experience": experience,
        "items": items,
        "item_source": source,
        "badge_items": badge_items,
        "other_items": other_items,
        "rewards_items": rewards_items,
        "packages": packages,
        "mission": mission,
        "unknown_keys": sorted(str(k) for k in doc if k not in _KNOWN_KEYS),
    }


def summarize(inc: dict) -> str:
    """一行摘要（日志/事件用）。"""
    if not isinstance(inc, dict) or not inc.get("ok"):
        return "结算响应不可解析"
    parts = ["+%d exp" % inc.get("experience", 0)]
    items = inc.get("items") or {}
    if items:
        parts.append("+%d 种物品（%s）" % (len(items), inc.get("item_source")))
        # 主要货币给具体数（medals 通常是最大项）
        top = sorted(items.items(), key=lambda kv: -kv[1])[:2]
        parts.append(" ".join("%s×%d" % (k, v) for k, v in top))
    pkgs = inc.get("packages") or {}
    if pkgs:
        parts.append("%d 个包进度" % len(pkgs))
    return " · ".join(parts)
