"""自建服存档导出（v0.7.0-alpha.1 最小切片）：**基线 ⊕ 本机账本 → 端点响应文档**。

与 `save_preview.py` 的分工：

  * `save_preview` 面向人：算"这份档会改什么 / 一局会加多少"，输出是差异报告；
  * 本模块面向**自建服**：把合并后的**完整响应体**写成文件，服务端按路径直接回放。

契约（研究线 2026-11-24 `SELFHOST-SAVE-CONTRACT`）：
  * 目录：`<data-root>/players/<steamId64>/{manifest,progression,inventory,stats_profile}.json` + `<data-root>/index.json`
  * **shape 保真**：输出 = 基线深拷贝只改值（不按语义重建 JSON，客户端对缺字段敏感）
  * **可复现**：同 baseline+ledger 两次导出除 `generatedAt` 外逐字节一致
  * **原子写**：`.tmp` → rename；`index.json` 读-合并-写
  * 合并语义沿用 `saves.apply_to_*`（单调量 max / 库存款只抬不降 / 集合并集），不在这里另写一套

基线由自建服提供（`--baseline <dir>`）：目录里放端点响应体文件即可，名字兼容
`progression.json` 与原始抓包名 `api_Progression.json` 两种；缺省的端点不导出。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from . import paths, saves

SCHEMA = 1
MERGE_POLICY = "max-monotonic/v1"

# 端点 -> 基线目录里可接受的文件名（按顺序找）
BASELINE_FILES = {
    "progression": ("progression.json", "api_Progression.json"),
    "inventory": ("inventory.json", "api_Progression_inventory.json"),
    "stats_profile": ("stats_profile.json", "api_Stats_profile_summary.json"),
    "stats_profile_war": ("stats_profile_801.json", "api_Stats_profile_801_summary.json"),
    "customize_v2": ("customize_v2.json", "api_Progression_Items_Customize_v2.json"),
}
CORE_ENDPOINTS = ("progression", "inventory", "stats_profile")
OUTPUT_FILES = {
    "progression": "progression.json",
    "inventory": "inventory.json",
    "stats_profile": "stats_profile.json",
    "stats_profile_war": "stats_profile_war.json",
    "customize_v2": "customize_v2.json",
}
INDEX_FILE = "index.json"
MANIFEST_FILE = "manifest.json"


def default_baseline() -> Path:
    """没给 --baseline 时按「空号基线」处理（产品仓自带样本）。"""
    return paths.DATA_DIR / "fixtures" / "saves" / "fresh"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_baseline(dir_path) -> dict:
    """读基线目录里存在的端点文件 -> ``{endpoint: {"name": 文件名, "bytes": 原始字节}}``。

    保留文件名 + 原始字节：shape 保真直接用字节；manifest 里逐文件记 sha256 让消费方可独立复算。
    """
    base = Path(dir_path)
    files = {}
    if not base.is_dir():
        raise ValueError("基线目录不存在：%s" % base)
    for key, names in BASELINE_FILES.items():
        for name in names:
            p = base / name
            if p.is_file():
                files[key] = {"name": name, "bytes": p.read_bytes()}
                break
    if not files:
        raise ValueError("基线目录里没有任何可用端点文件：%s（期望 progression/inventory/stats_profile ...）"
                         % base)
    return files


def baseline_id(dir_path) -> str:
    """基线标识：目录名就叫 fresh/main 时直接用，否则 ``custom:<名>``（manifest 供服务端分辨）。"""
    name = Path(dir_path).name or "unknown"
    return name if name in ("fresh", "main") else "custom:" + name


def baseline_files_info(files: dict) -> dict:
    """逐文件自描述：``{endpoint: {"name": ..., "sha256": ...}}``（消费方可独立校验）。"""
    return {k: {"name": v["name"], "sha256": _sha256(v["bytes"])} for k, v in sorted(files.items())}


def baseline_digest(files: dict) -> str:
    """基线总指纹：按端点名排序后 "name:sha256" 拼接再哈希（与文件顺序/时间无关）。"""
    parts = ["%s:%s" % (k, _sha256(files[k]["bytes"])) for k in sorted(files)]
    return _sha256(("\n".join(parts) + "\n").encode("utf-8"))


def ledger_digest(ledger_doc: dict, ledger_file=None) -> str:
    """账本指纹：优先原始文件字节；否则用规范 JSON（排序键、紧凑分隔）。"""
    if ledger_file:
        p = Path(ledger_file)
        if p.is_file():
            return _sha256(p.read_bytes())
    canon = json.dumps(ledger_doc or {}, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"))
    return _sha256(canon.encode("utf-8"))


# ---------------------------------------------------------------- 合并


def _merge_bytes(raw: bytes, ledger_doc: dict, fn) -> tuple[bytes, int]:
    """把合并纯函数套到基线响应体上：输入/输出都是字节，保证只改值、不改结构。"""
    if not raw:
        return raw, 0
    out, changed = fn(raw, ledger_doc)
    return out, changed


def merge_endpoints(files: dict, ledger_doc: dict, *, include_optional: bool = True) -> dict:
    """按端点合并，返回 ``{endpoint: (raw_bytes, changed)}``。

    **可选端点默认导出**（研究线 2026-11-24：`customize_v2` / `stats_profile_war` 都是按玩家数据，
    缺省会让服务端回落公共数据、把 A 玩家的数据显示给 B）。
    """
    out = {}
    for key in CORE_ENDPOINTS:
        if key not in files:
            continue
        out[key] = _merge_bytes(files[key]["bytes"], ledger_doc, _MERGE_FN[key])
    if include_optional and "stats_profile_war" in files:
        out["stats_profile_war"] = _merge_bytes(files["stats_profile_war"]["bytes"], ledger_doc,
                                                saves.apply_to_stats)
    if include_optional and "customize_v2" in files:
        # 改装槽快照没有账本合并语义（实验性写路径），只做 shape 保真拷贝
        out["customize_v2"] = (files["customize_v2"]["bytes"], 0)
    return out


_MERGE_FN = {
    "progression": saves.apply_to_progression,
    "inventory": saves.apply_to_inventory,
    "stats_profile": saves.apply_to_stats,
}


def _as_doc(raw, fallback_empty=None):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback_empty if fallback_empty is not None else {}


def player_key(ledger_doc: dict) -> str:
    """玩家目录键：优先 steamId64（主键），缺身份时退回 save_id（避免丢数据，manifest 里会标）。"""
    ident = (ledger_doc or {}).get("identity") or {}
    steam = str(ident.get("steam_id") or "").strip()
    if steam:
        return steam
    sid = str((ledger_doc or {}).get("save_id") or saves.DEFAULT_SAVE_ID)
    if sid.startswith("steam_"):
        return sid[len("steam_"):]
    return sid


def build_manifest(ledger_doc: dict, merged: dict, *, version, baseline_dir, baseline_sha,
                   ledger_sha, baseline_files=None, generated_at=None) -> dict:
    """manifest：字段按研究线契约 §3（counts 用于服务端启动自检）。"""
    ident = (ledger_doc or {}).get("identity") or {}
    earned = saves._normalize_earned(ledger_doc or {})
    prog = _as_doc(merged.get("progression", (b"", 0))[0])
    inv = _as_doc(merged.get("inventory", (b"", 0))[0])
    stats = _as_doc(merged.get("stats_profile", (b"", 0))[0])
    stats_nz = sum(1 for v in stats.values()
                   if isinstance(v, (int, float)) and not isinstance(v, bool) and v)
    exp = prog.get("experience")
    if exp is None:
        exp = earned.get("experience")
    missions = (earned.get("missions") or {}).get("count")
    resolved = os.path.normcase(os.path.realpath(str(baseline_dir)))
    return {
        "schema": SCHEMA,
        "saveId": (ledger_doc or {}).get("save_id"),
        "identity": {
            "steamId64": ident.get("steam_id"),
            "hd2AccountId": ident.get("hd2_account_id"),
        },
        "catalogBuild": (ledger_doc or {}).get("catalog_build"),
        "generatedAt": generated_at or now_iso(),
        "engine": {"version": str(version), "mergePolicy": MERGE_POLICY},
        "source": {
            "baselineSha256": baseline_sha,
            "baselineId": baseline_id(baseline_dir),
            "baselineDir": str(baseline_dir),
            "baselineDirResolved": resolved,
            "baselineFiles": baseline_files or {},
            "ledgerSha256": ledger_sha,
        },
        "counts": {
            "experience": exp,
            "achievements": len(prog.get("achievements") or []),
            "inventoryRows": len(inv.get("items") or []),
            "statsNonZero": stats_nz,
            "missions": missions,
        },
    }


# ---------------------------------------------------------------- 写盘


def _write_atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_json_atomic(path: Path, doc):
    _write_atomic(path, (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def read_index(root) -> dict:
    p = Path(root) / INDEX_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("players"), list):
            return doc
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA, "players": []}


def update_index(root, entry: dict) -> dict:
    root = Path(root)
    doc = read_index(root)
    players = [p for p in doc.get("players") or [] if not _same_player(p, entry)]
    players.append(entry)
    players.sort(key=lambda p: (str(p.get("steamId64") or ""), str(p.get("saveId") or "")))
    doc = {"schema": SCHEMA, "players": players}
    _write_json_atomic(root / INDEX_FILE, doc)
    return doc


def _same_player(a: dict, b: dict) -> bool:
    ka = (str(a.get("steamId64") or ""), str(a.get("saveId") or ""))
    kb = (str(b.get("steamId64") or ""), str(b.get("saveId") or ""))
    return ka == kb


def export_player(ledger_doc: dict, *, baseline_dir=None, data_root, version,
                  include_optional=True, ledger_file=None) -> dict:
    """导出一个玩家：写 `players/<key>/` + 更新 `index.json`。返回摘要（含 manifest）。"""
    if not data_root:
        raise ValueError("必须指定 --data-root（自建服数据根目录）")
    base_dir = Path(baseline_dir) if baseline_dir else default_baseline()
    files = load_baseline(base_dir)
    missing = [k for k in CORE_ENDPOINTS if k not in files]
    if missing:
        raise ValueError("基线缺必需端点文件：%s（目录 %s）" % (",".join(missing), base_dir))

    merged = merge_endpoints(files, ledger_doc, include_optional=include_optional)
    root = Path(data_root)
    key = player_key(ledger_doc)
    player_dir = root / "players" / key
    for ep, (raw, _changed) in merged.items():
        _write_json_atomic(player_dir / OUTPUT_FILES[ep], _as_doc(raw))
    manifest = build_manifest(
        ledger_doc, merged, version=version, baseline_dir=base_dir,
        baseline_sha=baseline_digest(files),
        ledger_sha=ledger_digest(ledger_doc, ledger_file),
        baseline_files=baseline_files_info(files),
    )
    _write_json_atomic(player_dir / MANIFEST_FILE, manifest)
    ident = (ledger_doc or {}).get("identity") or {}
    entry = {
        "steamId64": manifest["identity"]["steamId64"],
        "hd2AccountId": manifest["identity"]["hd2AccountId"],
        "saveId": manifest["saveId"],
        "updatedAt": manifest["generatedAt"],
    }
    update_index(root, entry)
    changed = {ep: n for ep, (_raw, n) in merged.items() if n}
    return {
        "ok": True,
        "dataRoot": str(root),
        "playerKey": key,
        "playerDir": str(player_dir),
        "files": sorted([MANIFEST_FILE] + [OUTPUT_FILES[ep] for ep in merged]),
        "manifest": manifest,
        "merged": changed,
    }
