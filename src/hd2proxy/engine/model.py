"""配置+目录+选择 → 「星球 → [effect id]」计划（M1 从 legacy_proxy.py 抽出）。

`Mod` 是状态机：目录、面板选择（热重载）、玩家当前星球、粘性星球上限 3。
`resolve_plan` 按星球 owner 过滤跨阵营词条；`rewrite_status` 把计划写进 Status 响应。
"""

import json
import threading

from . import paths
from .catalog import (FACTION_AUTOMATON, FACTION_ILLUMINATE, FACTION_TERMINID,
                      FACTION_UNIVERSAL, MAX_STRATAGEMS, OWNER_FACTIONS,
                      owner_faction, variant_faction)
from .hooks import status as status_hook
from .logutil import log
from .paths import (SELECTION, STATUS_FILE, STRATAGEM_CATALOG, STRATAGEM_SELECTION)


class Mod:
    """配置 + 目录 + 面板选择：把「变种名」翻译成「星球 → [tag, 玩法]」。

    优先级：面板选择（runtime/selection.json）> config.json 的 targets。
    面板模式下面板只写变种名，目标星球自动跟随玩家正在选的星球（从 /api/lobby 请求里读）。
    """

    def __init__(self, cfg, catalog, meta=None):
        self.host = cfg["host"]
        self.listen_ip = cfg.get("listenIp") or "127.0.0.1"
        self.port = int(cfg.get("port", 443))
        self.upstream_ip = cfg.get("upstreamIp") or None
        self.upstream_test = cfg.get("upstreamTest") or None   # "127.0.0.1:9099"，测试用明文上游
        self.passthrough = bool(cfg.get("passthrough", False))
        self.allow_dev = bool(cfg.get("allowDevFlags", False))
        self.catalog = catalog
        self.aliases = cfg.get("_aliases") or {}
        self.variant_meta = dict(meta or cfg.get("_meta") or {})
        for alias, target in self.aliases.items():
            if target in self.variant_meta:
                self.variant_meta[alias] = self.variant_meta[target]
        try:
            sdoc = json.loads(STRATAGEM_CATALOG.read_text(encoding="utf-8"))
            self.stratagem_catalog = {
                int(x["id"]): x for x in sdoc.get("items") or []
                if isinstance(x, dict) and "id" in x
            }
        except Exception as e:
            log("stratagem_catalog.json 读取失败: %r" % e)
            self.stratagem_catalog = {}
        self.plan = {}
        self.target_names = {}
        self.skipped = []
        for t in cfg.get("targets") or []:
            planet = t.get("planet")
            name = t.get("variant")
            ids = catalog.get(name)
            if not isinstance(planet, int) or not (0 <= planet <= 400):
                self.skipped.append(("planet", planet, name))
                continue
            if not ids:
                self.skipped.append(("variant", planet, name))
                continue
            self.plan[planet] = list(ids)
            self.target_names[planet] = name
        # 面板状态
        self.planet = None            # 玩家当前选中的星球（/api/lobby 里读到的）
        self.sticky = []              # 本次会话注入过的星球（粘性：不撤销，最多 3 颗）
        # 1.18：把**上次会话**注入过的星球继承过来。
        # 为什么：实测发现客户端只在游戏启动/登录时拉一次 Status，而那一发往往早于
        # "玩家在哪颗星球"的报告 —— 于是第一局经常什么都不改，要重启一次游戏才生效。
        # 有了这份继承，代理重启后的第一发 Status 就能直接改。
        try:
            prev = json.loads(STATUS_FILE.read_text(encoding="utf-8-sig"))
            for p in (prev.get("planets") or [])[:3]:
                if isinstance(p, int) and p not in self.sticky:
                    self.sticky.append(p)
            if self.sticky:
                log("继承上次会话的星球: %s（第一发 Status 就能改写）" % self.sticky)
        except Exception:
            pass
        self.selection = {}           # 最近一次读到的 selection.json
        self.sel_mtime = None
        self.stratagem_selection = {}
        self.stratagem_mtime = None
        self.lock = threading.Lock()

    # ---- 面板选择（热重载） -------------------------------------------------
    def reload_selection(self):
        self.reload_stratagems()
        try:
            mtime = SELECTION.stat().st_mtime
        except OSError:
            return
        if mtime == self.sel_mtime:
            return
        try:
            doc = json.loads(SELECTION.read_text(encoding="utf-8-sig"))
        except Exception as e:
            log("selection.json 读取失败: %r" % e)
            return
        with self.lock:
            self.sel_mtime = mtime
            self.selection = doc if isinstance(doc, dict) else {}
        log("selection reloaded: %s" % json.dumps(self.selection, ensure_ascii=False))

    def reload_stratagems(self):
        try:
            mtime = STRATAGEM_SELECTION.stat().st_mtime
        except OSError:
            return
        if mtime == self.stratagem_mtime:
            return
        try:
            doc = json.loads(STRATAGEM_SELECTION.read_text(encoding="utf-8-sig"))
        except Exception as e:
            log("stratagems.json 读取失败: %r" % e)
            return
        if not isinstance(doc, dict):
            doc = {}
        with self.lock:
            self.stratagem_mtime = mtime
            self.stratagem_selection = doc
        log("stratagem selection reloaded: %s"
            % json.dumps(self.stratagem_selection, ensure_ascii=False))

    def note_planet(self, planet, why="lobby"):
        """记录玩家触碰过的星球。粘性：一旦注入过就不再撤销。

        为什么粘性：Status 每 5 分钟才重拉、切星球又会立刻刷新。
        如果只注入"最近一次选择的那颗"，切走再切回来就可能出现
        "真正想进的星球上没有变种"（因为上一次响应把它撤掉了）。
        所以这里累积本次会话碰过的星球，每次响应都全量写入。
        """
        with self.lock:
            if planet != self.planet:
                self.planet = planet
                log("player planet -> %s (%s)" % (planet, why))
            if planet not in self.sticky:
                self.sticky.append(planet)
                if len(self.sticky) > 3:
                    self.sticky.pop(0)
                log("sticky planets -> %s" % self.sticky)

    def target_planets(self):
        """本次要注入的星球集合：粘性集合 + config 里固定目标。"""
        with self.lock:
            planets = list(self.sticky)
        for p in self.plan:
            if p not in planets:
                planets.append(p)
        return planets

    def variant_entry(self, name):
        ids = list(self.catalog.get(name) or [])
        if not ids:
            return None
        return {
            "name": name,
            "ids": ids,
            "faction": variant_faction(self.variant_meta.get(name)),
        }

    def effective_plan(self):
        """返回 {星球: {"variants": 词条候选, "trials": 通用战备}}。

        词条候选在这里只描述“玩家选了哪些”，不直接展开成 ID。真正写哪颗星
        必须在 rewrite_status 看到该星球的 owner 后再决定，避免混入外阵营词条。
        """
        self.reload_selection()
        with self.lock:
            sel = dict(self.selection)
            ssel = dict(self.stratagem_selection)

        names = []
        if sel and sel.get("enabled"):
            raw = sel.get("variants")
            if isinstance(raw, list):
                names = [x for x in raw if isinstance(x, str) and x]
            elif isinstance(sel.get("variant"), str) and sel["variant"]:
                names = [sel["variant"]]

        entries = []
        for name in names:
            entry = self.variant_entry(name)
            if entry and entry not in entries:
                entries.append(entry)

        trial_ids = []
        if ssel.get("enabled"):
            for raw in ssel.get("ids") or []:
                try:
                    eid = int(raw)
                except Exception:
                    continue
                if eid in self.stratagem_catalog and eid not in trial_ids:
                    trial_ids.append(eid)
                if len(trial_ids) >= MAX_STRATAGEMS:
                    break

        if entries or trial_ids:
            return {
                planet: {"variants": list(entries), "trials": list(trial_ids)}
                for planet in self.target_planets()
            }

        plan = {}
        for planet, name in self.target_names.items():
            entry = self.variant_entry(name)
            if entry:
                plan[planet] = {"variants": [entry], "trials": []}
        return plan

    def active_names(self):
        with self.lock:
            sel = dict(self.selection)
        if not sel.get("enabled"):
            return []
        raw = sel.get("variants")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, str) and x]
        if isinstance(sel.get("variant"), str):
            return [sel["variant"]]
        return []

    def active_stratagem_names(self):
        self.reload_stratagems()
        with self.lock:
            doc = dict(self.stratagem_selection)
        if not doc.get("enabled"):
            return []
        names, seen = [], set()
        for raw in doc.get("ids") or []:
            try:
                eid = int(raw)
            except Exception:
                continue
            item = self.stratagem_catalog.get(eid)
            if item and eid not in seen:
                seen.add(eid)
                names.append({"id": eid, "name": item.get("name") or str(eid)})
            if len(names) >= MAX_STRATAGEMS:
                break
        return names

    def describe(self):
        return {k: v for k, v in sorted(self.plan.items())}


