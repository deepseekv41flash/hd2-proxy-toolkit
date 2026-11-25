"""DSH_GWE_INV_V1：拥有的物品清单改写（/api/Progression/inventory）。

两件事：
1. `inventory_rewrite`：往 items[] 里增删 mixId（武器/附件/外观/战备四类分别有开关文件），
   并可补 customization[] 条目；
2. `customize_rewrite`：L2 改装槽快照（/api/Progression/Items/Customize/v2）—— 实测送达但不生效，
   默认关闭，只留作研究开关。
"""

import json

from ..logutil import log
from ..paths import (ATTACH_STATE, COSMETIC_STATE, CUSTOMIZE_STATE, INV_STATE,
                     PROBE_STATE, RUNTIME, STRATAGEM_STATE)


# ---- DSH_GWE_INV_V1 : 拥有的物品清单改写（/api/Progression/inventory） ----
def customize_rewrite(plain, spec=None, unlock_all_enabled=False):
    """改写 L2（/api/Progression/Items/Customize/v2，每把武器的改装槽快照）。

    两条来源，可叠加：
    1. `runtime/customize_inject.json`（研究开关，默认关）：按 edits 改槽位；
    2. `unlock_all_enabled=True`（一键解锁全部物品）：给所有**可改装武器**补空槽条目
       （alpha.4 起；空白号该响应是 `{"items":[]}`，主号是 74 条 —— 缺按钮的头号原因）。

    `spec` 配置示例：
        {"enabled": true,
         "edits": [
           {"mixId": 2112173638,
            "slots": {"1": 3905063732},          # 槽下标 -> optionId
            "allIndexes": true,                  # true=改全部 3 组预设；false=只改 activeIndex
            "createIfMissing": false,
            "baseSlots": [0, 0, 0, 0, 0, 0, 0, 0]  # createIfMissing 时新建条目用的 8 槽
           }]}

    返回 (new_body, 改动数)；无改动时 (None, 0)。
    """
    if spec is None:
        try:
            cfg = json.loads(CUSTOMIZE_STATE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    else:
        cfg = spec
    if not isinstance(cfg, dict):
        cfg = {}
    plan_on = bool(cfg.get("enabled"))
    if not (plan_on or unlock_all_enabled):
        return None, 0
    try:
        doc = json.loads(plain)
    except Exception:
        return None, 0
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        return None, 0

    items = doc["items"]
    by_mix = {}
    for it in items:
        if isinstance(it, dict):
            try:
                by_mix[int(it.get("mixId32", 0))] = it
            except (TypeError, ValueError):
                pass

    changed = 0
    touched = []
    for edit in (cfg.get("edits") or []) if plan_on else []:
        if not isinstance(edit, dict):
            continue
        try:
            mix = int(edit.get("mixId", 0))
        except (TypeError, ValueError):
            continue
        slots_spec = edit.get("slots") or {}
        if not slots_spec:
            continue
        it = by_mix.get(mix)
        if it is None:
            if not edit.get("createIfMissing"):
                continue
            base = edit.get("baseSlots") or [0] * 8
            it = {"mixId32": mix, "modes": [], "activeIndex": 0,
                  "customizations": [{"index": i, "slots": list(base[:8]) + [0] * max(0, 8 - len(base))}
                                     for i in range(3)]}
            items.append(it)
            by_mix[mix] = it
        customs = it.get("customizations") or []
        try:
            active = int(it.get("activeIndex", 0))
        except (TypeError, ValueError):
            active = 0
        for c in customs:
            if not isinstance(c, dict):
                continue
            if not edit.get("allIndexes"):
                try:
                    if int(c.get("index", 0)) != active:
                        continue
                except (TypeError, ValueError):
                    continue
            slots = c.get("slots")
            if not isinstance(slots, list) or len(slots) < 8:
                continue
            for key, val in slots_spec.items():
                try:
                    idx = int(key)
                    oid = int(val)
                except (TypeError, ValueError):
                    continue
                if not (0 <= idx < len(slots)):
                    continue
                if slots[idx] != oid:
                    slots[idx] = oid
                    changed += 1
        touched.append(mix)

    # 一键解锁全部物品（v0.10.1-alpha.4）：给所有可改装武器补空槽条目
    if unlock_all_enabled:
        from .. import unlock_all
        ua_added = unlock_all.inject_customizations(doc)
        if ua_added:
            changed += ua_added
            log("UNLOCK 改装条目 +%d（按运行期目录里带附件的武器展开）" % ua_added)

    if not changed:
        return None, 0
    if plan_on and touched and cfg.get("logEdits", True):
        log("CUSTOMIZE plan applied to mixId(s) %s" % ",".join(str(m) for m in touched))
    return json.dumps(doc, separators=(",", ":")).encode("utf-8"), changed


def inventory_rewrite(plain, spec=None):
    """按 runtime/inventory_inject.json 改写 inventory 响应。

    配置示例：
        {"enabled": true,
         "items":    [{"mixId": 2112173638, "amount": 1, "isDiscovered": false}],
         "remove":   [2308714558],
         "customization": [{"mixId32": 4161086429, "index": 0, "activeIndex": 0,
                            "slots": [1896165189, 3905063732, 2163992125, 0,0,0,0,0],
                            "modes": [0,0,0,0]}]}

    返回 (new_body, added, removed)；没有改动时返回 (None, 0, 0)。
    只动 items / customization 两个数组，其余字段原样保留。
    `added` 含一键解锁补的**库存行 + 改装条目**（alpha.4 起；两者日志分别打点）。
    """
    if spec is None:
        states = []
        for _p in (INV_STATE, ATTACH_STATE, COSMETIC_STATE, STRATAGEM_STATE, PROBE_STATE):
            try:
                states.append(json.loads(_p.read_text(encoding="utf-8")))
            except Exception:
                states.append({})
        if not any(s.get("enabled") for s in states):
            return None, 0, 0

        def _pack(c):
            return (c.get("items") or [], c.get("remove") or [], c.get("customization") or [])
        parts = [_pack(c) for c in states if c.get("enabled")]
        cfg = {"enabled": True,
               "items": [x for p in parts for x in p[0]],
               "remove": [x for p in parts for x in p[1]],
               "customization": [x for p in parts for x in p[2]]}
    else:
        cfg = spec if isinstance(spec, dict) else {}
        if not cfg.get("enabled", True):
            return None, 0, 0
    try:
        doc = json.loads(plain)
    except Exception:
        return None, 0, 0
    items = doc.get("items")
    if not isinstance(items, list):
        return None, 0, 0

    have = set()
    for it in items:
        if isinstance(it, dict):
            try:
                have.add(int(it.get("mixId", 0)))
            except (TypeError, ValueError):
                pass

    removed = 0
    drop = set()
    for v in cfg.get("remove") or []:
        try:
            drop.add(int(v))
        except (TypeError, ValueError):
            pass
    if drop:
        kept = []
        for it in items:
            try:
                mid = int(it.get("mixId", 0)) if isinstance(it, dict) else 0
            except (TypeError, ValueError):
                mid = 0
            if mid in drop:
                removed += 1
                continue
            kept.append(it)
        items = kept
        doc["items"] = items

    added = 0
    for spec in cfg.get("items") or []:
        try:
            mid = int(spec.get("mixId", 0))
        except (TypeError, ValueError):
            continue
        if not mid or mid in have:
            continue
        items.append({"mixId": mid,
                      "amount": int(spec.get("amount", 1)),
                      "isDiscovered": bool(spec.get("isDiscovered", False))})
        have.add(mid)
        added += 1

    cust = doc.get("customization")
    if isinstance(cust, list):
        seen = set()
        for c in cust:
            if isinstance(c, dict):
                try:
                    seen.add((int(c.get("mixId32", 0)), int(c.get("index", 0))))
                except (TypeError, ValueError):
                    pass
        for spec in cfg.get("customization") or []:
            try:
                key = (int(spec.get("mixId32", 0)), int(spec.get("index", 0)))
            except (TypeError, ValueError):
                continue
            if not key[0] or key in seen:
                continue
            slots = [int(x) for x in (spec.get("slots") or [])][:8]
            modes = [int(x) for x in (spec.get("modes") or [])][:4]
            cust.append({"mixId32": key[0], "index": key[1],
                         "activeIndex": int(spec.get("activeIndex", 0)),
                         "slots": slots + [0] * (8 - len(slots)),
                         "modes": modes + [0] * (4 - len(modes))})
            seen.add(key)
            added += 1

    # 一键解锁全部物品（v0.10.1-alpha.2）：按**运行时客户端目录**补行（isDiscovered=true）
    if cfg.get("unlockAll"):
        from .. import unlock_all
        _ua = cfg.get("unlockAll")
        _scope = _ua.get("scope") if isinstance(_ua, dict) else None
        _disc = bool(_ua.get("discovered")) if isinstance(_ua, dict) else False
        ua_added, ua_skipped = unlock_all.inject_inventory(items, _scope, discovered=_disc)
        if ua_added:
            doc["items"] = items
            added += ua_added
            if ua_skipped:
                log("UNLOCK 库存接近上限（%d）：本次跳过 %d 行"
                    % (unlock_all.INVENTORY_CAP, ua_skipped))
        # v0.10.1-alpha.4：改装条目（本响应里的扁平 customization[]，空白号只有 1 条）
        ua_cust = unlock_all.inject_inventory_customizations(doc)
        if ua_cust:
            added += ua_cust
            log("UNLOCK 改装条目 +%d（inventory.customization）" % ua_cust)

    if not (added or removed):
        return None, 0, 0
    return json.dumps(doc, separators=(",", ":")).encode("utf-8"), added, removed

