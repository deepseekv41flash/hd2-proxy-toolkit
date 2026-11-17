#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 hd2-proxy-toolkit 自带的 JSON 数据目录：data/catalogs/*.json。

源仓库（全部**只读**，本脚本绝不写入、不删除、不建文件）：
  D:\\Downloads\\variant_mod   旧面板研究副本（MT 代理路线的工作目录）
      - variant_catalog.json       变种目录（分组 + 变种名 + tag/mechanic 效果 id）
      - stratagem_catalog.json     type32「临时配发战备」目录（GWE effectType=32）
      - runtime/inventory_*.json   库存注入配置（物品解锁实验的 mixId 清单）
      - runtime/items_inject.json  武器目录注入（未发布武器行 itemId）
  D:\\mod\\work\\variant-net    网络层研究仓（hd2-network-proxy 的产物仓）
      - out/effects-full.csv       GWE 效果全量解码表（312 条，数值来自数据表）
      - out/effect-menu.csv        效果菜单展示表（presence/阵营/显示名，面向菜单）
      - refs/armor_rows_parsed.json   外观表（generated_customization_armor_sets）422 行解析
      - refs/store-cosmetics-20261106.json  已解名字的商店外观（mixId -> name）
      - refs/unreleased_candidates.json     无名外观候选（外观表 itemId）
      - configs/inventory_*.json / items_inject.json  同上的实验配置副本
  D:\\mod\\work\\repo-datamined  离线数据挖掘仓
      - out/planet/planet-index.json   星球索引（438 条：index/name/biome/planet_type/setup/region/locid）
      - out/planet/planet-data.json    星球全量设置（本脚本只用来查 settingsHash；当前无此字段）

本仓库输入（可写、随仓库走）：
  <repo>/data/sources/variant_overlay.json   变种目录覆盖层（源目录冻结之后由线上证据确认的变种；
                                             例如 2026-11-17 补的 腐蚀变种/毒瘴变种）
  <repo>/data/sources/progression_item_catalog.json
                                             服务端物品目录的紧凑索引（mixId -> itemId/类别）。
                                             用来给 items.json 补「内部名」：附件选项名从
                                             repo-datamined 的 weapon-customization-options 表取，
                                             外观名从 variant-net 的外观表取。

