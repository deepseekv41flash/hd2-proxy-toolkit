#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolve.py -- 从本机只读数据表解析《HELLDIVERS 2》服务端物品目录 3020 行的名字与类别含义。

WHY
    `GET /api/Progression/items` 抓包（build 26568081）只有 id（mixId/itemId/parentId/
    progressionCategory），没有名字。本脚本把目录行逐条去本机**只读**名字表里查名字：
    命中就写 name + name_source + confidence，查不到就 name=null（绝不编造/音译/按顺序猜）。
    同时给出每个 progressionCategory 的语义（只写有本机研究仓/表证据的；无证据整类留空）。

输入（全部只读，路径相对 --work-root，默认按脚本位置向上探测 <mod>/work）
    hd2-proxy-toolkit/data/sources/progression_item_catalog.json   3020 行权威行集（mix/item/cat/parent）
    hd2-proxy-toolkit/data/catalogs/items.json                     已有名字（优先级最高，不覆盖）
    hd2-proxy-toolkit/data/sources/item_names_derived.json         LoadoutEntry 内部名（itemId -> 名字）
    hd2-proxy-toolkit/data/sources/unreleased_items.json           未发布武器模板配对（**不作名字来源**，见下）
    hd2-proxy-toolkit/data/sources/fresh_account_inventory.json    空号默认拥有 55 项（只用于 coverage 对照）
    hd2-proxy-toolkit/data/legacy/stratagem_catalog.json           战备目录（effect_hash/native_hash -> 显示名）
    hd2-proxy-toolkit/data/catalogs/effects.json                   GWE 效果（target="stratagem:<名>" 且 values[0]=战备 hash）
    variant-net/refs/armor_rows_parsed.json                        外观表（行 id = 目录 itemId）
    variant-net/refs/store-cosmetics-20261106.json                 商店外观（id -> name/locids）
    repo-datamined/refs/weapon-customization-options-26251122.json  改装选项内部名（option_id 十六进制）
    repo-datamined/refs/boosters-26088801.json                     Booster 表（itemId -> name）

输出（默认写与脚本同目录的 resolved.json；可用 --out 指定，例如快照 resolved_v2.json）
    {note, build, rows[3020], category_meaning{cat: {label, zh, confidence, evidence}}, coverage{}, sources{}}

名字解析链（v1 直接映射 + v2 结构推断，前一级命中就不再往下走）
    v1（直接 id -> 名字）
      1. items.json（已有名字，不覆盖；mixId/itemId 精确；cat2 额外允许 optionId 精确）
      2. boosters（仅 cat5）
      3. armor-rows / store-cosmetics（仅 cat3/cat4）
      4. weapon-options（仅 cat2）
      5. loadout-entry（itemId 精确；cat1 同类别 high，其它类别 medium）
    v2（结构推断；只在上一级没名字/或 cat10 由战备名替换时生效；**不编造**，只做 id 空间/父子结构的等值推断）
      A. cat10：行 mixId=战备 effect_hash、itemId=native_hash（stratagem_catalog）或
         mixId=GWE effects 的 values_raw[0]（effects.json target="stratagem:<名>"）-> 战备显示名，
         name_source="stratagem-hash"，confidence=medium。
      B. cat11：目录里 108 条战备许可与 108 条 cat10 子行严格 1:1（每个 cat11 恰有 1 个子行），
         用子行的战备名命名 -> name_source="stratagem-permit-child"，confidence=medium。
      C. cat4：外观套装行若其 cat3 子行名字（casefold 归一）全部一致 -> 用子行显示名命名，
         >=2 个同名子行 confidence=medium、仅 1 个子行 confidence=low，
         name_source="armor-set-child"。

口径（重要）
    * 一条目录行只有「显式 id -> 名字」映射或上述等值结构推断才算命中；查不到就 name=null。
    * 跨类别同 id 命中（cat10 记账行 itemId 命中 cat1 武器 LoadoutEntry id）标 confidence=medium；
      v2 的 cat10 战备名优先于该 loadout 名（战备名才是这一行引用的外部实体显示名）。
    * `unreleased_items.json` 的 template 是「克隆哪条已有目录行」的模板 id，把它当名字会把
      已有武器错标成未发布武器，因此**不使用**（文件本身也声明 template 不是行名字）。
    * 「已有名字」不覆盖：items.json 里非空 name 永远排第一优先级。
    * category 语义只写本机证据（variant-net/docs/UNLOCK-MAP-2026-11-06.md 的实机类别注入台账 +
      API-ENDPOINTS 等）；没有语义证据的类别（如 cat16）保持 null，并写明「无证据」。

安全 / 可移植
    * 只读：只以读模式打开输入；除 --out 外不写任何文件；不写游戏目录、不写 <mod>/work。
    * 不联网：无网络调用、无第三方依赖（纯标准库）；不读抓包/运行时数据。
    * 确定性：无随机、无时间戳；缩进固定；输入内容的 sha256 写进 sources 便于追溯。
    * 路径：输入路径全部相对 --work-root 推导，可用 --work-root / --items / --out 覆盖，
      脚本内不写死任何绝对路径（默认可被放进产品仓 tools/resolve_catalog_names.py 直接复用）。

