"""DSH_SAVE_ACH_V1：`PUT /api/Progression/Achievements` **请求体** → 成就累计值（G5）。

研究线证据（2026-11-23）：

  * 结算后客户端**主动上报完整小列表**：PUT 请求体 141 B（按 `{"achievements":[{"id","value"}]}`
    紧凑写法 ≈ 5–6 条），而主号 `GET /api/Progression` 里只有 4 条 ⇒ 不是"只报本局增量"；
  * 同一次结算后 **44 ms** 内两个客户端各发一次（`x-real-ip` 12 / 14），响应都是 `200 {}`（2 B）
    ⇒ 服务端合并、客户端不读回；
  * 语义倾向**累计覆盖**，但建议落成 **per-key max**：等价累计覆盖、天然幂等（防双计）、
    还能防"客户端用旧快照把值改小"。

请求体真实形状**尚未采样**（现有抓包只落了响应 `{}`），所以解析是**防御式**的：
认三种外壳（`{"achievements":[...]}` / `[...]` / `{"items":[...]}`），行内认 `{id, value}`；
解析不出来就**不写档**（宁可不记，也不猜错把成就写脏），并记一次可操作日志。
"""

import json

from ..paths import ACHIEVEMENTS_PATH

_SHELL_KEYS = ("achievements", "items", "values")


def is_path(path) -> bool:
    """是否成就上报端点（去 query 后精确匹配）。"""
    return str(path or "").split("?", 1)[0].rstrip("/") == ACHIEVEMENTS_PATH


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


def extract_achievements(body) -> dict[str, int]:
    """从上报体抽出 ``{str(id): value}``；形状不认识时返回空 dict（调用方据此不写档）。"""
    doc = _decode(body)
    rows = None
    if isinstance(doc, dict):
        for key in _SHELL_KEYS:
            if isinstance(doc.get(key), list):
                rows = doc[key]
                break
    elif isinstance(doc, list):
        rows = doc
    out: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw_id, raw_value = row.get("id"), row.get("value")
        if raw_id is None or raw_value is None:
            continue
        try:
            aid, value = int(raw_id), int(raw_value)
        except (TypeError, ValueError):
            continue
        if aid < 0 or value < 0:
            continue
        key = str(aid)
        out[key] = max(out.get(key, 0), value)
    return out
