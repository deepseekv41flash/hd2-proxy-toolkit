"""DSH_SAVE_CONS_V1：`POST /api/Progression/inventory/consume` **请求体** → 库存扣减（G5）。

研究线证据（2026-11-23）：

  * 响应恒 `{}`（2 B）；扣减量**只在请求体**里（形态 `{mixId: number, amount: number, …}`，
    数字记原值）；
  * 真实请求体形状**尚未采样**（现有抓包只落响应），所以解析是**防御式**的：
    认 `{"items":[…]}` / `[…]` / `{"consumables":[…]}` 三种外壳，行内认 `{mixId|mixId32, amount}`；
    解析不出来就**不扣**（钱扣错比不扣更糟）。

扣减口径（与研究线逐条对齐）：

  * ``inventory_amounts[mixId] -= amount``，**下限 0**；
  * **保留行、amount=0，不删行** —— 库存行同时承担「是否拥有该物品」的语义（目录行 + 库存行成对
    才显示），删行可能让物品直接从军械库消失；服务端是否删行我们没有样本，**保留行是安全默认**；
  * 只扣**存档里已跟踪**的行：没跟踪的 mixId 说明本机账本里没有它的基线数量，
    宁可不扣也不凭空造数量（打 INFO 说明，等将来有 inventory 基线同步再覆盖）；
  * 每次扣减打一行 INFO（含本局 missionId，可与结算入账串起来对账）。
"""

import json

from ..paths import CONSUME_PATH

_SHELL_KEYS = ("items", "consumables", "values", "entries")


def is_path(path) -> bool:
    """是否消耗端点（去 query 后精确匹配）。"""
    return str(path or "").split("?", 1)[0].rstrip("/") == CONSUME_PATH


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


def _int(value, default=None):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_consumes(body) -> list[dict]:
    """从消耗请求体抽出 ``[{mixId, amount}]``；形状不认识时返回空列表（调用方据此不扣）。"""
    doc = _decode(body)
    rows = None
    if isinstance(doc, dict):
        for key in _SHELL_KEYS:
            if isinstance(doc.get(key), list):
                rows = doc[key]
                break
        if rows is None and ("mixId" in doc or "mixId32" in doc):
            rows = [doc]                        # 单条目直接摊平
    elif isinstance(doc, list):
        rows = doc
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        mix = _int(row.get("mixId"), None)
        if mix is None:
            mix = _int(row.get("mixId32"), None)
        amount = _int(row.get("amount"), None)
        if mix is None or amount is None or mix < 0 or amount <= 0:
            continue
        out.append({"mixId": mix, "amount": amount})
    return out