用法
    python resolve.py                                  # 按脚本位置自动探测 <mod>/work，输出同目录 resolved.json
    python resolve.py --work-root <mod>/work --out <out>/resolved_v2.json
    # 复现「集成前」来源归因：指向集成前 1950 条 items.json（目录产物里的 dist 副本）
    python resolve.py --items <mod>/work/hd2-proxy-toolkit/dist/hd2proxy/data/catalogs/items.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from collections import Counter, defaultdict

BUILD = "26568081"

# 相对 --work-root 的只读输入
REL = {
    "catalog": "hd2-proxy-toolkit/data/sources/progression_item_catalog.json",
    "items": "hd2-proxy-toolkit/data/catalogs/items.json",
    "item_names_derived": "hd2-proxy-toolkit/data/sources/item_names_derived.json",
    "unreleased_items": "hd2-proxy-toolkit/data/sources/unreleased_items.json",
    "fresh_account": "hd2-proxy-toolkit/data/sources/fresh_account_inventory.json",
    "stratagem_catalog": "hd2-proxy-toolkit/data/legacy/stratagem_catalog.json",
    "effects": "hd2-proxy-toolkit/data/catalogs/effects.json",
    "armor_rows": "variant-net/refs/armor_rows_parsed.json",
    "store_cosmetics": "variant-net/refs/store-cosmetics-20261106.json",
    "weapon_options": "repo-datamined/refs/weapon-customization-options-26251122.json",
    "boosters": "repo-datamined/refs/boosters-26088801.json",
}

