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
    "mission_end": "mission_end.json",
}
INDEX_FILE = "index.json"
MANIFEST_FILE = "manifest.json"
SETTLEMENTS_FILE = "settlements.jsonl"          # 每玩家结算事件流（契约形态 3）
ITEM_SOURCES = ("rewards", "badges", "both", "none")


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


def _player_account_id(ledger_doc: dict):
    """玩家自己的账号 id（mission_end 里 platformAccountId 的语义）：HD2 20 位优先（官方抓包口径），
    没有则退回 SteamID64。"""
    ident = (ledger_doc or {}).get("identity") or {}
    hd2 = str(ident.get("hd2_account_id") or "").strip()
    steam = str(ident.get("steam_id") or "").strip()
    return hd2 or steam or None


def correct_mission_end(doc: dict, ledger_doc: dict) -> dict:
    """按玩家校正 `mission_end.json`（契约 F07 / per-player 语义）。

    官方响应里 `progressionPackageUpdates[]` 每个元素带 `platformAccountId`（= **该玩家自己的**账号 id，
    真实抓包为 HD2 20 位）。这里：
      * 值统一校正为本玩家 identity（HD2 优先，退回 SteamID64）；
      * 字段缺失时**补齐**（我方公开夹具为脱敏起见剥掉了它；上游真实响应总是有）；
      * 元素其余键/嵌套**原样保留**（只改值，不重建 dict；platformAccountId 排在最前与官方键序一致）。
    """
    out = json.loads(json.dumps(doc))            # 深拷贝，绝不改入参
    account = _player_account_id(ledger_doc)
    if not account:
        return out
    for row in out.get("progressionPackageUpdates") or []:
        if not isinstance(row, dict):
            continue
        rest = {k: v for k, v in row.items() if k != "platformAccountId"}
        row.clear()
        row["platformAccountId"] = account
        row.update(rest)
    return out


def mission_end_payload(ledger_doc: dict):
    """账本里最近一局的**完整原始 Mission/end 响应**（v0.8.0 起引擎落盘）；没有则 None。

    为什么直接存原始响应：账本只存增量，按语义重建响应体必然与官方 shape 漂移
    （客户端对缺字段敏感）；原始响应按 shape 原样回放才安全。
    """
    earned = saves._normalize_earned(ledger_doc or {})
    ms = earned.get("missions") or {}
    doc = ms.get("last_response") if isinstance(ms, dict) else None
    return doc if isinstance(doc, dict) and doc else None


# ---------------------------------------------------------------- 结算事件流（形态 3）

def _iso_explicit(raw):
    """时间戳 → 始终带显式时区偏移的 ISO 串（契约 J08：不允许无时区本地时间）。"""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace(" ", "T"))
    except ValueError:
        return str(raw)
    if dt.tzinfo is None:
        dt = dt.astimezone()          # 旧账本只存本地时间 → 按本机时区补显式偏移
    return dt.isoformat(timespec="seconds")


def _item_source(value):
    """限定枚举 rewards|badges|both|none（未知值收敛为 none，不让消费端猜）。"""
    text = str(value or "").strip().lower()
    return text if text in ITEM_SOURCES else "none"


def _settlement_packages(last: dict, account) -> dict:
    """该局**结算后绝对值** level/progress（max 幂等）+ 本玩家 platformAccountId。"""
    out = {}
    for id32, row in (last.get("packages") or {}).items():
        if not isinstance(row, dict):
            continue
        item = {"level": row.get("level"), "progress": row.get("progress")}
        if account:
            item["platformAccountId"] = account
        out[str(id32)] = item
    return out


def settlement_event(ledger_doc: dict):
    """账本里最近一局 → 一行结算事件；没有可辨识的 missionId 时返回 None。

    ``source``：
      * ``mission_end``  = 引擎落过**完整原始响应**（alpha.1 起），事件字段取自该响应/账本；
      * ``ledger-only``  = 老局只有账本 `missions.last`（无原始响应），packages 记空、missionIndex 可为 null。
    """
    ledger_doc = ledger_doc or {}
    ident = ledger_doc.get("identity") or {}
    earned = saves._normalize_earned(ledger_doc)
    ms = earned.get("missions") or {}
    last = ms.get("last") or {}
    mission = last.get("mission") or {}
    mission_id = str(mission.get("mission_id") or "").strip()
    if not mission_id:
        return None
    has_raw = isinstance(ms.get("last_response"), dict) and bool(ms.get("last_response"))
    steam = str(ident.get("steam_id") or "").strip() or None
    hd2 = str(ident.get("hd2_account_id") or "").strip() or None
    account = hd2 or steam
    event = {
        "schema": SCHEMA,
        "event": "settlement",
        "ts": _iso_explicit(ms.get("last_response_at") or last.get("at")),
        "saveId": ledger_doc.get("save_id"),
        "steamId64": steam,
        "hd2AccountId": hd2,
        "missionId": mission_id,
        "operationId": mission.get("operation_id"),
        "missionIndex": mission.get("mission_index"),
        "experience": int(last.get("experience") or 0),
        "items": {str(k): int(v) for k, v in (last.get("items") or {}).items()},
        "packages": _settlement_packages(last, account) if has_raw else {},
        "itemSource": _item_source(last.get("item_source")),
        "catalogBuild": ledger_doc.get("catalog_build"),
        "source": "mission_end" if has_raw else "ledger-only",
    }
    return event


