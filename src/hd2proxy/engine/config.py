"""配置面（schema v2）：profile 的校验 / 存储 / 与引擎 spec 的映射 / 旧配置迁移。

设计取舍：
  * **单一 profile JSON** 取代研究线的三套入口（`HD2_GWE_EXTRA` 环境变量、`runtime/*.json`、
    `config.json.targets`）。GUI / CLI / 控制面都只操作这一份。
  * schema 里钩子键名与 `hooks/*` 一致（`planet_effects` / `globalEffects` / `settings_hash` …），
    所以映射是「搬运 + 类型校验」，不做语义翻译，减少两层名字不一致的坑。
  * 校验失败**不静默丢字段**：errors 阻止保存/启动；未知键进 warnings（便于发现拼写错误）。
  * 旧配置可以 `from_legacy()` 迁移成 profile，迁移只做能确定的部分，其余写进 notes。
"""

import copy
import json
import os
from pathlib import Path

from . import paths
from .spec import EngineSpec

SCHEMA_VERSION = 2
HOST_DEFAULT = "api.live.prod.thehelldiversgame.com"

DEFAULT_PROFILE = {
    "schema": SCHEMA_VERSION,
    "name": "默认",
    "proxy": {
        "host": HOST_DEFAULT,
        "listen_ip": "auto",
        "port": 443,
        "crl_port": 8080,
        "control_port": 17897,
        "passthrough": True,
        "verbose": False,
    },
    "cert": {"days": 2, "min_remaining_hours": 12, "auto_renew": True},
    "warinfo": {"settings_hash": {}, "planet_infos": []},
    "status": {
        "variants": [],
        "trials": [],
        "planet_effects": [],
        "globalEffects": {},
        "campaigns": [],
        "attacks": [],
        "events": [],
        "regions": [],
        "planet_nodes": [],
        "owner": {},
    },
    "inventory": {
        "weapons": [], "attachments": [], "cosmetics": [], "stratagems": [], "probe": [],
        "remove": [], "customization": [],
    },
    "items": {"template": None, "add": []},
    "capture": {
        "enabled": False, "dir": "", "paths": ["api/"], "req_paths": [],
        "max_bytes": 8388608, "planet_settings": False,
    },
    "experimental": {"customize": {"enabled": False, "edits": []}},
}

_KNOWN_TOP = set(DEFAULT_PROFILE)
_PLANET_MIN, _PLANET_MAX = 0, 400


# ---------------------------------------------------------------- 小工具