# 服务端 progressionCategory -> 语义。
# 证据来源（本机只读）：variant-net/docs/UNLOCK-MAP-2026-11-06.md §9/§10（类别注入台账，实机轮次 R1-R11）、
# variant-net/docs/API-ENDPOINTS-2026-11-01.md（cat2/cat3/cat11/cat18 的行结构）。
# label 只取外接生成器认的枚举 weapon|attachment|cosmetic|stratagem|booster|banner|currency；
# 枚举里没有的语义（warbond/emote/pose/记账类等）label 留 null，语义写 zh/evidence，避免硬凑。
CATEGORY_MEANING: dict[str, dict] = {
    "0": {
        "label": None,
        "zh": "战团（Warbond）相关条目（含战团解锁/记账条目集合，行级不统一）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP-2026-11-06.md §10.2 R7 实机：注入 cat0 全部 119 条未拥有项后用户回报"
            "『全部 Warbond 解锁』（内容仍需奖章购买），§10.3 定名 Warbond。"
            "目录 173 行 ≠ 本机 SeasonPass 抓包里的 26 个战团 id，故该类别是战团相关的条目集合"
            "（战团购买/代币/记账行），不能把每行都当战团本体。"
        ),
    },
    "1": {
        "label": "weapon",
        "zh": "武器/可装备装备（LoadoutEntry 类：主武器/副武器/投掷物/支援装备）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.3：cat1 = 武器（早前实机 ✓✓）。"
            "结构佐证：cat2 附件行 1455/1455 的 parentId 指向 cat1 行；"
            "item_names_derived 的 LoadoutEntry itemId 命中 cat1 的 107 行，名字正是武器/投掷物内部名。"
        ),
    },
    "2": {
        "label": "attachment",
        "zh": "武器附件/改装选项（每行 = 某把武器 + 某个 optionId 的库存键）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.3：cat2 = 武器附件（实机 ✓✓）；API-ENDPOINTS §7 记录"
            "『progressionCategory==2 且带 parentId 的记录就是附件解锁行』。"
            "结构佐证：1455 行全部带 parentId 且 parent 都是 cat1；行 itemId = 改装选项 id"
            "（weapon-customization-options 表命中 1404 行）。"
        ),
    },
    "3": {
        "label": "cosmetic",
        "zh": "外观（护甲/头盔/披风等可购买外观件）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §8 实机：超级商店真购买护甲/头盔/披风各 1 件，三件在目录里都是 cat3，"
            "注入未拥有 cat3 也在军械库出现且可装备（§10.3 记『外观（护甲/头盔/披风）』✓✓）；"
            "API-ENDPOINTS §9 同结论。结构佐证：外观表 armor_rows_parsed 行 id 命中 cat3 的 367 行。"
        ),
    },
    "4": {
        "label": "cosmetic",
        "zh": "外观套装/涂装组（载具涂装选项；也是 cat3 外观件的 parent 套装行）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.2 R6 实机：注入 cat4 全部 166 条未拥有项后用户确认解锁『载具涂装选项』；"
            "结构佐证：272 条 cat3 外观行的 parentId 指向 cat4 行，store-cosmetics 已证 3622341476 行"
            "是 DP-8 护甲套装行 —— 故该类别同时包含『可见的载具涂装选项』与『外观件所属套装』，"
            "注入可见效果已实机，行级组成仍需更细拆分，故 confidence=medium。"
        ),
    },
    "5": {
        "label": "booster",
        "zh": "Booster（配装增益）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R2 实机：注入 cat5 全部 13 条未拥有项 = Booster（用户确认）；"
            "§10.3 定名 Booster。结构佐证：boosters-26088801.json 的 21 行 itemId 命中目录 cat5 的 20 行。"
        ),
    },
    "6": {
        "label": None,
        "zh": "记账/占位条目（注入无任何 UI 可见变化；具体用途未定）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R8 实机：注入 cat6 全部 23 条未拥有项 → 无可见变化；"
            "§10.3 归为『记账/占位（无 UI）』。"
        ),
    },
    "7": {
        "label": "cosmetic",
        "zh": "Emote（动作/表情）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R5 实机：注入 cat7 全部 8 条未拥有项 → 出现新动作/表情（用户确认 Emote；"
            "并补充姿势与 Emote 有共用项）。枚举无 emote，label 归 cosmetic 属归类判断，语义以 zh 为准。"
        ),
    },
    "8": {
        "label": "cosmetic",
        "zh": "VICTORY POSE（胜利姿势）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R3 实机：注入 cat8 全部 8 条未拥有项 → 用户确认胜利姿势；"
            "§10.1 并更正旧结论（可解锁的姿势在 cat8）。枚举无 pose，label 归 cosmetic 属归类判断。"
        ),
    },
    "9": {
        "label": "banner",
        "zh": "横幅（Banner）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.1/§10.3：cat9 = 横幅；该类别未做全量注入实机（§10.3 标『未测』），"
            "故只有文档语义证据，无实机证据，confidence=medium。"
        ),
    },
    "10": {
        "label": None,
        "zh": "战备许可（cat11）下的子项/记账行（UI 不可见；子项语义未单独验证）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.2 R1 实机：注入 cat10 全部 108 条未拥有项 → 无可见 UI 变化；"
            "结构：111 行里 108 行 parentId 指向 cat11（战备许可）行，§10.2 推测为战备许可的子项"
            "（变体/弹药/升级），但『子项』含义未单独验证 ⇒ 只对『UI 不可见』给高置信，语义给 medium。"
        ),
    },
    "11": {
        "label": "stratagem",
        "zh": "战备许可（Stratagem Permit，正式名 permit；拥有它战备才可选）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §9 实机（2026-11-06 20:44）：注入 30 条 cat11 → 军械库多出约 30 个战备、"
            "全部可用，含未发布 ORBITAL CONFETTI / ORBITAL WALKING BARRAGE SMOKE；§9.1/§10.3 定名"
            "『战备许可』。尚未解出 cat11 id↔战备名的对应表（§9.4），故本类别行仍无名字。"
        ),
    },
    "13": {
        "label": None,
        "zh": "语音包（Voice Pack）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.1/§10.3：cat13 = 语音包；§10.2 R11 把 15+13+14+17 合并注入后无可见变化，"
            "未单独验证 ⇒ 语义来自研究仓文档，confidence=medium。"
        ),
    },
    "14": {
        "label": None,
        "zh": None,
        "confidence": "none",
        "evidence": (
            "无证据：UNLOCK-MAP §10.1/§10.3 对 cat14 只写『未知』；R11 合并注入无差异；"
            "只读输入表里也没有该类别的名字/结构线索。"
        ),
    },
    "15": {
        "label": None,
        "zh": "资源类条目（注入无 UI 可见变化；具体用途未定）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.1/§10.3 记 cat15 为『资源类』；§10.2 R11 合并注入无可见变化。"
            "该类只有文档『资源类』这一条弱语义，未单独实机，confidence=medium。"
        ),
    },
    "16": {
        "label": None,
        "zh": None,
        "confidence": "none",
        "evidence": (
            "无证据：UNLOCK-MAP 类别台账（§10.1/§10.3）没有 cat16 条目，API/表结构文档也没有该类别语义；"
            "只读输入表里 9 行 mix==item、无 parent、无字段，不足以定名，故整类留空。"
        ),
    },
    "17": {
        "label": None,
        "zh": "内衬（Under-suit 类）",
        "confidence": "low",
        "evidence": (
            "UNLOCK-MAP §10.1/§10.3 记 cat17 = 内衬（仅 2 行）；§10.2 R11 合并注入无差异，"
            "未单独验证 ⇒ 只有文档一句语义，confidence=low。"
        ),
    },
    "18": {
        "label": "currency",
        "zh": "货币（Requisition / Super Credits / Medals 等游戏内货币）",
        "confidence": "high",
        "evidence": (
            "API-ENDPOINTS-2026-11-01.md §8 实测：Requisition 行 `progressionCategory 18`+`isConsumable`；"
            "超级商店扣费的两条混合货币同样 `progressionCategory 18`；"
            "UNLOCK-MAP §10.1/§10.3 亦记 cat18 = 货币。"
        ),
    },
    "19": {
        "label": None,
        "zh": "记账条目（注入无 UI 可见变化；具体用途未定）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R9 实机：注入 cat19 全部 19 条未拥有项 → 无差异；§10.3 归为记账（无 UI）。"
        ),
    },
    "20": {
        "label": None,
        "zh": "记账条目（注入无 UI 可见变化；曾假设等级奖励，未获 UI 证据）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R10 实机：注入 cat20 全部 6 条未拥有项 → 无差异；"
            "§10.3 归为记账（无 UI），等级奖励假设未获 UI 证据。"
        ),
    },
    "21": {
        "label": None,
        "zh": "记账条目（注入无 UI 可见变化；具体用途未定）",
        "confidence": "high",
        "evidence": (
            "UNLOCK-MAP §10.2 R4 实机：注入 cat21 全部 32 条未拥有项 → 无变化；§10.3 归为记账（无 UI）。"
        ),
    },
    "23": {
        "label": None,
        "zh": "称号（Title）",
        "confidence": "medium",
        "evidence": (
            "UNLOCK-MAP §10.1/§10.3：cat23 = 称号；该类别未实测（§10.3 标『未测』），"
            "只有文档语义证据，confidence=medium。"
        ),
    },
}


