"""DSH_GWE_ITEMS_V1：服务端物品目录补条目（/api/Progression/items）。

研究线实测：克隆同族的已存在记录、只改 itemId/mixId，客户端就会把未发布武器「上架」。
配置示例：
    {"enabled": true, "template": 3866352840, "add": [2112173638]}
    {"enabled": true, "add": [{"id": 2112173638, "template": 200, "progressionCategory": 2}]}
"""

import json

from ..logutil import log
from ..paths import ITEMS_STATE, RUNTIME


# ---- DSH_GWE_ITEMS_V1 : 服务端物品目录补条目（/api/Progression/items） ----
def items_rewrite(plain, spec=None):
    """按 runtime/items_inject.json 往物品目录里补记录。

    配置示例：
        {"enabled": true, "template": 3866352840, "add": [2112173638]}

    `template` = 拿来克隆的 itemId（同族已存在的记录）；`add` = 要补的 itemId 列表。
    克隆只改 itemId / mixId，其余字段（progressionCategory / tags / 价格）保持一致。
    返回 (new_body, added)；无改动时 (None, 0)。
    """
    if spec is None:
        try:
            cfg = json.loads(ITEMS_STATE.read_text(encoding="utf-8"))
        except Exception:
            return None, 0
    else:
        cfg = spec
    if not isinstance(cfg, dict):
        return None, 0
    if not cfg.get("enabled"):
        return None, 0
    try:
        doc = json.loads(plain)
    except Exception:
        return None, 0
    if not isinstance(doc, list):
        return None, 0
    have = set()
    for r in doc:
        if isinstance(r, dict):
            try:
                have.add(int(r.get("itemId", 0)))
            except (TypeError, ValueError):
                pass
    tmpl = None
    try:
        t = int(cfg.get("template", 0) or 0)
    except (TypeError, ValueError):
        t = 0
    if t:
        for r in doc:
            if isinstance(r, dict):
                try:
                    if int(r.get("itemId", 0)) == t:
                        tmpl = r
                        break
                except (TypeError, ValueError):
                    continue
    by_id = {}
    for r in doc:
        if isinstance(r, dict):
            try:
                by_id[int(r.get("itemId", 0))] = r
            except (TypeError, ValueError):
                pass
    have_mix = set()
    for r in doc:
        if isinstance(r, dict):
            try:
                have_mix.add(int(r.get("mixId", 0)))
            except (TypeError, ValueError):
                pass
    # 允许的整行覆盖字段（附件行必须带 parentId / progressionCategory，且 itemId 与 mixId 不同）
    _OVERRIDES = ("itemId", "mixId", "parentId", "progressionCategory", "isConsumable",
                  "requiredLevel", "tags", "requiredItems", "buyPrice", "sellPrice", "maxCap")
    added = 0
    for spec in cfg.get("add") or []:
        overrides = {}
        if isinstance(spec, dict):
            try:
                mid = int(spec.get("id", 0) or spec.get("mixId", 0))
            except (TypeError, ValueError):
                continue
            try:
                src = int(spec.get("template", 0) or 0)
            except (TypeError, ValueError):
                src = 0
            for k in _OVERRIDES:
                if k in spec:
                    overrides[k] = spec[k]
            base = by_id.get(src) if src else tmpl
        else:
            try:
                mid = int(spec)
            except (TypeError, ValueError):
                continue
            base = tmpl
        if not mid or mid in have_mix or mid in have:
            continue
        if base is None:
            continue
        rec = json.loads(json.dumps(base))
        rec["itemId"] = mid
        rec["mixId"] = mid
        rec.update(overrides)
        doc.append(rec)
        have.add(mid)
        have_mix.add(mid)
        added += 1
    if not added:
        return None, 0
    return json.dumps(doc, separators=(",", ":")).encode("utf-8"), added

