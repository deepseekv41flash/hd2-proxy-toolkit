"""数据目录（GUI 用的只读目录）：变种 / 战备 / 效果 / 星球 / 物品 / build。

数据来自 `data/catalogs/`（由 tools/gen_catalogs.py 从研究仓产物固化）。
文件缺失时降级为空目录，并在 `warnings` 里说明 —— GUI 不应因为数据缺失就崩溃。
"""

import json
from pathlib import Path

from ..engine import paths


class Catalogs:
    def __init__(self, catalogs_dir=None):
        self.dir = Path(catalogs_dir) if catalogs_dir else paths.CATALOGS_DIR
        self.warnings = []
        self.build = self._load("build", default={})
        self._variants_doc = self._load("variants", default={})
        self.variants = {}
        self.variant_groups = []
        self.aliases = {}
        self._load_variants(self._variants_doc)

        self.stratagems = self._load("stratagems", default={}).get("items") or []
        self._stratagem_by_id = {int(s.get("id") or 0): s for s in self.stratagems
                                 if isinstance(s, dict)}
        self.effects = self._load("effects", default={}).get("items") or []
        self._effect_by_id = {}
        for e in self.effects:
            try:
                self._effect_by_id[int(e.get("effect_id"))] = e
            except (TypeError, ValueError):
                continue
        self.planets = self._load("planets", default={}).get("items") or []
        self._planet_by_index = {}
        for p in self.planets:
            try:
                self._planet_by_index[int(p.get("index"))] = p
            except (TypeError, ValueError):
                continue
        self.items = self._load("items", default={}).get("items") or []
        self._item_by_mix = {}
        for it in self.items:
            for key in ("mix_id", "item_id"):
                try:
                    k = int(it.get(key))
                except (TypeError, ValueError):
                    continue
                self._item_by_mix.setdefault(k, it)

    # ---- 载入 ---------------------------------------------------------
    def _load(self, name, default):
        p = self.dir / (name + ".json")
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.warnings.append("缺少 %s（先跑 tools/gen_catalogs.py）" % p.name)
        except Exception as e:      # noqa: BLE001
            self.warnings.append("读取 %s 失败：%r" % (p.name, e))
        return default

    def _load_variants(self, doc):
        if not isinstance(doc, dict):
            return
        self.aliases = doc.get("aliases") or {}
        items = doc.get("items")
        if isinstance(items, dict):
            self.variants = items
        elif isinstance(items, list):
            for row in items:
                if isinstance(row, dict) and row.get("name"):
                    self.variants[row["name"]] = row
        groups = doc.get("groups") or []
        if groups:
            self.variant_groups = [g for g in groups if isinstance(g, dict)]
        else:
            # 无分组信息时按 faction 兜底分组
            buckets = {}
            for name, meta in self.variants.items():
                buckets.setdefault((meta or {}).get("faction") or "universal", []).append(name)
            label = {"terminid": "虫族", "automaton": "机器人", "illuminate": "光能者",
                     "universal": "通用"}
            self.variant_groups = [{"name": label.get(k, k), "variants": v}
                                   for k, v in sorted(buckets.items())]

    # ---- 变种 ---------------------------------------------------------
    def variant_entries(self):
        out = []
        for group in self.variant_groups:
            for name in group.get("variants") or []:
                meta = self.variants.get(name) or {}
                out.append((name, "%s · %s" % (group.get("name") or "", name)))
        if not out:
            out = [(name, name) for name in self.variants]
        return out

    def resolve_variant(self, name):
        meta = self.variants.get(name) or self.variants.get(self.aliases.get(name)) or {}
        if not meta and name not in self.variants:
            return None
        ids = meta.get("ids") or []
        return {"name": name, "ids": list(ids),
                "faction": meta.get("faction") or "universal"}

    def variant_summary(self, name):
        meta = self.variants.get(name) or {}
        ids = meta.get("ids") or ([meta["tag"], meta["mechanic"]]
                                  if meta.get("tag") and meta.get("mechanic") else [])
        return "ids=%s" % ",".join(str(x) for x in ids)

    # ---- 战备 / 效果 / 星球 / 物品 -------------------------------------
    def stratagem_entries(self):
        return [(int(s.get("id") or 0), "%s · %s" % (s.get("id"), s.get("name") or "?"))
                for s in self.stratagems if isinstance(s, dict)]

    def stratagem_label(self, sid):
        s = self._stratagem_by_id.get(int(sid) if str(sid).isdigit() else -1) or {}
        return "%s · %s" % (sid, s.get("name") or "?")

    def effect_entries(self):
        out = []
        for e in self.effects:
            try:
                eid = int(e.get("effect_id"))
            except (TypeError, ValueError):
                continue
            name = e.get("name") or e.get("display_name") or e.get("type_semantics") or ""
            out.append((eid, "%d · %s (type%s)" % (eid, name or "?", e.get("effect_type"))))
        return out

    def effect_label(self, eid):
        e = self._effect_by_id.get(int(eid) if str(eid).isdigit() else -1) or {}
        name = e.get("name") or e.get("display_name") or "?"
        return "%s · %s" % (eid, name)

    def planet_label(self, index):
        p = self._planet_by_index.get(int(index) if str(index).isdigit() else -1) or {}
        return "%s · %s (%s)" % (index, p.get("name") or "?", p.get("biome") or "?")

    def planet_entries(self):
        return [(int(p.get("index")), self.planet_label(p.get("index")))
                for p in self.planets if p.get("index") is not None]

    def item_label(self, mix_id):
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        return "%s · %s" % (mix_id, it.get("name") or it.get("category") or "?")

    def search_items(self, text, limit=80):
        q = (text or "").strip().lower()
        out = []
        for it in self.items:
            name = (it.get("name") or "")
            mix = it.get("mix_id") or it.get("item_id")
            if mix is None:
                continue
            label = "%s · %s" % (mix, name or it.get("category") or "?")
            if not q or q in label.lower():
                out.append((int(mix), label))
                if len(out) >= limit:
                    break
        return out

    # ---- 汇总 ---------------------------------------------------------
    def summary(self):
        return {"variants": len(self.variants), "stratagems": len(self.stratagems),
                "effects": len(self.effects), "planets": len(self.planets),
                "items": len(self.items), "warnings": list(self.warnings)}