class SourceError(Exception):
    """输入缺失 / 结构不符预期。"""


# ---------------------------------------------------------------- 通用工具


def log(msg: str) -> None:
    print(f"[resolve] {msg}")


def load_json(path: pathlib.Path, what: str):
    if not path.is_file():
        raise SourceError(f"缺少{what}: {path}")
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def to_int(value, where: str):
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SourceError(f"{where}: 期望整数，实际 {value!r}") from exc


def norm_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def first(items) -> str | None:
    for item in items or ():
        if item:
            return item
    return None


def pick_display(candidates) -> str | None:
    """同名多个写法时优先 Title-Case（含小写字母）的那一个，否则取第一个。"""
    cleaned = [c for c in candidates if isinstance(c, str) and c.strip()]
    for name in cleaned:
        if any(ch.islower() for ch in name):
            return name.strip()
    return cleaned[0].strip() if cleaned else None


# ---------------------------------------------------------------- 名字源加载


def load_items_names(path: pathlib.Path):
    """items.json：已有名字（最高优先级）。按 mix/item/option 三个键建索引。

    返回 (by_mix, by_item, by_opt)，每个 bucket 的 value 是 [(name, catalog_category), ...]。
    """
    doc = load_json(path, "items.json")
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise SourceError("items.json 结构异常：缺少 items[]")
    by_mix: dict[int, list[tuple[str, int | None]]] = defaultdict(list)
    by_item: dict[int, list[tuple[str, int | None]]] = defaultdict(list)
    by_opt: dict[int, list[tuple[str, int | None]]] = defaultdict(list)
    for entry in doc["items"]:
        if not isinstance(entry, dict):
            continue
        name = norm_name(entry.get("name"))
        if not name:
            continue  # 只有名字非空的条目才参与「已有名字」优先链
        cc = entry.get("catalog_category")
        cc = int(cc) if isinstance(cc, int) else None
        for field, bucket in (("mix_id", by_mix), ("item_id", by_item), ("option_id", by_opt)):
            value = entry.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                bucket[value].append((name, cc))
    log(
        f"items.json: 有名字的条目 {sum(len(v) for v in by_mix.values())} 个 mix 键 / "
        f"{len(by_item)} 个 item 键 / {len(by_opt)} 个 option 键"
    )
    return by_mix, by_item, by_opt


def load_loadout_names(path: pathlib.Path):
    """item_names_derived.json：LoadoutEntry itemId -> 实体内部名。"""
    doc = load_json(path, "item_names_derived.json")
    items = ((doc.get("loadout_entry") or {}).get("items")) if isinstance(doc, dict) else None
    if not isinstance(items, dict):
        raise SourceError("item_names_derived.json 结构异常：缺少 loadout_entry.items")
    out: dict[int, str] = {}
    for key, value in items.items():
        name = norm_name((value or {}).get("name")) if isinstance(value, dict) else None
        if not name:
            continue
        try:
            out[int(key)] = name
        except (TypeError, ValueError):
            continue
    log(f"item_names_derived: {len(out)} 个 LoadoutEntry id -> 内部名")
    return out


def load_armor_names(path: pathlib.Path):
    """armor_rows_parsed.json：外观表行 id -> 显示名（names 里优先 Title-Case 变体）。"""
    doc = load_json(path, "armor_rows_parsed.json")
    if not isinstance(doc, list):
        raise SourceError("armor_rows_parsed.json 结构异常：顶层应为数组")
    out: dict[int, str] = {}
    for row in doc:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id")
        if not isinstance(row_id, int):
            continue
        names = [pair[1] for pair in (row.get("names") or []) if isinstance(pair, (list, tuple)) and len(pair) > 1]
        name = pick_display(names)
        if name:
            out.setdefault(row_id, name)
    log(f"armor_rows_parsed: {len(out)} 个行 id -> 外观名")
    return out


def load_store_cosmetics(path: pathlib.Path):
    """store-cosmetics-20261106.json：{id: {name, locids}} -> 显示名。"""
    doc = load_json(path, "store-cosmetics-20261106.json")
    if not isinstance(doc, dict):
        raise SourceError("store-cosmetics-20261106.json 结构异常：顶层应为对象")
    out: dict[int, str] = {}
    for key, value in doc.items():
        if not isinstance(value, dict):
            continue
        try:
            item_id = int(key)
        except (TypeError, ValueError):
            continue
        name = norm_name(value.get("name"))
        if not name:
            names = [pair[1] for pair in (value.get("locids") or []) if isinstance(pair, (list, tuple)) and len(pair) > 1]
            name = pick_display(names)
        if name:
            out[item_id] = name
    log(f"store-cosmetics: {len(out)} 个 id -> 商店外观名")
    return out


