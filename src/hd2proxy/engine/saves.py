"""存档层底座（G1）：每玩家可持久化的「已获得」账本 + 合并到响应。

背景（交接档 `HANDOFF-SAVE-SYSTEM-TO-MITM-2026-11-23.md` §3 G1 / §4 S1）：

    base ⊕ config ⊕ earned

  * ``base``   = 服务端当前响应（官方/研究线 mock 返回的档案底子）；
  * ``config`` = 用户在 GUI 里勾的注入（仍在 profile 层，由现有 inventory/items 钩子负责）；
  * ``earned`` = 本存档累计的「已获得」事实账本（经验、成就、包进度、货币、已解锁物品…）。

本模块只负责 **earned 的持久化与合并语义**；把「哪种响应怎么改」留给 hooks（G2/G3）。

G2 追加的**回滚粒度**（研究线 2026-11-23 反馈：``.bak`` 只有「上一版」单槽，回滚不到「会话前」）：

  * 每个引擎会话在**首次写入前**留一份基准快照 ``runtime/saves/_session-start/<saveId>.json``；
  * 身份不一致时整档回滚到这份基准（而不是 ``.bak``），**无快照 = 本局没写过 = 不动档**；
  * 身份校验通过后把基准**重建**为当前状态（= 最后一次已验证点），并清 ``_last.json.pending``；
  * ``pending`` 让快照跨引擎重启存活：上局没校验完就崩/关，本局沿用最早基准（有 24 h 上限）。

设计约束（与研究线现有设施保持一致）：

  * **单文件存档**：``runtime/saves/<saveId>.json``（含 ``schema`` 版本），默认 ``saveId=local``；
  * **原子写**：先写 ``.tmp`` 再 ``os.replace``；每次覆盖前把旧文件留成 ``.bak``；
  * **损坏不崩**：JSON/schema 不合法 → 备份成 ``.corrupt-<ts>``、回退空档并记日志，绝不抛到代理主流程；
  * **saveId 参数化**：将来「多玩家/多存档」只换 id，不改数据结构；
  * **合并是纯函数**：``apply_to_progression`` / ``apply_to_inventory`` 吃 bytes、吐 bytes + 改动数，
    离线可单测（配合 ``engine/preview.py`` 的 fixture 预演）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import paths
from .logutil import log

SAVE_SCHEMA = 2                  # 2: + catalog_build / identity（2026-11-23 研究线反馈）
DEFAULT_SAVE_ID = "local"
LAST_FILE = "_last.json"          # 上次使用的档指针：启动时乐观预绑定，规避"首屏空档"
SESSION_DIR = "_session-start"    # 会话基准快照（G2 回滚粒度）：<saveId>.json，不进档扫描
SESSION_SCHEMA = 1
PENDING_MAX_AGE_HOURS = 24.0      # pending 快照的复用上限：超过就当过期，重新取基准
_SAVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HD2_ID_RE = re.compile(r"^\d{17,20}$")      # HD2 accountId：20 位数字（GetMessages）
_STEAM_ID_RE = re.compile(r"^7656119\d{10}$")  # SteamID64：17 位（GetMotd）


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value) -> list:
    return list(value) if isinstance(value, list) else []


def normal_save_id(save_id=None) -> str:
    """存档 id 规范化：只允许安全字符；非法值退回 ``local``（绝不拼出路径穿越）。"""
    raw = str(save_id or "").strip()
    if raw and _SAVE_ID_RE.match(raw):
        return raw
    if raw:
        log("存档 id %r 不合法（只允许字母数字 _ -），回退 %s" % (raw, DEFAULT_SAVE_ID))
    return DEFAULT_SAVE_ID


def save_id_for(steam_id=None, hd2_account=None) -> str:
    """身份 → 存档 id：**SteamID64 为主键**，HD2 20 位账号 id 只作别名（2026-11-23 研究线修订）。

    为什么以 SteamID64 为主键（实测证据）：
      * ``POST /api/Pes/GetMotd`` 响应 ``accountId`` = **SteamID64（17 位）** —— 每会话稳定出现
        （主号登录后 +42 s、空号 +24 s；真实会话里 46 分钟出现 7 次）；
      * ``POST /api/Pes/GetMessages`` 响应 ``accountId`` = **20 位 HD2 账号 id** —— 不保证出现
        （主号整份抓包没有；空号只在登录后 +3m09s 出现 1 次）。
      ⇒ 若以 HD2 为主键，同一玩家会分别落进 ``steam_*`` 与 ``hd2_*`` 两个档、看起来"进度丢了"。

    取值：``steam_<SteamID64>``；没有 SteamID64 但拿得到 HD2 id 时退 ``hd2_<id>``；都没有 ``local``。
    后出现的别名用 ``SaveStore.bind_identity`` 记录，用 ``adopt_identity`` 合并迁移（见该类）。
    """
    steam = "" if steam_id is None else str(steam_id).strip()
    hd2 = "" if hd2_account is None else str(hd2_account).strip()
    if steam and _STEAM_ID_RE.match(steam):
        return "steam_" + steam
    if hd2 and _HD2_ID_RE.match(hd2):
        return "hd2_" + hd2
    return DEFAULT_SAVE_ID


def save_id_for_identity(steam_id=None, hd2_account=None, root=None) -> str:
    """身份 → 档 id，带 **HD2 反查**：只有 HD2 20 位时先扫存档 identity 块复用已有档。"""
    sid = save_id_for(steam_id, hd2_account)
    if sid.startswith("hd2_"):
        found = find_save_by_hd2(hd2_account, root=root)
        if found:
            return found
    return sid


def catalog_build_id(items_body, client_version=None) -> dict:
    """计算目录版本标识：``{"sha8", "rows", "client_version", "value"}``。

    口径（研究线 2026-11-23 定）：``"<items_sha8>/<items_rows>/<clientVersion>"``，缺段留空。
    必须传 **注入前** 的 ``/api/Progression/items`` 原始响应（注入后再算会随配置变化、失去可比性）。
    参考实测：11-16/11-17 两账号 `d71655e6`/3020 行；11-18 主号 `93e7575a`/3021 行（版本差异）。
    """
    raw = None
    if isinstance(items_body, (bytes, bytearray)):
        raw = bytes(items_body)
    elif isinstance(items_body, str):
        raw = items_body.encode("utf-8")
    rows = None
    try:
        doc = json.loads(raw.decode("utf-8")) if raw is not None else items_body
        if isinstance(doc, list):
            rows = len(doc)
        elif isinstance(doc, dict) and isinstance(doc.get("items"), list):
            rows = len(doc["items"])
    except (ValueError, UnicodeDecodeError):
        rows = None
    sha8 = hashlib.sha256(raw).hexdigest()[:8] if raw is not None else ""
    ver = "" if client_version is None else str(client_version).strip()
    value = "%s/%s/%s" % (sha8, "" if rows is None else rows, ver or "-")
    return {"sha8": sha8, "rows": rows, "client_version": ver or None, "value": value}


def empty_save(save_id=None) -> dict:
    """空档：等价于「空号基线 + 什么都没挣到」。"""
    sid = normal_save_id(save_id)
    now = _now()
    return {
        "schema": SAVE_SCHEMA,
        "save_id": sid,
        "created_at": now,
        "updated_at": now,
        # 目录漂移追溯（Progression/items 会随 build 变；11-16→11-18 多 1 行）
        "catalog_build": None,
        # 身份别名（只用于选档/排障，不做鉴权）：HD2 20 位账号 id / SteamID64
        # source / identified_at 只作**审计**：将来排查「这份档是怎么认到身份的」能省很多时间
        "identity": {"hd2_account_id": None, "steam_id": None,
                     "source": None, "identified_at": None},
        "earned": {
            # /api/Progression 根
            "experience": 0,
            "onboarding_flags": 0,
            "onboarding_state": 0,
            "ship_name": None,
            "location": None,
            "achievements": {},              # {str(id): value}
            "package_progress": {},          # {str(id32): {level?, progress?, claimedLevels?}}
            "purchased_season_pass_items": [],
            # /api/Progression/inventory
            "inventory_amounts": {},         # {str(mixId): amount}（绝对数量，权威值）
            "inventory_ids": [],             # 需要确保存在的 mixId
            # 预留（G4/G5）：按存档返回的统计 / 季票 / 合约
            "stats": {},
            "season_pass": {},
            "assignments": {},
            # G3：结算审计（本局增量记录 + missionId 去重，防重试双计）
            "missions": {"count": 0, "recent_ids": [], "last": None},
            # G5+：购买/解锁审计（响应增量 + 去重键，防重试双扣）
            "purchases": {"count": 0, "recent_keys": [], "last": None},
        },
    }


def _normalize_identity(doc: dict) -> dict:
    """把 identity 补齐成完整形状（老档没有 source/identified_at 也能读）。"""
    got = (doc or {}).get("identity")
    if not isinstance(got, dict):
        got = {}
    out = {"hd2_account_id": got.get("hd2_account_id"),
           "steam_id": got.get("steam_id"),
           "source": got.get("source"),
           "identified_at": got.get("identified_at")}
    for key, value in got.items():          # 保留将来新增的字段，不丢信息
        out.setdefault(key, value)
    doc["identity"] = out
    return out


def _normalize_earned(doc: dict) -> dict:
    """把任意来源的 earned 补齐成完整形状（老档/手改档也能用）。"""
    base = empty_save((doc or {}).get("save_id"))["earned"]
    got = (doc or {}).get("earned")
    if not isinstance(got, dict):
        return base
    for key, default in base.items():
        if key not in got:
            got[key] = default
            continue
        if isinstance(default, dict) and not isinstance(got[key], dict):
            got[key] = default
        elif isinstance(default, list) and not isinstance(got[key], list):
            got[key] = default
    return got


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# G4：终身统计（Stats/profile）—— 纯展示的单调计数器，**逐 key 取 max**
# --------------------------------------------------------------------------- #
def stats_profile_of(save) -> dict:
    """取存档里的 ``stats.profile``（兼容两种档：嵌套 ``stats.profile`` 或老档扁平 ``stats``）。"""
    earned = _normalize_earned(save or {})
    stats = earned.get("stats")
    if not isinstance(stats, dict) or not stats:
        return {}
    profile = stats.get("profile")
    if isinstance(profile, dict):
        return {str(k): v for k, v in profile.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
    # 老档/手改档：stats 本身就是 {key: value}
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in stats.values()):
        return {str(k): v for k, v in stats.items()}
    return {}


def parse_stats_numbers(body) -> dict:
    """从 Stats 响应/任意 body 抽出 ``{key: 数值}``（拒绝 bool 与非数值）。"""
    doc, _ = _decode(body)
    if not isinstance(doc, dict):
        return {}
    return {str(k): v for k, v in doc.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def apply_to_stats(body, save):
    """把存档里的终身统计合并进 ``Stats/profile`` 响应（逐 key **取 max**，只抬不降）。

    Stats 是纯展示的终身计数器（27 项 totalXxx）。用 max 而不是覆盖的原因：
      * 计数器只增，服务端/客户端上报都只会变大；
      * 换号/新号返回 0 时，不能把本地已记录的终身战绩"抹掉"（研究线 2026-11-23 口径）。
    返回 ``(new_body, 改动字段数)``；没有可合并项时 body 原样返回。
    """
    doc, as_bytes = _decode(body)
    if not isinstance(doc, dict):
        return body, 0
    mine = stats_profile_of(save)
    if not mine:
        return body, 0
    changed = 0
    for key, value in mine.items():
        if key not in doc:
            continue                       # 只改响应里已有的键：不往客户端凭空加字段
        cur = doc.get(key)
        if not isinstance(cur, (int, float)) or isinstance(cur, bool):
            continue
        if value > cur:
            doc[key] = value
            changed += 1
    if not changed:
        return body, 0
    return _encode(doc, as_bytes), changed


def merge_stats_into(dst_earned: dict, src_earned: dict) -> dict:
    """把 ``src_earned`` 的终身统计按 key max 合并进 ``dst_earned``（迁移/换号合并用）。"""
    mine = stats_profile_of({"earned": dst_earned})
    theirs = stats_profile_of({"earned": src_earned})
    if not theirs:
        return dst_earned
    for key, value in theirs.items():
        cur = mine.get(key)
        if cur is None or value > cur:
            mine[key] = value
    stats = dst_earned.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = dst_earned["stats"] = {}
    stats["profile"] = mine
    return dst_earned


def _merge_earned_into(dst: dict, src: dict) -> dict:
    """把 ``src`` 合并进 ``dst``（迁移/换主键时用），按研究线 2026-11-23 定的字段类型分语义：

      * **单调量**（experience / onboarding / 成就计数 / 包 level·progress / 终身统计）→ ``max``（防倒退）；
      * **可消耗量**（货币/消耗品 ``inventory_amounts``）→ **``updated_at`` 较新的档为准**
        （取 max 会把"已经花掉的钱"复活）；
      * **覆盖量**（ship_name / location）→ 较新的档为准；
      * **集合类**（已解锁 id / purchased / claimedLevels）→ 并集。

    绝不因为换档丢「已获得」；返回合并后的 earned（就地改 ``dst``）。
    """
    de = _normalize_earned(dst)
    se = _normalize_earned(src)
    # 时间戳只到秒：相等时以「正在迁入的 src」为准（adopt 刚写完的档就是 src）
    src_newer = str(src.get("updated_at") or "") >= str(dst.get("updated_at") or "")

    # 单调量：取大（与新旧无关）
    for key in ("experience", "onboarding_flags", "onboarding_state"):
        if _as_int(se.get(key)) > _as_int(de.get(key)):
            de[key] = _as_int(se[key])

    # 覆盖量：较新的档为准
    for key in ("ship_name", "location"):
        if src_newer and se.get(key):
            de[key] = se[key]
        elif not de.get(key) and se.get(key):
            de[key] = se[key]

    # 单调字典：成就计数（取大）、包进度（level/progress 取大 + claimedLevels 并集）
    for key in ("achievements", "package_progress"):
        cur = de.setdefault(key, {})
        for k2, v2 in (se.get(key) or {}).items():
            if isinstance(v2, dict):
                got = cur.setdefault(k2, {})
                for k3, v3 in v2.items():
                    if isinstance(v3, list):
                        for item in v3:
                            if item not in got.setdefault(k3, []):
                                got[k3].append(item)
                    elif _as_int(v3) > _as_int(got.get(k3)):
                        got[k3] = v3
            elif _as_int(v2) > _as_int(cur.get(k2, 0)) or k2 not in cur:
                cur[k2] = v2

    # 可消耗量：较新的档为准（键仍取并，避免丢解锁条目）
    cur_amounts = de.setdefault("inventory_amounts", {})
    new_amounts = se.get("inventory_amounts") or {}
    if src_newer:
        cur_amounts.update(new_amounts)
    else:
        for k2, v2 in new_amounts.items():
            cur_amounts.setdefault(k2, v2)

    # 集合类：取并
    for key in ("purchased_season_pass_items", "inventory_ids"):
        cur = de.setdefault(key, [])
        for item in _as_list(se.get(key)):
            if item not in cur:
                cur.append(item)

    # G4：终身统计按 key 取 max（单调计数器；迁移时不能因为"较新"把战绩改小）
    merge_stats_into(de, se)

    # 预留复杂结构：较新的档为准，缺键补齐
    for key in ("season_pass", "assignments", "missions", "purchases"):
        got = se.get(key) or {}
        if not isinstance(got, dict) or not got:
            continue
        cur = de.setdefault(key, {})
        if not isinstance(cur, dict):
            cur = de[key] = {}
        if src_newer:
            cur.update(got)
        else:
            for k2, v2 in got.items():
                cur.setdefault(k2, v2)
    return de



def _archive_save(store: "SaveStore", reason: str = "merged") -> None:
    """把存档文件归档成 ``<save_id>.<reason>-<ts>.json``（保留现场审计，不参与读取）。"""
    p = store.path()
    if not p.exists():
        return
    target = p.with_name("%s.%s-%s.json" % (store.save_id, reason,
                                           time.strftime("%Y%m%d-%H%M%S")))
    try:
        p.replace(target)
        log("存档 %s 已归档为 %s" % (store.save_id, target.name))
    except OSError as e:
        log("存档归档失败（%s）：%r" % (store.save_id, e))


def _saves_root(root=None) -> Path:
    return Path(root) if root else Path(paths.SAVES_DIR)


def read_last(root=None) -> dict:
    """读 ``_last.json``（上次使用的档指针）。不存在/损坏 → 空 dict。

    用途（研究线 2026-11-23 实测的时序问题）：客户端 **一次会话只拉一次** `/api/Progression`，
    且它比身份端点 `Pes/GetMotd` 早 ~0.5–26 s。所以引擎启动时先按上次档渲染首屏，
    等身份到达再校验/切换，避免老玩家整局看到空档。
    """
    p = _saves_root(root) / LAST_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_json_atomic(path: Path, doc) -> bool:
    """原子写 JSON（tmp + os.replace）。失败只记日志，绝不抛到代理主流程。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as e:
        log("JSON 写入失败（%s）：%r" % (path, e))
        return False


