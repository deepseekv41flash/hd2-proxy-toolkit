"""离线预演：把 profile 套到样本响应上，回答「到底会改什么」。

为什么要有它：
  * 实机验证要装证书 + 改 hosts + 开游戏，成本高；而 profile 写错（星球没选、变种名拼错、
    物品模板不在目录里）在实机上只表现为「什么都没发生」，很难排查。
  * 预演用 `data/samples/` 里裁剪过的真实结构响应，跑**同一批钩子**（model / hooks/*），
    把「会新增/修改哪些条目」和「为什么预演看不到变化」提前说清楚。

边界（有意为之）：
  * 不发网络、不写磁盘、不读 `runtime/*.json`：钩子一律显式传 `spec=...`；
    spec 为 None 时**不调用钩子**（旧行为会去读 runtime 文件，那样预演就不纯了）。
  * warinfo 的 `record_planet_settings` 在预演里被剥掉：它是「抓 live 值落盘」，不是改写。
  * 样本是裁剪过的：样本里没有的星球/物品在预演里看不到变化，但实机可能仍然生效 ——
    这类情况一律给 warning，不假装「不会生效」。
"""

import json
from pathlib import Path

from . import config, logutil, model, paths
from .hooks import inventory as inventory_hook
from .hooks import items as items_hook
from .hooks import status as status_hook
from .hooks import warinfo as warinfo_hook

FIXTURE_NAMES = ("status", "warinfo", "inventory", "items", "customize")

_FIXTURE_LABELS = {
    "status": "战况 Status",
    "warinfo": "星球 WarInfo",
    "inventory": "物品库存",
    "items": "物品目录",
    "customize": "L2 改装（实验）",
}

_STATUS_LIST_LABELS = {
    "planetActiveEffects": "星球效果",
    "campaigns": "战役",
    "planetAttacks": "攻击边",
    "planetEvents": "星球事件",
    "planetRegions": "分区状态",
    "planetStatus": "星球节点",
    "globalEvents": "全局事件",
    "jointOperations": "联合作战",
}


# ---------------------------------------------------------------- 小工具


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_json(path):
    """读 JSON，返回 (doc | None, error | None)。"""
    p = Path(path)
    if not p.exists():
        return None, "文件不存在：%s" % p
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:      # noqa: BLE001
        return None, "读取 %s 失败：%r" % (p, e)


def load_catalog_doc(path=None):
    """读变种目录（默认 `data/legacy/variant_catalog.json`，与引擎 --catalog 默认一致）。"""
    p = Path(path) if path else paths.LEGACY_DIR / "variant_catalog.json"
    doc, err = _load_json(p)
    return (doc if isinstance(doc, dict) else None), err


def samples_dir_default():
    return Path(paths.SAMPLES_DIR)


def _noop(**counts):
    out = {"counts": dict(counts), "changes": [], "warnings": [], "applied": False}
    return out


def _change(kind, summary, **fields):
    item = {"kind": kind, "summary": summary}
    item.update(fields)
    return item


# ---------------------------------------------------------------- status


def _status_snapshot(doc):
    counts = {}
    for key in _STATUS_LIST_LABELS:
        if isinstance(doc.get(key), list):
            counts[key] = len(doc[key])
    owners = {}
    for row in doc.get("planetStatus") or []:
        if isinstance(row, dict):
            owners[row.get("index")] = row.get("owner")
    globals_ = {}
    for ev in doc.get("globalEvents") or []:
        if isinstance(ev, dict):
            globals_[ev.get("eventId")] = len(ev.get("effectIds") or [])
    effects = set()
    for row in doc.get("planetActiveEffects") or []:
        if isinstance(row, dict):
            effects.add((row.get("index"), row.get("galacticEffectId")))
    return {"counts": counts, "owners": owners, "globals": globals_, "effects": effects}


