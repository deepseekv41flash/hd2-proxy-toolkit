"""DSH_SAVE_BUY_V1：真正的"解锁/购买"写路径 → 响应里的增量入账（G5+）。

为什么看**响应**而不是请求（旧仓 `variant-net` 逐字节实证，2026-11-06）：

  * `POST /api/Progression/ProgressionPackage/AcquireUnlockableItem`（武器/配件）
    请求（135 B）``{"expectedCost":[{"mixId":3608481516,"amount":5000}],"itemMixId":718265621,
    "targetLevel":7,"packageId32":2221505542}``
    响应（114 B）``{"packageId32":2221505542,"inventoryChanges":[{"mixId":3608481516,"amount":-5000},
    {"mixId":718265621,"amount":1}]}``
  * `POST /api/SeasonPass/item/buy`（战备/季票物品）
    请求（102 B）``{"expectedCost":[{"mixId":1276729503,"amount":85}],"seasonPassItemId":919,"warId":801}``
    响应（130 B）``{"items":[{"mixId":1276729503,"amount":-85},{"mixId":3859732805,"amount":1},
    {"mixId":905852432,"amount":85}],"packageProgress":[]}``

⇒ **负 amount = 扣钱，正 amount = 授予/记账**；直接对响应做增量就能同时覆盖"扣钱 + 解锁物品"。

三个实现约束（研究线 2026-11-23 提醒）：

1. **增量必须幂等/去重**：客户端重试会重复同一份响应；按
   `(packageId32, itemMixId)` / `(seasonPassItemId, warId)` + 短窗口（10 s）去重，绝不双扣；
2. **`SeasonPass/item/buy` 里的 `+85` 不是"获得 85 奖章"**，它是 `medalsSpentMixId`
   （该战团"已花奖章"累计计数器）—— 按普通 mixId 增量 + 处理，但文档/日志不能写成"获得奖章"；
3. 请求里的 `expectedCost` 只作**交叉校验/兜底**（响应缺失时用它扣费）；`targetLevel` 只是 UI 门槛，
   客户端不校验（旧仓 UNLOCK-MAP §3.1）。

本模块是纯函数：只负责"从响应/请求里抽增量 + 生成去重键"，落盘与等待在 `ActiveSave`。
"""

from __future__ import annotations

import json

from ..paths import ACQUIRE_ITEM_PATH, SEASONPASS_BUY_PATH

ACQUIRE = "acquire"
SEASONPASS = "seasonpass"


def kind_of(path) -> str:
    """路径 → 购买类型（``acquire`` / ``seasonpass`` / 空串）。"""
    raw = str(path or "").split("?", 1)[0].rstrip("/")
    if raw == ACQUIRE_ITEM_PATH:
        return ACQUIRE
    if raw == SEASONPASS_BUY_PATH:
        return SEASONPASS
    return ""


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


def _deltas(rows) -> list[dict]:
    """``[{mixId, amount}]`` → 规范化增量（跳过非法行，保留正负号）。"""
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            mix = int(row.get("mixId"))
            amount = int(row.get("amount"))
        except (TypeError, ValueError):
            continue
        if mix < 0 or amount == 0:
            continue
        out.append({"mixId": mix, "amount": amount})
    return out


def extract_acquire(response_body) -> dict:
    """`AcquireUnlockableItem` 响应 → ``{ok, kind, package_id32, deltas}``。"""
    doc = _decode(response_body)
    if not isinstance(doc, dict):
        return {"ok": False, "kind": ACQUIRE, "package_id32": None, "deltas": []}
    try:
        package_id32 = int(doc.get("packageId32"))
    except (TypeError, ValueError):
        package_id32 = None
    deltas = _deltas(doc.get("inventoryChanges"))
    return {"ok": bool(deltas), "kind": ACQUIRE, "package_id32": package_id32,
            "deltas": deltas}


def extract_seasonpass(response_body) -> dict:
    """`SeasonPass/item/buy` 响应 → ``{ok, kind, deltas, package_progress}``。"""
    doc = _decode(response_body)
    if not isinstance(doc, dict):
        return {"ok": False, "kind": SEASONPASS, "deltas": [], "package_progress": []}
    deltas = _deltas(doc.get("items"))
    return {"ok": bool(deltas), "kind": SEASONPASS, "deltas": deltas,
            "package_progress": doc.get("packageProgress") or []}


def extract_expected_cost(request_body) -> list[dict]:
    """从购买**请求体**的 ``expectedCost`` 抽 `[{mixId, amount}]`（正数；兜底/交叉校验用）。"""
    doc = _decode(request_body)
    if not isinstance(doc, dict):
        return []
    return [{"mixId": row["mixId"], "amount": abs(row["amount"])}
            for row in _deltas(doc.get("expectedCost"))]


def request_context(request_body) -> dict:
    """购买请求里的去重上下文：``seasonPassItemId`` / ``warId`` / ``itemMixId``。"""
    doc = _decode(request_body)
    if not isinstance(doc, dict):
        return {}
    out = {}
    for key in ("seasonPassItemId", "warId", "itemMixId"):
        try:
            out[key] = int(doc.get(key))
        except (TypeError, ValueError):
            continue
    return out


def dedupe_key(parsed: dict, context: dict) -> str:
    """生成去重键：够唯一、又能在重试时命中同一条。

    * acquire：``acquire:<packageId32>:<itemMixId>``（itemMixId 在响应里没有，靠"响应增量里唯一正项"）
    * seasonpass：``seasonpass:<seasonPassItemId>:<warId>``（都来自请求体）
    """
    kind = parsed.get("kind") or ""
    if kind == ACQUIRE:
        package = parsed.get("package_id32")
        positives = sorted(d["mixId"] for d in parsed.get("deltas") or [] if d["amount"] > 0)
        item = positives[0] if positives else (context.get("itemMixId") or 0)
        return "acquire:%s:%s" % (package, item)
    return "seasonpass:%s:%s" % (context.get("seasonPassItemId"), context.get("warId"))