def write_last(save_id, steam_id=None, hd2_account=None, root=None) -> dict:
    """原子更新 ``_last.json``；返回写入内容。

    **保留 pending**：只要 pending 属于同一个 saveId 就原样带过去 —— 它的语义是
    「该档身份尚未校验」，与「上次用了哪个档」是两件事，不能被普通写入清掉
    （清了就等于宣布"已校验"，下次启动会拿脏档当基准）。
    """
    sid = normal_save_id(save_id)
    doc = {
        "last_save_id": sid,
        "last_steam_id": str(steam_id) if steam_id else None,
        "last_hd2_account_id": str(hd2_account) if hd2_account else None,
        "updated_at": _now(),
    }
    old = read_last(root)
    pending = old.get("pending")
    if isinstance(pending, dict) and str(pending.get("save_id") or "") == sid:
        doc["pending"] = pending
    _write_json_atomic(_saves_root(root) / LAST_FILE, doc)
    return doc


def mark_pending(save_id, *, run_id=None, root=None, since=None) -> dict:
    """标记「该档身份尚未校验」（配合 `_session-start` 快照跨引擎重启存活）。

    ``since``：沿用上一局的起始时间（跨重启复用基准时必须保留原值，否则每次启动都刷新
    新鲜度，pending 永不过期 —— 几周后一复用就会把合法进度一起回滚掉）。
    """
    sid = normal_save_id(save_id)
    doc = read_last(root)
    doc["last_save_id"] = sid
    doc.setdefault("last_steam_id", None)
    doc.setdefault("last_hd2_account_id", None)
    doc["pending"] = {"save_id": sid, "run_id": str(run_id or ""),
                      "since": str(since or "") or _now()}
    doc["updated_at"] = doc.get("updated_at") or _now()
    _write_json_atomic(_saves_root(root) / LAST_FILE, doc)
    return doc


