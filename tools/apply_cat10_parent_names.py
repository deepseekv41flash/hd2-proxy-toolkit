#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_cat10_parent_names.py -- 用已命名的 cat11 战备许可行反推未命名的 cat10 记账子行。

WHY
    目录里 cat11（战备许可）与 cat10（战备记账/子行）是**严格 1:1**：每个 cat10 行的
    `parent` 就是它对应的 cat11 `mix_id`（v2 的 `stratagem-permit-child` 用的正是这条结构，
    方向是「子行名 → 许可行」）。补完 cat11 名字后，反向用「许可行名 → 子行」即可把
    仍为空的 cat10 行补齐 —— 纯结构推断，不需要任何新数据源。

输入（只读）
    data/sources/catalog_names_resolved.json   目录名称解析快照（cat10/cat11 行与名字）
输出（--snapshot 指定，默认就地更新快照）
    同一份快照：cat10 空名行写 name / name_source="stratagem-permit-parent" / confidence="medium"，
    同步 coverage（named / unresolved / by_cat[10] / by_source），并在 coverage.name_patches
    追加/覆盖一条补丁记录（同一 name_source 幂等）。

口径
    * 只补空位：cat10 行 name 为空、且其 parent 指向的 cat11 行已有名字时才写；同名重复运行幂等。
    * **不做跨行乱推**：只认 `parent` 精确指向的 cat11 行；parent 为空或指向无名行就跳过（不猜）。
    * 名字沿用许可行的名字（含英文名/中文名，取决于上游来源）。

用法
    python tools/apply_cat10_parent_names.py            # 就地更新快照
    python tools/apply_cat10_parent_names.py --check    # 只校验并打印将发生的变化
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apply_stratagem_client_names import (  # noqa: E402
    DEFAULT_SNAPSHOT,
    PatchError,
    load_json,
    log,
    update_coverage,
    verify_consistency,
)

NAME_SOURCE = "stratagem-permit-parent"
CONFIDENCE = "medium"
PERMIT_CAT = 11
ACCOUNT_CAT = 10
PATCH_NOTE = (
    "cat10 战备记账行与 cat11 许可行 1:1（子行 parent == 许可 mixId）；"
    "用已命名的许可行名字反推未命名的子行（与 v2 stratagem-permit-child 同一条结构、方向相反）。"
)
SOURCE_FILE = "data/sources/catalog_names_resolved.json（cat11 已命名行）"


def propagate(snapshot: dict) -> int:
    """就地反推 cat10 名字；返回补上的行数。"""
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        raise PatchError("快照结构异常：缺少非空 rows[]")

    permit_names: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict) or int(row.get("cat") or -1) != PERMIT_CAT:
            continue
        name = row.get("name")
        if not name:
            continue
        try:
            mix = int(row.get("mix"))
        except (TypeError, ValueError) as exc:
            raise PatchError(f"cat11 行 mix 非法: {row!r}") from exc
        permit_names[mix] = str(name)

    patched = 0
    for row in rows:
        if not isinstance(row, dict) or int(row.get("cat") or -1) != ACCOUNT_CAT:
            continue
        if row.get("name"):
            continue
        parent = row.get("parent")
        if parent is None:
            continue
        try:
            parent_mix = int(parent)
        except (TypeError, ValueError):
            continue
        name = permit_names.get(parent_mix)
        if not name:
            continue
        row["name"] = name
        row["name_source"] = NAME_SOURCE
        row["confidence"] = CONFIDENCE
        patched += 1

    if patched:
        update_coverage(snapshot, patched, NAME_SOURCE, ACCOUNT_CAT, SOURCE_FILE, PATCH_NOTE)
    return patched


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="用已命名的 cat11 许可行反推未命名的 cat10 记账子行")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="目录名称解析快照路径")
    parser.add_argument("--check", action="store_true", help="只校验并打印将发生的变化，不写文件")
    args = parser.parse_args(argv)

    snapshot_path = args.snapshot.resolve()
    try:
        snapshot = load_json(snapshot_path, "catalog_names_resolved.json")
        before = int((snapshot.get("coverage") or {}).get("named", -1))
        patched = propagate(snapshot)
        verify_consistency(snapshot)
    except PatchError as exc:
        log(f"ERROR: {exc}")
        return 2

    after = int((snapshot.get("coverage") or {}).get("named", -1))
    log(f"patched={patched} named: {before} -> {after}")
    if args.check:
        log("--check：未写文件")
        return 0
    if patched == 0:
        log("无需变更（快照已是目标状态），未写文件")
        return 0
    snapshot_path.write_text(
        __import__("json").dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    log(f"wrote {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
