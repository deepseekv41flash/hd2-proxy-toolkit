"""存档层底座（G1）：每玩家可持久化的「已获得」账本 + 合并到响应。

背景（交接档 `HANDOFF-SAVE-SYSTEM-TO-MITM-2026-11-23.md` §3 G1 / §4 S1）：

    base ⊕ config ⊕ earned

  * ``base``   = 服务端当前响应（官方/研究线 mock 返回的档案底子）；
  * ``config`` = 用户在 GUI 里勾的注入（仍在 profile 层，由现有 inventory/items 钩子负责）；
  * ``earned`` = 本存档累计的「已获得」事实账本（经验、成就、包进度、货币、已解锁物品…）。

本模块只负责 **earned 的持久化与合并语义**；把「哪种响应怎么改」留给 hooks（G2/G3）。

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
        "identity": {"hd2_account_id": None, "steam_id": None},
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
        },
    }


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

    # 预留复杂结构：较新的档为准，缺键补齐
    for key in ("stats", "season_pass", "assignments"):
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


def write_last(save_id, steam_id=None, hd2_account=None, root=None) -> dict:
    """原子更新 ``_last.json``；返回写入内容。"""
    base = _saves_root(root)
    base.mkdir(parents=True, exist_ok=True)
    doc = {
        "last_save_id": normal_save_id(save_id),
        "last_steam_id": str(steam_id) if steam_id else None,
        "last_hd2_account_id": str(hd2_account) if hd2_account else None,
        "updated_at": _now(),
    }
    p = base / LAST_FILE
    tmp = base / (LAST_FILE + ".tmp")
    try:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        log("_last.json 写入失败：%r" % e)
    return doc


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
        if name == LAST_FILE or name.endswith((".bak", ".tmp")) or ".merged-" in name                 or ".corrupt-" in name or ".archived-" in name:
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
    """把当前档回滚成 ``.bak``（会话前状态）；坏档先挪成 ``.rollback-<ts>.json`` 留审计。

    用于「同机换号」场景：本局对旧档的写入必须撤回，宁可丢窗口内少量写入也不混档。
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


def write_orphan(save_id, doc, root=None, reason: str = "dirty") -> str:
    """把「不属于任何现有玩家」的增量写入 ``_orphan/<ts>-<src>.json``，供人工处理。"""
    base = _saves_root(root) / "_orphan"
    base.mkdir(parents=True, exist_ok=True)
    name = "%s-%s-%s.json" % (time.strftime("%Y%m%d-%H%M%S"), normal_save_id(save_id), reason)
    p = base / name
    try:
        p.write_text(json.dumps(doc or {}, ensure_ascii=False, indent=1), encoding="utf-8")
        log("⚠ 存档增量已另存 orphan：%s（来源档 %s）" % (p, save_id))
        return str(p)
    except OSError as e:
        log("orphan 写入失败（%s）：%r" % (p, e))
        return ""


def switch_identity(store: "SaveStore", *, hd2_account=None, steam_id=None,
                    root=None) -> dict:
    """处理「GetMotd 与当前 activeSave 不一致」的切档，按研究线 2026-11-23 口径分流：

      * 旧档 ``local``/未识别 → **合并**进目标档（等价 adopt_identity）；
      * 旧档是另一个**已识别**档（同机换 Steam 号）→ **不合并**，只返回目标档；
        本局对旧档的写入由调用方（引擎）用 ``rollback_from_backup`` 撤回，
        并把增量 ``write_orphan`` 另存（引擎侧有 session_dirty 时才做）。

    返回 ``{"action": "same"|"merged"|"switched", "store": SaveStore,
             "old_identified": bool, "target_id": str}``。
    """
    base_root = root or store.root
    target_id = save_id_for_identity(steam_id, hd2_account, root=base_root)
    current = store.load()
    old_identified = is_identified(current)
    if target_id == store.save_id:
        target = store
        target.set_identity(hd2_account, steam_id)
        action = "same"
    elif not old_identified:
        target = store.adopt_identity(hd2_account=hd2_account, steam_id=steam_id,
                                      root=base_root)
        action = "merged"
    else:
        target = SaveStore(target_id, root=base_root)
        target.set_identity(hd2_account, steam_id)
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

    def bind_identity(self, hd2_account=None, steam_id=None) -> dict:
        """把后观测到的身份别名写进当前档（主键不变；20 位 HD2 id 只是别名）。"""
        return self.set_identity(hd2_account, steam_id)

    def set_identity(self, hd2_account=None, steam_id=None) -> dict:
        """记录身份别名（不影响 save_id；换档见 adopt_identity）。"""
        def _mut(doc):
            ident = doc.setdefault("identity", {})
            if hd2_account:
                ident["hd2_account_id"] = str(hd2_account)
            if steam_id:
                ident["steam_id"] = str(steam_id)
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
            target.set_identity(hd2_account, steam_id)
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
        target.set_identity(hd2_account, steam_id)
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


def apply_to_progression(body, save: dict):
    """把存档的 earned 合并进 ``GET /api/Progression`` 响应体。返回 (新 body, 改动数)。"""
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
    if isinstance(ach, list):
        changed += _merge_achievements(ach, earned.get("achievements"))

    pkg = doc.get("packageProgress")
    if isinstance(pkg, list):
        changed += _merge_package_progress(pkg, earned.get("package_progress"))

    if not changed:
        return body, 0
    return _encode(doc, as_bytes), changed


def apply_to_inventory(body, save: dict):
    """把存档的 earned 合并进 ``GET /api/Progression/inventory`` 响应体。

    ``inventory_amounts`` 是**绝对数量**（G5 的 consume 会把它减下去），这里直接覆盖；
    ``inventory_ids`` 只保证条目存在。返回 (新 body, 改动数)。
    """
    doc, as_bytes = _decode(body)
    if not isinstance(doc, dict):
        return body, 0
    items = doc.get("items")
    if not isinstance(items, list):
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
        amount = max(0, _as_int(value))
        row = by_mix.get(mix)
        if row is None:
            items.append({"mixId": mix, "amount": amount, "isDiscovered": False})
            changed += 1
        elif _as_int(row.get("amount")) != amount:
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
