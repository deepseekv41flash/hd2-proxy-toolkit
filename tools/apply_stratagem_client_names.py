#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_stratagem_client_names.py -- 把客户端静态表的战备英文名补进「目录名称解析快照」。

WHY
    v3 快照（`data/sources/catalog_names_resolved.json`）里 cat11 战备许可 108 行只命名了 73 行。
    本轮对照 wiki Stratagems 页的 7 个 Permit 表（95 条已发布战备，排除 Other/Unavailable 与
    Orbital Confetti、Eagle Fly By）逐条核对：**95 条全部能在目录里找到行（id 已知）**，
    其中 73 条已有名字，剩下 **22 条**既有的取名管线（旧 stratagem_catalog 58 条 + effects GWE）
    没覆盖到。这 22 条的名字在客户端静态表里是齐全的，派生结果已固化进
    `data/sources/stratagem_client_names.json`（含 client 内部名 / 原生哈希 / wiki 名，便于追溯）。

输入（只读）
    data/sources/catalog_names_resolved.json   目录名称解析快照（v3 基线）
    data/sources/stratagem_client_names.json   本工具的补丁数据（22 行：mix_id -> 英文名 + 证据）
输出（--snapshot 指定，默认就地更新快照）
    同一份快照：已被补丁的行写 name / name_source="stratagem-client-settings" / confidence="high"，
    同步更新 coverage（named / unresolved / by_cat[11] / by_source），并在 coverage.name_patches
    追加一条补丁记录（同一 name_source 再次运行时覆盖记录而不是重复追加）。

口径（重要）
    * **只补空位**：快照里 name 为空的行才写入；已有同名 -> 跳过（幂等）；已有不同名 -> 报错退出
      （绝不覆盖人工/其它来源已确定的名字）。
    * 名字是**英文名**（wiki 全名，含代号前缀，与当前游戏内显示一致）；中文译名不在本轮范围，
      未来补中文时用新的 name_source 覆盖本来源即可（届时把本条从 --check 白名单里换掉）。
    * 校验证据字段：每行必须有 mix_id/name/client_internal_name/native_hash；快照里必须恰有一行、
      且 catalog_category==11；不一致即报错，不产出半成品。
    * 只读输入、不联网、确定性输出（无时间戳/随机数）。

安全
    * 只以读模式打开输入；除 --snapshot 外不写任何文件；不碰游戏目录。
    * `--check` 只校验并打印将发生的变化，不写文件（给 CI/门禁用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "sources" / "catalog_names_resolved.json"
DEFAULT_SOURCE = REPO_ROOT / "data" / "sources" / "stratagem_client_names.json"

NAME_SOURCE = "stratagem-client-settings"
CONFIDENCE = "high"
STRATAGEM_CAT = 11
REQUIRED_FIELDS = ("mix_id", "name", "client_internal_name", "native_hash")

CLIENT_NAME_PATCH_NOTE = (
    "cat11 战备许可行的客户端静态表英文名：cat11.mix_id --parent--> cat10 子行.item"
    "(uint32 原生哈希) --> stratagem_settings.csv 的 +4 列 --> client 内部名 --> 显示名；"
    "中文译名待后续批次。"
)


class PatchError(RuntimeError):
    """输入/快照结构或证据不自洽。"""


def log(message: str) -> None:
    print(f"[apply] {message}")