def load_weapon_options(path: pathlib.Path):
    """weapon-customization-options：option_id(hex) -> 改装选项内部名。"""
    doc = load_json(path, "weapon-customization-options-26251122.json")
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise SourceError("weapon-customization-options 结构异常：缺少 items[]")
    out: dict[int, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = norm_name(entry.get("name"))
        raw = entry.get("option_id")
        if not name or not isinstance(raw, str):
            continue
        try:
            out[int(raw, 16)] = name
        except ValueError:
            continue
    log(f"weapon-customization-options: {len(out)} 个 optionId -> 内部名")
    return out


def load_boosters(path: pathlib.Path):
    """boosters-26088801.json：booster 行 itemId -> 名字。"""
    doc = load_json(path, "boosters-26088801.json")
    rows = doc.get("boosters") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise SourceError("boosters 结构异常：缺少 boosters[]")
    out: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = norm_name(row.get("name"))
        item_id = row.get("itemId")
        if name and isinstance(item_id, int):
            out[item_id] = name
    log(f"boosters: {len(out)} 个 itemId -> Booster 名")
    return out


def load_stratagem_hashes(path: pathlib.Path):
    """stratagem_catalog.json：战备的 (effect_hash, native_hash) -> 显示名（v2 cat10 用）。

    目录 cat10 行实测：mixId = 战备 effect_hash、itemId = native_hash
    （58/111 行与 catalog 里 58 条战备精确相等，见 report §9.1）。只收两个 hash 都齐的条目。
    """
    doc = load_json(path, "stratagem_catalog.json")
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise SourceError("stratagem_catalog.json 结构异常：缺少 items[]")
    by_pair: dict[tuple[int, int], str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = norm_name(entry.get("name"))
        raw_effect, raw_native = entry.get("effect_hash"), entry.get("native_hash")
        if not name or not isinstance(raw_effect, str) or not isinstance(raw_native, str):
            continue
        try:
            by_pair[(int(raw_effect, 16), int(raw_native, 16))] = name
        except ValueError:
            continue
    log(f"stratagem_catalog: {len(by_pair)} 个 (effect_hash,native_hash) -> 战备名")
    return by_pair


def load_effect_stratagem_targets(path: pathlib.Path):
    """effects.json：GWE effect 的 values_raw[0]（= 战备 hash）-> target 里的战备显示名（v2 cat10 用）。"""
    doc = load_json(path, "effects.json")
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise SourceError("effects.json 结构异常：缺少 items[]")
    out: dict[int, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target") or ""
        if not isinstance(target, str) or not target.startswith("stratagem:"):
            continue
        name = norm_name(target.split(":", 1)[1])
        raw_values = entry.get("values_raw") or ""
        if not name or not isinstance(raw_values, str):
            continue
        try:
            value = int(raw_values.split(",", 1)[0].strip())
        except ValueError:
            continue
        out.setdefault(value, name)
    log(f"effects.json: {len(out)} 个 values[0] -> 战备名（GWE target=stratagem:*）")
    return out


def load_fresh_account(path: pathlib.Path):
    """空号默认拥有 55 项（只做 coverage 对照，不参与命名）。"""
    doc = load_json(path, "fresh_account_inventory.json")
    raw = doc.get("mix_ids") if isinstance(doc, dict) else None
    if not isinstance(raw, list):
        raise SourceError("fresh_account_inventory.json 结构异常：缺少 mix_ids[]")
    out = set()
    for value in raw:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    log(f"fresh_account_inventory: {len(out)} 个默认拥有 mixId")
    return out


# ---------------------------------------------------------------- 逐行解析


def resolve(rows, items_names, loadout_names, armor_names, store_names, option_names,
            booster_names, stratagem_pairs, effect_targets):
    """逐行解析名字。返回 rows_out, stats。

    v1 直接映射优先级（高 -> 低）：
      1. items.json（已有名字，不覆盖；cat2 额外允许 optionId 精确匹配）
      2. boosters（仅 cat5）
      3. armor-rows / store-cosmetics（仅 cat3/cat4）
      4. weapon-options（仅 cat2）
      5. loadout-entry（cat1 高置信；其它类别按『跨表同 id 引用』记 medium）
    v2 结构推断（只补空位 / 只改 cat10 的 loadout 名，不动 items.json 名字）：
      A. cat10：mixId=战备 effect_hash、itemId=native_hash，或 mixId=GWE values[0] -> 战备显示名
      B. cat11：108 条许可与 108 条 cat10 子行严格 1:1 -> 用子行战备名
      C. cat4：外观套装行的 cat3 子行名字归一后一致 -> 用子行名（>=2 子行 medium、1 子行 low）
    """
    by_mix, by_item, by_opt = items_names
    rows_out = []
    source_counter: Counter[str] = Counter()
    by_cat_rows: Counter[int] = Counter()
    by_cat_named: Counter[int] = Counter()
    by_cat_sources: dict[int, Counter[str]] = defaultdict(Counter)
    unresolved_by_cat: dict[int, list[int]] = defaultdict(list)
    items_json_named = 0
    items_json_hit = 0

    for row in rows:
        mix = to_int(row.get("mix"), "catalog rows[].mix")
        item = to_int(row.get("item"), "catalog rows[].item")
        cat = to_int(row.get("cat"), "catalog rows[].cat")
        parent = row.get("parent")
        parent = int(parent) if parent is not None else None
        by_cat_rows[cat] += 1

        name = None
        source = None
        confidence = None
        items_json_hit_row = False

        # 1) items.json：mix 精确 -> item 精确（cat2 走 optionId）
        for candidate_name, entry_cc in by_mix.get(mix) or ():
            items_json_hit_row = True
            name, source, confidence = candidate_name, "items.json", "high"
            break
        if not name:
            if cat == 2:
                for candidate_name, _ in by_opt.get(item) or ():
                    items_json_hit_row = True
                    name, source, confidence = candidate_name, "items.json", "high"
                    break
            else:
                for candidate_name, entry_cc in by_item.get(item) or ():
                    items_json_hit_row = True
                    # 条目带类别且与目录行类别不同 => 跨类别同 id 引用 -> medium；
                    # 条目没带类别（旧版/目录外条目）不构成「类别不同」的证据 -> high
                    confidence = "medium" if entry_cc is not None and entry_cc != cat else "high"
                    name, source = candidate_name, "items.json"
                    break
        if name:
            items_json_named += 1
        if items_json_hit_row:
            items_json_hit += 1

        # 2) boosters（仅 cat5）
        if not name and cat == 5:
            candidate = booster_names.get(item) or booster_names.get(mix)
            if candidate:
                name, source, confidence = candidate, "boosters", "high"

        # 3) 外观表 / 商店外观（仅 cat3/cat4）
        if not name and cat in (3, 4):
            candidate = armor_names.get(item) or armor_names.get(mix)
            if candidate:
                name, source, confidence = candidate, "armor-rows", "high"
            else:
                candidate = store_names.get(item) or store_names.get(mix)
                if candidate:
                    name, source, confidence = candidate, "store-cosmetics", "high"

        # 4) 改装选项内部名（仅 cat2：目录 cat2 行的 itemId 就是 optionId）
        if not name and cat == 2:
            candidate = option_names.get(item)
            if candidate:
                name, source, confidence = candidate, "weapon-options", "high"

        # 5) LoadoutEntry 内部名（itemId 精确；cat1 是同一类别 -> high，其它类别 -> medium）
        if not name:
            candidate = loadout_names.get(item)
            if candidate:
                name, source = candidate, "loadout-entry"
                confidence = "high" if cat == 1 else "medium"

        rows_out.append(
            {
                "mix": mix,
                "item": item,
                "cat": cat,
                "parent": parent,
                "name": name,
                "name_source": source,
                "confidence": confidence,
            }
        )
        if name:
            by_cat_named[cat] += 1
            source_counter[source] += 1
            by_cat_sources[cat][source] += 1
        else:
            unresolved_by_cat[cat].append(mix)

    # ---------------- v2：结构推断（只补空位；cat10 的战备名替换 loadout 内部名） ----------------
    named_before_v2 = sum(1 for row in rows_out if row["name"])
    batch2 = {
        "cat10_stratagem_new": 0,      # cat10 原来无名、被战备名补上
        "cat10_loadout_replaced": 0,   # cat10 原有 loadout 内部名、被战备显示名替换
        "cat10_kept_loadout": 0,       # cat10 有 loadout 名但战备 hash 未命中，保留
        "cat11_permit_child": 0,       # cat11 用 1:1 子行战备名
        "cat4_set_medium": 0,          # cat4 套装名（>=2 个同名子行）
        "cat4_set_low": 0,             # cat4 套装名（仅 1 个子行）
    }

    # A. cat10：战备显示名优先于 loadout-entry 内部名（items.json 名字不动）
    cat10_final: dict[int, str] = {}
    for row in rows_out:
        if row["cat"] != 10:
            continue
        stratagem_name = stratagem_pairs.get((row["mix"], row["item"])) or effect_targets.get(row["mix"])
        if stratagem_name:
            if row["name_source"] == "items.json":
                continue  # 理论上不会发生；防御性保留已有名字
            if row["name"]:
                if row["name"] != stratagem_name:
                    batch2["cat10_loadout_replaced"] += 1
            else:
                batch2["cat10_stratagem_new"] += 1
            row["name"] = stratagem_name
            row["name_source"] = "stratagem-hash"
            row["confidence"] = "medium"
            cat10_final[row["mix"]] = stratagem_name
        elif row["name"]:
            cat10_final[row["mix"]] = row["name"]
            batch2["cat10_kept_loadout"] += 1

    # B. cat11：许可与其 cat10 子行严格 1:1 -> 用子行名字
    child_name: dict[int, str] = {}
    for row in rows_out:
        if row["cat"] == 10 and row["parent"] is not None:
            name = cat10_final.get(row["mix"])
            if name:
                child_name[row["parent"]] = name
    for row in rows_out:
        if row["cat"] != 11 or row["name"]:
            continue
        name = child_name.get(row["mix"])
        if name:
            row["name"] = name
            row["name_source"] = "stratagem-permit-child"
            row["confidence"] = "medium"
            batch2["cat11_permit_child"] += 1

    # C. cat4：外观套装行名 = 其 cat3 子行的显示名（子行名 casefold 归一后必须一致）
    armor_children: dict[int, list[dict]] = defaultdict(list)
    for row in rows_out:
        if row["cat"] == 3 and row["parent"] is not None:
            armor_children[row["parent"]].append(row)
    for row in rows_out:
        if row["cat"] != 4 or row["name"]:
            continue
        named_children = [child["name"] for child in armor_children.get(row["mix"], []) if child["name"]]
        if not named_children:
            continue
        if len({name.strip().casefold() for name in named_children}) != 1:
            continue  # 子行名字不唯一 -> 不猜
        variants = sorted(set(named_children))
        display = next((v for v in variants if any(ch.islower() for ch in v)), variants[0])
        row["name"] = display
        row["name_source"] = "armor-set-child"
        if len(named_children) >= 2:
            row["confidence"] = "medium"
            batch2["cat4_set_medium"] += 1
        else:
            row["confidence"] = "low"
            batch2["cat4_set_low"] += 1

    # v2 改变了名字/来源分布，重新统计
    source_counter = Counter()
    by_cat_named = Counter()
    by_cat_sources = defaultdict(Counter)
    unresolved_by_cat = defaultdict(list)
    for row in rows_out:
        if row["name"]:
            by_cat_named[row["cat"]] += 1
            source_counter[row["name_source"]] += 1
            by_cat_sources[row["cat"]][row["name_source"]] += 1
        else:
            unresolved_by_cat[row["cat"]].append(row["mix"])

    stats = {
        "total": len(rows),
        "named": sum(by_cat_named.values()),
        "by_cat_rows": by_cat_rows,
        "by_cat_named": by_cat_named,
        "by_cat_sources": by_cat_sources,
        "unresolved_by_cat": unresolved_by_cat,
        "source_counter": source_counter,
        "items_json_named": items_json_named,
        "items_json_hit": items_json_hit,
        "named_before_v2": named_before_v2,
        "batch2": batch2,
    }
    return rows_out, stats


def build_coverage(rows_out, stats, fresh):
    by_cat = {}
    for cat in sorted(stats["by_cat_rows"]):
        by_cat[str(cat)] = {
            "rows": stats["by_cat_rows"][cat],
            "named": stats["by_cat_named"].get(cat, 0),
            "unresolved": stats["by_cat_rows"][cat] - stats["by_cat_named"].get(cat, 0),
            "sources": dict(sorted(stats["by_cat_sources"].get(cat, Counter()).items())),
        }
    by_source = dict(sorted(stats["source_counter"].items()))
    default_owned_by_cat: Counter[int] = Counter()
    default_owned_named_by_cat: Counter[int] = Counter()
    fresh_cats = Counter()
    for row in rows_out:
        if row["mix"] in fresh:
            fresh_cats[row["cat"]] += 1
            default_owned_by_cat[row["cat"]] += 1
            if row["name"]:
                default_owned_named_by_cat[row["cat"]] += 1
    coverage = {
        "total": stats["total"],
        "named": stats["named"],
        "unresolved": stats["total"] - stats["named"],
        "by_cat": by_cat,
        "by_source": by_source,
        "v2_inference": {
            "note": (
                "第二批结构推断（cat10/cat11 战备 hash、cat4 套装名=同名子行）；"
                "named_before 是仅 v1 直接映射时的命名行数（对集成前 items.json 输入 = 1932）"
            ),
            "named_before": stats["named_before_v2"],
            "named_after": stats["named"],
            "delta": stats["named"] - stats["named_before_v2"],
            "breakdown": stats["batch2"],
        },
        "baseline": {
            "items_json_named_rows": stats["items_json_named"],
            "items_json_hit_rows": stats["items_json_hit"],
            "lead_reference_1908": {
                "value": 1908,
                "meaning": (
                    "任务书里的『现状 1908』复核为**旧版 items.json（1950 条）的目录行覆盖率**："
                    "按 mixId 或 itemId 命中（cat2 另加 optionId）即算覆盖，含名字为空的条目；"
                    "同一版 items.json 的『已命名』行数是 1794。两者不是同一口径。"
                ),
            },
            "delta_vs_items_json_named": stats["named"] - stats["items_json_named"],
            "delta_vs_1908_coverage": stats["named"] - 1908,
        },
        "default_owned": {
            "note": "空号（未解锁任何东西）默认拥有的 55 个 mixId 在各目录类别的分布（只作类别对照，不参与命名）",
            "count": sum(fresh_cats.values()),
            "by_cat": {str(c): fresh_cats[c] for c in sorted(fresh_cats)},
            "named_by_cat": {str(c): default_owned_named_by_cat[c] for c in sorted(fresh_cats)},
        },
    }
    return coverage


# ---------------------------------------------------------------- main


def default_work_root() -> pathlib.Path:
    """按脚本位置向上探测 <mod>/work（不写死绝对路径）。

    兼容两种落点：
      * 快照目录 <mod>/tmp/catalog-names/  -> <mod>/work
      * 产品仓 <mod>/work/hd2-proxy-toolkit/tools/ -> <mod>/work
    判定依据：某目录下存在 `hd2-proxy-toolkit/data/sources/progression_item_catalog.json`
    （即该目录本身就是 work 根），或存在 `work/hd2-proxy-toolkit/data/sources/progression_item_catalog.json`
    （即该目录是 <mod>）。
    """
    catalog_rel = pathlib.Path("hd2-proxy-toolkit/data/sources/progression_item_catalog.json")
    start = pathlib.Path(__file__).resolve().parent
    for candidate in [start] + list(start.parents):
        if (candidate / catalog_rel).is_file():
            return candidate
        if (candidate / "work" / catalog_rel).is_file():
            return candidate / "work"
    # 兜底：保持旧约定 <mod>/tmp/<x>/ -> <mod>/work（探测不到时由 main 报错提示 --work-root）
    return start.parents[2] / "work"


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="只读解析 HD2 服务端物品目录 3020 行的名字与类别含义")
    parser.add_argument("--work-root", type=pathlib.Path, default=None,
                        help="只读数据根目录（默认按脚本位置推导 <mod>/work）")
    parser.add_argument("--items", type=pathlib.Path, default=None,
                        help="覆盖 items.json 路径（复现本快照请指向集成前的 1950 条版本，"
                             "例如 hd2-proxy-toolkit/dist/hd2proxy/data/catalogs/items.json）")
    parser.add_argument("--out", type=pathlib.Path, default=None,
                        help="输出 resolved.json（默认与脚本同目录）")
    args = parser.parse_args(argv)

    work_root = (args.work_root or default_work_root()).resolve()
    out_path = (args.out or pathlib.Path(__file__).resolve().parent / "resolved.json").resolve()
    if not work_root.is_dir():
        raise SourceError(f"--work-root 不存在: {work_root}")

    paths = {key: work_root / rel for key, rel in REL.items()}
    if args.items is not None:  # 复现快照时允许指定集成前的 items.json
        paths["items"] = args.items.resolve()
    log(f"work-root = {work_root}")

    catalog = load_json(paths["catalog"], "progression_item_catalog.json")
    rows = catalog.get("rows") if isinstance(catalog, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SourceError("progression_item_catalog.json 结构异常：缺少非空 rows[]")
    log(f"目录行 {len(rows)} 行（cat 分布见 coverage.by_cat）")

    items_names = load_items_names(paths["items"])
    loadout_names = load_loadout_names(paths["item_names_derived"])
    armor_names = load_armor_names(paths["armor_rows"])
    store_names = load_store_cosmetics(paths["store_cosmetics"])
    option_names = load_weapon_options(paths["weapon_options"])
    booster_names = load_boosters(paths["boosters"])
    stratagem_pairs = load_stratagem_hashes(paths["stratagem_catalog"])
    effect_targets = load_effect_stratagem_targets(paths["effects"])
    fresh = load_fresh_account(paths["fresh_account"])
    # unreleased_items 只校验存在性：它是「克隆模板」配对，不是名字来源（见脚本 docstring 口径）
    load_json(paths["unreleased_items"], "unreleased_items.json")

    rows_out, stats = resolve(
        rows, items_names, loadout_names, armor_names, store_names, option_names,
        booster_names, stratagem_pairs, effect_targets,
    )
    coverage = build_coverage(rows_out, stats, fresh)

    # ---- 自检：数字必须自洽（失败即抛错，不产出半成品）
    assert len(rows_out) == len(rows), "输出行数与输入行数不一致"
    assert sum(v["rows"] for v in coverage["by_cat"].values()) == coverage["total"], "by_cat.rows 合计 != total"
    assert sum(v["named"] for v in coverage["by_cat"].values()) == coverage["named"], "by_cat.named 合计 != named"
    assert sum(coverage["by_source"].values()) == coverage["named"], "by_source 合计 != named"
    assert coverage["named"] + coverage["unresolved"] == coverage["total"], "named+unresolved != total"
    for row in rows_out:
        assert row["name"] is None or row["name_source"], f"有名字但无来源: {row}"
        assert row["confidence"] in (None, "high", "medium", "low"), f"非法 confidence: {row}"
    assert all(key in ("weapon", "attachment", "cosmetic", "stratagem", "booster", "banner",
                       "currency", None) for key in
               (meta.get("label") for meta in CATEGORY_MEANING.values())), "category_meaning.label 出现枚举外的值"

    def shown_path(path: pathlib.Path) -> str:
        try:
            return path.resolve().relative_to(work_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    payload = {
        "note": (
            "只读解析产物：服务端 /api/Progression/items 目录 3020 行的名字与 progressionCategory 语义；"
            "名字只取自本机只读数据表的显式 id->name 映射与等值结构推断（cat10/cat11 战备 hash、"
            "cat4 套装名=同名子行），查不到即为 null（不编造、不音译、不按顺序猜）；"
            "脚本 resolve.py 可重复运行（只读输入、不联网、确定性输出）。"
        ),
        "build": BUILD,
        "category_meaning": CATEGORY_MEANING,
        "rows": rows_out,
        "coverage": coverage,
        "sources": {
            key: {"path": shown_path(paths[key]), "sha256": sha256_of(paths[key])}
            for key in REL
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    out_path.write_text(text, encoding="utf-8", newline="\n")

    log(f"wrote {out_path} rows={len(rows_out)} named={coverage['named']} unresolved={coverage['unresolved']}")
    log(f"by_source = {coverage['by_source']}")
    log(f"v2_inference = {coverage['v2_inference']}")
    log(f"baseline = {coverage['baseline']['items_json_named_rows']} 已命名 / "
        f"{coverage['baseline']['items_json_hit_rows']} 命中；"
        f"delta vs 已命名 = {coverage['baseline']['delta_vs_items_json_named']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SourceError as exc:
        print(f"[resolve] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