def read_pending(root=None) -> dict:
    """读 pending 块（没有则空 dict）。"""
    pending = (read_last(root) or {}).get("pending")
    return pending if isinstance(pending, dict) else {}


def clear_pending(root=None) -> dict:
    """清掉 pending（身份校验通过 / 已切档完成）。"""
    doc = read_last(root)
    if doc.pop("pending", None) is not None:
        _write_json_atomic(_saves_root(root) / LAST_FILE, doc)
    return doc


def pending_age_hours(pending: dict) -> float | None:
    """pending 距今多少小时；时间戳不可解析返回 None（= 当作过期，不冒险复用）。"""
    since = "" if not isinstance(pending, dict) else str(pending.get("since") or "")
    if not since:
        return None
    try:
        started = time.mktime(time.strptime(since, "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0.0, (time.time() - started) / 3600.0)


def pending_reusable(pending: dict, max_age_hours: float = PENDING_MAX_AGE_HOURS) -> bool:
    """上局留下的 pending 是否还能当「同一个未校验窗口」继续沿用基准快照。

    为什么要新鲜度上限：崩溃/关机留下的 pending 如果几周后才复用，会把这段时间里
    的合法进度一起回滚掉 —— 宁可重新取基准（丢的只是崩溃前未校验的窗口）。
    """
    if not isinstance(pending, dict) or not pending.get("save_id"):
        return False
    age = pending_age_hours(pending)
    return age is not None and age <= float(max_age_hours)


# --------------------------------------------------------------------------- #
# 会话基准快照（G2）：回滚粒度 = 「本次引擎会话第一次写入之前」
#
# 研究线 2026-11-23 反馈：`.bak` 只是「上一版」单槽，同局连续写 3 次后再回滚只会退到第 2 次，
# 前两次的写入仍留在错误身份的档里（部分写入比整档污染更难排查）。所以回滚源改成会话基准快照。
# --------------------------------------------------------------------------- #
def doc_sha(doc) -> str:
    """文档内容指纹（排序键紧凑 JSON 的 sha256 前 16 位）；用于日志 / orphan 审计。"""
    if doc is None:
        return ""
    try:
        raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _value_shape(value):
    """给差异摘要用的形状描述：标量原值，容器只列规模与变化键（不撑爆日志）。"""
    if isinstance(value, dict):
        return {"kind": "dict", "size": len(value)}
    if isinstance(value, list):
        return {"kind": "list", "size": len(value)}
    return value


def _is_number_map(value) -> bool:
    """``{str(id): 数值}`` 形态（货币/道具数量/成就计数）—— 差异里要给**具体数值**。"""
    if not isinstance(value, dict) or not value:
        return False
    return all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in value.values())


def _number_map_diff(before: dict, after: dict, max_detail: int) -> dict:
    """货币/数量类字典的差异：``{mixId: amount}`` 直接给数值（人工判断"哪笔钱该不该退"）。"""
    out = {"currency": True}
    added = {k: after[k] for k in sorted(set(after) - set(before))}
    removed = {k: before[k] for k in sorted(set(before) - set(after))}
    changed = {k: {"before": before[k], "after": after[k]}
               for k in sorted(set(before) & set(after)) if before[k] != after[k]}
    for key, val in (("added", added), ("removed", removed), ("changed", changed)):
        if val:
            items = list(val.items())
            out[key] = dict(items[:max_detail])
            if len(items) > max_detail:
                out[key]["…"] = "+%d" % (len(items) - max_detail)
    return out


def earned_diff(before, after, *, max_keys: int = 12, max_detail: int = 8) -> dict:
    """对比两份 earned，列出差异摘要（orphan 里回答「到底哪些条被丢弃」）。

    容器类给出「规模 + 变化键名」；**数值字典（货币/道具数量）额外给具体值**
    （研究线 2026-11-23 建议：换号回滚后要能人工判断"哪笔钱该不该退"）。
    完整内容另存在 orphan 的 dirty/restored doc 里。
    """
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    out = {}
    for key in sorted(set(b) | set(a)):
        bv, av = b.get(key), a.get(key)
        if bv == av:
            continue
        item = {"before": _value_shape(bv), "after": _value_shape(av)}
        if isinstance(bv, dict) and isinstance(av, dict):
            if _is_number_map(bv) or _is_number_map(av):
                item.update(_number_map_diff(bv, av, max_detail))
            else:
                added = sorted(str(k) for k in set(av) - set(bv))
                removed = sorted(str(k) for k in set(bv) - set(av))
                changed = sorted(str(k) for k in set(bv) & set(av) if bv[k] != av[k])
                item["added"] = added[:max_detail]
                item["removed"] = removed[:max_detail]
                item["changed"] = changed[:max_detail]
        elif isinstance(bv, list) and isinstance(av, list):
            added = [x for x in av if x not in bv]
            removed = [x for x in bv if x not in av]
            item["added"] = added[:max_detail]
            item["removed"] = removed[:max_detail]
        out[key] = item
        if len(out) >= max_keys:
            out["..."] = {"note": "差异项超过上限，详见 orphan 全文"}
            break
    return out


def session_snapshot_path(save_id, root=None) -> Path:
    """会话基准快照路径：``runtime/saves/_session-start/<saveId>.json``（目录不进档扫描）。"""
    return _saves_root(root) / SESSION_DIR / (normal_save_id(save_id) + ".json")


def read_session_snapshot(save_id, root=None) -> dict | None:
    """读会话基准快照；不存在/损坏 → None。"""
    p = session_snapshot_path(save_id, root)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def begin_session(store: "SaveStore", *, run_id=None, reuse=False) -> dict:
    """取「会话基准」：把当前档原样快照到 `_session-start/<saveId>.json`。

      * ``reuse=True``：上一个引擎会话没校验完（`_last.json.pending` 且新鲜）→ 沿用**最早**基准，
        崩溃/关窗跨重启也能回滚到整个未校验窗口之前；
      * 否则（含身份已校验）→ 用当前状态重建基准。

    返回 ``{"path", "action": created|reused|rebased, "existed", "sha", "started_at"}``。
    """
    p = session_snapshot_path(store.save_id, store.root)
    existing = read_session_snapshot(store.save_id, store.root)
    if reuse and existing is not None:
        return {"path": str(p), "action": "reused",
                "existed": bool(existing.get("existed")),
                "sha": str(existing.get("sha") or ""),
                "started_at": str(existing.get("started_at") or "")}
    existed = store.path().exists()
    doc = store.load() if existed else None      # load() 顺带处理损坏档（隔离 + 空档）
    payload = {"schema": SESSION_SCHEMA, "save_id": store.save_id,
               "run_id": str(run_id or ""), "started_at": _now(),
               "existed": bool(existed), "sha": doc_sha(doc), "doc": doc}
    _write_json_atomic(p, payload)
    return {"path": str(p), "action": "rebased" if existing is not None else "created",
            "existed": bool(existed), "sha": payload["sha"],
            "started_at": payload["started_at"]}


def rebase_session(store: "SaveStore", *, run_id=None) -> dict:
    """身份校验通过后把基准重建为**当前状态**（= 最后一次已验证点）。"""
    return begin_session(store, run_id=run_id, reuse=False)


def restore_session_snapshot(store: "SaveStore") -> dict:
    """把档整档回滚到会话基准快照（**不经过 `.bak`**，也不产生新 `.bak`）。

    返回 ``{"ok","mode","snapshot_sha","path"}``，``mode``：
      * ``restored`` —— 恢复成快照内容；
      * ``deleted``  —— 会话前没有这份档（本局新建的脏档整份删除）；
      * ``none``     —— 没有快照（= 本局没写过），**不动档**；
      * ``failed``   —— 磁盘错误（调用方保留脏档 + 打 WARN，绝不假装回滚成功）。
    """
    snap = read_session_snapshot(store.save_id, store.root)
    snap_path = session_snapshot_path(store.save_id, store.root)
    if not snap:
        return {"ok": False, "mode": "none", "snapshot_sha": "", "path": str(snap_path)}
    p = store.path()
    if not snap.get("existed"):
        try:
            if p.exists():
                p.unlink()
        except OSError as e:
            log("会话回滚失败（删除本局新建档 %s）：%r" % (p, e))
            return {"ok": False, "mode": "failed", "snapshot_sha": "", "path": str(snap_path)}
        mode = "deleted"
    else:
        doc = snap.get("doc")
        if not isinstance(doc, dict):
            return {"ok": False, "mode": "none", "snapshot_sha": "", "path": str(snap_path)}
        tmp = p.with_name(store.save_id + ".json.restore.tmp")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            log("会话回滚失败（恢复 %s）：%r" % (p, e))
            return {"ok": False, "mode": "failed", "snapshot_sha": "", "path": str(snap_path)}
        mode = "restored"
    return {"ok": True, "mode": mode, "snapshot_sha": str(snap.get("sha") or ""),
            "path": str(snap_path)}


def clear_session_snapshot(save_id, root=None) -> bool:
    """删掉会话基准快照（身份已校验的收摊 / 测试清理）。"""
    p = session_snapshot_path(save_id, root)
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        log("会话快照清理失败（%s）：%r" % (p, e))
        return False


def find_save_by_hd2(hd2_account, root=None) -> str:
    """已知 HD2 20 位 id、但没有 SteamID64 时，**扫描存档文件的 identity 块**反查档 id。

    不为身份新造状态源：存档文件本身就是事实源（研究线建议）。找不到返回空串。
    """
    want = "" if hd2_account is None else str(hd2_account).strip()
    if not want:
        return ""
    base = _saves_root(root)
    try:
        paths_iter = sorted(base.glob("*.json"))
    except OSError:
        return ""
    for p in paths_iter:
        name = p.name
        if (name == LAST_FILE or name.endswith((".bak", ".tmp"))
                or ".merged-" in name or ".corrupt-" in name
                or ".archived-" in name or ".rollback-" in name):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        ident = doc.get("identity") or {}
        if str(ident.get("hd2_account_id") or "") == want:
            return str(doc.get("save_id") or p.stem)
    return ""


def is_identified(doc: dict) -> bool:
    """档是否「已识别身份」：非 ``local`` 即视为已识别（local/未确认一律 false）。

    用途：``GetMotd`` 到达后发现与当前 activeSave 不一致时，按研究线口径分流——
    旧档未识别 → 合并（不会混进别人的进度）；旧档已识别 → **绝不合并**（跨玩家污染）。
    """
    if not isinstance(doc, dict):
        return False
    return str(doc.get("save_id") or "") not in ("", DEFAULT_SAVE_ID)


def rollback_from_backup(store: "SaveStore") -> bool:
    """把当前档回滚成 ``.bak``（**旧口径，粒度不足**，G2 起不再作为回滚源）。

    问题（研究线 2026-11-23 反馈）：``.bak`` 只是「上一次保存的上一版」单槽 ——
    同局连续写 3 次后回滚只会退到第 2 次，前两次写入仍留在档里（部分写入）。
    现在由 `restore_session_snapshot()`（会话基准快照）承担回滚；本函数只保留给
    手工作业/旧测试，别再接到引擎主流程上。
    """
    p = store.path()
    bak = p.with_name(store.save_id + ".json.bak")
    if not bak.exists():
        return False
    try:
        if p.exists():
            p.replace(p.with_name("%s.rollback-%s.json" % (store.save_id,
                                                         time.strftime("%Y%m%d-%H%M%S"))))
        bak.replace(p)
        return True
    except OSError as e:
        log("存档回滚失败（%s）：%r" % (store.save_id, e))
        return False


def write_orphan(save_id, doc, root=None, reason: str = "dirty", extra=None) -> str:
    """把「不属于任何现有玩家」的整份脏档写入 ``_orphan/<ts>-<src>.json``，供人工处理。

    存的是**回滚前的脏档全文**（研究线要求）+ ``extra`` 里的审计信息：
    脏档/回滚后 hash、被丢弃条目摘要、回滚方式 —— 事后能核对「到底哪些条被丢弃」。
    """
    base = _saves_root(root) / "_orphan"
    name = "%s-%s-%s.json" % (time.strftime("%Y%m%d-%H%M%S"), normal_save_id(save_id), reason)
    p = base / name
    payload = {"created_at": _now(), "save_id": normal_save_id(save_id),
               "reason": str(reason), "doc_sha": doc_sha(doc), "doc": doc or {}}
    if isinstance(extra, dict):
        payload.update(extra)
    try:
        base.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        log("⚠ 存档增量已另存 orphan：%s（来源档 %s，hash %s）"
            % (p, save_id, payload["doc_sha"]))
        return str(p)
    except OSError as e:
        log("orphan 写入失败（%s）：%r" % (p, e))
        return ""


def switch_identity(store: "SaveStore", *, hd2_account=None, steam_id=None,
                    root=None) -> dict:
    """处理「GetMotd 与当前 activeSave 不一致」的切档，按研究线 2026-11-23 口径分流：

      * 旧档 ``local``/未识别 → **合并**进目标档（等价 adopt_identity）；
      * 旧档是另一个**已识别**档（同机换 Steam 号）→ **不合并**，只返回目标档；
        本局对旧档的写入由调用方（引擎）先用 `restore_session_snapshot()` 整档回滚
        （回滚粒度见模块头注释），再把脏档 `write_orphan()` 另存 —— 引擎侧只看
        ``session_dirty``（本局有没有写过）决定要不要回滚。

    返回 ``{"action": "same"|"merged"|"switched", "store": SaveStore,
             "old_identified": bool, "target_id": str}``。
    """
    base_root = root or store.root
    target_id = save_id_for_identity(steam_id, hd2_account, root=base_root)
    current = store.load()
    old_identified = is_identified(current)
    if target_id == store.save_id:
        target = store
        target.set_identity(hd2_account, steam_id, source="getmotd")
        action = "same"
    elif not old_identified:
        target = store.adopt_identity(hd2_account=hd2_account, steam_id=steam_id,
                                      root=base_root)
        action = "merged"
    else:
        target = SaveStore(target_id, root=base_root)
        target.set_identity(hd2_account, steam_id, source="getmotd")
        write_last(target_id, steam_id, hd2_account, root=base_root)
        log("⚠ 身份切换：旧档 %s（已识别）→ 新档 %s；不合并（避免跨玩家混档）"
            % (store.save_id, target_id))
        action = "switched"
    return {"action": action, "store": target, "old_identified": old_identified,
            "target_id": target_id}


class SaveStore:
    """一份存档的读写门面（原子写 / 备份 / 损坏回退 / 热重载友好：每次操作都重新读盘）。"""

    def __init__(self, save_id=None, root=None):
        self.save_id = normal_save_id(save_id)
        self.root = Path(root) if root else Path(paths.SAVES_DIR)

    # ---- 路径 ------------------------------------------------------
    def path(self) -> Path:
        return self.root / ("%s.json" % self.save_id)

    # ---- 读 --------------------------------------------------------
    def load(self) -> dict:
        """读存档；不存在 → 空档；损坏 → 备份 + 空档（不抛异常）。"""
        p = self.path()
        try:
            raw = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty_save(self.save_id)
        except OSError as e:
            log("存档读取失败（%s）：%r —— 按空档继续" % (p, e))
            return empty_save(self.save_id)
        try:
            doc = json.loads(raw)
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or _as_int(doc.get("schema"), -1) != SAVE_SCHEMA:
            self._quarantine(p, "schema 或 JSON 不合法")
            return empty_save(self.save_id)
        doc.setdefault("save_id", self.save_id)
        doc["earned"] = _normalize_earned(doc)
        _normalize_identity(doc)
        return doc

    def _quarantine(self, p: Path, why: str) -> None:
        """把坏档挪走（保留现场供排查），绝不动其它文件。"""
        target = p.with_name("%s.corrupt-%s" % (self.save_id, time.strftime("%Y%m%d-%H%M%S")))
        try:
            p.replace(target)
            log("存档损坏（%s）：已备份为 %s，回退空档" % (why, target.name))
        except OSError as e:
            log("存档损坏（%s）且备份失败：%r" % (why, e))

    # ---- 写 --------------------------------------------------------
    def save(self, doc: dict) -> dict:
        """原子写；覆盖前把旧文件留成 .bak。返回落盘后的文档。"""
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        out = dict(doc or {})
        out["schema"] = SAVE_SCHEMA
        out["save_id"] = self.save_id
        out.setdefault("created_at", _now())
        out["updated_at"] = _now()
        out["earned"] = _normalize_earned(out)
        try:
            if p.exists():
                try:
                    p.replace(p.with_name(self.save_id + ".json.bak"))
                except OSError as e:      # 备份失败不阻断写入（只记日志）
                    log("存档 .bak 备份失败：%r" % e)
            tmp = p.with_name(self.save_id + ".json.tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, p)
            ident = out.get("identity") or {}
            write_last(self.save_id, ident.get("steam_id"), ident.get("hd2_account_id"),
                       root=self.root)
        except OSError as e:
            log("存档写入失败（%s）：%r" % (p, e))
        return out

    def update(self, mutate) -> dict:
        """读 → 改（mutate(doc) 就地修改）→ 写；返回新文档。"""
        doc = self.load()
        mutate(doc)
        return self.save(doc)

    def reset(self) -> dict:
        """清空成空档（旧文件留 .bak）。"""
        return self.save(empty_save(self.save_id))

    def set_catalog_build(self, build) -> dict:
        """记录本次目录对应的游戏 build（Progression/items 会随版本漂移，必须可追溯）。"""
        if build in (None, ""):
            return self.load()

        def _mut(doc):
            doc["catalog_build"] = str(build)
        return self.update(_mut)

    def record_catalog(self, items_body, client_version=None) -> dict:
        """用**注入前**的 ``/api/Progression/items`` 响应记录目录版本（sha8/行数/clientVersion）。"""
        info = catalog_build_id(items_body, client_version)
        if info["sha8"] and self.load().get("catalog_build") != info["value"]:
            self.set_catalog_build(info["value"])
        return info

    def bind_identity(self, hd2_account=None, steam_id=None, source=None) -> dict:
        """把后观测到的身份别名写进当前档（主键不变；20 位 HD2 id 只是别名）。"""
        return self.set_identity(hd2_account, steam_id, source=source)

    def set_identity(self, hd2_account=None, steam_id=None, source=None) -> dict:
        """记录身份别名 + **识别来源审计**（``source`` = getmotd / getmessages / adopted）。

        不影响 save_id（换档见 adopt_identity）。``identified_at`` 只记第一次
        「这份档认到身份」的时刻 —— 排查「这档是怎么来的」时这行最省时间（研究线建议）。
        """
        def _mut(doc):
            ident = doc.setdefault("identity", {})
            if hd2_account:
                ident["hd2_account_id"] = str(hd2_account)
            if steam_id:
                ident["steam_id"] = str(steam_id)
            if source:
                ident["source"] = str(source)
            if is_identified(doc) and not ident.get("identified_at"):
                ident["identified_at"] = _now()
        return self.update(_mut)

    def adopt_identity(self, *, hd2_account=None, steam_id=None, root=None):
        """见到真实身份后把当前档迁移/合并到身份档；返回身份档的 SaveStore。

        规则（研究线 2026-11-23 修订：**目标已存在也要合并**，绝不静默丢进度）：
          * 目标档不存在 → 把本档内容写过去；
          * 目标档已存在 → 本档 earned **合并进目标**（earned 取并 / 金额取大 / 集合取并）；
          * 合并后把本档文件归档成 ``<id>.merged-<ts>.json``（保留审计）；
          * 身份别名（HD2 id / SteamID64）写进目标档的 ``identity``。
        """
        target_id = save_id_for_identity(steam_id, hd2_account, root=root or self.root)
        target = SaveStore(target_id, root=root or self.root)
        mine = self.load()
        has_content = any(bool(v) for v in (mine.get("earned") or {}).values())
        if target_id == self.save_id:
            target.set_identity(hd2_account, steam_id, source="adopted")
            return target
        if target.path().exists():
            if has_content:
                theirs = target.load()
                theirs["earned"] = _merge_earned_into(theirs, mine)
                if mine.get("catalog_build") and not theirs.get("catalog_build"):
                    theirs["catalog_build"] = mine["catalog_build"]
                target.save(theirs)
        elif has_content:
            target.save(mine)
        target.set_identity(hd2_account, steam_id, source="adopted")
        if has_content:
            _archive_save(self, "merged")
        return target

    # ---- 便捷：累计「已获得」 --------------------------------------
    def add_experience(self, amount) -> dict:
        n = max(0, _as_int(amount))
        if not n:
            return self.load()

        def _mut(doc):
            e = doc["earned"]
            e["experience"] = _as_int(e.get("experience")) + n
        return self.update(_mut)

    def grant_items(self, amounts: dict | None = None, ids=None) -> dict:
        """把一批 mixId 记为「已获得」：``amounts`` 是绝对数量，``ids`` 只保证存在（amount≥1）。"""
        amounts = {str(k): max(0, _as_int(v)) for k, v in (amounts or {}).items()}

        def _mut(doc):
            e = doc["earned"]
            cur = e.setdefault("inventory_amounts", {})
            for mix, amount in amounts.items():
                if amount > _as_int(cur.get(mix)):
                    cur[mix] = amount
                elif mix not in cur:
                    cur[mix] = amount
            have = set(_as_int(x, -1) for x in e.setdefault("inventory_ids", []))
            for mix in ids or []:
                if _as_int(mix, -1) >= 0 and _as_int(mix) not in have:
                    e["inventory_ids"].append(_as_int(mix))
                    have.add(_as_int(mix))
        return self.update(_mut)


# --------------------------------------------------------------------------- #
# 合并（纯函数：吃 bytes / dict，吐 bytes + 改动数）
# --------------------------------------------------------------------------- #
def _decode(body):
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(bytes(body).decode("utf-8")), True
        except (ValueError, UnicodeDecodeError):
            return None, True
    if isinstance(body, str):
        try:
            return json.loads(body), True
        except ValueError:
            return None, True
    if isinstance(body, dict):
        return body, False
    return None, False


def _encode(doc, as_bytes: bool):
    text = json.dumps(doc, ensure_ascii=False)
    return text.encode("utf-8") if as_bytes else doc


def _merge_achievements(items: list, earned: dict) -> int:
    """按 id 合并成就累计值（取较大者）；``earned`` 形如 {str(id): value}。"""
    changed = 0
    by_id = {}
    for row in items:
        if isinstance(row, dict) and row.get("id") is not None:
            by_id[str(row["id"])] = row
            row["value"] = _as_int(row.get("value"))
    for key, value in (earned or {}).items():
        want = _as_int(value)
        row = by_id.get(str(key))
        if row is None:
            items.append({"id": _as_int(key), "value": want})
            changed += 1
        elif want > _as_int(row.get("value")):
            row["value"] = want
            changed += 1
    return changed


def _merge_package_progress(items: list, earned: dict) -> int:
    """按 id32 合并包进度：level/progress 取大，claimedLevels 取并集。"""
    changed = 0
    by_id = {}
    for row in items:
        if isinstance(row, dict) and row.get("id32") is not None:
            by_id[str(row["id32"])] = row
    for key, patch in (earned or {}).items():
        if not isinstance(patch, dict):
            continue
        row = by_id.get(str(key))
        if row is None:
            row = {"id32": _as_int(key), "level": 0, "progress": 0,
                   "sortOrder": 0, "claimedLevels": []}
            items.append(row)
            changed += 1
        level = _as_int(patch.get("level"))
        if level > _as_int(row.get("level")):
            row["level"] = level
            changed += 1
        progress = _as_int(patch.get("progress"))
        if progress > _as_int(row.get("progress")):
            row["progress"] = progress
            changed += 1
        claimed = row.get("claimedLevels")
        if not isinstance(claimed, list):
            claimed = row["claimedLevels"] = []
        for lv in _as_list(patch.get("claimedLevels")):
            lv = _as_int(lv, -1)
            if lv >= 0 and lv not in claimed:
                claimed.append(lv)
                changed += 1
    return changed


def apply_to_progression(body, save: dict, *, include_achievements: bool = True):
    """把存档的 earned 合并进 ``GET /api/Progression`` 响应体。返回 (新 body, 改动数)。

    ``include_achievements=False``：**身份未校验的预绑定首屏**用（``saves.preverify_merge=safe``）。
    成就与 Stats 是客户端会**回显上报**的字段：若把上一档的值合并给另一个账号看到，客户端会把
    这些"看到的数"加增量后 PUT 回来，被账本记成自己的成就（2026-11-23 ④ 换号实测）。
    经验/包进度/库存数量是服务端自算字段，回显不改变它们，可安全合并。
    """
    doc, as_bytes = _decode(body)
    if not isinstance(doc, dict):
        return body, 0
    earned = _normalize_earned(save or {})
    changed = 0

    exp = _as_int(earned.get("experience"))
    if exp > _as_int(doc.get("experience")):
        doc["experience"] = exp
        changed += 1

    flags = _as_int(earned.get("onboarding_flags"))
    if flags:
        merged = _as_int(doc.get("onboardingFlags")) | flags
        if merged != _as_int(doc.get("onboardingFlags")):
            doc["onboardingFlags"] = merged
            changed += 1

    state = _as_int(earned.get("onboarding_state"))
    if state > _as_int(doc.get("onboardingState")):
        doc["onboardingState"] = state
        changed += 1

    ship = earned.get("ship_name")
    if isinstance(ship, list) and ship and ship != doc.get("shipName"):
        doc["shipName"] = list(ship)
        changed += 1

    loc = earned.get("location")
    if isinstance(loc, dict) and loc and loc != doc.get("location"):
        doc["location"] = dict(loc)
        changed += 1

    # purchasedSeasonPassItems：并集（保持原顺序，新的追加）
    bought = _as_list(doc.get("purchasedSeasonPassItems"))
    have = set(_as_int(x, -1) for x in bought)
    added = 0
    for item in _as_list(earned.get("purchased_season_pass_items")):
        iid = _as_int(item, -1)
        if iid >= 0 and iid not in have:
            bought.append(iid)
            have.add(iid)
            added += 1
    if added:
        doc["purchasedSeasonPassItems"] = bought
        changed += added

    ach = doc.get("achievements")
    if include_achievements and isinstance(ach, list):
        changed += _merge_achievements(ach, earned.get("achievements"))

    pkg = doc.get("packageProgress")
    if isinstance(pkg, list):
        changed += _merge_package_progress(pkg, earned.get("package_progress"))

    if not changed:
        return body, 0
    return _encode(doc, as_bytes), changed


def apply_to_inventory(body, save: dict):
    """把存档的 earned 合并进 ``GET /api/Progression/inventory`` 响应体。

    **数量只抬不降**：``inventory_amounts`` 与响应里的 amount 取 **max**，
    绝不把服务端的数量改小。原因（2026-11-23 实机验收前复核）：
      * 本机账本只记录"经过存档层"的增量（结算奖励/消耗），**不知道玩家历史基线**；
      * 早期实现是"绝对值覆盖"，会把老玩家 5000 货币显示成"本局奖励那点"——解锁时直接被判余额不足；
      * 服务端仍是事实源：它给得更多就听它的；它给得更少（离线/私服/回滚）才用本机账本兜底。
    代价：纯本机消耗（服务端没扣）不会在界面上减数量——可接受，服务端真实扣减时它会跟着降。
    ``inventory_ids`` 只保证条目存在。返回 (新 body, 改动数)。
    """
    doc, as_bytes = _decode(body)
    if not isinstance(doc, dict):
        return body, 0
    items = doc.get("items")
    if items is None:
        items = []                       # 上游整份没给 items：视为空库存，账本兜底补行
        doc["items"] = items
    elif not isinstance(items, list):
        return body, 0
    earned = _normalize_earned(save or {})
    by_mix = {}
    for row in items:
        if isinstance(row, dict) and row.get("mixId") is not None:
            row["amount"] = _as_int(row.get("amount"))
            by_mix[_as_int(row["mixId"], -1)] = row

    changed = 0
    for key, value in (earned.get("inventory_amounts") or {}).items():
        mix = _as_int(key, -1)
        if mix < 0:
            continue
        ledger = max(0, _as_int(value))
        row = by_mix.get(mix)
        if row is None:
            items.append({"mixId": mix, "amount": ledger, "isDiscovered": False})
            changed += 1
        else:
            # 只抬不降：服务端数量更大时保留服务端的（历史基线我们不知道）
            amount = max(_as_int(row.get("amount")), ledger)
            if _as_int(row.get("amount")) != amount:
                row["amount"] = amount
                changed += 1
            else:
                continue
        by_mix[mix] = row

    for mix_raw in _as_list(earned.get("inventory_ids")):
        mix = _as_int(mix_raw, -1)
        if mix < 0 or mix in by_mix:
            continue
        items.append({"mixId": mix, "amount": 1, "isDiscovered": False})
        by_mix[mix] = items[-1]
        changed += 1

    if not changed:
        return body, 0
    return _encode(doc, as_bytes), changed