只读约定：
  1. 三个源目录只读；脚本只写本仓库内两个固定产物：
     <repo>/data/catalogs/*.json（GUI 目录）与 <repo>/data/legacy/variant_catalog.json（引擎目录）。
  2. JSON 数据内不出现绝对路径，source 一律写逻辑名（如 variant-net/refs/...）。
  3. 缺任何一个必需源文件 -> 明确报错并退出（退出码 1），绝不静默产出空表。

默认源路径：代码里不写死本机绝对路径，而是按本仓库在工作区中的相对位置推导
（<repo>/../variant-net、<repo>/../repo-datamined、<repo 所在盘符>/Downloads/variant_mod），
解析结果即本机真实源路径；换机器/换目录时用下面的 --variant-mod/--variant-net/--datamined 覆盖。

确定性：
  所有输出 UTF-8（无 BOM）、ensure_ascii=False、indent=1；
  GUI 目录（data/catalogs/*.json）sort_keys=True、结尾带换行，列表按主键排序；
  引擎目录（data/legacy/variant_catalog.json）保留源文件的键序、结尾**不带**换行（与迁入时逐字节一致）；
  不使用当前时间/随机数/绝对路径进数据 ⇒ 同样的源重跑字节一致。

用法：
  python tools/gen_catalogs.py
  python tools/gen_catalogs.py --variant-mod <path> --variant-net <path> \\
                               --datamined <path> --out <path>
  python tools/gen_catalogs.py --overlay data/sources/variant_overlay.json --legacy-out data/legacy/variant_catalog.json
  python tools/gen_catalogs.py --no-legacy        # 只出 GUI 目录，不动引擎目录
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- 路径与常量

REPO_ROOT = Path(__file__).resolve().parents[1]

# 默认源路径：代码里**不写死本机绝对路径**（tools/check_gate.py 的 M0 门禁要求），
# 按本仓库在工作区中的相对位置推导，解析结果就是本机真实源路径：
#   <repo>/../variant-net、<repo>/../repo-datamined、<repo 所在盘符>/Downloads/variant_mod
# 换机器/换目录时用 --variant-mod / --variant-net / --datamined 显式覆盖即可复现。
_DISK_ROOT = Path(REPO_ROOT.anchor)  # 例如 D:\
DEFAULT_VARIANT_MOD = _DISK_ROOT / "Downloads" / "variant_mod"
DEFAULT_VARIANT_NET = REPO_ROOT.parent / "variant-net"
DEFAULT_DATAMINED = REPO_ROOT.parent / "repo-datamined"
DEFAULT_OUT = REPO_ROOT / "data" / "catalogs"
# 变种覆盖层（本仓库输入；源目录 variant_mod 冻结后新增的变种写这里）与引擎目录输出
DEFAULT_OVERLAY = REPO_ROOT / "data" / "sources" / "variant_overlay.json"
DEFAULT_LEGACY_OUT = REPO_ROOT / "data" / "legacy" / "variant_catalog.json"
DEFAULT_CATALOG_INDEX = REPO_ROOT / "data" / "sources" / "progression_item_catalog.json"

# build.json 的手工常量（游戏 build 变化时改这里并重跑；variant_catalog 里的 build 另见 generated_from）
GAME_BUILD = "26568081"
WAR_ID = 801
API_HOST = "api.live.prod.thehelldiversgame.com"
WAR_SEASON = 801

# source 字段使用的逻辑名（数据里绝不出现绝对路径）
SRC_VARIANTS = "variant_mod/variant_catalog.json"
SRC_VARIANTS_OVERLAY = "data/sources/variant_overlay.json"
SRC_STRATAGEMS = "variant_mod/stratagem_catalog.json"
SRC_EFFECTS_FULL = "variant-net/out/effects-full.csv"
SRC_EFFECTS_MENU = "variant-net/out/effect-menu.csv"
SRC_ARMOR_ROWS = "variant-net/refs/armor_rows_parsed.json"
SRC_STORE_COSMETICS = "variant-net/refs/store-cosmetics-20261106.json"
SRC_UNRELEASED = "variant-net/refs/unreleased_candidates.json"
SRC_PLANET_INDEX = "repo-datamined/out/planet/planet-index.json"
# 物品内部名解析用：目录索引（本仓库快照）+ 武器改装选项内部名表（研究仓解析产物）
SRC_CATALOG_INDEX = "data/sources/progression_item_catalog.json"
SRC_WEAPON_OPTIONS = "repo-datamined/refs/weapon-customization-options-26251122.json"
SRC_PLANET_DATA = "repo-datamined/out/planet/planet-data.json"
# 行号 -> 游戏索引 的权威映射（war 801 抓包 + planet_data 尾部 hashmap 对齐产物）。
# 为什么必须合并：planet-index.json 的 `index` 是 planet_data **行号**，不是游戏索引；
# 游戏里 Status/warinfo 用的是「压缩后」的游戏索引，两者偏移不是常数（M4 实机踩坑）。
SRC_INDEX_NAMES = "repo-datamined/out/planet/index-names-801.json"

# 库存配置文件的来源分类（粗分类；不是游戏内 progressionCategory 原字段的转述，
# 而是按文件语义/文件名给出：武器=cat1 实验、附件=cat2、外观=cat3、战备许可=cat11）。
# None 表示该文件的条目类别未知（探针文件混了多个 cat）。
INVENTORY_CATEGORIES: dict[str, str | None] = {
    "inventory_attach": "attachment",
    "inventory_cosmetic": "cosmetic",
    "inventory_stratagem": "stratagem",
    "inventory_inject": "weapon",
    "inventory_probe": None,
}


class SourceError(Exception):
    """源数据缺失 / 结构不符合预期。直接导致脚本失败退出。"""


# ---------------------------------------------------------------- 通用工具


def log(message: str) -> None:
    print(f"[gen_catalogs] {message}")


def require_file(path: Path, what: str) -> Path:
    if not path.is_file():
        raise SourceError(f"缺少{what}: {path}")
    return path


def load_json(path: Path, what: str, expect: type | tuple[type, ...] = dict) -> Any:
    """读取 UTF-8 JSON（容忍 BOM），并校验顶层类型。"""
    require_file(path, what)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise SourceError(f"{what} 不是 UTF-8 文本: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"{what} 不是合法 JSON: {path}: {exc}") from exc
    if not isinstance(data, expect):
        names = " / ".join(t.__name__ for t in (expect if isinstance(expect, tuple) else (expect,)))
        raise SourceError(f"{what} 顶层类型应为 {names}，实际是 {type(data).__name__}: {path}")
    return data


def load_csv(path: Path, what: str, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    """读取 CSV（带 BOM 也无妨）；缺列直接报错，避免把结构变化静默吞掉。"""
    require_file(path, what)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fieldnames = tuple(reader.fieldnames or ())
    except UnicodeDecodeError as exc:
        raise SourceError(f"{what} 不是 UTF-8 文本: {path}: {exc}") from exc
    missing = [col for col in required_columns if col not in fieldnames]
    if missing:
        raise SourceError(f"{what} 缺少列 {missing}（实际表头: {list(fieldnames)}）")
    return rows


def to_int(value: Any, where: str) -> int:
    """空值/None 不合法（用于必需整数）；供 to_opt_int 之外的强校验。"""
    result = to_opt_int(value, where)
    if result is None:
        raise SourceError(f"{where}: 期望整数，实际为空")
    return result


def to_opt_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 10)
    except ValueError as exc:
        raise SourceError(f"{where}: 期望整数，实际为 {value!r}") from exc


def to_text(value: Any) -> str | None:
    """去首尾空白；空字符串归一为 None（源里 '' 表示缺失）。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_float(value: Any) -> float | None:
    """可选浮点（星图坐标；空/非法一律 None，不猜值）。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pick_display_name(candidates: list[str]) -> str | None:
    """名字里有 Title-Case 变体（含小写字母）就优先它，否则取第一个。"""
    for name in candidates:
        if any(ch.islower() for ch in name):
            return name
    return candidates[0] if candidates else None


def write_json(out_dir: Path, filename: str, payload: Any, entries: int) -> None:
    """UTF-8 / indent=1 / sort_keys 写出；同一份源重跑必须字节一致。"""
    path = out_dir / filename
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # --out 指到仓库外时按传入路径显示
        shown = path.as_posix()
    print(f"wrote {shown} entries={entries}")


# ---------------------------------------------------------------- 1. 变种目录


def infer_faction(presence: str | None) -> str:
    """源里没有 faction 时按 presence 前缀推断（任务约定）。"""
    if not presence:
        return "universal"
    if presence.startswith("bugs_"):
        return "terminid"
    if presence.startswith(("bots_", "elite_bot_")):
        return "automaton"
    if presence.startswith("illuminate_"):
        return "illuminate"
    return "universal"


def load_variant_overlay(path: Path | None) -> dict[str, Any]:
    """读覆盖层；文件不存在视为「没有覆盖」（不报错：干净 checkout 也能重跑源目录）。"""
    if path is None:
        return {}
    if not Path(path).is_file():
        log(f"note: 没有覆盖层 {path}（按纯源目录生成）")
        return {}
    doc = load_json(Path(path), "变种覆盖层 variant_overlay.json", dict)
    for key, expect in (("items", dict), ("aliases", dict), ("groups", list), ("remove", list)):
        if key in doc and not isinstance(doc[key], expect):
            raise SourceError(
                f"variant_overlay.json 的 {key} 类型异常: {type(doc[key]).__name__}（应为 {expect.__name__}）"
            )
    return doc


def apply_variant_overlay(data: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """把覆盖层合并进源变种目录，返回新对象（源数据不动）。

    覆盖层支持的键（都可用、都可缺）：
      remove  [name, ...]                从 variants/meta 里摘掉（改名/合并时用）
      items   {name: {ids, faction, presence, tag, mechanic, help, ...}}
                                         新增（或覆盖同名）变种；ids 之外都是 meta 字段
      aliases {alias: 正式名}             追加别名（旧名必须能解析回新名，避免老 profile 失效）
      groups  [{match, append: [name]}]  往名字前缀命中的分组追加成员；组名末尾若带数量
                                         （"虫族 5"）自动改成实际条数（"虫族 7"）
    """
    if not overlay:
        return data
    merged = copy.deepcopy(data)
    groups = merged.get("groups") or []
    variants = merged.get("variants") or {}
    meta = merged.get("meta") or {}
    aliases = merged.setdefault("aliases", {})

    for name in overlay.get("remove") or []:
        if name not in variants and name not in meta:
            raise SourceError(f"variant_overlay.json remove 里的 {name!r} 不在源目录中")
        variants.pop(name, None)
        meta.pop(name, None)

    for name, spec in (overlay.get("items") or {}).items():
        if not isinstance(spec, dict):
            raise SourceError(f"variant_overlay.json items[{name!r}] 应为对象")
        ids = spec.get("ids")
        if not isinstance(ids, list) or not ids:
            raise SourceError(f"variant_overlay.json items[{name!r}].ids 应为非空数组")
        if name in variants:
            raise SourceError(f"variant_overlay.json items 里的 {name!r} 与源目录重名（改名请用 remove + items）")
        variants[name] = [to_int(x, f"variant_overlay.json items[{name!r}].ids") for x in ids]
        meta[name] = {key: value for key, value in spec.items() if key != "ids"}

    for alias, target in (overlay.get("aliases") or {}).items():
        if target not in variants:
            raise SourceError(f"variant_overlay.json aliases[{alias!r}] 指向不存在的变种 {target!r}")
        existing = aliases.get(alias)
        if existing not in (None, target):
            raise SourceError(
                f"variant_overlay.json aliases[{alias!r}] 与源目录冲突（{existing!r} != {target!r}）"
            )
        aliases[alias] = target

    for rule in overlay.get("groups") or []:
        if not isinstance(rule, dict) or not rule.get("match"):
            raise SourceError(f"variant_overlay.json groups 规则结构异常: {rule!r}")
        match = str(rule["match"])
        append = list(rule.get("append") or [])
        hits = [group for group in groups if str(group.get("name") or "").startswith(match)]
        if len(hits) != 1:
            raise SourceError(
                f"variant_overlay.json groups 规则 {match!r} 命中 {len(hits)} 个分组（应恰好 1 个）"
            )
        group = hits[0]
        members = group.setdefault("variants", [])
        for name in append:
            if name not in variants:
                raise SourceError(f"variant_overlay.json groups 规则 {match!r} 追加了不存在的变种 {name!r}")
            if name not in members:
                members.append(name)
        m = re.match(r"^(.*?)\s*(\d+)$", str(group.get("name") or ""))
        if m:  # 组名带数量后缀 -> 跟着实际条数走
            group["name"] = f"{m.group(1)} {len(members)}"

    return merged


def build_variants(
    variant_mod: Path, overlay_path: Path | None = None
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    data = load_json(variant_mod / "variant_catalog.json", "变种目录 variant_catalog.json", dict)
    data = apply_variant_overlay(data, load_variant_overlay(overlay_path))

    for key in ("build", "gameVersion", "note", "groups", "variants", "meta"):
        if key not in data:
            raise SourceError(f"variant_catalog.json 缺少字段 {key!r}")

    groups = data["groups"]
    if not isinstance(groups, list) or not groups:
        raise SourceError("variant_catalog.json 的 groups 必须是非空数组")
    for group in groups:
        if not isinstance(group, dict) or "name" not in group or "variants" not in group:
            raise SourceError(f"variant_catalog.json 的 group 结构异常: {group!r}")

    variants_ids: dict[str, list[int]] = data["variants"]
    meta: dict[str, dict[str, Any]] = data["meta"]
    if not isinstance(variants_ids, dict) or not variants_ids:
        raise SourceError("variant_catalog.json 的 variants 必须是非空对象")
    if not isinstance(meta, dict):
        raise SourceError("variant_catalog.json 的 meta 必须是对象")

    all_names = set(variants_ids) | set(meta)
    if set(variants_ids) != set(meta):
        log(
            "note: variants 与 meta 的变种名不一致 "
            f"(只在 variants: {sorted(set(variants_ids) - set(meta))}; "
            f"只在 meta: {sorted(set(meta) - set(variants_ids))})"
        )

    items: dict[str, Any] = {}
    for name in sorted(all_names):
        ids_raw = variants_ids.get(name, [])
        if not isinstance(ids_raw, list):
            raise SourceError(f"variant_catalog.json variants[{name!r}] 应为数组")
        ids = [to_int(effect_id, f"variant_catalog.json variants[{name!r}]") for effect_id in ids_raw]

        entry: dict[str, Any] = {}
        source_meta = meta.get(name, {})
        if not isinstance(source_meta, dict):
            raise SourceError(f"variant_catalog.json meta[{name!r}] 应为对象")
        presence = to_text(source_meta.get("presence"))
        faction = to_text(source_meta.get("faction")) or infer_faction(presence)
        # 原样保留 tag / mechanic / help 等其它字段
        for key, value in source_meta.items():
            if key not in ("faction", "presence"):
                entry[key] = value
        entry["ids"] = ids
        entry["faction"] = faction
        entry["presence"] = presence
        items[name] = entry

    if not items:
        raise SourceError("variant_catalog.json 没有解析出任何变种")

    payload = {
        "build": data["build"],
        "game_version": data["gameVersion"],
        "note": data["note"],
        # aliases 是源里的简称->正式名映射，保留给界面搜索用（不属于 items 主键）
        "aliases": data.get("aliases", {}),
        "groups": [dict(group) for group in groups],
        "items": items,
    }
    # 第三个返回值是「合并覆盖层之后的源目录」：引擎目录直接用它的键序与结构，避免两份目录漂移
    return payload, len(items), data


def build_legacy(variants: dict[str, Any]) -> dict[str, Any]:
    """引擎目录 data/legacy/variant_catalog.json：与 GUI 目录同源，只是键名/顺序沿用引擎老格式。

    键序固定，不排序、不补换行 —— 与 M0 迁入的那份文件逐字节可比，改动一眼能看出来。
    """
    order = ("build", "gameVersion", "note", "groups", "variants", "meta", "aliases")
    missing = [key for key in ("build", "gameVersion", "note", "groups", "variants", "meta")
               if key not in variants]
    if missing:
        raise SourceError(f"引擎目录缺少字段 {missing}")
    return {key: variants[key] for key in order if key in variants}


def write_legacy(path: Path, doc: dict[str, Any]) -> None:
    """写引擎目录：键序/缩进沿用老文件，**结尾不加换行**（与迁入文件逐字节一致）。"""
    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        shown = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = path.as_posix()
    print(f"wrote {shown} entries={len(doc.get('variants') or {})}")


# ---------------------------------------------------------------- 2. 战备目录


def build_stratagems(variant_mod: Path) -> tuple[dict[str, Any], int]:
    data = load_json(
        variant_mod / "stratagem_catalog.json", "战备目录 stratagem_catalog.json", dict
    )
    rows = data.get("items")
    if not isinstance(rows, list) or not rows:
        raise SourceError("stratagem_catalog.json 的 items 必须是非空数组")

    seen: set[int] = set()
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or "id" not in row:
            raise SourceError(f"stratagem_catalog.json items[{index}] 结构异常: {row!r}")
        stratagem_id = to_int(row["id"], f"stratagem_catalog.json items[{index}].id")
        if stratagem_id in seen:
            raise SourceError(f"stratagem_catalog.json 出现重复 id {stratagem_id}")
        seen.add(stratagem_id)
        items.append(dict(row))  # 保留 id / name / key / native_hash / effect_hash / group 等全部字段

    items.sort(key=lambda item: to_int(item["id"], "stratagem_catalog.json items[].id"))
    return {"items": items, "count": len(items)}, len(items)


# ---------------------------------------------------------------- 3. GWE 效果


EFFECTS_FULL_COLUMNS = (
    "effect_id",
    "effect_type",
    "type_semantics",
    "flags",
    "value_types",
    "values_raw",
    "values_hex",
    "name",
    "short_desc",
    "long_desc",
    "fluff",
    "target",
    "target_extra",
    "note",
    "label",
    "decode_level",
    "live_count",
    "live_planets",
    "ever_snapshot_count",
    "ever_planet_count",
    "gameplay_effect_id32",
)

EFFECT_MENU_COLUMNS = (
    "effect_id",
    "effect_type",
    "type_hint",
    "presence",
    "kind",
    "kind_label",
    "sub",
    "race",
    "display_name",
    "description",
    "live_count",
    "live_planets",
    "gameplay_effect_id32",
    "evidence",
)


def build_effects(variant_net: Path) -> tuple[dict[str, Any], int]:
    full_rows = load_csv(
        variant_net / "out" / "effects-full.csv", "效果全量表 effects-full.csv", EFFECTS_FULL_COLUMNS
    )
    menu_rows = load_csv(
        variant_net / "out" / "effect-menu.csv", "效果菜单表 effect-menu.csv", EFFECT_MENU_COLUMNS
    )

    def index_rows(rows: list[dict[str, str]], what: str) -> dict[int, dict[str, str]]:
        indexed: dict[int, dict[str, str]] = {}
        for row in rows:
            effect_id = to_int(row.get("effect_id"), f"{what} effect_id")
            if effect_id in indexed:
                raise SourceError(f"{what} 出现重复 effect_id {effect_id}")
            indexed[effect_id] = row
        return indexed

    full = index_rows(full_rows, "effects-full.csv")
    menu = index_rows(menu_rows, "effect-menu.csv")

    only_full = sorted(set(full) - set(menu))
    only_menu = sorted(set(menu) - set(full))
    if only_full:
        log(f"note: {SRC_EFFECTS_FULL} 独有 effect_id {len(only_full)} 条: {only_full[:20]}")
    if only_menu:
        log(f"note: {SRC_EFFECTS_MENU} 独有 effect_id {len(only_menu)} 条: {only_menu[:20]}")
    log("note: 两表的 live_planets 格式不同（effects-full 为原始文本，effect-menu 为纯 index 串），采用 effects-full 文本")

    # 数值列的一致性强校验；两边不一致时按任务口径保留 effects-full，并显式提示
    for column in ("effect_type", "flags", "live_count", "gameplay_effect_id32"):
        mismatched: list[int] = []
        for effect_id in sorted(set(full) & set(menu)):
            left = to_opt_int(full[effect_id].get(column), f"effects-full.csv[{effect_id}].{column}")
            right = to_opt_int(menu[effect_id].get(column), f"effect-menu.csv[{effect_id}].{column}")
            if left != right:
                mismatched.append(effect_id)
        if mismatched:
            log(
                f"note: {column} 两表不一致 {len(mismatched)} 条（采用 effects-full）: "
                f"{mismatched[:20]}"
            )

    items: list[dict[str, Any]] = []
    for effect_id in sorted(set(full) | set(menu)):
        row = full.get(effect_id, {})
        display = menu.get(effect_id, {})

        def full_text(column: str) -> str | None:
            return to_text(row.get(column))

        def menu_text(column: str) -> str | None:
            return to_text(display.get(column))

        item = {
            # 主键与数值/解码字段：effects-full 优先（数据表侧）
            "effect_id": effect_id,
            "effect_type": to_opt_int(row.get("effect_type") or display.get("effect_type"), f"effect {effect_id} effect_type"),
            "type_semantics": full_text("type_semantics"),
            "flags": to_opt_int(row.get("flags"), f"effect {effect_id} flags"),
            "value_types": full_text("value_types"),
            "values_raw": full_text("values_raw"),
            "values_hex": full_text("values_hex"),
            "name": full_text("name"),
            "short_desc": full_text("short_desc"),
            "long_desc": full_text("long_desc"),
            "fluff": full_text("fluff"),
            "target": full_text("target"),
            "target_extra": full_text("target_extra"),
            "note": full_text("note"),
            "label": full_text("label"),
            "decode_level": full_text("decode_level"),
            "live_count": to_opt_int(row.get("live_count"), f"effect {effect_id} live_count"),
            "live_planets": full_text("live_planets"),
            "ever_snapshot_count": to_opt_int(
                row.get("ever_snapshot_count"), f"effect {effect_id} ever_snapshot_count"
            ),
            "ever_planet_count": to_opt_int(
                row.get("ever_planet_count"), f"effect {effect_id} ever_planet_count"
            ),
            "gameplay_effect_id32": to_opt_int(
                row.get("gameplay_effect_id32"), f"effect {effect_id} gameplay_effect_id32"
            ),
            # 菜单展示字段：effect-menu 优先
            "type_hint": menu_text("type_hint"),
            "presence": menu_text("presence"),
            "kind": to_opt_int(display.get("kind"), f"effect {effect_id} kind"),
            "kind_label": menu_text("kind_label"),
            "sub": to_opt_int(display.get("sub"), f"effect {effect_id} sub"),
            "race": menu_text("race"),
            "display_name": menu_text("display_name"),
            "description": menu_text("description"),
            "evidence": menu_text("evidence"),
        }
        items.append(item)

    if not items:
        raise SourceError("effects 两表合并后为空")
    return {"items": items, "count": len(items)}, len(items)


# ---------------------------------------------------------------- 4. 星球


def collect_key_names(node: Any, wanted: frozenset[str], found: list[str], path: str = "") -> None:
    """递归收集出现过的键名（只用于确认 settingsHash 是否存在）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in wanted:
                found.append(f"{path}/{key}")
            collect_key_names(value, wanted, found, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            collect_key_names(value, wanted, found, f"{path}[{index}]")


def build_planets(datamined: Path) -> tuple[dict[str, Any], int]:
    index_path = datamined / "out" / "planet" / "planet-index.json"
    data_path = datamined / "out" / "planet" / "planet-data.json"
    rows = load_json(index_path, "星球索引 planet-index.json", list)
    planet_data = load_json(data_path, "星球全量 planet-data.json", list)

    # 行号 -> 游戏索引（权威映射；只覆盖上战场的 273 颗，休眠星为 null）
    map_path = datamined / "out" / "planet" / "index-names-801.json"
    game_by_row: dict[int, dict[str, Any]] = {}
    map_meta: dict[str, Any] = {}
    if map_path.exists():
        mapping_doc = load_json(map_path, "游戏索引映射 index-names-801.json", dict)
        map_meta = {
            "war_id": to_opt_int(mapping_doc.get("warId"), f"{SRC_INDEX_NAMES} warId"),
            "source": to_text(mapping_doc.get("source")),
        }
        for position, entry in enumerate(mapping_doc.get("mapping") or []):
            if not isinstance(entry, dict):
                continue
            gidx = to_opt_int(entry.get("index"), f"index-names[{position}].index")
            row = to_opt_int(entry.get("row"), f"index-names[{position}].row")
            if gidx is None or row is None:
                continue
            game_by_row[row] = {
                "game_index": gidx,
                "x": _opt_float(entry.get("x")),
                "y": _opt_float(entry.get("y")),
            }
        log(
            f"note: {SRC_INDEX_NAMES} 合并游戏索引 {len(game_by_row)} 条"
            f"（行号≠游戏索引；其余 {len(rows) - len(game_by_row)} 行为休眠星，game_index=null）"
        )
    else:
        log(f"warn: 缺少 {SRC_INDEX_NAMES} -> planets.json 的 game_index 全部为 null")

    # 任务要求：检查 planet-data.json 是否有 settingsHash；有则按 index 合并，无则 null + 日志说明。
    settings_hash_by_index: dict[int, Any] = {}
    discovered_keys: list[str] = []
    collect_key_names(planet_data, frozenset({"settingsHash", "settings_hash"}), discovered_keys)
    if discovered_keys:
        for row in planet_data:
            if not isinstance(row, dict):
                continue
            for key in ("settingsHash", "settings_hash"):
                if key in row:
                    idx = to_opt_int(row.get("index"), f"{SRC_PLANET_DATA} index")
                    if idx is not None:
                        settings_hash_by_index[idx] = row[key]
                    break
        log(
            f"note: {SRC_PLANET_DATA} 找到 settingsHash 字段 {len(settings_hash_by_index)} 条，"
            f"按 index 合并进 planets.json"
        )
    else:
        log(
            f"note: {SRC_PLANET_DATA} 没有 settingsHash / settings_hash 字段 "
            f"(共 {len(planet_data)} 条, 键名已递归确认) -> planets.json 的 settings_hash 全部置 null"
        )

    items: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceError(f"planet-index.json[{position}] 不是对象")
        index = to_int(row.get("index"), f"planet-index.json[{position}].index")
        if index in seen_indices:
            raise SourceError(f"planet-index.json 出现重复 index {index}")
        seen_indices.add(index)
        game_info = game_by_row.get(index) or {}
        items.append(
            {
                "index": index,
                "game_index": game_info.get("game_index"),
                "name": to_text(row.get("name")),
                "biome": to_text(row.get("biome")),
                "planet_type": to_opt_int(row.get("planet_type"), f"planet {index} planet_type"),
                "setup": to_text(row.get("setup")),
                "region": to_text(row.get("region")),
                "locid": to_opt_int(row.get("locid"), f"planet {index} locid"),
                "settings_hash": settings_hash_by_index.get(index),
                "x": game_info.get("x"),
                "y": game_info.get("y"),
            }
        )

    if not items:
        raise SourceError("planet-index.json 没有解析出任何星球")
    items.sort(key=lambda item: item["index"])
    payload: dict[str, Any] = {"items": items, "count": len(items)}
    if map_meta:
        payload["game_index_source"] = map_meta
    return payload, len(items)


# ---------------------------------------------------------------- 5. 物品


def iter_id_objects(node: Any) -> Any:
    """递归产出所有含 mixId 或 itemId 键的对象（用于库存配置的通用扫描）。"""
    if isinstance(node, dict):
        if "mixId" in node or "itemId" in node:
            yield node
        for value in node.values():
            yield from iter_id_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_id_objects(value)


def inventory_category(filename: str) -> tuple[str | None, bool]:
    stem = filename[:-5] if filename.endswith(".json") else filename
    for prefix, category in INVENTORY_CATEGORIES.items():
        if stem.startswith(prefix):
            return category, True
    return None, False


class UnionFind:
    """极简并查集：把「同 id 的多来源记录」合并成同一个物品。"""

    def __init__(self) -> None:
        self._parent: list[int] = []

    def add(self) -> int:
        index = len(self._parent)
        self._parent.append(index)
        return index

    def find(self, index: int) -> int:
        root = index
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[index] != root:  # 路径压缩
            self._parent[index], index = root, self._parent[index]
        return root

    def union(self, left: int, right: int) -> int:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[right_root] = left_root
        return left_root


# 物品内部名解析：目录类别 -> 名字来源
#   2 = 附件：`itemId` 是改装选项 id（optionId），内部名在 weapon_customization_settings 表；
#   3 = 外观：`itemId` 是外观表行 id，名字来自外观表的 names 字段；
#   其它类别（1 武器 / 11 战备 / …）：目录行只有 id，没有可用的名字来源 -> 留空（界面显示"内部名未解"）。
ITEM_CATEGORY_NAMES = {
    0: "未分类",
    1: "武器",
    2: "附件",
    3: "外观",
    4: "护甲套装",
    9: "战备升级/通行证",
    10: "未分类",
    11: "战备",
    18: "货币",
    19: "表情/动作",
    20: "未分类",
    21: "未分类",
    23: "未分类",
}


def _load_item_catalog_index(path: Path) -> dict[int, dict[str, int]]:
    """读目录索引（mixId -> {item, cat}）；同一 mixId 出现多次时按 mixId+itemId 去重，类别冲突报错。"""
    require_file(path, "物品目录索引 progression_item_catalog.json")
    doc = load_json(path, "物品目录索引 progression_item_catalog.json", dict)
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SourceError("progression_item_catalog.json 的 rows 必须是非空数组")
    by_mix: dict[int, dict[str, int]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceError(f"progression_item_catalog.json rows[{position}] 不是对象")
        mix = to_int(row.get("mix"), f"progression_item_catalog.json rows[{position}].mix")
        item = to_int(row.get("item"), f"progression_item_catalog.json rows[{position}].item")
        cat = to_opt_int(row.get("cat"), f"progression_item_catalog.json rows[{position}].cat") or 0
        existing = by_mix.get(mix)
        if existing is not None and existing["cat"] != cat:
            raise SourceError(
                f"progression_item_catalog.json 里 mixId {mix} 的类别冲突："
                f"{existing['cat']} vs {cat}"
            )
        by_mix.setdefault(mix, {"item": item, "cat": cat})
    return by_mix


def _load_attachment_option_names(path: Path) -> dict[int, str]:
    """读武器改装选项表：option_id(32 位) -> 内部名（如 "TUBE REDDOT 1,5x"）。"""
    doc = load_json(path, "武器改装选项表 weapon-customization-options", dict)
    options = doc.get("items")
    if not isinstance(options, list) or not options:
        raise SourceError("weapon-customization-options 的 items 必须是非空数组")
    out: dict[int, str] = {}
    for position, option in enumerate(options):
        if not isinstance(option, dict) or "option_id" not in option:
            raise SourceError(f"weapon-customization-options items[{position}] 结构异常")
        raw = to_text(option.get("option_id"))
        if not raw:
            continue
        try:
            option_id = int(raw, 16)
        except ValueError as exc:
            raise SourceError(
                f"weapon-customization-options items[{position}].option_id 不是 16 进制: {raw!r}"
            ) from exc
        name = to_text(option.get("name"))
        if name and option_id not in out:
            out[option_id] = name
    return out


def enrich_item_names(
    items: list[dict[str, Any]],
    catalog_index: dict[int, dict[str, int]],
    attachment_options: dict[int, str],
    armor_names: dict[int, str],
) -> int:
    """给 items 补 `catalog_category` 与（名字缺失时的）内部名 / 名字来源。

    只填空缺，不覆盖已有的显示名（外观表/商店表解出的名字更贴近玩家）；
    解析不到就留空 —— 界面会显示「内部名未解」，不编造。
    """
    resolved = 0
    for item in items:
        mix = item.get("mix_id")
        row = catalog_index.get(int(mix)) if mix is not None else None
        item["catalog_category"] = row["cat"] if row else None
        if item.get("name") or not row:
            continue
        name, source = None, None
        if row["cat"] == 2:
            name = attachment_options.get(row["item"])
            source = "catalog-option"
        elif row["cat"] == 3:
            name = armor_names.get(row["item"])
            source = "armor-table"
        if name:
            item["name"] = name
            item["name_source"] = source
            resolved += 1
    return resolved


def build_items(
    variant_net: Path,
    variant_mod: Path,
    datamined: Path,
    catalog_index_path: Path,
) -> tuple[dict[str, Any], int]:
    records: list[dict[str, Any]] = []

    def add_record(
        *,
        mix_id: int | None = None,
        item_id: int | None = None,
        name: str | None = None,
        category: str | None = None,
        source: str,
    ) -> None:
        if mix_id is None and item_id is None:
            raise SourceError(f"{source}: 记录既没有 mix_id 也没有 item_id")
        records.append(
            {
                "mix_id": mix_id,
                "item_id": item_id,
                "name": name,
                "category": category,
                "source": source,
            }
        )

    # --- 外观表 422 行：行 id 是目录 itemId（UNLOCK-MAP §8.2），名字是 [[locid, name], ...]
    armor_rows = load_json(variant_net / "refs" / "armor_rows_parsed.json", "外观表 armor_rows_parsed.json", list)
    armor_seen: set[int] = set()
    for position, row in enumerate(armor_rows):
        if not isinstance(row, dict) or "id" not in row:
            raise SourceError(f"armor_rows_parsed.json[{position}] 结构异常: {row!r}")
        item_id = to_int(row["id"], f"armor_rows_parsed.json[{position}].id")
        if item_id in armor_seen:
            raise SourceError(f"armor_rows_parsed.json 出现重复 id {item_id}")
        armor_seen.add(item_id)
        names: list[str] = []
        for pair in row.get("names") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[1]:
                text = to_text(pair[1])
                if text:
                    names.append(text)
        add_record(
            item_id=item_id,
            name=pick_display_name(names),
            category="cosmetic",
            source=SRC_ARMOR_ROWS,
        )

    # --- 未发布外观候选：id 为外观表 itemId（15 行全部是上面 422 行的子集，会合并来源）
    unreleased_rows = load_json(
        variant_net / "refs" / "unreleased_candidates.json", "未发布外观候选", list
    )
    for position, row in enumerate(unreleased_rows):
        if not isinstance(row, dict) or "id" not in row:
            raise SourceError(f"unreleased_candidates.json[{position}] 结构异常: {row!r}")
        add_record(
            item_id=to_int(row["id"], f"unreleased_candidates.json[{position}].id"),
            category="cosmetic",
            source=SRC_UNRELEASED,
        )

    # --- 商店外观：键是 mixId；name 可能为 null（未解出）
    store = load_json(variant_net / "refs" / "store-cosmetics-20261106.json", "商店外观表", dict)
    for raw_key in sorted(store, key=lambda key: to_int(key, "store-cosmetics.json key")):
        value = store[raw_key]
        if not isinstance(value, dict):
            raise SourceError(f"store-cosmetics-20261106.json[{raw_key!r}] 应为对象")
        add_record(
            mix_id=to_int(raw_key, "store-cosmetics.json key"),
            name=to_text(value.get("name")),
            category="cosmetic",
            source=SRC_STORE_COSMETICS,
        )

    # --- 库存注入配置：configs/ 与 runtime/ 两处都扫；items[].mixId、以及任何 mixId/itemId 出现处
    inventory_roots = (
        ("variant-net/configs", variant_net / "configs"),
        ("variant_mod/runtime", variant_mod / "runtime"),
    )
    for label, directory in inventory_roots:
        if not directory.is_dir():
            raise SourceError(f"缺少库存配置目录: {directory}")
        inventory_files = sorted(directory.glob("inventory_*.json"))
        if not inventory_files:
            raise SourceError(f"{directory} 下没有任何 inventory_*.json")
        for path in inventory_files:
            data = load_json(path, f"库存配置 {label}/{path.name}", dict)
            source = f"{label}/{path.name}"
            category, known = inventory_category(path.name)
            if not known:
                log(f"note: 未识别的库存文件名 {source}，category 记 null")
            for obj in iter_id_objects(data):
                mix_id = to_opt_int(obj.get("mixId"), f"{source} mixId") if "mixId" in obj else None
                item_id = to_opt_int(obj.get("itemId"), f"{source} itemId") if "itemId" in obj else None
                if mix_id is None and item_id is None:
                    continue
                add_record(
                    mix_id=mix_id,
                    item_id=item_id,
                    category=category,
                    source=source,
                )

        # --- 目录注入（未发布武器行）：add[].id 在武器行上同时是 itemId 与 mixId
        #     （UNLOCK-MAP §2.3「要补的 itemId（= mixId）」）；若将来出现显式 mixId/itemId 字段则优先用字段。
        items_inject_path = directory / "items_inject.json"
        data = load_json(items_inject_path, f"目录注入 {label}/items_inject.json", dict)
        source = f"{label}/items_inject.json"
        injection_rows: list[Any] = []
        for key in ("items", "add"):
            value = data.get(key)
            if isinstance(value, list):
                injection_rows.extend(value)
        if not injection_rows:
            raise SourceError(f"{source} 里没有 items/add 行")
        for position, row in enumerate(injection_rows):
            if not isinstance(row, dict):
                raise SourceError(f"{source} items/add[{position}] 不是对象")
            if "mixId" in row or "itemId" in row:
                mix_id = to_opt_int(row.get("mixId"), f"{source} mixId")
                item_id = to_opt_int(row.get("itemId"), f"{source} itemId")
            elif "id" in row:
                row_id = to_int(row["id"], f"{source} add[{position}].id")
                mix_id = item_id = row_id
            else:
                raise SourceError(f"{source} add[{position}] 没有 id/mixId/itemId")
            add_record(
                mix_id=mix_id,
                item_id=item_id,
                category="weapon",
                source=source,
            )

    # --- 合并：同一 mix_id / 同一 item_id 视为同一物品；itemId 与 mixId 数值相同也视为同一物品
    #     （外观表简单件 itemId == 目录 mixId，见 UNLOCK-MAP §8.2；本次仅零星几例，下面会打印）。
    uf = UnionFind()
    token_owner: dict[tuple[str, int], int] = {}
    for index, record in enumerate(records):
        uf.add()
        for namespace, value in (("mix", record["mix_id"]), ("item", record["item_id"])):
            if value is None:
                continue
            token = (namespace, value)
            if token in token_owner:
                uf.union(index, token_owner[token])
            else:
                token_owner[token] = index

    mix_values = {value for namespace, value in token_owner if namespace == "mix"}
    item_values = {value for namespace, value in token_owner if namespace == "item"}
    cross_merged: list[int] = []
    for value in sorted(mix_values & item_values):
        mix_root = uf.find(token_owner[("mix", value)])
        item_root = uf.find(token_owner[("item", value)])
        if mix_root != item_root:
            uf.union(mix_root, item_root)
            cross_merged.append(value)
    if cross_merged:
        log(
            "note: items 里 itemId 与 mixId 数值相同的记录按同一物品合并: "
            f"{cross_merged}（依据 UNLOCK-MAP §8.2：外观表简单件 itemId == 目录 mixId）"
        )

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        grouped.setdefault(uf.find(index), []).append(record)

    merged_items: list[dict[str, Any]] = []
    for group in grouped.values():
        mix_ids = {record["mix_id"] for record in group if record["mix_id"] is not None}
        item_ids = {record["item_id"] for record in group if record["item_id"] is not None}
        if len(mix_ids) > 1 or len(item_ids) > 1:
            raise SourceError(
                "items 合并出现一对多 id（同组多个 mixId/itemId），需要人工确认: "
                f"mix={sorted(mix_ids)} item={sorted(item_ids)} "
                f"sources={sorted({record['source'] for record in group})}"
            )
        categories = {record["category"] for record in group if record["category"]}
        if len(categories) > 1:
            raise SourceError(
                "items 合并出现类别冲突（同一物品来自不同类别来源），需要人工确认: "
                f"mix={sorted(mix_ids)} item={sorted(item_ids)} categories={sorted(categories)}"
            )
        name_candidates: list[str] = []
        for record in group:
            if record["name"] and record["name"] not in name_candidates:
                name_candidates.append(record["name"])
        sources = sorted({record["source"] for record in group})
        merged_items.append(
            {
                "mix_id": min(mix_ids) if mix_ids else None,
                "item_id": min(item_ids) if item_ids else None,
                "name": pick_display_name(name_candidates),
                "category": next(iter(categories)) if categories else None,
                # 单来源写字符串，多来源合并成去重数组（任务口径）
                "source": sources[0] if len(sources) == 1 else sources,
            }
        )

    if not merged_items:
        raise SourceError("items 没有解析出任何物品")

    # --- 内部名补全（2026-11-17 用户报「物品只有 id 没有名字」）
    armor_names: dict[int, str] = {}
    for row in armor_rows:
        if not isinstance(row, dict):
            continue
        try:
            row_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        texts = [to_text(pair[1]) for pair in (row.get("names") or [])
                 if isinstance(pair, (list, tuple)) and len(pair) == 2]
        picked = pick_display_name([t for t in texts if t])
        if picked:
            armor_names.setdefault(row_id, picked)
    resolved = enrich_item_names(
        merged_items,
        _load_item_catalog_index(catalog_index_path),
        _load_attachment_option_names(datamined / "refs" / "weapon-customization-options-26251122.json"),
        armor_names,
    )
    named = sum(1 for item in merged_items if item.get("name"))
    log(
        f"note: items 内部名解析 {resolved} 条；有名字 {named}/{len(merged_items)}"
        f"（来源：附件选项内部名 + 外观表；武器/战备等类别目录行没有名字来源 -> 留空）"
    )

    merged_items.sort(
        key=lambda item: (
            item["mix_id"] is None,
            item["mix_id"] if item["mix_id"] is not None else 0,
            item["item_id"] if item["item_id"] is not None else 0,
        )
    )
    return {"items": merged_items, "count": len(merged_items)}, len(merged_items)


# ---------------------------------------------------------------- 6. build 指纹


def build_build(variants: dict[str, Any]) -> tuple[dict[str, Any], int]:
    payload = {
        "game_build": GAME_BUILD,
        "war_id": WAR_ID,
        "api_host": API_HOST,
        "warseason": WAR_SEASON,
        "generated_from": {
            # 旧面板变种目录里记录的 build（与 PRODUCT game_build 不同，见 README）
            "variant_mod": variants["build"],
            # 星球索引的逻辑来源；settingsHash 检查结果见生成日志 / README
            "datamined": SRC_PLANET_INDEX,
        },
    }
    return payload, len(payload)


# ---------------------------------------------------------------- 主流程


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从只读研究仓生成 hd2-proxy-toolkit 的 data/catalogs/*.json（确定性输出）。"
    )
    parser.add_argument(
        "--variant-mod",
        type=Path,
        default=DEFAULT_VARIANT_MOD,
        help=f"旧面板研究副本目录（默认 {DEFAULT_VARIANT_MOD}）",
    )
    parser.add_argument(
        "--variant-net",
        type=Path,
        default=DEFAULT_VARIANT_NET,
        help=f"variant-net 研究仓目录（默认 {DEFAULT_VARIANT_NET}）",
    )
    parser.add_argument(
        "--datamined",
        type=Path,
        default=DEFAULT_DATAMINED,
        help=f"repo-datamined 研究仓目录（默认 {DEFAULT_DATAMINED}）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"输出目录（默认 {DEFAULT_OUT}）",
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        default=DEFAULT_OVERLAY,
        help=f"变种目录覆盖层（默认 {DEFAULT_OVERLAY}；不存在则按纯源目录生成）",
    )
    parser.add_argument(
        "--legacy-out",
        type=Path,
        default=DEFAULT_LEGACY_OUT,
        help=f"引擎变种目录输出（默认 {DEFAULT_LEGACY_OUT}）",
    )
    parser.add_argument(
        "--catalog-index",
        type=Path,
        default=DEFAULT_CATALOG_INDEX,
        help=f"物品目录紧凑索引（默认 {DEFAULT_CATALOG_INDEX}），用于补物品内部名",
    )
    parser.add_argument(
        "--no-legacy",
        action="store_true",
        help="只写 GUI 目录，不写引擎目录 data/legacy/variant_catalog.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # 日志里有中文/⚠ 等字符，避免控制台编码报错

    args = parse_args(argv)
    try:
        variants, variants_count, variants_source = build_variants(args.variant_mod, args.overlay)
        stratagems, stratagems_count = build_stratagems(args.variant_mod)
        effects, effects_count = build_effects(args.variant_net)
        planets, planets_count = build_planets(args.datamined)
        items, items_count = build_items(
            args.variant_net, args.variant_mod, args.datamined, args.catalog_index
        )
        build, build_count = build_build(variants)

        # 全部构建成功后再落盘，避免中途失败留下半套目录
        args.out.mkdir(parents=True, exist_ok=True)
        write_json(args.out, "variants.json", variants, variants_count)
        write_json(args.out, "stratagems.json", stratagems, stratagems_count)
        write_json(args.out, "effects.json", effects, effects_count)
        write_json(args.out, "planets.json", planets, planets_count)
        write_json(args.out, "items.json", items, items_count)
        write_json(args.out, "build.json", build, build_count)
        if not args.no_legacy:
            write_legacy(args.legacy_out, build_legacy(variants_source))
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