def _deep_merge(base: dict, user: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (user or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int(v, default=None):
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _num(v):
    """数值归一化：int/float 原样（float 保留小数），其它返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if isinstance(v, float) else v
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _as_list(v):
    return list(v) if isinstance(v, list) else []


def _as_dict(v):
    return dict(v) if isinstance(v, dict) else {}


def _planet_ok(v) -> bool:
    return _is_int(v) and _PLANET_MIN <= v <= _PLANET_MAX


def default_profile(**overrides) -> dict:
    doc = copy.deepcopy(DEFAULT_PROFILE)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(doc.get(k), dict):
            doc[k] = _deep_merge(doc[k], v)
        else:
            doc[k] = copy.deepcopy(v)
    return doc


# ---------------------------------------------------------------- 校验


def validate(raw) -> tuple[dict, list[str], list[str]]:
    """校验并归一化 profile。返回 (normalized, errors, warnings)。

    errors 非空 => 不允许保存/启动；warnings 只提示（例如未知键、空计划）。
    """
    errors, warnings = [], []
    if not isinstance(raw, dict):
        return default_profile(), ["profile 不是 JSON 对象"], warnings
    for k in raw:
        if k not in _KNOWN_TOP:
            warnings.append("未知顶层键 %r（已忽略）" % k)
    doc = _deep_merge(DEFAULT_PROFILE, {k: v for k, v in raw.items() if k in _KNOWN_TOP})

    if _int(doc.get("schema")) != SCHEMA_VERSION:
        errors.append("schema 必须是 %d（当前 %r）" % (SCHEMA_VERSION, raw.get("schema")))
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name 必须是非空字符串")
    else:
        doc["name"] = name.strip()

    # ---- proxy ------------------------------------------------------------
    proxy = _as_dict(doc.get("proxy"))
    host = proxy.get("host")
    if not isinstance(host, str) or not host.strip():
        errors.append("proxy.host 必须是非空字符串")
    listen_ip = proxy.get("listen_ip", "auto")
    if not isinstance(listen_ip, str) or not listen_ip.strip():
        errors.append("proxy.listen_ip 必须是字符串（auto 或本机非回环 IP）")
    elif listen_ip.strip().startswith(("127.", "0.")):
        errors.append("proxy.listen_ip 不能是回环地址（新版客户端会拒绝连接）：%r" % listen_ip)
    for key, lo, hi in (("port", 1, 65535), ("crl_port", 1, 65535),
                        ("control_port", 0, 65535)):
        v = _int(proxy.get(key))
        if v is None or not (lo <= v <= hi):
            errors.append("proxy.%s 必须是 %d..%d 的整数（当前 %r）"
                          % (key, lo, hi, proxy.get(key)))
        else:
            proxy[key] = v
    for key in ("passthrough", "verbose"):
        if not isinstance(proxy.get(key), bool):
            errors.append("proxy.%s 必须是 true/false（当前 %r）" % (key, proxy.get(key)))
    doc["proxy"] = proxy

    # ---- cert -------------------------------------------------------------
    cert = _as_dict(doc.get("cert"))
    days = _int(cert.get("days"))
    if days is None or days < 1:
        errors.append("cert.days 必须是 >=1 的整数")
    elif days > 2:
        errors.append("cert.days 不能超过 2（安全硬上限）")
    else:
        cert["days"] = days
    mrh = cert.get("min_remaining_hours")
    if not isinstance(mrh, (int, float)) or isinstance(mrh, bool) or not (0 <= float(mrh) <= 48):
        errors.append("cert.min_remaining_hours 必须是 0..48 的数字")
    else:
        cert["min_remaining_hours"] = float(mrh)
    if not isinstance(cert.get("auto_renew"), bool):
        errors.append("cert.auto_renew 必须是 true/false")
    doc["cert"] = cert

    # ---- warinfo ----------------------------------------------------------
    wi = _as_dict(doc.get("warinfo"))
    sh = _as_dict(wi.get("settings_hash"))
    clean_sh = {}
    for k, v in sh.items():
        pi, hv = _int(k), _int(v)
        if pi is None or not _planet_ok(pi):
            errors.append("warinfo.settings_hash 的键必须是 0..400 的星球号：%r" % k)
            continue
        if hv is None:
            errors.append("warinfo.settings_hash[%r] 必须是整数 hash" % k)
            continue
        clean_sh[str(pi)] = hv
    wi["settings_hash"] = clean_sh
    infos = []
    for row in _as_list(wi.get("planet_infos")):
        if not isinstance(row, dict):
            errors.append("warinfo.planet_infos 里每一项必须是对象")
            continue
        idx = _int(row.get("index"))
        if idx is None or not _planet_ok(idx):
            errors.append("warinfo.planet_infos 需要 0..400 的 index：%r" % (row,))
            continue
        info = {"index": idx}
        for k in ("settingsHash", "maxHealth", "initialOwner", "sector"):
            if k in row and _int(row[k]) is not None:
                info[k] = _int(row[k])
        if isinstance(row.get("position"), dict):
            pos = row["position"]
            # 坐标是浮点（星图位置），不能用 int 归一化，否则 0.3 会被截成 0
            px, py = _num(pos.get("x")), _num(pos.get("y"))
            if px is not None and py is not None:
                info["position"] = {"x": px, "y": py}
        if isinstance(row.get("waypoints"), list):
            info["waypoints"] = [w for w in (_int(x) for x in row["waypoints"]) if w is not None]
        infos.append(info)
    wi["planet_infos"] = infos
    doc["warinfo"] = wi

    # ---- status -----------------------------------------------------------
    st = _as_dict(doc.get("status"))
    variants, seen_names = [], set()
    for row in _as_list(st.get("variants")):
        if isinstance(row, str):
            row = {"name": row, "planets": []}
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            errors.append("status.variants 每项需要 name（字符串）")
            continue
        planets = []
        for p in _as_list(row.get("planets")):
            if not _planet_ok(_int(p)):
                errors.append("status.variants[%r].planets 里有非法星球号：%r" % (row["name"], p))
                continue
            planets.append(_int(p))
        if row["name"] in seen_names:
            warnings.append("status.variants 重复项已合并：%r" % row["name"])
            continue
        seen_names.add(row["name"])
        variants.append({"name": row["name"], "planets": planets})
    st["variants"] = variants
    trials = []
    for t in _as_list(st.get("trials")):
        v = _int(t)
        if v is None or v <= 0:
            errors.append("status.trials 必须是正整数 effect id：%r" % (t,))
        elif v not in trials:
            trials.append(v)
    st["trials"] = trials
    pe = []
    for row in _as_list(st.get("planet_effects")):
        if not isinstance(row, dict):
            errors.append("status.planet_effects 每项必须是对象")
            continue
        idx = _int(row.get("index"))
        ids = [_int(x) for x in _as_list(row.get("ids"))]
        ids = [x for x in ids if x is not None and x > 0]
        if idx is None or not _planet_ok(idx) or not ids:
            errors.append("status.planet_effects 需要 index(0..400) 与非空 ids：%r" % (row,))
            continue
        pe.append({"index": idx, "ids": ids})
    st["planet_effects"] = pe
    ge = {}
    for k, v in _as_dict(st.get("globalEffects")).items():
        eid = _int(k)
        ids = [x for x in (_int(y) for y in _as_list(v)) if x is not None and x > 0]
        if eid is None or not ids:
            errors.append("status.globalEffects[%r] 需要事件 id 键与非空 effect 列表" % k)
            continue
        ge[str(eid)] = ids
    st["globalEffects"] = ge
    for key in ("campaigns", "attacks", "events", "regions", "planet_nodes"):
        rows = _as_list(st.get(key))
        clean = [r for r in rows if isinstance(r, dict)]
        if len(clean) != len(rows):
            errors.append("status.%s 里只能放对象（发现 %d 个非法项）"
                          % (key, len(rows) - len(clean)))
        st[key] = clean
    owners = {}
    for k, v in _as_dict(st.get("owner")).items():
        pi, ov = _int(k), _int(v)
        if pi is None or not _planet_ok(pi) or ov not in (0, 1, 2, 3, 4):
            errors.append("status.owner[%r]=%r 非法（星球 0..400，owner 0..4）" % (k, v))
            continue
        owners[str(pi)] = ov
    st["owner"] = owners
    doc["status"] = st

    # ---- inventory --------------------------------------------------------
    inv = _as_dict(doc.get("inventory"))
    for key in ("weapons", "attachments", "cosmetics", "stratagems", "probe"):
        rows, clean = _as_list(inv.get(key)), []
        for row in rows:
            if isinstance(row, dict) and _int(row.get("mixId")) is not None:
                item = {"mixId": _int(row["mixId"])}
                if _int(row.get("amount")) is not None:
                    item["amount"] = _int(row["amount"])
                if isinstance(row.get("isDiscovered"), bool):
                    item["isDiscovered"] = row["isDiscovered"]
                clean.append(item)
                continue
            mid = _int(row)
            if mid is not None:
                clean.append({"mixId": mid, "amount": 1, "isDiscovered": False})
            else:
                errors.append("inventory.%s 里有非法 mixId：%r" % (key, row))
        inv[key] = clean
    inv["remove"] = [x for x in (_int(y) for y in _as_list(inv.get("remove"))) if x]
    cust = []
    for row in _as_list(inv.get("customization")):
        if not isinstance(row, dict) or _int(row.get("mixId32")) is None:
            errors.append("inventory.customization 每项需要 mixId32：%r" % (row,))
            continue
        cust.append(row)
    inv["customization"] = cust
    doc["inventory"] = inv

    # ---- items ------------------------------------------------------------
    items = _as_dict(doc.get("items"))
    add = []
    for row in _as_list(items.get("add")):
        if isinstance(row, dict) and _int(row.get("id")) is not None:
            add.append(row)
        elif _int(row) is not None:
            add.append(_int(row))
        else:
            errors.append("items.add 每项必须是 itemId 或带 id 的对象：%r" % (row,))
    items["add"] = add
    tmpl = items.get("template")
    if tmpl is not None and _int(tmpl) is None:
        errors.append("items.template 必须是 itemId 或 null")
    items["template"] = _int(tmpl) if tmpl is not None else None
    doc["items"] = items

    # ---- capture ----------------------------------------------------------
    cap = _as_dict(doc.get("capture"))
    if not isinstance(cap.get("enabled"), bool):
        errors.append("capture.enabled 必须是 true/false")
    if cap.get("enabled") and not str(cap.get("dir") or "").strip():
        warnings.append("capture.enabled=true 但 dir 为空 —— 抓包目录将用默认位置")
    cap["paths"] = [str(x) for x in _as_list(cap.get("paths")) if str(x).strip()]
    cap["req_paths"] = [str(x) for x in _as_list(cap.get("req_paths")) if str(x).strip()]
    mb = _int(cap.get("max_bytes"))
    if mb is None or mb <= 0:
        errors.append("capture.max_bytes 必须是正整数")
    else:
        cap["max_bytes"] = mb
    if not isinstance(cap.get("planet_settings"), bool):
        errors.append("capture.planet_settings 必须是 true/false")
    doc["capture"] = cap

    # ---- experimental -----------------------------------------------------
    exp = _as_dict(doc.get("experimental"))
    cz = _as_dict(exp.get("customize"))
    if not isinstance(cz.get("enabled"), bool):
        errors.append("experimental.customize.enabled 必须是 true/false")
    if not isinstance(cz.get("edits"), list):
        errors.append("experimental.customize.edits 必须是数组")
    exp["customize"] = {"enabled": bool(cz.get("enabled") and isinstance(cz.get("edits"), list)),
                        "edits": _as_list(cz.get("edits"))}
    doc["experimental"] = exp

    # ---- 语义提醒（不阻塞） -------------------------------------------------
    if not variants and not trials and not pe and not ge and not st["campaigns"] \
            and not st["owner"] and not sh and not infos:
        warnings.append("当前 profile 没有任何改写内容（passthrough 之外等于纯转发）")
    return doc, errors, warnings


# ---------------------------------------------------------------- 存取


def _ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def save_profile_file(path, profile: dict) -> Path:
    """校验后原子写入 profile 文件；返回最终路径。errors 非空抛 ValueError。"""
    normalized, errors, warnings = validate(profile)
    if errors:
        raise ValueError("profile 校验失败: " + "; ".join(errors))
    path = Path(path)
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_profile_file(path) -> dict:
    """读并校验 profile；失败抛 ValueError（带具体字段）。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    normalized, errors, warnings = validate(raw)
    if errors:
        raise ValueError("profile 校验失败（%s）: %s" % (path, "; ".join(errors)))
    normalized["_warnings"] = warnings
    return normalized


def profile_dir() -> Path:
    d = paths.profile_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list[dict]:
    out = []
    for p in sorted(profile_dir().glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": p.stem, "path": str(p),
                        "title": doc.get("name") or p.stem,
                        "mtime": p.stat().st_mtime})
        except Exception:
            out.append({"name": p.stem, "path": str(p), "title": p.stem, "error": "读取失败"})
    return out


def profile_path(name: str) -> Path:
    bad = set('/:*?"<>|') | {chr(92)}      # 文件名非法字符（反斜杠用 chr 避免字面量歧义）
    safe = "".join(c for c in str(name) if c not in bad).strip() or "default"
    return profile_dir() / (safe + ".json")


def save_profile(name: str, profile: dict) -> Path:
    doc = dict(profile)
    doc.setdefault("name", name)
    return save_profile_file(profile_path(name), doc)


def load_profile(name: str) -> dict:
    return load_profile_file(profile_path(name))


# ---------------------------------------------------------------- profile -> EngineSpec


def _resolve_variant(catalog_doc, name):
    """从变种目录解析 name/alias -> {ids, faction}；解析不到返回 None。"""
    cat = _as_dict((catalog_doc or {}).get("variants"))
    meta = _as_dict((catalog_doc or {}).get("meta"))
    aliases = _as_dict((catalog_doc or {}).get("aliases"))
    key = name if name in cat else aliases.get(name)
    if not key or key not in cat:
        return None
    ids = [_int(x) for x in _as_list(cat[key])]
    ids = [x for x in ids if x]
    info = _as_dict(meta.get(key))
    faction = info.get("faction")
    if not faction:
        presence = str(info.get("presence") or "").lower()
        if presence.startswith("bugs_"):
            faction = "terminid"
        elif presence.startswith("bots_") or presence.startswith("elite_bot_"):
            faction = "automaton"
        elif presence.startswith("illuminate_"):
            faction = "illuminate"
        else:
            faction = "universal"
    return {"name": key, "ids": ids, "faction": faction}


def build_status_plan(profile: dict, catalog_doc=None) -> tuple[dict, list[str]]:
    """把 profile 的 variants/trials 变成引擎的 explicit plan：{planet: {variants, trials}}。"""
    warnings = []
    st = _as_dict(profile.get("status"))
    variants = [v for v in (st.get("variants") or []) if isinstance(v, dict)]
    trials = [_int(x) for x in (st.get("trials") or []) if _int(x)]
    if not variants and not trials:
        return {}, warnings
    resolved = []
    for row in variants:
        entry = _resolve_variant(catalog_doc, row.get("name"))
        if not entry:
            warnings.append("变种 %r 在目录里找不到（检查拼写/别名），已跳过" % row.get("name"))
            continue
        planets = [_int(p) for p in (row.get("planets") or []) if _planet_ok(_int(p))]
        if not planets:
            warnings.append("变种 %r 没有指定 planets（本版不做「自动跟随当前星球」），已跳过"
                            % row.get("name"))
            continue
        resolved.append((planets, entry))
    plan = {}
    for planets, entry in resolved:
        for planet in planets:
            spec = plan.setdefault(planet, {"variants": [], "trials": list(trials)})
            if entry not in spec["variants"]:
                spec["variants"].append(entry)
    for planet in list(plan):
        if not plan[planet]["variants"] and not plan[planet]["trials"]:
            del plan[planet]
    return plan, warnings


def to_engine_spec(profile: dict, catalog_doc=None) -> EngineSpec:
    """profile -> EngineSpec（引擎/控制面消费的唯一形态）。"""
    raw = profile or {}
    proxy = _as_dict(raw.get("proxy"))
    cert = _as_dict(raw.get("cert"))
    wi = _as_dict(raw.get("warinfo"))
    st = _as_dict(raw.get("status"))
    inv = _as_dict(raw.get("inventory"))
    items = _as_dict(raw.get("items"))
    cap = _as_dict(raw.get("capture"))
    exp = _as_dict(raw.get("experimental"))
    _, _, warnings = validate(_deep_merge(DEFAULT_PROFILE, raw)) if raw else (
        default_profile(), [], [])

    spec = EngineSpec(
        host=proxy.get("host") or HOST_DEFAULT,
        listen_ip=(proxy.get("listen_ip") or "auto"),
        port=_int(proxy.get("port"), 443),
        crl_port=_int(proxy.get("crl_port"), 8080),
        control_port=_int(proxy.get("control_port"), 0) or 0,
        passthrough=bool(proxy.get("passthrough", True)),
        verbose=bool(proxy.get("verbose", False)),
        cert_days=_int(cert.get("days"), 2) or 2,
        cert_min_remaining_hours=float(cert.get("min_remaining_hours", 12) or 0),
        cert_auto_renew=bool(cert.get("auto_renew", True)),
        profile_name=str(raw.get("name") or ""),
    )

    # warinfo（settingsHash 记录开关挂在 capture.planet_settings 上：抓一次 live warinfo 即可）
    if wi.get("settings_hash") or wi.get("planet_infos") or cap.get("planet_settings"):
        spec.warinfo = {"settings_hash": dict(wi.get("settings_hash") or {}),
                        "planet_infos": list(wi.get("planet_infos") or [])}
        if cap.get("planet_settings"):
            spec.warinfo["record_planet_settings"] = str(
                paths.state_dir() / "planet_settings.json")

    # status：额外结构化改写
    extra = {}
    for key in ("campaigns", "attacks", "events", "globalEffects", "regions",
                "planet_nodes", "planet_effects", "owner"):
        val = st.get(key)
        if val:
            extra[key] = val
    spec.status_extra = extra or None

    # status：变种/战备计划
    plan, plan_warnings = build_status_plan(raw, catalog_doc)
    spec.status_plan = plan or None
    warnings.extend(plan_warnings)

    # inventory：四类聚合（引擎只认一个聚合 spec）
    inv_items = []
    for key in ("weapons", "attachments", "cosmetics", "stratagems", "probe"):
        for row in inv.get(key) or []:
            if isinstance(row, dict) and _int(row.get("mixId")):
                inv_items.append({"mixId": _int(row["mixId"]),
                                  "amount": _int(row.get("amount"), 1) or 1,
                                  "isDiscovered": bool(row.get("isDiscovered", False))})
    inv_cfg = {"enabled": bool(inv_items or inv.get("remove") or inv.get("customization")),
               "items": inv_items,
               "remove": list(inv.get("remove") or []),
               "customization": list(inv.get("customization") or [])}
    spec.inventory = inv_cfg if inv_cfg["enabled"] else None

    # items
    if items.get("add"):
        spec.items = {"enabled": True, "template": items.get("template"),
                      "add": list(items.get("add") or [])}

    # customize（实验，默认关）
    cz = _as_dict(exp.get("customize"))
    if cz.get("enabled") and cz.get("edits"):
        spec.customize = {"enabled": True, "edits": list(cz["edits"]),
                          "logEdits": True}

    # capture
    cap_dir = str(cap.get("dir") or "").strip()
    if cap.get("enabled"):
        spec.capture = {
            "enabled": True,
            "dir": cap_dir or str(paths.capture_default_dir()),
            "paths": list(cap.get("paths") or ["api/"]),
            "req_paths": list(cap.get("req_paths") or []),
            "max_bytes": _int(cap.get("max_bytes"), 8 << 20) or (8 << 20),
        }
    else:
        spec.capture = {"enabled": False, "dir": "", "paths": [], "req_paths": [],
                        "max_bytes": _int(cap.get("max_bytes"), 8 << 20) or (8 << 20)}

    spec.warnings = list(dict.fromkeys([w for w in warnings if w]))
    return spec


# ---------------------------------------------------------------- 旧配置迁移


def from_legacy(cfg_path, runtime_dir=None, extra_spec=None) -> tuple[dict, list[str]]:
    """把研究线的 config.json + runtime/*.json + HD2_GWE_EXTRA 迁移成 profile。

    原则：只搬能确定的；搬不了的写 notes，不猜。
    """
    notes = []
    profile = default_profile()
    cfg = {}
    try:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8-sig"))
    except Exception as e:      # noqa: BLE001
        notes.append("config.json 读取失败（%r），用默认值" % e)

    proxy = profile["proxy"]
    proxy["host"] = cfg.get("host") or HOST_DEFAULT
    if cfg.get("listenIp"):
        proxy["listen_ip"] = cfg["listenIp"]
    for src, dst in (("port", "port"), ("crlPort", "crl_port")):
        if _int(cfg.get(src)) is not None:
            proxy[dst] = _int(cfg[src])
    proxy["passthrough"] = bool(cfg.get("passthrough", True))
    proxy["verbose"] = bool(cfg.get("verbose", False))

    rt = Path(runtime_dir) if runtime_dir else paths.RUNTIME

    def _read(name):
        try:
            return json.loads((rt / name).read_text(encoding="utf-8"))
        except Exception:
            return {}

    # 变种选择 + targets 星球
    targets = [t for t in (cfg.get("targets") or []) if isinstance(t, dict)]
    target_planets = [_int(t.get("planet")) for t in targets if _planet_ok(_int(t.get("planet")))]
    sel = _read("selection.json")
    names = []
    if sel.get("enabled"):
        names = [x for x in (sel.get("variants") or []) if isinstance(x, str)] or \
                ([sel["variant"]] if isinstance(sel.get("variant"), str) else [])
    elif targets:
        names = [t.get("variant") for t in targets if isinstance(t.get("variant"), str)]
    if names:
        profile["status"]["variants"] = [{"name": n, "planets": target_planets} for n in names]
        if not target_planets:
            notes.append("变种 %s 已迁移但 planets 为空：旧版是「自动跟随当前星球」，"
                         "新版不做该行为，需要你在界面里选星球" % "、".join(names))

    # 战备试用
    strat = _read("stratagems.json")
    if strat.get("enabled"):
        profile["status"]["trials"] = [_int(x) for x in (strat.get("ids") or [])
                                       if _int(x) is not None]
        if len(profile["status"]["trials"]) > 3:
            notes.append("旧版战备试用最多 3 条（引擎会再截断）；profile 里保留了 %d 条"
                         % len(profile["status"]["trials"]))

    # 库存四类 + 探针 + 移除
    keymap = [("inventory_inject.json", "weapons"),
              ("inventory_attach_inject.json", "attachments"),
              ("inventory_cosmetic_inject.json", "cosmetics"),
              ("inventory_stratagem_inject.json", "stratagems"),
              ("inventory_probe_inject.json", "probe")]
    for fname, key in keymap:
        doc = _read(fname)
        if not doc.get("enabled"):
            continue
        rows = doc.get("items") if key != "probe" else doc.get("probe")
        rows = rows or doc.get("items") or []
        profile["inventory"][key] = [{"mixId": r["mixId"], "amount": r.get("amount", 1),
                                      "isDiscovered": bool(r.get("isDiscovered", False))}
                                     for r in rows if isinstance(r, dict) and _int(r.get("mixId"))]
        profile["inventory"]["remove"] += [_int(x) for x in doc.get("remove") or [] if _int(x)]
        profile["inventory"]["customization"] += [r for r in doc.get("customization") or []
                                                  if isinstance(r, dict)]

    # 物品目录追加
    items = _read("items_inject.json")
    if items.get("enabled"):
        profile["items"]["template"] = _int(items.get("template"))
        profile["items"]["add"] = [r for r in items.get("add") or []]
        if profile["items"]["template"] is None:
            notes.append("items_inject 没有 template：逐条 add 必须自带 template 才能克隆")

    # L2 改装（实验，默认关）
    cz = _read("customize_inject.json")
    if cz.get("enabled"):
        profile["experimental"]["customize"] = {"enabled": True,
                                                "edits": cz.get("edits") or []}
        notes.append("customize_inject 已迁移到 experimental.customize（研究线实测「送达不生效」）")

    # HD2_GWE_EXTRA
    extra = extra_spec
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            notes.append("HD2_GWE_EXTRA 解析失败，未迁移")
            extra = None
    if isinstance(extra, dict):
        for key in ("settings_hash", "planet_infos"):
            if key in extra:
                profile["warinfo"][key] = extra[key]
        for key in ("campaigns", "attacks", "events", "globalEffects", "regions",
                    "planet_nodes", "planet_effects", "owner"):
            if key in extra:
                profile["status"][key] = extra[key]

    # 抓包
    dump = os.environ.get("HD2_GWE_DUMP")
    if dump:
        profile["capture"]["enabled"] = True
        profile["capture"]["dir"] = dump
        profile["capture"]["paths"] = [p for p in
                                       (os.environ.get("HD2_GWE_PATHS") or "api/").split(",")
                                       if p.strip()]
        profile["capture"]["req_paths"] = [p for p in
                                           (os.environ.get("HD2_GWE_REQ_PATHS") or "").split(",")
                                           if p.strip()]

    normalized, errors, warnings = validate(profile)
    if errors:
        notes.append("迁移结果未能通过校验（已尽量保留）：" + "; ".join(errors))
    notes.extend(warnings)
    return normalized, notes
