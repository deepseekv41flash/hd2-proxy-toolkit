#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_item_names.py -- 用 dlbin 路线（只读）从游戏数据表里提取「物品内部名」映射。

WHY
    「物品与战备」页要显示物品内部名，但服务端 `/api/Progression/items` 的目录行只有 id，
    没有名字。名字在客户端本地数据里：
      * **武器 / 投掷物 / 背包等 LoadoutEntry 条目**：`generated_entities.dl_bin` 里的
        `LoadoutEntryComponentData`（块类型 `0x4F2CF417`）行 `+0x00` 就是**后端物品 id**
        （= 服务端目录行的 `itemId`）；该行所属实体在 `EncyclopediaEntryComponentData` 里有名字
        （"Veto" / "Smokescreen" / "Gallant" …）。
      * 附件（改装选项）与外观另有来源，见 `tools/gen_catalogs.py::enrich_item_names`
        （改装选项表 / 外观表）。
    本工具只做第一类：LoadoutEntry id → 实体内部名，产出 `data/sources/item_names_derived.json`
    给生成器用。

为什么写这个工具（而不是一次性脚本）
    2026-11-13 之后游戏更新到 26568081，**写** `data/game/*.dl_bin` 会被 EAC 判「未知的文件版本」，
    但**读**一直可用（解包密钥在 `refs/dlbin/keys/`，明文缓存落在 `refs/dlbin/plaintext-<build>/`）。
    所以这条路是可复用的只读侦察路线：换 build 后重跑本工具即可刷新内部名。

数据依赖（全部只读）
    --plain-root   D:/mod/refs/dlbin
        plaintext-<build>/generated_entities.dl_bin      实体库（明文缓存，解包产物）
        plaintext-<typelib-build>/dl_library.dl_typelib  类型库（跨 build 结构稳定时可直接用旧 build 的）
    --research     D:/mod/work/repo-datamined（hd2-datamined，只读）
        refs/dl-type-names.txt               类型名哈希表（filediver 公共表）
        refs/entity-locid-names.json         实体名（由 `tools/entity_locid_scan.py` 用 .strings 解析）
        tools/entity_locid_scan.py           块解析 / 几何自证 / 哈希图（本工具直接复用）

输出（本仓库，可入库）
    data/sources/item_names_derived.json
        {note, build, source, loadout_entry: {block_type, rows, named, items: {id: {name, type}}}}

用法
    python tools/extract_item_names.py                       # 用默认路径 + 自动挑最新 plaintext-<build>
    python tools/extract_item_names.py --build 26568081
    python tools/extract_item_names.py --plain-root D:/mod/refs/dlbin --research D:/mod/work/repo-datamined \\
        --out data/sources/item_names_derived.json

安全
    只读：不碰游戏安装目录、不启动游戏、不写任何 `data/game` 文件、不联网。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# 路径推导：<repo>/../repo-datamined、<repo>/../../refs/dlbin（与 gen_catalogs.py 同款约定，代码里不写死绝对路径）
DEFAULT_RESEARCH = REPO_ROOT.parent / "repo-datamined"
DEFAULT_PLAIN_ROOT = REPO_ROOT.parents[1] / "refs" / "dlbin"
DEFAULT_OUT = REPO_ROOT / "data" / "sources" / "item_names_derived.json"

LOADOUT_BLOCK_TYPE = 0x4F2CF417      # LoadoutEntryComponentData


class SourceError(Exception):
    """缺少输入 / 结构不符合预期。"""


def log(message: str) -> None:
    print(f"[extract_item_names] {message}")


def require_file(path: pathlib.Path, what: str) -> pathlib.Path:
    if not path.is_file():
        raise SourceError(f"缺少{what}: {path}")
    return path


def pick_build(plain_root: pathlib.Path, build: str | None) -> str:
    if build:
        if not (plain_root / f"plaintext-{build}").is_dir():
            raise SourceError(f"没有明文缓存目录: {plain_root / ('plaintext-' + build)}")
        return build
    builds = sorted(
        (p.name[len("plaintext-"):] for p in plain_root.glob("plaintext-*")
         if (p / "generated_entities.dl_bin").is_file()),
        key=lambda text: int(text) if text.isdigit() else -1,
    )
    if not builds:
        raise SourceError(f"{plain_root} 下没有 plaintext-<build>/generated_entities.dl_bin")
    return builds[-1]