def _status_extra_changes(before, after):
    changes = []
    # planetActiveEffects 精确定位到「哪颗星 + 哪个效果」；其它数组只报条数增减
    after_effects = set()
    for row in after.get("planetActiveEffects") or []:
        if isinstance(row, dict):
            after_effects.add((row.get("index"), row.get("galacticEffectId")))
    for planet, eid in sorted(after_effects - before["effects"]):
        changes.append(_change(
            "effect", "星球 %s 追加效果 %s" % (planet, eid), planet=planet, effect_id=eid))

    for key, old_n in before["counts"].items():
        if key == "planetActiveEffects":
            continue                  # 上面已经精确报了
        now = len(after.get(key) or [])
        if now > old_n:
            changes.append(_change(
                "status_extra", "结构化改写：%s +%d 条"
                % (_STATUS_LIST_LABELS.get(key, key), now - old_n),
                key=key, delta=now - old_n))
    for event_id, old_n in before["globals"].items():
        row = next((e for e in after.get("globalEvents") or []
                    if isinstance(e, dict) and e.get("eventId") == event_id), None)
        if row is None:
            continue
        now = len(row.get("effectIds") or [])
        if now > old_n:
            changes.append(_change(
                "global_effects", "全局事件 %s 追加 %d 个效果" % (event_id, now - old_n),
                event_id=event_id, delta=now - old_n))
    for index, old_owner in before["owners"].items():
        row = next((r for r in after.get("planetStatus") or []
                    if isinstance(r, dict) and r.get("index") == index), None)
        if row is not None and row.get("owner") != old_owner:
            changes.append(_change(
                "owner", "星球 %s 归属 %s → %s" % (index, old_owner, row.get("owner")),
                planet=index, before=old_owner, after=row.get("owner")))
    return changes


def _preview_status(spec, raw):
    plan = spec.status_plan or {}
    extra = spec.status_extra
    if not plan and not extra:
        return _noop(effects=0, extra=0, filtered=0)
    doc = json.loads(raw)
    resolved, filtered = model.resolve_plan(doc, plan)

    have = {(e.get("index"), e.get("galacticEffectId"))
            for e in (doc.get("planetActiveEffects") or []) if isinstance(e, dict)}
    changes = []
    for planet in sorted(resolved):
        for eid in resolved[planet]:
            if (planet, eid) in have:
                continue
            changes.append(_change(
                "effect", "星球 %d 追加效果 %d" % (planet, eid),
                planet=planet, effect_id=eid))

    warnings = []
    for planet, name, faction, owner in filtered:
        warnings.append("变种 %s（%s）与星球 %d 的 owner=%s 不同阵营，实机会被过滤掉"
                        % (name, faction, planet, owner or "unknown"))

    extra_changes = []
    if extra:
        probe = json.loads(raw)
        before = _status_snapshot(probe)
        status_hook.apply_extra(probe, extra)
        extra_changes = _status_extra_changes(before, probe)
        if not extra_changes:
            warnings.append("status 的结构化改写（campaigns/owner…）在样本里没有产生新增："
                            "条目已存在会被去重，或目标星球不在样本里")
    changes.extend(extra_changes)
    # 变种计划与 planet_effects 原始通道指向同一条目时只报一次
    unique, seen = [], set()
    for change in changes:
        if change["summary"] in seen:
            continue
        seen.add(change["summary"])
        unique.append(change)
    changes = unique

    _body, added = model.rewrite_status(raw, resolved, extra)
    return {"counts": {"effects": sum(1 for c in changes if c["kind"] == "effect"),
                       "extra": len(extra_changes), "filtered": len(filtered),
                       "hook_added": int(added)},
            "changes": changes, "warnings": warnings, "applied": bool(added)}


# ---------------------------------------------------------------- warinfo


