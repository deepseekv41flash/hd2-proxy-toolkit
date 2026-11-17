"""数据目录（GUI 用的只读目录）：变种 / 战备 / 效果 / 星球 / 物品 / build。

数据来自 `data/catalogs/`（由 tools/gen_catalogs.py 从研究仓产物固化）。
文件缺失时降级为空目录，并在 `warnings` 里说明 —— GUI 不应因为数据缺失就崩溃。
"""

import json
from pathlib import Path

from ..engine import paths


# 物品类别中文名（items.json 的 `category` 字段；来自库存配置文件的粗分类）
ITEM_CATEGORY_LABELS = {
    "weapon": "武器",
    "attachment": "附件",
    "cosmetic": "外观",
    "stratagem": "战备",
    "universal": "通用",
}


def item_display_label(mix_id, item):
    """物品列表/编辑器的统一显示：`mixId · 名字`；没有名字时写明类别与「内部名未解」。

    名字优先用目录里解出的显示名/内部名（2026-11-17 起 items.json 会带内部名：
    附件=改装选项内部名，外观=外观表名）；解不出来就明确标注，绝不编造。
    """
    item = item or {}
    name = (item.get("name") or "").strip()
    if name:
        return "%s · %s" % (mix_id, name)
    category = ITEM_CATEGORY_LABELS.get(str(item.get("category") or "").strip(),
                                        item.get("category") or "?")
    return "%s · %s（内部名未解）" % (mix_id, category)


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
        self._planet_by_index = {}          # planet_data **行号** -> row（离线资料）
        self._planet_by_game_index = {}     # 游戏索引 -> row（写 profile / 调引擎用这个）
        self.game_planets = []
        for p in self.planets:
            try:
                self._planet_by_index[int(p.get("index"))] = p
            except (TypeError, ValueError):
                pass
            try:
                game_index = int(p.get("game_index"))
            except (TypeError, ValueError):
                continue
            self._planet_by_game_index[game_index] = p
            self.game_planets.append(p)
        self.game_planets.sort(key=lambda p: int(p.get("game_index")))
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

    def planet_row(self, game_index):
        """游戏索引 -> planet_data 行（含 name/biome/坐标）；找不到返回 {}。

        ⚠ 行号 ≠ 游戏索引：`planets.json` 的 `index` 是 planet_data 行号，
        引擎/Status 用的是 game_index（M4 实机踩坑，详见 data/catalogs/README.md）。
        """
        try:
            return self._planet_by_game_index.get(int(game_index)) or {}
        except (TypeError, ValueError):
            return {}

    def planet_label(self, index):
        p = self.planet_row(index)
        if not p:
            try:
                p = self._planet_by_index.get(int(index)) or {}
            except (TypeError, ValueError):
                p = {}
        return "%s · %s (%s)" % (index, p.get("name") or "?", p.get("biome") or "?")

    def planet_entries(self):
        """选择器用：[(游戏索引, 标签)]；旧目录（无 game_index）退回行号。"""
        rows = self.game_planets or self.planets
        out = []
        for p in rows:
            key = p.get("game_index")
            if key is None:
                key = p.get("index")
            if key is None:
                continue
            out.append((int(key), self.planet_label(key)))
        return out

    def item_label(self, mix_id):
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        return item_display_label(mix_id, it)

    def item_category(self, mix_id):
        """物品的类别（items.json 的 `category`：weapon / attachment / cosmetic / stratagem）。

        解析不到返回 None（例如只存在于目录里的条目、探测文件里的混类条目）。
        """
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        return it.get("category")

    def unlock_template(self, mix_id):
        """目录里缺失的物品：克隆哪一行目录记录来上架（`unlock_template`），没有则 None。

        为什么需要：服务端 `/api/Progression/items` 里没有这条物品时，只给库存行客户端不显示；
        引擎要克隆一个同族已存在的 itemId（模板）改出这条目录行。配对值来自研究线 M4 实机验证，
        由 `tools/gen_catalogs.py` 从 `data/sources/unreleased_items.json` 写进 items.json。
        """
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        tmpl = it.get("unlock_template")
        return int(tmpl) if tmpl else None

    def attachment_groups(self):
        """附件按武器分组：[(parent_id, 武器名, [(mix_id, label), ...]), ...]。

        附件解锁是「武器 × 附件」粒度（每条附件的 mixId 属于某把武器，见
        docs/UNLOCK-MAP 与 data/catalogs/README.md），所以界面先列武器、再列该武器的配件。
        返回项按武器名排序；没有 parent_id 的条目不会出现（目前数据里没有）。
        """
        groups = {}
        for it in self.items:
            if it.get("category") != "attachment" or it.get("parent_id") is None:
                continue
            mix = it.get("mix_id")
            if mix is None:
                continue
            parent = int(it["parent_id"])
            group = groups.setdefault(parent, {"name": None, "items": []})
            if not group["name"] and it.get("parent_name"):
                group["name"] = it["parent_name"]
            group["items"].append((int(mix), item_display_label(mix, it)))
        out = []
        for parent, group in groups.items():
            out.append((parent, group["name"] or "武器 #%08X" % parent, sorted(group["items"])))
        out.sort(key=lambda entry: (entry[1].lower(), entry[0]))
        return out

    def search_items(self, text, limit=None, category=None):
        """关键词搜索物品；`category` 给定就只返回该类别（各 tab 的筛选器靠它）。

        `limit=None`（默认）= **不截断**：列表要把本类全部条目交给界面，否则会出现
        「目录里 1176 条、界面只显示 80 条」的错觉（2026-11-17 用户报）。物品总量 ~1.7k，
        Tk Listbox 直接装得下；需要截断时显式传 limit。
        """
        q = (text or "").strip().lower()
        out = []
        for it in self.items:
            if category is not None and it.get("category") != category:
                continue
            mix = it.get("mix_id") or it.get("item_id")
            if mix is None:
                continue
            label = item_display_label(mix, it)
            if not q or q in label.lower():
                out.append((int(mix), label))
                if limit is not None and len(out) >= limit:
                    break
        return out

    # ---- 汇总 ---------------------------------------------------------
    def summary(self):
        return {"variants": len(self.variants), "stratagems": len(self.stratagems),
                "effects": len(self.effects), "planets": len(self.planets),
                "items": len(self.items), "warnings": list(self.warnings)}
