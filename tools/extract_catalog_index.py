#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_catalog_index.py -- 把服务端 `/api/Progression/items` 抓包压成紧凑索引，供目录生成用。

WHY
    服务端物品目录（3020 行）每次生成目录都要读，但整份抓包 ~560 KB 且字段大多是空的；
    `tools/gen_catalogs.py` 只需要每行的 `mixId / itemId / progressionCategory / parentId`
    （parentId 仅附件行有：= 该附件属于哪把武器）。所以把抓包压成紧凑索引存进本仓库：
      * `data/sources/progression_item_catalog.json`（可入库，含原始抓包 sha256 便于回溯）
      * 附件「按武器筛选」功能靠 `parentId`（武器 mixId）分组。

输入（只读）
    --capture   `*_api_Progression_items.json` 抓包（默认在 `--gwe-dir` 里挑最新的）

用法
    python tools/extract_catalog_index.py --capture D:/mod/out/gwe/capture-20261111/85909932_api_Progression_items.json
    python tools/extract_catalog_index.py --gwe-dir D:/mod/out/gwe        # 自动挑最新抓包
    python tools/extract_catalog_index.py --capture <path> --out data/sources/progression_item_catalog.json

输出结构
    {"note": ..., "source": "Progression/items 抓包 <id>（war 801 · build … · 日期）",
     "source_sha256": ..., "rows": [{"mix": int, "item": int, "cat": int, "parent": int|null}, ...]}

安全
    只读抓包、只写 --out 指定的 JSON；不联网、不启动游戏。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "sources" / "progression_item_catalog.json"


def log(message: str) -> None:
    print(f"[extract_catalog_index] {message}")


def latest_capture(gwe_dir: pathlib.Path) -> pathlib.Path:
    files = sorted(gwe_dir.glob("**/*api_Progression_items.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"{gwe_dir} 下没有 *api_Progression_items.json")
    return files[-1]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="把 Progression/items 抓包压成紧凑索引")
    ap.add_argument("--capture", type=pathlib.Path, default=None,
                    help="抓包文件（缺省从 --gwe-dir 挑最新的）")
    ap.add_argument("--gwe-dir", type=pathlib.Path, default=None,
                    help="抓包目录（递归找 *api_Progression_items.json）")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT,
                    help=f"输出（默认 {DEFAULT_OUT}）")
    a = ap.parse_args(argv)

    capture = a.capture or (latest_capture(a.gwe_dir) if a.gwe_dir else None)
    if capture is None or not capture.is_file():
        raise SystemExit("需要 --capture 或 --gwe-dir（指向抓包）")
    raw = capture.read_bytes()
    rows = json.loads(raw)
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"{capture} 里没有 items 数组")

    compact = []
    for row in rows:
        if not isinstance(row, dict) or "mixId" not in row or "itemId" not in row:
            continue
        parent = row.get("parentId")
        compact.append({
            "mix": int(row["mixId"]),
            "item": int(row["itemId"]),
            "cat": int(row.get("progressionCategory") or 0),
            "parent": int(parent) if parent else None,
        })
    compact.sort(key=lambda r: (r["mix"], r["item"], r["cat"]))

    # 从文件名/目录猜 build 与日期（仅用于 note 的可读溯源，猜不到就留空）
    name = capture.name
    build = ""
    for part in capture.parts:
        m = re.match(r"capture-(\d{8})", part)
        if m:
            build = m.group(1)
    if not build:
        m = re.search(r"(\d{8})", name)
        build = m.group(1) if m else ""
    date = ""
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", " ".join(capture.parts))
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    payload = {
        "note": (
            "服务端物品目录的紧凑索引：{rows} 行的 mixId/itemId/progressionCategory/parentId。"
            "parentId 仅附件行（cat=2）有，= 该附件所属武器的 mixId（「附件按武器筛选」靠它）。"
            "源 = GET /api/Progression/items 抓包（war 801{tail}）；纯目录数据、与账号无关。"
            "由 tools/extract_catalog_index.py 生成，不要手改；换 build 重跑即可。"
        ).format(rows=len(compact),
                 tail=(f" · build {build}" if build else "") + (f" · {date} 采集" if date else "")),
        "source": "Progression/items 抓包 {name}".format(name=name),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": compact,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8", newline="\n")
    attachments = sum(1 for r in compact if r["cat"] == 2)
    parents = len({r["parent"] for r in compact if r["cat"] == 2})
    log(f"wrote {a.out} | rows={len(compact)} cat2={attachments} 附件武器数={parents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
