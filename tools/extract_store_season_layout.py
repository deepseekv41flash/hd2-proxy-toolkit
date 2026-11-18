"""从抓包目录提取 store / season（商店、战争债券）与相关养成响应里的「结构映射」，用于补物品名字。

背景（2026-11-18）
    服务端目录 3020 行里还有 ~856 行没有名字（cat 0 战团相关 / cat 9 横幅 / cat 23 称号 /
    cat 4 剩余套装 / cat 11 剩余许可 / cat 3 剩余外观 …）。这些行在本地只读表里没有 id→名字映射。
    已验证：`/api/StoreFront`、`/api/SeasonPass`、`/api/Progression/ProgressionPackages` 等响应
    **只含 id/布局，不含名字或 locid** —— 所以抓包本身不会直接给出名字，但它给出两样关键东西：
      1) mixId 出现在哪个商店货架/战争债券页（含 grid 坐标）—— 这是「用截图/OCR 补名字」的定位锚点；
      2) 可能暴露我们还没见过的新端点（若某个端点带 nameHash/locid，就能直接本地解名）。

本工具做的事
    * 盘点抓包目录里的端点（index.txt + body 文件），标出已知/新端点；
    * 提取结构映射：storefront/section/item grid、season pass 页 → itemMixId、ItemPackages、
      ProgressionPackages 奖励、Customize；
    * 扫描整份抓包里任何 name/locid/title/label 类字段（有就说明能直接解名）；
    * 与目录里的「无名行」对账：哪些无名行被这些响应覆盖（可按 cat 统计）。

用法
    python tools/extract_store_season_layout.py --capture-dir D:/mod/tmp/capture-xxx/raw \
        --out D:/mod/tmp/capture-xxx/analysis

产物
    <out>/layout.json   结构映射（mixId -> 角色/位置）与端点清单
    <out>/report.md     人读报告（端点、覆盖统计、无名行样例）
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO / "data" / "catalogs" / "items.json"

# 已知端点族（用于把本次抓到的端点分成「已知 / 新」）
KNOWN_FAMILIES = (
    ("/api/StoreFront", "商店货架（布局 + item mixId）"),
    ("/api/SeasonPass", "战争债券（列表 / 单赛季详情：页 → itemMixId）"),
    ("/api/Progression/ProgressionPackages", "养成包（等级奖励 / 解锁项 mixId）"),
    ("/api/Progression/ItemPackages", "物品包（包 mixId → 内容 mixId）"),
    ("/api/Progression/Items/Customize", "自定义（已装备项）"),
    ("/api/Progression/items", "服务端物品目录（3020 行）"),
    ("/api/Progression/inventory", "账号库存"),
    ("/api/Progression", "养成总览"),
    ("/api/Progression/levelspec", "等级表"),
    ("/api/Monetization", "氪金/兑换（Steam 兑换等）"),
    ("/api/Configuration", "客户端配置"),
    ("/api/WarSeason", "战况/全局效果"),
    ("/api/Stats", "战绩"),
    ("/api/NewsFeed", "新闻"),
    ("/api/Pes", "PlayFab 类消息"),
    ("/api/FriendsV2", "社交"),
    ("/api/Mail", "邮件"),
    ("/api/Mission", "任务"),
    ("/api/Operation", "战役操作"),
    ("/api/lobby", "大厅"),
    ("/api/v2/Assignment", "命令/任务"),
    ("/api/Account", "账号"),
)

NAMEISH = re.compile(r"(name|locid|loc_id|title|label|display|desc|string|text)", re.I)


# ---------------------------------------------------------------- 抓包读取


def read_index(capture_dir: Path) -> list[dict]:
    """读 index.txt：每行 `时间\t路径\t字节数\tsha256\tjson|not-json`。"""
    index = capture_dir / "index.txt"
    if not index.exists():
        return []
    out = []
    for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        out.append({"stamp": parts[0], "path": parts[1], "size": int(parts[2] or 0),
                    "sha256": parts[3], "kind": parts[4] if len(parts) > 4 else ""})
    return out


def resolve_body(capture_dir: Path, entry: dict) -> Path | None:
    """按 sha 前缀找 body 文件（命名 `<sha8>_<slug>.json`），找不到返回 None。"""
    prefix = entry["sha256"][:8]
    hits = sorted(capture_dir.glob(prefix + "_*.json"))
    return hits[0] if hits else None


def classify(path: str) -> tuple[str, str]:
    """响应路径 -> (族, 用途说明)。"""
    base = path.split("?")[0]
    for prefix, desc in KNOWN_FAMILIES:
        if base.startswith(prefix):
            return prefix, desc
    return "其它", "本工具未登记（重点看：可能是新端点）"


# ---------------------------------------------------------------- 结构提取


def _walk_strings(obj, path="", out=None, depth=0):
    """收集所有 (keypath, value) 叶子，用于 name/locid 字段扫描。"""
    if out is None:
        out = []
    if depth > 12:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(v, path + "." + k, out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:800]):
            _walk_strings(v, path + "[%d]" % i, out, depth + 1)
    else:
        out.append((path, obj))
    return out


def scan_nameish(obj) -> list[dict]:
    """扫描 name/locid/title/... 类字段；非空字符串/整数都记。"""
    hits = []
    for p, v in _walk_strings(obj):
        last = p.rsplit(".", 1)[-1]
        if NAMEISH.search(last or "") and v not in (None, "", 0, False, [], {}):
            hits.append({"field": p, "value": v})
    return hits


def extract_storefront(doc) -> dict:
    """`/api/StoreFront` / `/api/StoreFront/rotation` / `/api/StoreFront/{id}` -> 货架树。

    三种响应形状不同：列表（[storefront...]）、rotation（{expireTime, salesPage}）、
    单个 storefront 详情（{id32, sections}）。三者都要合并，不能互相覆盖（2026-11-18 踩坑）。
    """
    roles = defaultdict(list)
    shelves = []
    if isinstance(doc, list):
        rows = doc
    elif isinstance(doc, dict) and isinstance(doc.get("salesPage"), dict):
        rows = [doc["salesPage"]]
    else:
        rows = [doc]
    for sf in rows:
        if not isinstance(sf, dict):
            continue
        sf_id = sf.get("id32")
        shelf = {"storefront": sf_id, "sections": []}
        for sec in sf.get("sections") or []:
            sec_row = {"section": sec.get("id32"), "banner": sec.get("bannerId32"),
                       "items": []}
            for item in sec.get("items") or []:
                mix = item.get("mixId")
                if mix is None:
                    continue
                mix = int(mix)
                pos = item.get("position") or {}
                sec_row["items"].append({"mixId": mix,
                                         "pos": [pos.get("x"), pos.get("y")],
                                         "salesId": item.get("salesId")})
                roles[mix].append("storefront:%s/section:%s/pos(%s,%s)"
                                  % (sf_id, sec.get("id32"), pos.get("x"), pos.get("y")))
            shelf["sections"].append(sec_row)
        shelves.append(shelf)
    return {"roles": roles, "shelves": shelves}


def extract_season_pass(docs: dict) -> dict:
    """`/api/SeasonPass`（列表）+ `/api/SeasonPass/{id}`（详情） -> 结构映射。"""
    roles = defaultdict(list)
    passes = []
    # 列表：每个赛季 id32 + itemIds（这里是 seasonPassItemId，不是 mixId）+ premiumTokenMixIds
    for path, doc in docs.items():
        if not path.split("?")[0].rstrip("/").endswith("/api/SeasonPass"):
            continue
        for sp in doc if isinstance(doc, list) else [doc]:
            if not isinstance(sp, dict):
                continue
            passes.append({"season": sp.get("id32"),
                           "itemIds": sp.get("itemIds"),
                           "premiumTokenMixIds": sp.get("premiumTokenMixIds"),
                           "totalCost": sp.get("totalCost")})
            for token in sp.get("premiumTokenMixIds") or []:
                try:
                    roles[int(token)].append("seasonpass:%s/premium-token" % sp.get("id32"))
                except (TypeError, ValueError):
                    pass
    # 详情：seasonPassPages -> seasonPassItems -> itemMixId（真正可对到目录的 mixId）
    for path, doc in docs.items():
        parts = [p for p in path.split("?")[0].split("/") if p]
        if len(parts) >= 2 and parts[-2] == "SeasonPass" and parts[-1].isdigit():
            season_id = parts[-1]
            pages = doc.get("seasonPassPages") if isinstance(doc, dict) else None
            for page_idx, page in enumerate(pages or []):
                for item in (page or {}).get("seasonPassItems") or []:
                    mix = item.get("itemMixId")
                    if mix is None:
                        continue
                    try:
                        mix = int(mix)
                    except (TypeError, ValueError):
                        continue
                    pos = item.get("gridPosition") or {}
                    roles[mix].append(
                        "seasonpass:%s/page:%d/pos(%s,%s)/cost:%s%s"
                        % (season_id, page_idx, pos.get("x"), pos.get("y"),
                           item.get("medalCost"),
                           "/premium" if item.get("isPremium") else ""))
            passes.append({"season": season_id, "pages": len(pages or [])})
    return {"roles": roles, "passes": passes}


def extract_item_packages(doc) -> dict:
    """`/api/Progression/ItemPackages`：包 mixId → 包含的 mixId。"""
    roles = defaultdict(list)
    packages = []
    rows = doc if isinstance(doc, list) else [doc]
    for pkg in rows:
        if not isinstance(pkg, dict):
            continue
        outer = pkg.get("itemMixId32")
        items = []
        for it in pkg.get("items") or []:
            try:
                item_mix = int(it.get("mixId"))
            except (TypeError, ValueError):
                continue
            items.append({"mixId": item_mix, "amount": it.get("amount")})
            if outer is not None:
                roles[item_mix].append("itempackage:%s" % outer)
        packages.append({"package": outer, "items": items})
    return {"roles": roles, "packages": packages}


def extract_progression_packages(doc) -> dict:
    """`/api/Progression/ProgressionPackages`：包 id → 奖励/解锁的 mixId（战团/等级奖励）。"""
    roles = defaultdict(list)
    packages = []
    rows = doc if isinstance(doc, list) else [doc]
    for pkg in rows:
        if not isinstance(pkg, dict):
            continue
        pid = pkg.get("id32")

        def add_mix(raw, role):
            try:
                mix = int(raw)
            except (TypeError, ValueError):
                return
            roles[mix].append("progression:%s/%s" % (pid, role))

        for item in pkg.get("requiredItems") or []:
            add_mix(item, "required")
        for level in pkg.get("levels") or []:
            for reward in level.get("rewards") or []:
                add_mix(reward.get("id32"), "reward")
            for item in level.get("unlockableItems") or []:
                add_mix(item, "unlockable")
        packages.append({"package": pid, "type": pkg.get("type"),
                         "levels": len(pkg.get("levels") or [])})
    return {"roles": roles, "packages": packages}


def extract_avatar_customization(inventory_doc) -> dict:
    """`/api/Progression/inventory.avatarCustomization`：已装备的自定义项 + 称号 locid。

    2026-11-18 新发现：`titleId32` 是**本地化字符串 id（locid）**，其余槽位（banner /
    victory_pose_index / undergarment_type …）是已装备物品 id —— 这是「称号名 = locid」的直接证据，
    也说明客户端本地化表可以把称号/横幅类名字解出来（若行 id 能对上目录 mixId）。
    """
    av = {}
    if isinstance(inventory_doc, dict):
        av = inventory_doc.get("avatarCustomization") or {}
    if not isinstance(av, dict):
        av = {}
    roles = defaultdict(list)
    locids = []
    for key, raw in av.items():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if "title" in key.lower() or "locid" in key.lower():
            locids.append({"field": key, "locid": value})
            continue
        roles[value].append("avatar:%s" % key)
    return {"roles": roles, "equipped": av, "locids": locids}


def extract_customize(doc) -> dict:
    """`/api/Progression/Items/Customize/v2`：已装备的自定义项（可能为空）。"""
    roles = defaultdict(list)
    items = doc.get("items") if isinstance(doc, dict) else None
    for it in items or []:
        if not isinstance(it, dict):
            continue
        for key in ("mixId", "itemMixId", "id32"):
            raw = it.get(key)
            try:
                roles[int(raw)].append("customize:equipped")
            except (TypeError, ValueError):
                pass
    return {"roles": roles, "equipped": items or []}


# ---------------------------------------------------------------- 对账


def load_unresolved(catalog_path: Path) -> list[dict]:
    """目录里没名字的行（name 为空），带 cat / mix_id / item_id。"""
    doc = json.loads(catalog_path.read_text(encoding="utf-8"))
    out = []
    for it in doc.get("items") or []:
        if it.get("name"):
            continue
        mix = it.get("mix_id") if it.get("mix_id") is not None else it.get("item_id")
        try:
            mix = int(mix)
        except (TypeError, ValueError):
            continue
        out.append({"mix": mix, "item": it.get("item_id"),
                    "cat": it.get("catalog_category"), "category": it.get("category"),
                    "in_catalog": it.get("in_catalog")})
    return out


def coverage(unresolved: list[dict], roles: dict) -> dict:
    """按 cat 统计无名行被结构映射覆盖的情况。"""
    by_cat = defaultdict(lambda: {"total": 0, "covered": 0, "samples": []})
    for row in unresolved:
        cat = row["cat"] if row["cat"] is not None else -1
        stat = by_cat[cat]
        stat["total"] += 1
        hit = roles.get(row["mix"]) or roles.get(row["item"])
        if hit:
            stat["covered"] += 1
            if len(stat["samples"]) < 5:
                stat["samples"].append({"mix": row["mix"], "role": hit[0]})
    total = len(unresolved)
    covered = sum(1 for row in unresolved
                  if roles.get(row["mix"]) or roles.get(row["item"]))
    return {"total": total, "covered": covered,
            "by_cat": {str(k): v for k, v in sorted(by_cat.items())}}


# ---------------------------------------------------------------- 主流程


def analyze(capture_dir: Path, catalog_path: Path) -> dict:
    entries = read_index(capture_dir)
    docs = {}
    pending = {}
    for entry in entries:
        body = resolve_body(capture_dir, entry)
        if body is None:
            continue
        base = entry["path"].split("?")[0]
        try:
            doc = json.loads(body.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        docs[entry["path"]] = doc
        pending[base] = doc

    family_counts = Counter()
    for path in docs:
        fam, _desc = classify(path)
        family_counts[fam] += 1

    roles = defaultdict(list)
    parts = {}
    storefront_roles = defaultdict(list)
    storefront_shelves = []
    for base, doc in pending.items():
        if base.startswith("/api/StoreFront"):
            sf = extract_storefront(doc)
            for mix, hits in sf["roles"].items():
                storefront_roles[mix].extend(hits)
            storefront_shelves.extend(sf["shelves"])
    if storefront_shelves:
        parts["storefront"] = {"roles": storefront_roles, "shelves": storefront_shelves}
    for base, doc in pending.items():
        if base.startswith("/api/StoreFront"):
            continue
        elif base.startswith("/api/SeasonPass"):
            parts["seasonpass"] = extract_season_pass(
                {p: d for p, d in docs.items() if "/api/SeasonPass" in p})
        elif base.startswith("/api/Progression/ItemPackages"):
            parts["itempackages"] = extract_item_packages(doc)
        elif base.startswith("/api/Progression/ProgressionPackages"):
            parts["progressionpackages"] = extract_progression_packages(doc)
        elif base.startswith("/api/Progression/Items/Customize"):
            parts["customize"] = extract_customize(doc)
        elif base.startswith("/api/Progression/inventory"):
            parts["avatar"] = extract_avatar_customization(doc)
    for part in parts.values():
        for mix, hits in (part.get("roles") or {}).items():
            roles[mix].extend(hits)

    nameish = []
    for path, doc in docs.items():
        hits = scan_nameish(doc)
        if hits:
            nameish.append({"path": path, "hits": hits[:20]})

    unresolved = load_unresolved(catalog_path)
    return {
        "capture_dir": str(capture_dir),
        "endpoints": [{"path": p, "family": classify(p)[0], "bytes": len(json.dumps(d) or ""),
                       "nameish_hits": len(scan_nameish(d))} for p, d in sorted(docs.items())],
        "family_counts": dict(family_counts),
        "layout": {k: v for k, v in parts.items()},
        "roles": {str(k): v for k, v in roles.items()},
        "nameish": nameish,
        "coverage": coverage(unresolved, roles),
    }


def render_report(result: dict) -> str:
    lines = ["# store / season 抓包结构分析", ""]
    lines.append("抓包目录：`%s`" % result["capture_dir"])
    lines.append("")
    lines.append("## 端点盘点")
    for ep in result["endpoints"]:
        lines.append("- `%s` ｜ 族：%s ｜ name/loc 类字段命中：%d"
                     % (ep["path"], ep["family"], ep["nameish_hits"]))
    if not result["endpoints"]:
        lines.append("- （没读到响应体：检查抓包目录与 index.txt）")
    lines.append("")
    lines.append("## name/locid 类字段（>0 说明可直接解名）")
    if result["nameish"]:
        for row in result["nameish"]:
            lines.append("- `%s`：" % row["path"])
            for hit in row["hits"][:6]:
                lines.append("  - %s = %r" % (hit["field"], hit["value"]))
    else:
        lines.append("- 无。当前 store/season 响应只有 id/布局，名字需要「截图 + OCR + 布局坐标」"
                     "或客户端本地化表来补（见 docs/CAPTURE-STORE-SEASON-2026-11-18.md）。")
    lines.append("")
    cov = result["coverage"]
    lines.append("## 与目录无名行的对账")
    lines.append("")
    lines.append("目录无名行共 **%d**，被本次抓包结构覆盖 **%d**（%.1f%%）。"
                 % (cov["total"], cov["covered"],
                    100.0 * cov["covered"] / cov["total"] if cov["total"] else 0.0))
    lines.append("")
    lines.append("| cat | 无名行 | 有结构映射 | 样例（mixId → 角色） |")
    lines.append("|---:|---:|---:|---|")
    for cat, stat in cov["by_cat"].items():
        samples = "；".join("%s → %s" % (s["mix"], s["role"]) for s in stat["samples"][:2])
        lines.append("| %s | %d | %d | %s |" % (cat, stat["total"], stat["covered"], samples))
    lines.append("")
    layout = result["layout"]
    if "storefront" in layout:
        sf = layout["storefront"]["shelves"]
        item_total = sum(len(sec["items"]) for shelf in sf for sec in shelf["sections"])
        lines.append("商店货架：%d 个 storefront、%d 个 section、%d 个 item 位置。"
                     % (len(sf), sum(len(s["sections"]) for s in sf), item_total))
    if "seasonpass" in layout:
        sp = layout["seasonpass"]["passes"]
        pages = [p for p in sp if "pages" in p]
        lines.append("战争债券：列表 %d 条、详情 %d 条（详情含 %s 页）。"
                     % (len([p for p in sp if "itemIds" in p]), len(pages),
                        "/".join(str(p["pages"]) for p in pages[:6])))
    if "itempackages" in layout:
        lines.append("物品包：%d 个。" % len(layout["itempackages"]["packages"]))
    if "progressionpackages" in layout:
        lines.append("养成包：%d 个。" % len(layout["progressionpackages"]["packages"]))
    if "avatar" in layout:
        av = layout["avatar"]
        lines.append("已装备自定义：%d 个槽位、称号 locid：%s。"
                     % (len(av.get("equipped") or {}),
                        ", ".join("%s=%s" % (x["field"], x["locid"]) for x in av.get("locids") or [])
                        or "无"))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="store/season 抓包 -> 结构映射 + 无名行对账")
    ap.add_argument("--capture-dir", required=True, type=Path,
                    help="抓包 raw 目录（含 index.txt 与 <sha8>_<slug>.json）")
    ap.add_argument("--out", type=Path, required=True, help="输出目录（layout.json + report.md）")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG,
                    help="物品目录 items.json（默认 data/catalogs/items.json）")
    a = ap.parse_args(argv)
    capture_dir = Path(a.capture_dir)
    if not capture_dir.is_dir():
        print("抓包目录不存在：%s" % capture_dir)
        return 2
    result = analyze(capture_dir, Path(a.catalog))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "layout.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    report = render_report(result)
    (a.out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print("产物：%s" % (a.out / "layout.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
