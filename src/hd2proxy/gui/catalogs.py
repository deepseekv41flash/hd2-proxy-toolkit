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
    "booster": "强化资源",     # 空号基线里出现的类别（2026-11-18 目录补全后启用）
    "banner": "徽章",
    "currency": "货币",
    "unknown": "未分类",       # 服务端目录里有行、但类别语义无证据（不臆测）
}

# 「目录总览」tab 的筛选器：key -> 中文名（顺序即下拉框顺序）
# 前 9 个 key = items.json 的 `category` 值（与编辑 tab 同口径）；后 2 个是目录整体筛选
CATALOG_SCOPES = (
    ("all", "全部"),
    ("weapon", "武器"),
    ("attachment", "附件"),
    ("cosmetic", "外观"),
    ("stratagem", "战备"),
    ("booster", "强化资源"),
    ("banner", "徽章"),
    ("currency", "货币"),
    ("unknown", "未分类"),
    ("default", "仅空号默认拥有"),
    ("extra", "仅目录外（可追加）"),
)
# scope key 里属于「物品类别筛选」的那批（其余是目录整体筛选）
_CATEGORY_SCOPES = frozenset(key for key, _label in CATALOG_SCOPES) - {"all", "default", "extra"}


def item_display_label(mix_id, item):
    """物品列表/编辑器的统一显示：`mixId · 名字`；没有名字时写明类别与「内部名未解」。

    名字优先用目录里解出的显示名/内部名（2026-11-17 起 items.json 会带内部名：
    附件=改装选项内部名，外观=外观表名）；解不出来就明确标注，绝不编造。
    2026-11-18 起目录全量并入 items.json：类别未知的行带上服务端 catalog 编号
    （`未分类 cat8`），这样至少能在 3020 行里定位，而不是只剩一个 mixId。
    """
    item = item or {}
    name = (item.get("name") or "").strip()
    if name:
        return "%s · %s" % (mix_id, name)
    category = str(item.get("category") or "").strip()
    label = ITEM_CATEGORY_LABELS.get(category, category or "?")
    if category == "unknown":
        cat = item.get("catalog_category")
        if cat is not None:
            label = "未分类 cat%s" % cat
    return "%s · %s（内部名未解）" % (mix_id, label)


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
        items_doc = self._load("items", default={})
        if not isinstance(items_doc, dict):
            items_doc = {}
        self.items = items_doc.get("items") or []
        # 目录覆盖统计（gen_catalogs 写入；老目录没有这一段 -> {}，界面按 items 现算兜底）
        self.catalog = items_doc.get("catalog") if isinstance(items_doc.get("catalog"), dict) else {}
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
        「目录里 1176 条、界面只显示 80 条」的错觉（2026-11-17 用户报）。目录补全后条目
        ~3k（2026-11-18），Tk Listbox 直接装得下；需要截断时显式传 limit。
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

    # ---- 目录总览（2026-11-18 全量目录） -------------------------------
    def is_default_owned(self, mix_id):
        """空号（未解锁任何东西）也拥有的物品：解锁工具不必再添加。旧目录一律 False。"""
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        return bool(it.get("default_owned"))

    def is_in_server_catalog(self, mix_id):
        """是否存在于服务端 `/api/Progression/items` 目录行集。

        旧目录（没有 in_catalog 字段）返回 None = 未知，不当成 False 用（避免误报「目录缺」）。
        """
        it = self._item_by_mix.get(int(mix_id) if str(mix_id).isdigit() else -1) or {}
        value = it.get("in_catalog")
        return bool(value) if value is not None else None

    def catalog_summary(self):
        """目录覆盖汇总（界面与测试共用；数据结构稳定，不在这里拼中文句子）。

        返回键：rows=服务端目录行数 / in_catalog=已并入目录的行数 / items=条目总数 /
        extra=目录外条目数 / named / unnamed / default_owned / by_kind / by_category。
        老目录没有 `catalog` 段时按 items 现算，并在 `has_catalog_doc` 标 False。
        """
        doc = self.catalog or {}
        items = self.items or []
        by_category = doc.get("by_category") if isinstance(doc.get("by_category"), dict) else {}
        by_kind = {}
        for stat in by_category.values():
            if not isinstance(stat, dict):
                continue
            kind = str(stat.get("kind") or "unknown")
            row = by_kind.setdefault(kind, {"rows": 0, "named": 0})
            row["rows"] += int(stat.get("rows") or 0)
            row["named"] += int(stat.get("named") or 0)
        in_catalog = doc.get("in_catalog")
        if in_catalog is None:
            # 老目录：没有任何 in_catalog 标记 -> 全部条目视为在目录里（旧行为）
            in_catalog = sum(1 for it in items if it.get("in_catalog") is not False)
        named = doc.get("named")
        if named is None:
            named = sum(1 for it in items if it.get("name"))
        unnamed = doc.get("unnamed")
        if unnamed is None:
            unnamed = len(items) - int(named)
        rows = doc.get("catalog_rows")
        if rows is None:
            rows = int(in_catalog)
        default_owned = doc.get("default_owned")
        if default_owned is None:
            default_owned = sum(1 for it in items if it.get("default_owned"))
        return {
            "has_catalog_doc": bool(doc),
            "rows": int(rows),
            "in_catalog": int(in_catalog),
            "items": len(items),
            "extra": max(0, len(items) - int(in_catalog)),
            "named": int(named),
            "unnamed": int(unnamed),
            "default_owned": int(default_owned or 0),
            "by_kind": by_kind,
            "by_category": by_category,
        }

    def catalog_entries(self, scope="all", keyword=""):
        """目录总览列表：[(mixId, 带标记的标签)]；scope 见 CATALOG_SCOPES。

        标签比编辑列表多两个标记：「默认已有」（空号就有）、「目录缺」（服务端目录里没有，
        需要走「目录追加」）。只读查询，不写 profile。
        """
        q = (keyword or "").strip().lower()
        scope = scope or "all"
        out = []
        for it in self.items:
            # 外观行（armor_rows）只有 item_id 没有 mix_id —— 与 search_items 口径保持一致
            mix = it.get("mix_id")
            if mix is None:
                mix = it.get("item_id")
            if mix is None:
                continue
            if scope in _CATEGORY_SCOPES and it.get("category") != scope:
                continue
            if scope == "default" and not it.get("default_owned"):
                continue
            if scope == "extra" and it.get("in_catalog") is True:
                continue
            try:
                mix_int = int(mix)
            except (TypeError, ValueError):
                continue
            label = item_display_label(mix_int, it)
            if it.get("name"):
                # 有名字时标签里没有类别（item_display_label 只在无名时写类别），总览页补上，
                # 否则「这个名字属于武器还是外观」在目录视图里看不出来
                label += "（%s）" % (ITEM_CATEGORY_LABELS.get(str(it.get("category") or ""),
                                                           it.get("category") or "?"))
            marks = []
            if it.get("default_owned"):
                marks.append("默认已有")
            if it.get("in_catalog") is False:
                marks.append("目录缺")
            if marks:
                label += " · " + " · ".join(marks)
            if q and q not in label.lower() and q not in str(mix_int):
                continue
            out.append((mix_int, label))
        return out

    # ---- 汇总 ---------------------------------------------------------
    def summary(self):
        return {"variants": len(self.variants), "stratagems": len(self.stratagems),
                "effects": len(self.effects), "planets": len(self.planets),
                "items": len(self.items), "warnings": list(self.warnings)}