def _preview_warinfo(spec, raw):
    cfg = spec.warinfo
    if not cfg:
        return _noop(settings_hash=0, planet_infos=0)
    want = cfg.get("settings_hash") or {}
    adds = cfg.get("planet_infos") or []
    if not want and not adds:
        out = _noop(settings_hash=0, planet_infos=0)
        if cfg.get("record_planet_settings"):
            out["warnings"].append(
                "只开了「记录星球 settingsHash」（capture.planet_settings），它不改写响应，"
                "预演里没有增量")
        return out

    doc = json.loads(raw)
    infos = {}
    for row in doc.get("planetInfos") or []:
        if isinstance(row, dict):
            infos[row.get("index")] = row

    changes, warnings = [], []
    for key, value in want.items():
        index = _int(key)
        new_hash = _int(value)
        if index is None or new_hash is None:
            warnings.append("settings_hash 条目 %r → %r 不是整数，引擎会忽略" % (key, value))
            continue
        new_hash &= 0xFFFFFFFF
        row = infos.get(index)
        if row is None:
            warnings.append("样本 warinfo 里没有星球 %s：预演看不到变化；"
                            "实机 live warinfo 里有这颗星时才会改写" % index)
            continue
        old_hash = row.get("settingsHash")
        if old_hash == new_hash:
            continue
        changes.append(_change(
            "settings_hash",
            "星球 %s 生态 settingsHash 0x%08X → 0x%08X" % (index, _int(old_hash) or 0, new_hash),
            planet=index, before=old_hash, after=new_hash))
    for item in adds:
        if not isinstance(item, dict):
            continue
        index = _int(item.get("index"))
        if index is None:
            warnings.append("planet_infos 里有一条没有 index，引擎会忽略")
            continue
        if index in infos:
            warnings.append("星球 %d 在样本 warinfo 里已存在，实机同样会跳过追加"
                            "（要补身份请先删掉原条目）" % index)
            continue
        changes.append(_change("planet_info", "追加星球身份 index=%d（休眠星补节点身份）" % index,
                               planet=index))

    sim = {k: v for k, v in cfg.items() if k != "record_planet_settings"}
    _body, changed = warinfo_hook.apply(raw, spec=sim)
    return {"counts": {"settings_hash": sum(1 for c in changes
                                            if c["kind"] == "settings_hash"),
                       "planet_infos": sum(1 for c in changes
                                           if c["kind"] == "planet_info"),
                       "hook_changed": int(changed)},
            "changes": changes, "warnings": warnings, "applied": bool(changed)}


# ---------------------------------------------------------------- inventory


def _preview_inventory(spec, raw):
    cfg = spec.inventory
    if not cfg or not cfg.get("enabled", True):
        return _noop(items=0, remove=0, customization=0)
    doc = json.loads(raw)
    have = set()
    for it in doc.get("items") or []:
        if isinstance(it, dict):
            mid = _int(it.get("mixId"))
            if mid:
                have.add(mid)

    changes, warnings = [], []
    for row in cfg.get("items") or []:
        mid = _int(row.get("mixId")) if isinstance(row, dict) else None
        if not mid:
            warnings.append("inventory.items 里有一条没有 mixId，引擎会忽略")
            continue
        if mid in have:
            continue                      # 已拥有：实机也不会有变化
        changes.append(_change("inventory_add", "解锁物品 mixId %d" % mid, mix_id=mid))
    for value in cfg.get("remove") or []:
        mid = _int(value)
        if not mid:
            continue
        if mid not in have:
            warnings.append("样本库存里没有 mixId %d，移除在预演里看不到；实机会按 live 数据生效"
                            % mid)
            continue
        changes.append(_change("inventory_remove", "移除物品 mixId %d" % mid, mix_id=mid))

    seen_cust = set()
    for row in doc.get("customization") or []:
        if isinstance(row, dict):
            seen_cust.add((_int(row.get("mixId32")), _int(row.get("index"))))
    for row in cfg.get("customization") or []:
        if not isinstance(row, dict):
            continue
        key = (_int(row.get("mixId32")), _int(row.get("index")))
        if not key[0]:
            warnings.append("inventory.customization 里有一条没有 mixId32，引擎会忽略")
            continue
        if key in seen_cust:
            continue
        changes.append(_change("inventory_custom", "补改装预设 mixId32=%s index=%s"
                               % (key[0], key[1]), mix_id=key[0]))
        seen_cust.add(key)

    _body, added, removed = inventory_hook.inventory_rewrite(raw, spec=cfg)
    return {"counts": {"items_added": added, "items_removed": removed,
                       "customization": sum(1 for c in changes
                                            if c["kind"] == "inventory_custom")},
            "changes": changes, "warnings": warnings, "applied": bool(added or removed)}


# ---------------------------------------------------------------- items