def read_settlements(path) -> dict:
    """读现有 JSONL：返回 ``{"missionIds": set, "lines": [dict], "bad": n}``（坏行跳过，不删）。"""
    p = Path(path)
    ids, lines, bad = set(), [], 0
    if not p.is_file():
        return {"missionIds": ids, "lines": lines, "bad": bad}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {"missionIds": ids, "lines": lines, "bad": bad}
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            doc = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(doc, dict):
            bad += 1
            continue
        lines.append(doc)
        mid = str(doc.get("missionId") or "").strip()
        if mid:
            ids.add(mid)
    return {"missionIds": ids, "lines": lines, "bad": bad}


def append_settlements(player_dir, ledger_doc) -> dict:
    """把一个结算事件追加到该玩家 ``settlements.jsonl``（按 missionId 幂等去重）。

    契约（研究线 2026-11-24 §2）：每玩家一文件、append-only、UTF-8/LF/无 BOM、一行一对象（紧凑）、
    去重范围=该玩家文件内；重复导出不追加；坏行容忍由消费端负责（我方读取时跳过、不删）。
    返回 ``{"appended":0|1, "skipped": bool, "lines": N, "ledgerOnly": N, "cursor": {...}}``。
    """
    path = Path(player_dir) / SETTLEMENTS_FILE
    existing = read_settlements(path)
    event = settlement_event(ledger_doc)
    if event is None:
        return {"appended": 0, "skipped": True, "lines": len(existing["lines"]),
                "ledgerOnly": sum(1 for x in existing["lines"] if x.get("source") == "ledger-only"),
                "cursor": _settlements_cursor(existing["lines"])}
    if event["missionId"] in existing["missionIds"]:
        return {"appended": 0, "skipped": True, "lines": len(existing["lines"]),
                "ledgerOnly": sum(1 for x in existing["lines"] if x.get("source") == "ledger-only"),
                "cursor": _settlements_cursor(existing["lines"])}
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.is_file() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                prefix = "\n"                     # 上次被截断成半行：补换行，保持一行一对象
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(prefix + line + "\n")
        fh.flush()
    after = read_settlements(path)
    return {"appended": 1, "skipped": False, "lines": len(after["lines"]),
            "ledgerOnly": sum(1 for x in after["lines"] if x.get("source") == "ledger-only"),
            "cursor": _settlements_cursor(after["lines"])}


def _settlements_cursor(lines):
    """manifest 游标：``{lines, lastMissionId, lastTs}``（导出时按文件重算）。"""
    if not lines:
        return {"lines": 0, "lastMissionId": None, "lastTs": None}
    tail = lines[-1]
    return {"lines": len(lines),
            "lastMissionId": tail.get("missionId"),
            "lastTs": tail.get("ts")}


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
                   ledger_sha, baseline_files=None, settlements=None, generated_at=None) -> dict:
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
    doc = {
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
    if settlements:
        # 契约形态 3：结算事件流审计信息（ledger-only 行数 + 游标，供消费端对账）
        doc["settlements"] = {"ledgerOnly": int(settlements.get("ledgerOnly") or 0)}
        doc["settlementsCursor"] = dict(settlements.get("cursor") or {})
    return doc


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
    mission_end = mission_end_payload(ledger_doc) if include_optional else None
    if mission_end is not None:
        mission_end = correct_mission_end(mission_end, ledger_doc)
        _write_json_atomic(player_dir / OUTPUT_FILES["mission_end"], mission_end)
    settlements = append_settlements(player_dir, ledger_doc) if include_optional else None
    manifest = build_manifest(
        ledger_doc, merged, version=version, baseline_dir=base_dir,
        baseline_sha=baseline_digest(files),
        ledger_sha=ledger_digest(ledger_doc, ledger_file),
        baseline_files=baseline_files_info(files),
        settlements=settlements,
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
        "files": sorted([MANIFEST_FILE] + [OUTPUT_FILES[ep] for ep in merged]
                        + ([OUTPUT_FILES["mission_end"]] if mission_end is not None else [])
                        + ([SETTLEMENTS_FILE] if settlements and settlements.get("lines") else [])),
        "manifest": manifest,
        "merged": changed,
        "settlements": settlements,
    }
