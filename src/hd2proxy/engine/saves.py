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

import json
import os
import re
import time
from pathlib import Path

from . import paths
from .logutil import log

SAVE_SCHEMA = 1
DEFAULT_SAVE_ID = "local"
_SAVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


def empty_save(save_id=None) -> dict:
    """空档：等价于「空号基线 + 什么都没挣到」。"""
    sid = normal_save_id(save_id)
    now = _now()
    return {
        "schema": SAVE_SCHEMA,
        "save_id": sid,
        "created_at": now,
        "updated_at": now,
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
