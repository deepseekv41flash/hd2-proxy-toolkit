"""存档预演（G6）：把一份存档「套」到真实响应样本上，看它会改什么 / 一局结算会加多少。

与 `preview.py` 的分工：

  * `preview.py` 预演**profile 配置**（会在响应里注入什么，属于"配置驱动改写"）；
  * 本模块预演**本机账本**（earned 会把服务端响应抬成什么、打完一局账本怎么长）。

两者都是纯计算：**不联网、不写盘、不读 runtime** —— 存档与样本都由调用方以路径/字典注入
（CLI 默认读 `runtime/saves/_last.json` 指向的档；测试用 tmp 目录）。

为什么要有它：存档的效果要"重启游戏"才可见（客户端结算后不重取 `/api/Progression`），
实机验证成本高；预演能在开游戏前回答「这份档现在会让我看到多少经验/统计」「打完一局会多多少」。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths, saves
from .hooks import mission_end as mission_hook

FIXTURES_REL = Path("fixtures") / "saves"
ACCOUNTS = ("main", "fresh")


# ---------------------------------------------------------------- 载入


def fixtures_dir(base=None) -> Path:
    """存档夹具根目录（默认 `data/fixtures/saves`）。"""
    return Path(base) if base else (paths.DATA_DIR / FIXTURES_REL)


def load_save(save_id=None, root=None, save_file=None) -> tuple[dict, str]:
    """载入一份存档：返回 ``(save_doc, 来源说明)``。

    优先级：``save_file``（显式文件）→ ``save_id``（指定 id）→ `_last.json` 指向的档 → ``local``。
    文件不存在/损坏时退回空档（预演不因为缺档失败）。
    """
    if save_file:
        p = Path(save_file)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return saves.empty_save(), "读取失败（%r）→ 空档" % (e,)
        if not isinstance(doc, dict):
            return saves.empty_save(), "不是 JSON 对象 → 空档"
        doc.setdefault("save_id", saves.normal_save_id(p.stem))
        doc["earned"] = saves._normalize_earned(doc)
        return doc, "文件 %s" % p
    base_root = Path(root) if root else Path(paths.SAVES_DIR)
    sid = save_id
    source = "指定 --save"
    if not sid:
        last = saves.read_last(base_root)
        sid = last.get("last_save_id")
        source = "_last.json" if sid else "无历史（local）"
    if not sid:
        sid = saves.DEFAULT_SAVE_ID
    store = saves.SaveStore(sid, root=base_root)
    return store.load(), "%s（saveId=%s）" % (source, store.save_id)


# ---------------------------------------------------------------- 摘要


def summarize_save(doc: dict) -> dict:
    """存档一屏摘要（人读/JSON 都用它）。"""
    earned = saves._normalize_earned(doc or {})
    identity = (doc or {}).get("identity") or {}
    missions = earned.get("missions") or {}
    stats = saves.stats_profile_of(doc or {})
    return {
        "save_id": (doc or {}).get("save_id"),
        "identity": {"steam_id": identity.get("steam_id"),
                     "hd2_account_id": identity.get("hd2_account_id"),
                     "source": identity.get("source"),
                     "identified_at": identity.get("identified_at")},
        "catalog_build": (doc or {}).get("catalog_build"),
        "updated_at": (doc or {}).get("updated_at"),
        "experience": saves._as_int(earned.get("experience")),
        "achievements": len(earned.get("achievements") or {}),
        "package_progress": len(earned.get("package_progress") or {}),
        "inventory_amounts": len(earned.get("inventory_amounts") or {}),
        "inventory_ids": len(earned.get("inventory_ids") or []),
        "purchased_season_pass_items": len(earned.get("purchased_season_pass_items") or []),
        "stats_fields": len(stats),
        "missions_count": saves._as_int(missions.get("count")),
        "last_mission": missions.get("last"),
    }


# ---------------------------------------------------------------- 合并预演


def _diff_fields(before: dict, after: dict, *, max_items: int = 20) -> list[dict]:
    """顶层字段差异（``[{field, before, after}]``）。"""
    out = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            out.append({"field": key, "before": before.get(key), "after": after.get(key)})
            if len(out) >= max_items:
                break
    return out


def _merge_one(kind: str, body: bytes, save_doc: dict) -> dict:
    """把存档套到一份样本响应上，返回 ``{changed, diffs, applied}``。"""
    before = json.loads(body.decode("utf-8"))
    if kind == "progression":
        out, changed = saves.apply_to_progression(body, save_doc)
    elif kind == "stats":
        out, changed = saves.apply_to_stats(body, save_doc)
    else:                                       # inventory
        out, changed = saves.apply_to_inventory(body, save_doc)
    after = out if isinstance(out, dict) else json.loads(out.decode("utf-8"))
    return {"changed": changed, "applied": bool(changed),
            "diffs": _diff_fields(before, after)}


def _inventory_diff(body: bytes, save_doc: dict, *, max_items: int = 20) -> dict:
    """库存差异按 mixId 给（行级，比顶层字段更有用）。"""
    before = {int(r["mixId"]): saves._as_int(r.get("amount"))
              for r in (json.loads(body.decode("utf-8")).get("items") or [])
              if isinstance(r, dict) and r.get("mixId") is not None}
    out, changed = saves.apply_to_inventory(body, save_doc)
    after_doc = out if isinstance(out, dict) else json.loads(out.decode("utf-8"))
    diffs = []
    for row in after_doc.get("items") or []:
        if not isinstance(row, dict) or row.get("mixId") is None:
            continue
        mix = int(row["mixId"])
        amount = saves._as_int(row.get("amount"))
        if before.get(mix) != amount:
            diffs.append({"mixId": mix, "before": before.get(mix), "after": amount})
        if len(diffs) >= max_items:
            break
    return {"changed": changed, "applied": bool(changed), "diffs": diffs}


def project_mission(save_doc: dict, mission_body, *, label: str = "") -> dict:
    """模拟一局结算：返回本局增量 + 结算后的账本投影（不写盘）。"""
    inc = mission_hook.extract_increments(mission_body)
    if not inc.get("ok"):
        return {"ok": False, "label": label, "reason": "结算样本不可解析"}
    earned = saves._normalize_earned(save_doc or {})
    before_exp = saves._as_int(earned.get("experience"))
    after_exp = before_exp + saves._as_int(inc.get("experience"))
    before_amounts = dict(earned.get("inventory_amounts") or {})
    after_amounts = dict(before_amounts)
    for mix, amount in (inc.get("items") or {}).items():
        after_amounts[str(mix)] = saves._as_int(after_amounts.get(str(mix))) + saves._as_int(amount)
    item_delta = [{"mixId": mix, "amount": amount,
                   "before": saves._as_int(before_amounts.get(mix)),
                   "after": after_amounts.get(mix)}
                  for mix, amount in (inc.get("items") or {}).items()]
    return {"ok": True, "label": label,
            "mission": inc.get("mission") or {},
            "item_source": inc.get("item_source"),
            "experience_delta": saves._as_int(inc.get("experience")),
            "experience_before": before_exp, "experience_after": after_exp,
            "item_delta": item_delta,
            "packages": inc.get("packages") or {},
            "unknown_keys": inc.get("unknown_keys") or []}


# ---------------------------------------------------------------- 总入口


def preview(save_doc=None, *, save_id=None, root=None, save_file=None,
            base_dir=None, mission_names=None) -> dict:
    """存档预演总入口：摘要 + （main/fresh × progression/stats/inventory）合并 + 结算投影。

    返回 ``{"source","save","merge":{"main":{...},"fresh":{...}},"missions":[...],"warnings":[...]}``
    """
    warnings = []
    if save_doc is None:
        save_doc, source = load_save(save_id=save_id, root=root, save_file=save_file)
    else:
        source = "调用方提供"
    base = fixtures_dir(base_dir)
    result = {"source": source, "fixtures_dir": str(base),
              "save": summarize_save(save_doc), "merge": {}, "missions": [],
              "warnings": warnings}
    if not base.is_dir():
        warnings.append("存档夹具目录不存在（%s）：只能看摘要" % base)
        return result

    for account in ACCOUNTS:
        folder = base / account
        item = {}
        for name, kind in (("progression", "progression"), ("stats_profile", "stats"),
                           ("inventory", "inventory")):
            path = folder / ("%s.json" % name)
            if not path.exists():
                continue
            try:
                body = path.read_bytes()
                if kind == "inventory":
                    item[name] = _inventory_diff(body, save_doc)
                else:
                    item[name] = _merge_one(kind, body, save_doc)
            except Exception as e:            # noqa: BLE001 - 预演失败不该中断
                warnings.append("%s/%s 预演失败：%r" % (account, name, e))
        result["merge"][account] = item

    mission_dir = base / "mission_end"
    if mission_dir.is_dir():
        names = list(mission_names or sorted(p.name for p in mission_dir.glob("*.json")))
        # 默认只投影"典型一局"，避免把 5 份样本全列出来（--mission 可指定）
        for name in names[:1]:
            path = mission_dir / name
            try:
                result["missions"].append(
                    project_mission(save_doc, path.read_bytes(), label=name))
            except Exception as e:            # noqa: BLE001
                warnings.append("结算样本 %s 预演失败：%r" % (name, e))
    return result


# ---------------------------------------------------------------- 人读文本


def format_text(result: dict, max_diffs: int = 6) -> str:
    """把 preview() 结果排成人读文本（CLI 用）。"""
    save = result.get("save") or {}
    lines = ["存档预演 · saveId=%s（%s）" % (save.get("save_id") or "?", result.get("source"))]
    identity = save.get("identity") or {}
    if identity.get("steam_id"):
        lines.append("  身份：steam %s%s" % (
            identity["steam_id"],
            "（%s）" % identity["source"] if identity.get("source") else ""))
    else:
        lines.append("  身份：未识别（local 档）")
    lines.append("  经验 %d · 成就 %d · 包进度 %d · 库存 %d · 统计 %d 项 · 结算 %d 局"
                 % (save.get("experience", 0), save.get("achievements", 0),
                    save.get("package_progress", 0), save.get("inventory_amounts", 0),
                    save.get("stats_fields", 0), save.get("missions_count", 0)))
    if save.get("catalog_build"):
        lines.append("  目录：%s" % save["catalog_build"])

    for account, fixtures in (result.get("merge") or {}).items():
        lines.append("")
        lines.append("合并到 %s/ 样本：" % account)
        for name, info in fixtures.items():
            title = {"progression": "Progression 根", "stats_profile": "Stats/profile",
                     "inventory": "库存"}.get(name, name)
            if not info.get("applied"):
                lines.append("  · %s：无改动" % title)
                continue
            lines.append("  · %s：%d 处变化" % (title, info.get("changed", 0)))
            for diff in (info.get("diffs") or [])[:max_diffs]:
                if "mixId" in diff:
                    lines.append("      mixId %s：%s → %s"
                                 % (diff["mixId"], diff.get("before"), diff.get("after")))
                else:
                    lines.append("      %s：%s → %s" % (diff["field"], diff.get("before"),
                                                       _short(diff.get("after"))))

    for proj in result.get("missions") or []:
        lines.append("")
        if not proj.get("ok"):
            lines.append("模拟一局结算（%s）：%s" % (proj.get("label"), proj.get("reason")))
            continue
        lines.append("模拟一局结算（%s）：经验 +%d（%d → %d）"
                     % (proj.get("label"), proj.get("experience_delta"),
                        proj.get("experience_before"), proj.get("experience_after")))
        for delta in (proj.get("item_delta") or [])[:max_diffs]:
            lines.append("      mixId %s：+%d（%s → %s）" % (
                delta["mixId"], delta["amount"], delta.get("before"), delta.get("after")))
        if proj.get("packages"):
            lines.append("      包进度 %d 项（按 max 合并）" % len(proj["packages"]))
        if proj.get("unknown_keys"):
            lines.append("      未消费字段：%s" % "、".join(proj["unknown_keys"][:8]))

    warnings = result.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("注意：")
        for warn in warnings:
            lines.append("  ! %s" % warn)
    return "\n".join(lines)


def _short(value, limit: int = 60):
    """长值截断显示（列表/字典只显示前若干字符）。"""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else str(value)
    return text if len(text) <= limit else text[:limit] + "…"