def resolve_plan(doc, plan):
    """按每一行 planetStatus 的 owner 过滤候选词条。

    返回 (实际要写的 {planet: [id...]}, 被跨阵营过滤掉的条目)。
    旧式 list plan 原样透传，兼容已有离线测试与手工配置。
    """
    owners = {}
    for row in doc.get("planetStatus") or []:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        owners[index] = owner_faction(row.get("owner", row.get("race")))

    resolved = {}
    filtered = []
    for raw_planet, spec in plan.items():
        try:
            planet = int(raw_planet)
        except (TypeError, ValueError):
            continue
        if isinstance(spec, list):              # 旧格式
            resolved[planet] = list(spec)
            continue
        if not isinstance(spec, dict):
            continue
        planet_faction = owners.get(planet)
        ids = []
        for variant in spec.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            faction = variant.get("faction") or FACTION_UNIVERSAL
            if faction != FACTION_UNIVERSAL and faction != planet_faction:
                filtered.append((planet, variant.get("name") or "?", faction, planet_faction))
                continue
            for eid in variant.get("ids") or []:
                if eid not in ids:
                    ids.append(eid)
        for eid in spec.get("trials") or []:
            if eid not in ids:
                ids.append(eid)
        resolved[planet] = ids
    return resolved, filtered


def rewrite_status(body, plan, spec=None):
    """只处理 Status 响应：给目标星球追加 [tag, 玩法]。"""
    doc = json.loads(body)
    if not isinstance(doc, dict):
        return body, 0
    effects = doc.get("planetActiveEffects")
    if not isinstance(effects, list):
        return body, 0
    plan, _ = resolve_plan(doc, plan)
    extra = status_hook.apply_extra(doc, spec)   # ← 结构化额外改写（campaigns / owner…）
    have = {(e.get("index"), e.get("galacticEffectId")) for e in effects if isinstance(e, dict)}
    added = 0
    for planet, ids in plan.items():
        for eid in ids:
            if (planet, eid) not in have:
                effects.append({"index": planet, "galacticEffectId": eid})
                added += 1
    if not added and not extra:
        return body, 0
    # extra 也算"改动"，否则调用方会认为没东西可写、把原始 body 发回去（2026-10-27 踩过）
    return json.dumps(doc).encode(), added + extra