def _preview_items(spec, raw):
    cfg = spec.items
    if not cfg or not cfg.get("add"):
        return _noop(items=0)
    doc = json.loads(raw)
    if not isinstance(doc, list):
        return _noop(items=0)
    by_id, have_mix = {}, set()
    for rec in doc:
        if not isinstance(rec, dict):
            continue
        rid = _int(rec.get("itemId"))
        if rid:
            by_id[rid] = rec
        mix = _int(rec.get("mixId"))
        if mix:
            have_mix.add(mix)

    template = _int(cfg.get("template"))
    changes, warnings = [], []
    for row in cfg.get("add") or []:
        if isinstance(row, dict):
            mid = _int(row.get("id")) or _int(row.get("mixId"))
            src = _int(row.get("template")) or template
        else:
            mid, src = _int(row), template
        if not mid:
            warnings.append("items.add 里有一条没有 id/mixId，引擎会忽略")
            continue
        if mid in by_id or mid in have_mix:
            continue
        base = by_id.get(src) if src else by_id.get(template)
        if base is None:
            if src or template:
                warnings.append("克隆模板 itemId %s 不在样本目录里，预演展示不了；"
                                "实机 live 目录里有这条才生效" % (src or template))
            else:
                warnings.append("items.add 没有模板 itemId（items.template 为空），引擎不会上架")
            continue
        changes.append(_change("items_add", "物品目录补 itemId %d（克隆模板 %d）"
                               % (mid, base.get("itemId")), item_id=mid))
    _body, added = items_hook.items_rewrite(raw, spec=cfg)
    return {"counts": {"items": added},
            "changes": changes, "warnings": warnings, "applied": bool(added)}


# ---------------------------------------------------------------- customize


def _customize_slot_diff(raw, spec):
    """跑一次 customize 钩子，按 (mixId, 槽) 给出前后差异（钩子返回 None 时为空）。"""
    before = json.loads(raw)
    body, _hits = inventory_hook.customize_rewrite(raw, spec=spec)
    if body is None:
        return []
    after = json.loads(body)
    before_map, after_map = {}, {}
    for doc, bucket in ((before, before_map), (after, after_map)):
        for it in doc.get("items") or []:
            if not isinstance(it, dict):
                continue
            mix = _int(it.get("mixId32"))
            for cust in it.get("customizations") or []:
                if not isinstance(cust, dict):
                    continue
                bucket[(mix, _int(cust.get("index")))] = list(cust.get("slots") or [])
    out = []
    for key, old_slots in before_map.items():
        new_slots = after_map.get(key)
        if new_slots is None:
            continue
        for i, (old, new) in enumerate(zip(old_slots, new_slots)):
            if old != new:
                out.append((key, i, old, new))
    return out


def _preview_customize(spec, raw):
    cfg = spec.customize
    if not cfg or not cfg.get("enabled") or not cfg.get("edits"):
        out = _noop(edits=0)
        out["warnings"].append("L2 改装（实验）未启用：研究线结论是「送达但客户端不生效」，默认关闭")
        return out
    diffs = _customize_slot_diff(raw, cfg)
    changes = [_change("customize_slot", "mixId %s 第 %d 槽 %s → %s（L2 实验）"
                       % (key[0], slot, old, new), mix_id=key[0], slot=slot,
                       before=old, after=new)
               for key, slot, old, new in diffs]
    warnings = []
    if not changes:
        warnings.append("L2 改装在样本里没有产生槽位变化：条目不存在（可开 createIfMissing）"
                        "或槽值已经相同")
    return {"counts": {"slots": len(changes)},
            "changes": changes, "warnings": warnings, "applied": bool(changes)}


# ---------------------------------------------------------------- 入口

_RUNNERS = {
    "status": _preview_status,
    "warinfo": _preview_warinfo,
    "inventory": _preview_inventory,
    "items": _preview_items,
    "customize": _preview_customize,
}


def _pick_fixtures(fixtures, warnings):
    if fixtures is None:
        return list(FIXTURE_NAMES)
    raw = [fixtures] if isinstance(fixtures, str) else list(fixtures)
    names = []
    for name in raw:
        key = str(name or "").strip().lower()
        if not key:
            continue
        if key not in FIXTURE_NAMES:
            warnings.append("未知样本 %r（可选：%s），已忽略"
                            % (name, "、".join(FIXTURE_NAMES)))
            continue
        if key not in names:
            names.append(key)
    return names