def load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise PatchError(f"{label} 不存在: {path}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PatchError(f"{label} JSON 解析失败: {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise PatchError(f"{label} 顶层不是对象: {path}")
    return doc


def load_source(path: Path) -> dict[int, str]:
    """读补丁数据 -> mix_id -> 英文名（同时校验证据字段齐全）。"""
    doc = load_json(path, "stratagem_client_names.json")
    rows = doc.get("rows")
    if not isinstance(rows, list) or not rows:
        raise PatchError("stratagem_client_names.json 结构异常：缺少非空 rows[]")
    out: dict[int, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PatchError(f"rows[{index}] 不是对象")
        missing = [key for key in REQUIRED_FIELDS if not row.get(key)]
        if missing:
            raise PatchError(f"rows[{index}] 缺证据字段 {missing}: {row!r}")
        try:
            mix = int(row["mix_id"])
        except (TypeError, ValueError) as exc:
            raise PatchError(f"rows[{index}].mix_id 不是整数: {row['mix_id']!r}") from exc
        if mix in out:
            raise PatchError(f"rows[{index}].mix_id 重复: {mix}")
        name = str(row["name"]).strip()
        if not name:
            raise PatchError(f"rows[{index}].name 为空: {mix}")
        out[mix] = name
    declared = doc.get("count")
    if declared is not None and int(declared) != len(out):
        raise PatchError(f"count={declared} 与实际行数 {len(out)} 不一致")
    log(f"补丁数据 {len(out)} 行（{path.name}）")
    return out


def apply_patch(snapshot: dict, names: dict[int, str], source_name: str) -> tuple[int, int]:
    """就地补名并更新 coverage；返回 (patched, skipped)。"""
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        raise PatchError("快照结构异常：缺少非空 rows[]")
    by_mix: dict[int, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PatchError("快照 rows[] 里出现非对象")
        try:
            mix = int(row.get("mix"))
        except (TypeError, ValueError) as exc:
            raise PatchError(f"快照行 mix 非法: {row!r}") from exc
        by_mix[mix] = row

    patched = skipped = 0
    for mix, name in names.items():
        row = by_mix.get(mix)
        if row is None:
            raise PatchError(f"快照里没有 mix={mix}（{name}）")
        if int(row.get("cat")) != STRATAGEM_CAT:
            raise PatchError(f"mix={mix} 的 cat={row.get('cat')} != {STRATAGEM_CAT}（{name}）")
        current = row.get("name")
        if current:
            if str(current).strip() == name:
                skipped += 1
                continue
            raise PatchError(
                f"mix={mix} 已有别的名字 {current!r}（来源 {row.get('name_source')!r}），"
                f"拒绝覆盖为 {name!r}"
            )
        row["name"] = name
        row["name_source"] = NAME_SOURCE
        row["confidence"] = CONFIDENCE
        patched += 1

    if patched:
        update_coverage(
            snapshot, patched, NAME_SOURCE, STRATAGEM_CAT, source_name, CLIENT_NAME_PATCH_NOTE
        )
    return patched, skipped


def update_coverage(snapshot: dict, patched: int, name_source: str, cat: int,
                    source_file: str, note: str) -> None:
    """把 patched 条名字计入 coverage（named/unresolved/by_cat[cat]/by_source + name_patches）。"""
    coverage = snapshot.get("coverage")
    if not isinstance(coverage, dict):
        raise PatchError("快照缺少 coverage（无法保持统计自洽）")
    coverage["named"] = int(coverage.get("named", 0)) + patched
    coverage["unresolved"] = int(coverage.get("unresolved", 0)) - patched

    by_cat = coverage.get("by_cat")
    if isinstance(by_cat, dict):
        key = str(cat)
        cat_cov = by_cat.get(key)
        if isinstance(cat_cov, dict):
            cat_cov["named"] = int(cat_cov.get("named", 0)) + patched
            cat_cov["unresolved"] = int(cat_cov.get("unresolved", 0)) - patched
            sources = cat_cov.get("sources")
            if isinstance(sources, dict):
                sources[name_source] = int(sources.get(name_source, 0)) + patched

    by_source = coverage.get("by_source")
    if isinstance(by_source, dict):
        by_source[name_source] = int(by_source.get(name_source, 0)) + patched

    patches = coverage.get("name_patches")
    if not isinstance(patches, list):
        patches = []
        coverage["name_patches"] = patches
    record = {
        "name_source": name_source,
        "source_file": source_file,
        "added": patched,
        "note": note,
    }
    for index, existing in enumerate(patches):
        if isinstance(existing, dict) and existing.get("name_source") == name_source:
            patches[index] = record
            break
    else:
        patches.append(record)


def verify_consistency(snapshot: dict) -> None:
    """补丁后自检：coverage 与 rows 必须一致（失败即抛错）。"""
    rows = snapshot["rows"]
    named = sum(1 for row in rows if row.get("name"))
    coverage = snapshot.get("coverage") or {}
    if int(coverage.get("named", -1)) != named:
        raise PatchError(f"coverage.named={coverage.get('named')} 与实际有名字行数 {named} 不一致")
    total = len(rows)
    if int(coverage.get("total", total)) != total:
        raise PatchError(f"coverage.total={coverage.get('total')} != rows={total}")
    if int(coverage.get("named", 0)) + int(coverage.get("unresolved", 0)) != total:
        raise PatchError("coverage.named + unresolved != total")
    by_cat = coverage.get("by_cat") or {}
    if by_cat:
        if sum(int(v.get("named", 0)) for v in by_cat.values()) != named:
            raise PatchError("coverage.by_cat[].named 合计 != named")
        if sum(int(v.get("rows", 0)) for v in by_cat.values()) != total:
            raise PatchError("coverage.by_cat[].rows 合计 != total")
    by_source = coverage.get("by_source") or {}
    counters = Counter(str(row.get("name_source")) for row in rows if row.get("name"))
    if by_source and sum(int(v) for v in by_source.values()) != named:
        raise PatchError("coverage.by_source 合计 != named")
    if by_source:
        for key, value in by_source.items():
            if int(value) != counters.get(key, 0):
                raise PatchError(f"coverage.by_source[{key}]={value} != 实际 {counters.get(key, 0)}")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="把客户端静态表的战备英文名补进目录名称解析快照")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="目录名称解析快照路径")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="补丁数据路径")
    parser.add_argument("--check", action="store_true", help="只校验并打印将发生的变化，不写文件")
    args = parser.parse_args(argv)

    snapshot_path = args.snapshot.resolve()
    source_path = args.source.resolve()
    try:
        names = load_source(source_path)
        snapshot = load_json(snapshot_path, "catalog_names_resolved.json")
        before = int((snapshot.get("coverage") or {}).get("named", -1))
        patched, skipped = apply_patch(snapshot, names, source_path.name)
        verify_consistency(snapshot)
    except PatchError as exc:
        log(f"ERROR: {exc}")
        return 2

    after = int((snapshot.get("coverage") or {}).get("named", -1))
    log(f"patched={patched} skipped(已同名)={skipped} named: {before} -> {after}")
    if args.check:
        log("--check：未写文件")
        return 0
    if patched == 0:
        log("无需变更（快照已是目标状态），未写文件")
        return 0
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    log(f"wrote {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