def pick_typelib(plain_root: pathlib.Path, build: str) -> pathlib.Path:
    """优先同 build 的类型库；没有就退到最新的其它 build（类型库结构跨 build 稳定时才成立）。"""
    same = plain_root / f"plaintext-{build}" / "dl_library.dl_typelib"
    if same.is_file():
        return same
    candidates = sorted(
        (p for p in plain_root.glob("plaintext-*/dl_library.dl_typelib")),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise SourceError(f"{plain_root} 下没有 dl_library.dl_typelib")
    log(f"note: build {build} 没有自己的 typelib，退回 {candidates[-1]}")
    return candidates[-1]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")   # 中文日志，避免控制台 GBK 报错

    ap = argparse.ArgumentParser(description="只读提取 LoadoutEntry 物品内部名（dlbin 路线）")
    ap.add_argument("--plain-root", type=pathlib.Path, default=DEFAULT_PLAIN_ROOT,
                    help=f"dlbin 明文缓存根目录（默认 {DEFAULT_PLAIN_ROOT}）")
    ap.add_argument("--research", type=pathlib.Path, default=DEFAULT_RESEARCH,
                    help=f"hd2-datamined 仓库目录（默认 {DEFAULT_RESEARCH}）")
    ap.add_argument("--build", default=None, help="游戏 build（缺省用 plaintext-* 里最大的）")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT,
                    help=f"输出 JSON（默认 {DEFAULT_OUT}）")
    a = ap.parse_args(argv)

    try:
        build = pick_build(a.plain_root, a.build)
        plain_path = require_file(
            a.plain_root / f"plaintext-{build}" / "generated_entities.dl_bin", "实体库明文缓存")
        typelib_path = pick_typelib(a.plain_root, build)
        tools_dir = require_file(a.research / "tools" / "entity_locid_scan.py", "研究仓工具目录").parent
        names_txt = require_file(a.research / "refs" / "dl-type-names.txt", "类型名表")
        entity_names_path = require_file(a.research / "refs" / "entity-locid-names.json", "实体名表")

        sys.path.insert(0, str(tools_dir))
        import entity_locid_scan as scan                       # noqa: E402
        from table_dictionary import Dictionary, load_names    # noqa: E402

        plain = plain_path.read_bytes()
        dic = Dictionary(typelib_path.read_bytes(), load_names(names_txt))
        blocks = [block for block in scan.parse_blocks(plain) if block["type_id"] == LOADOUT_BLOCK_TYPE]
        if len(blocks) != 1:
            raise SourceError(f"实体库里 LoadoutEntry 块应恰好 1 个，实际 {len(blocks)} 个")
        block = blocks[0]
        geo = scan.check_geometry(plain, block, scan.geometry(dic, block))
        if not geo.get("ok"):
            raise SourceError(f"LoadoutEntry 几何自证失败（typelib 与本 build 漂移？）: {geo}")
        log(f"LoadoutEntry: rows={geo['rows']} stride={geo['stride']} keys={geo['keys']}")

        row_entity = {row: key for key, row in scan.hashmap(plain, block, geo).items()}
        entity_doc = json.loads(entity_names_path.read_text(encoding="utf-8"))
        entity_build = entity_doc.get("build")
        entity_names = {
            int(entry["key"], 16): entry.get("name")
            for entry in entity_doc.get("entity_index") or []
            if entry.get("key")
        }
        base = block["payload_at"] + geo["index_offset"] + geo["index_size"]
        items: dict[str, dict[str, object]] = {}
        named_rows = 0
        unnamed_rows = 0
        for row in range(geo["rows"]):
            item_id, item_type, _dlc = struct.unpack_from("<III", plain, base + row * 32)
            key = row_entity.get(row)
            name = entity_names.get(key) if key else None
            if not name or name == "未知":
                unnamed_rows += 1
                continue
            named_rows += 1
            items[str(item_id)] = {"name": name, "type": item_type}

        payload = {
            "note": (
                "LoadoutEntry 物品内部名（dlbin 只读路线产物）。只读生成，不要手改："
                "换 build 后重跑 tools/extract_item_names.py。"
                "键 = 服务端 /api/Progression/items 目录行的 itemId；值 = 实体内部名。"
                "实体名来自 repo-datamined 用 .strings 解析的 entity-locid-names.json"
                "（该文件是上一个可用 strings 语料的 build：{eb}；新 build 新增实体可能缺失）。"
            ).format(eb=entity_build),
            "build": build,
            "source": {
                "entities": f"plaintext-{build}/generated_entities.dl_bin",
                "typelib": f"plaintext-{build}/dl_library.dl_typelib"
                           if (a.plain_root / f"plaintext-{build}" / "dl_library.dl_typelib").is_file()
                           else str(typelib_path.parent.name) + "/dl_library.dl_typelib",
                "type_names": "repo-datamined/refs/dl-type-names.txt",
                "entity_names": f"repo-datamined/refs/entity-locid-names.json (build {entity_build})",
            },
            "loadout_entry": {
                "block_type": "0x%08X" % LOADOUT_BLOCK_TYPE,
                "rows": geo["rows"],
                "named_rows": named_rows,      # 有名字的行数（同 id 多行会重复计数）
                "unnamed_rows": unnamed_rows,
                "named_ids": len(items),       # 去重后的 itemId 数（下游实际用这个）
                "items": dict(sorted(items.items(), key=lambda kv: int(kv[0]))),
            },
        }
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8", newline="\n")
        log(f"wrote {a.out} | build={build} named_rows={named_rows} named_ids={len(items)} rows={geo['rows']}")
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