def preview(profile, catalog_doc=None, samples_dir=None, fixtures=None):
    """把 profile 套到样本上，返回结构化 diff。纯函数（只读样本/目录文件，不写盘）。

    profile: schema v2 profile（dict）。
    catalog_doc: 变种目录 doc；None = 读 `data/legacy/variant_catalog.json`。
    samples_dir: 样本目录；None = `data/samples`。
    fixtures: None=全部 / "status" / ["status", "inventory"] ...

    返回 {"profile","passthrough","samples_dir","fixtures":{name:{counts,changes,warnings,applied}},
          "warnings":[...],"totals":{"changes","applied"}}。
    """
    warnings = []
    if catalog_doc is None:
        catalog_doc, err = load_catalog_doc()
        if err:
            warnings.append("变种目录不可用（%s）：变种计划会是空的" % err)
    spec = config.to_engine_spec(profile or {}, catalog_doc)
    warnings.extend(spec.warnings or [])
    if spec.passthrough:
        warnings.append("profile 当前是直通模式（passthrough=true）：实机不会改写。"
                        "下面是「关闭直通后」的增量，确认无误后去设置里关掉直通。")

    names = _pick_fixtures(fixtures, warnings)
    base = Path(samples_dir) if samples_dir else samples_dir_default()
    result = {"profile": spec.profile_name, "passthrough": bool(spec.passthrough),
              "samples_dir": str(base), "fixtures": {}, "warnings": warnings,
              "totals": {"changes": 0, "applied": 0}}
    for name in names:
        raw, err = _load_json(base / ("%s.json" % name))
        if raw is None:
            result["fixtures"][name] = {
                "counts": {}, "changes": [], "warnings": [err or "样本缺失"],
                "applied": False, "missing": True}
            continue
        try:
            with logutil.quiet():       # 预演是纯计算：不 print、不写 proxy.log
                res = _RUNNERS[name](spec, json.dumps(raw).encode("utf-8"))
        except Exception as e:      # noqa: BLE001  —— 预演失败不该让 GUI/CLI 崩
            res = {"counts": {}, "changes": [],
                   "warnings": ["预演失败：%r" % e], "applied": False}
        res.setdefault("changes", [])
        res.setdefault("warnings", [])
        res["change_count"] = len(res["changes"])
        result["totals"]["changes"] += res["change_count"]
        if res.get("applied"):
            result["totals"]["applied"] += 1
        result["fixtures"][name] = res
    return result


def _fixture_title(name):
    return _FIXTURE_LABELS.get(name, name)


def format_text(result, max_changes=40):
    """把 preview() 结果排成人读文本（CLI / GUI 弹窗共用）。"""
    lines = ["离线预演 · profile=%s · %s"
             % (result.get("profile") or "(未命名)",
                "直通模式（实机不改写）" if result.get("passthrough") else "改写模式")]
    lines.append("样本目录：%s" % result.get("samples_dir"))
    lines.append("")
    shown = 0
    truncated = False
    for name, res in (result.get("fixtures") or {}).items():
        title = _fixture_title(name)
        if res.get("missing"):
            lines.append("· %s：样本缺失（%s）" % (title, "；".join(res.get("warnings") or [])))
            continue
        count = res.get("change_count", len(res.get("changes") or []))
        flag = "会改写" if res.get("applied") else "无改写"
        lines.append("· %s：%d 处增量（%s）" % (title, count, flag))
        for change in res.get("changes") or []:
            if shown >= max_changes:
                truncated = True
                break
            lines.append("  - %s" % change.get("summary", ""))
            shown += 1
        for warn in res.get("warnings") or []:
            lines.append("  ! %s" % warn)
    if truncated:
        lines.append("  …（增量过多，已截断到 %d 条；完整内容用 --json）" % max_changes)
    lines.append("")
    lines.append("合计：%d 处增量，%d 类响应会被改写"
                 % (result.get("totals", {}).get("changes", 0),
                    result.get("totals", {}).get("applied", 0)))
    if result.get("warnings"):
        lines.append("")
        lines.append("注意：")
        for warn in result["warnings"]:
            lines.append("  ! %s" % warn)
    return "\n".join(lines)
