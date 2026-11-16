"""DSH-WARINFO-SETTINGS-V1：改写 warinfo（星球身份 + 生态借用）。

两个键：
  * `settings_hash`: {"<planetIndex>": <settingsHash>}  改已存在条目 → 借生态/地形/天气；
  * `planet_infos`:  [{...}]                            追加条目 → 给休眠星补身份。
"""

import json
import os
from pathlib import Path

from ..logutil import log, log_throttled


def load_spec():
    """旧行为：从环境变量 HD2_GWE_EXTRA 读 spec（JSON 字符串）。空 = 不改 warinfo。"""
    return (os.environ.get("HD2_GWE_EXTRA") or "").strip()


def apply(body, spec=None):
    """改写 warinfo：planetInfos[].settingsHash（生态/地形借用）+ 追加 planetInfo（给伪造节点补身份）。

    HD2_GWE_EXTRA 里：
        "settings_hash": {"<planetIndex>": <settingsHash>}        # 改已存在的条目
        "planet_infos": [{"index":300, "settingsHash":694418289,  # 追加新条目（休眠星伪造）
                          "position":{"x":0.3,"y":-0.55}, "maxHealth":1000000,
                          "initialOwner":1, "sector":20, "waypoints":[76]}]
    本地 bridge：planet_data 尾部每行高 4 字节 = 该行 settingsHash。
    返回 (body_bytes, changed)。
    """
    if spec is None:
        spec = load_spec()
    if not spec:
        return body, 0
    if isinstance(spec, dict):
        cfg = spec
    else:
        try:
            cfg = json.loads(spec)
        except Exception:
            return body, 0
    want = cfg.get("settings_hash") or {}
    adds = cfg.get("planet_infos") or []
    record_path = cfg.get("record_planet_settings")
    if (not (isinstance(want, dict) and want)
            and not (isinstance(adds, list) and adds)
            and not record_path):
        return body, 0
    try:
        doc = json.loads(body)
    except Exception:
        return body, 0
    infos = doc.get("planetInfos")
    if not isinstance(infos, list):
        return body, 0
    if record_path:
        _record_planet_settings(infos, record_path)
    n = 0
    # 1) 改已有条目的 settingsHash
    if isinstance(want, dict) and want:
        m = {}
        for k, v in want.items():
            try:
                m[int(k)] = int(v) & 0xFFFFFFFF
            except (TypeError, ValueError):
                continue
        for row in infos:
            if not isinstance(row, dict):
                continue
            idx = row.get("index")
            if idx in m and row.get("settingsHash") != m[idx]:
                old = row.get("settingsHash")
                row["settingsHash"] = m[idx]
                n += 1
                log("REWRITE-WARINFO planet %s settingsHash %s -> %s (0x%08X)"
                    % (idx, old, m[idx], m[idx]))
    # 2) 追加 planetInfo（DSH-WARINFO-NODE-V1）
    if isinstance(adds, list) and adds:
        have = {r.get("index") for r in infos if isinstance(r, dict)}
        tpl = next((r for r in infos if isinstance(r, dict)), {})
        for a in adds:
            if not isinstance(a, dict):
                continue
            try:
                nidx = int(a.get("index"))
            except (TypeError, ValueError):
                continue
            if nidx in have:
                log_throttled("wi-node-dup", "warinfo: planetInfo %d 已存在，跳过" % nidx, every=3600)
                continue
            pos = a.get("position") or {}
            entry = {
                "index": nidx,
                "settingsHash": int(a.get("settingsHash") or 0) & 0xFFFFFFFF,
                "planetNameId32": int(a.get("planetNameId32") or 0),
                "planetBiomeId32": int(a.get("planetBiomeId32") or 0),
                "position": {"x": float(pos.get("x") or 0.0), "y": float(pos.get("y") or 0.0)},
                "waypoints": [int(x) for x in (a.get("waypoints") or [])],
                "sector": int(a.get("sector") if a.get("sector") is not None else tpl.get("sector") or 0),
                "maxHealth": int(a.get("maxHealth") or 1000000),
                "disabled": bool(a.get("disabled") or False),
                "initialOwner": int(a.get("initialOwner") or 1),
            }
            infos.append(entry)
            have.add(nidx)
            n += 1
            log("REWRITE-WARINFO 追加 planetInfo %s" % json.dumps(entry, ensure_ascii=False))
    if not n:
        return body, 0
    return json.dumps(doc, ensure_ascii=False).encode("utf-8"), n


def _record_planet_settings(infos, path):
    """把 live warinfo 的 planetInfos[].settingsHash 落盘：{index: settingsHash}。

    为什么需要：能力 6「生态借用」要知道源星球的 settingsHash，而该值随 build 变化；
    以运行时抓到的 live 值为准，比离线 dl_bin 映射可靠（研究线 planet-data 里没有这个字段）。
    只写映射，不写名称/坐标等其它字段，避免把账号相关内容带进数据文件。
    """
    try:
        mapping = {}
        for row in infos:
            if not isinstance(row, dict):
                continue
            idx, sh = row.get("index"), row.get("settingsHash")
            if isinstance(idx, int) and isinstance(sh, int):
                mapping[str(idx)] = sh
        if not mapping:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"source": "live-warinfo", "count": len(mapping),
                                   "items": mapping},
                                  ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
        log("warinfo: 记录 %d 条 settingsHash -> %s" % (len(mapping), target))
    except Exception as e:      # noqa: BLE001
        log_throttled("wi-record", "warinfo: settingsHash 落盘失败 %r" % (e,), every=600)
