"""能力模板：一键把「研究线已验证的一组配置」写进当前 profile。

为什么要有：
  * 6 项核心能力各自牵动 2–4 个 profile 字段（休眠星四件套必须同 index 全齐，漏一件就不生效）；
  * 哪些 id 组合真的在实机生效，是研究线花很久试出来的；把「已验证组合」固化成模板，
    用户不必从零猜。

边界：
  * 只改**内存里的 profile**：不落盘、不调引擎。GUI 由右上角「应用配置」统一热更新；
  * 模板值是研究线 / 黄金回归里记录的原值，不编造；缺名字的 id 直接标 id；
  * `deferred=True` 的项引擎已实现，但按 v0.1 范围折叠在「扩展 / 实验」区，并在按钮上标验证状态。
"""

from dataclasses import dataclass
from typing import Callable, Optional

# ---- 研究线 / M4 实机已验证的原值（改动前先核对） ---------------------------
VARIANT_NAME = "掠食变种"          # 虫族双 id 词条：1243 tag + 1245 PREDATOR STRAIN
GLOBAL_EVENT_ID = "1501113"       # 全局效果通道示例事件（须是当前 war 的 globalEvents 之一）
GLOBAL_EFFECT_ID = 1346           # INCENDIARY GATLING BARRAGE（type94，局内轨道加特林变燃烧）
TRIAL_IDS = (1227, 1263)          # MG-43 机枪 / M-105 盟友（type32 临时配发，上限 3）
UNLOCK_WEAPON_ID = 2112173638     # 研究线未发布武器候选（库存键 mixId）
# 研究线/M4 实机配对的「目录行 + 库存行」（只注库存行客户端不显示，必须成对）
UNRELEASED_ITEMS = (
    (2112173638, 3866352840),     # LAS-22？（M4 实机出现）
    (3388344762, 2811723672),     # P-41 OMBUDSMAN（M4 实机出现）
    (1934208922, 2852344585),     # SG-8F PUNISHER FIRE OF LIBERTY（M4 实机出现）
    (2870692210, 3866352840),     # 目录里已存在 → 只靠库存行解锁（M4 实机 = LAS-13 TRIDENT）
)
DORMANT_INDEX = 300               # BICEP（本季无游戏索引，自选节点号）
DORMANT_HASH = 2995599666         # BICEP 行自己的 settingsHash（决定名字/生态，不能借别行）
DORMANT_POS = {"x": 0.3, "y": -0.55}
DORMANT_SECTOR = 20
DORMANT_CAMP_ID = 51999
# 就近星球 waypoints（BICEP 用 180/7；180 = HERTHON SECUNDUS，M4 实机连线正常）
DORMANT_WAYPOINTS = (180, 7)
BORROW_HASH = 721718208           # 落叶林：研究线/M4 实机「TRANDOR 变落叶林」实测值
MAX_HEALTH = 1000000
REGEN_PER_SECOND = 4.1666665
CUSTOMIZE_MIX = 2112173638        # L2 改装实验对象
CUSTOMIZE_SLOT = 1                # 槽下标（0=下挂 1=光学 …）
CUSTOMIZE_OPTION = 3905063732     # 附件 optionId


@dataclass(frozen=True)
class Template:
    tid: str
    title: str
    desc: str
    apply: Callable            # (profile, planet=None) -> list[str] notes
    needs_planet: bool = False
    deferred: bool = False
    evidence: str = ""         # 验证状态 / 研究线证据（延后项必填）


# ---------------------------------------------------------------- 小工具


def _status(profile):
    st = profile.get("status")
    if not isinstance(st, dict):
        st = {}
        profile["status"] = st
    return st


def _warinfo(profile):
    wi = profile.get("warinfo")
    if not isinstance(wi, dict):
        wi = {}
        profile["warinfo"] = wi
    return wi


def _inventory(profile):
    inv = profile.get("inventory")
    if not isinstance(inv, dict):
        inv = {}
        profile["inventory"] = inv
    return inv


def _rows(container, key, dict_like=False):
    val = container.get(key)
    want = dict if dict_like else list
    if not isinstance(val, want):
        val = want()
        container[key] = val
    return val


def _need_planet(planet):
    if planet is None:
        raise ValueError("该模板需要指定一颗星球")
    return int(planet)


def _replace_row(rows, entry, key="index"):
    """同 key 的条目就地替换，避免同一星球出现两份。"""
    for i, row in enumerate(rows):
        if isinstance(row, dict) and _as_int(row.get(key)) == _as_int(entry.get(key)):
            rows[i] = entry
            return entry
    rows.append(entry)
    return entry


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 6 项核心


def apply_variant_trial(profile, planet=None):
    """变种词条：掠食变种（虫族双 id）挂到指定星球。

    走 `planet_effects` **原始通道**（绕过引擎的阵营过滤）——M4 实机验证：
    人类星/虫族星都能出卡面；`status.variants` 那条通道会按 owner 过滤，
    挂在 TERREK（人类星）上会被丢掉。
    """
    planet = _need_planet(planet)
    rows = _rows(_status(profile), "planet_effects")
    target = next((r for r in rows
                   if isinstance(r, dict) and _as_int(r.get("index")) == planet), None)
    if target is None:
        target = {"index": planet, "ids": []}
        rows.append(target)
    ids = target.get("ids")
    if not isinstance(ids, list):
        ids = target["ids"] = []
    added = []
    for effect_id in (1243, 1245):          # tag + PREDATOR STRAIN
        if effect_id not in ids:
            ids.append(effect_id)
            added.append(effect_id)
    return [
        "变种词条：星球 %d += PREDATOR STRAIN（ids 1243 + 1245，planet_effects 原始通道）"
        % planet,
        "原始通道不按 owner 过滤（人类/机器人星也会显示）；星球必须**有战役可点**，"
        "否则卡面打不开（M4 实机：TERREK 本季无战役，看不到效果）",
        "本次新增 %d 个 id；当前该星球共 %d 个" % (len(added), len(ids)),
    ]


def apply_global_effect(profile, planet=None):
    """全局效果：往已存在的全局事件挂 type94 效果。"""
    ge = _rows(_status(profile), "globalEffects", dict_like=True)
    ids = ge.get(GLOBAL_EVENT_ID)
    if not isinstance(ids, list):
        ids = ge[GLOBAL_EVENT_ID] = []
    if GLOBAL_EFFECT_ID not in ids:
        ids.append(GLOBAL_EFFECT_ID)
    return [
        "全局效果：事件 %s += effect %d（INCENDIARY GATLING BARRAGE，type94）"
        % (GLOBAL_EVENT_ID, GLOBAL_EFFECT_ID),
        "事件 id 必须是**当前 war 的 globalEvents 之一**（本季 live 是 1501107/1501115，"
        "M4 实测 1501107 生效）；不在列表里就不会有任何效果，可在「全局效果」卡里改事件 id",
    ]


def apply_stratagem_trial(profile, planet=None):
    """战备试用：往指定星球的临时配发栏加快捷战备（≤3）。

    试用是「按星球下发」的（引擎把它并进该星的 planetActiveEffects），所以必须指定星球：
    只有 trials 没有星球的 profile 不会生效 —— M3 之前 build_status_plan 会把这种 profile
    静默丢成空计划，这里连同 trials_planet 一起写，保证模板一按就能用。
    """
    planet = _need_planet(planet)
    st = _status(profile)
    trials = _rows(st, "trials")
    added = []
    for sid in TRIAL_IDS:
        if sid not in trials:
            trials.append(sid)
            added.append(sid)
    if len(trials) > 3:
        del trials[3:]
    st["trials_planet"] = planet
    names = {1227: "MG-43 机枪", 1263: "M-105 盟友"}
    return [
        "战备试用：%s（type32 临时配发，最多 3 条，引擎会再截断）"
        % "、".join("%d %s" % (sid, names.get(sid, "")) for sid in TRIAL_IDS),
        "挂到星球 %d（status.trials_planet）：本模板已加 %d 条，当前 profile 共 %d 条"
        % (planet, len(added), len(trials)),
    ]


def apply_item_unlock(profile, planet=None):
    """物品解锁：库存行 + 目录行**成对**注入（只注库存行客户端不显示）。

    值来自研究线 / M4 实机配对：`items.add` 克隆同族模板行，库存里加同一个 mixId。
    M4 实机结果：目录新增 3 行（第 4 个 id 目录里本来就有）+ 库存 4 行 →
    军械库出现 P-41 OMBUDSMAN / SG-8F PUNISHER FIRE OF LIBERTY / LAS-22 / LAS-13 TRIDENT。
    """
    inv = _inventory(profile)
    rows = _rows(inv, "weapons")
    existing = {_as_int(r.get("mixId")) for r in rows if isinstance(r, dict)}
    added = []
    for mix_id, _template in UNRELEASED_ITEMS:
        if mix_id in existing:
            continue
        rows.append({"mixId": mix_id, "amount": 1, "isDiscovered": False})
        added.append(mix_id)
    items = profile.get("items")
    if not isinstance(items, dict):
        items = {}
        profile["items"] = items
    adds = items.get("add")
    if not isinstance(adds, list):
        adds = items["add"] = []
    have_ids = {_as_int(r.get("id")) if isinstance(r, dict) else _as_int(r) for r in adds}
    for mix_id, template in UNRELEASED_ITEMS:
        if mix_id in have_ids:
            continue
        adds.append({"id": mix_id, "template": template})
        have_ids.add(mix_id)
    if items.get("template") is None:
        items["template"] = UNRELEASED_ITEMS[0][1]
    return [
        "物品解锁：库存 weapons += %d 件、items.add += %d 行（目录行 + 库存行成对）"
        % (len(added), len(adds)),
        "其中 2870692210 目录里已有 → 只靠库存行解锁（M4 实机显示为 LAS-13 TRIDENT）",
        "目录行要克隆同族模板 itemId（%d 等）；模板行不存在时该行会被引擎跳过"
        % UNRELEASED_ITEMS[0][1],
    ]


def apply_dormant_star(profile, planet=None):
    """休眠星四件套：warinfo 身份 + status 节点 + 战役 + 归属，必须同 index 全齐。

    配方为研究线实机通过的原值（PROXY-CAPABILITY-TEST-20261111 §6.2/M4）：
      * settingsHash 必须是**目标星球行自己的**（BICEP = 2995599666）——
        客户端靠它解析名字/生态；借别行的 hash 会显示成那颗星（M4 实机显示成 BALDRICK PRIME）；
      * waypoints 必须给就近星球（BICEP 用 180/7），否则星图上没有连线；
      * initialOwner / planet_nodes.owner / owner 三处一致（BICEP 用 2=虫族）。
    """
    index = _need_planet(planet) if planet is not None else DORMANT_INDEX
    pos = dict(DORMANT_POS)
    wi = _warinfo(profile)
    infos = _rows(wi, "planet_infos")
    _replace_row(infos, {
        "index": index, "settingsHash": DORMANT_HASH,
        "position": pos, "waypoints": list(DORMANT_WAYPOINTS), "sector": DORMANT_SECTOR,
        "maxHealth": MAX_HEALTH, "initialOwner": 2, "disabled": False,
    })
    st = _status(profile)
    _replace_row(_rows(st, "planet_nodes"), {
        "index": index, "owner": 2, "health": MAX_HEALTH,
        "regenPerSecond": REGEN_PER_SECOND, "players": 0, "position": dict(pos),
    })
    _replace_row(_rows(st, "campaigns"), {
        "planet": index, "id": DORMANT_CAMP_ID, "type": 0, "count": 1, "race": 1,
    }, key="planet")
    owners = _rows(st, "owner", dict_like=True)
    owners[str(index)] = 2
    return [
        "休眠星四件套（星球 %d）：warinfo.planet_infos + status.planet_nodes + campaigns + owner"
        % index,
        "settingsHash %d 是 BICEP 自己的（决定卡面名字/生态）；waypoints=%s 让星图有连线；"
        "owner 三处统一为 2（虫族）"
        % (DORMANT_HASH, list(DORMANT_WAYPOINTS)),
        "换星时请换 settingsHash 为目标行自己的值，并在 live warinfo 里核对坐标（不能是 0,0）",
    ]


def apply_ecosystem_borrow(profile, planet=None):
    """生态借用：把落叶林的 settingsHash 写到目标星球（改生态/地形/天气）。"""
    planet = _need_planet(planet)
    wi = _warinfo(profile)
    sh = _rows(wi, "settings_hash", dict_like=True)
    sh[str(planet)] = BORROW_HASH
    return [
        "生态借用：星球 %d 的 settingsHash → %d（落叶林，研究线/M4 实机值）"
        % (planet, BORROW_HASH),
        "settingsHash 同时决定「星球身份」——M4 实机把 TRANDOR 写成该 hash 后，"
        "星图上名字变成了落叶林那颗星（UVP ALPHA），属预期机制变化",
        "只在局内可见（落地地形）；目标星需有战役可进",
    ]


# ---------------------------------------------------------------- 延后项（引擎已实现，界面折叠）


def apply_defense_campaign(profile, planet=None):
    """防守战役伪造：campaigns(type4) + 反向攻击边 + planetEvent + owner。"""
    planet = _need_planet(planet)
    st = _status(profile)
    _replace_row(_rows(st, "campaigns"), {
        "planet": planet, "id": DORMANT_CAMP_ID, "type": 4, "count": 2, "race": 1,
    }, key="planet")
    atk = _rows(st, "attacks")
    if not any(isinstance(r, dict) and _as_int(r.get("source")) == 100
               and _as_int(r.get("target")) == planet for r in atk):
        atk.append({"source": 100, "target": planet})
    ev = _rows(st, "events")
    if not any(isinstance(r, dict) and _as_int(r.get("planet")) == planet
               and _as_int(r.get("eventType")) == 2 for r in ev):
        ev.append({"planet": planet, "eventType": 2, "race": 2, "health": 900000,
                   "maxHealth": MAX_HEALTH, "startOffset": -30, "endOffset": 7200})
    _rows(st, "owner", dict_like=True)[str(planet)] = 1
    return [
        "防守战役（实验）：星球 %d 加 type4 战役 + 反向攻击边 + 防守事件 + 归属 1" % planet,
        "攻击边源星用了样本里的虫族星 100；实机请换成当前真正在进犯的敌星，"
        "jointOperations 由钩子自动补",
    ]


def apply_city_regions(profile, planet=None):
    """城市分区：给目标星球补 regionIndex 0/1/2 的分区状态。"""
    planet = _need_planet(planet)
    regions = _rows(_status(profile), "regions")
    added = 0
    for ridx in (0, 1, 2):
        if any(isinstance(r, dict) and _as_int(r.get("planet")) == planet
               and _as_int(r.get("regionIndex")) == ridx for r in regions):
            continue
        regions.append({"planet": planet, "regionIndex": ridx, "owner": 1,
                        "maxHealth": 400000})
        added += 1
    return [
        "城市分区（实验）：星球 %d 补 %d 条分区状态（已有编号保留，只补缺失）"
        % (planet, added),
        "原生 WarInfo 的分区定义无法离线核对，条目数按研究线样例取 3；进局后可能多/少块",
    ]


def apply_l2_customize(profile, planet=None):
    """L2 改装槽（实验）：写一份改装槽快照 —— 实测送达但客户端不生效。"""
    exp = profile.get("experimental")
    if not isinstance(exp, dict):
        exp = {}
        profile["experimental"] = exp
    exp["customize"] = {
        "enabled": True,
        "edits": [{"mixId": CUSTOMIZE_MIX,
                   "slots": {str(CUSTOMIZE_SLOT): CUSTOMIZE_OPTION},
                   "allIndexes": True}],
    }
    return [
        "L2 改装（实验）：mixId %d 第 %d 槽 → optionId %d（写 experimental.customize）"
        % (CUSTOMIZE_MIX, CUSTOMIZE_SLOT, CUSTOMIZE_OPTION),
        "研究线实测：改装槽快照能送达客户端，但游戏内不生效 —— 只作研究开关，别期待效果",
    ]


# ---------------------------------------------------------------- 模板表


TEMPLATES = [
    Template("variant_trial", "变种词条试用",
             "把虫族变种「掠食变种」（双 id 1243+1245）以原始通道挂到目标星球，星图卡面出 PREDATOR STRAIN"
             "（不按 owner 过滤；星球需有战役可点）。",
             apply_variant_trial, needs_planet=True),
    Template("global_effect", "全局效果试用",
             "给当前 war 的全局事件挂 type94 效果 1346：局内轨道加特林变燃烧"
             "（事件 id 不在 live globalEvents 里则不生效，可在卡片里改）。",
             apply_global_effect),
    Template("stratagem_trial", "战备试用",
             "往目标星球的临时配发栏加 MG-43 机枪 / M-105 盟友（type32，上限 3 条）。",
             apply_stratagem_trial, needs_planet=True),
    Template("item_unlock", "物品解锁",
             "未发布武器：目录行（克隆同族模板）+ 库存行成对注入，军械库出现 LAS-22 / P-41 / SG-8F 等。",
             apply_item_unlock),
    Template("dormant_star", "休眠星可玩化",
             "给休眠星补身份四件套：warinfo 身份（settingsHash 决定名字/生态）+ 节点 + 战役 + 归属，"
             "带就近连线，星图上可点可开局。",
             apply_dormant_star),
    Template("ecosystem_borrow", "生态借用",
             "把落叶林的 settingsHash（721718208）写到目标星球，局内地形变落叶林"
             "（该 hash 同时决定星球身份，星图名字会变成源星）。",
             apply_ecosystem_borrow, needs_planet=True),
    Template("defense_campaign", "防守战役伪造",
             "在目标星球上造一场防守战役（type4 战役 + 反向攻击边 + 防守事件 + 归属）。",
             apply_defense_campaign, needs_planet=True, deferred=True,
             evidence="✓ 研究线实机出过 DEFENSE 卡；v0.2 做正式模板卡"),
    Template("city_regions", "城市分区",
             "给目标星球补 regionIndex 0/1/2 的分区状态（只补缺失编号）。",
             apply_city_regions, needs_planet=True, deferred=True,
             evidence="✓ 离线双验 + 实机验证；v0.2 做正式 UI"),
    Template("l2_customize", "L2 改装槽",
             "写一份 L2 改装槽快照（mixId 2112173638 第 2 槽 → optionId 3905063732）。",
             apply_l2_customize, deferred=True,
             evidence="⚠ 研究线实测：送达但客户端不生效（引擎默认关）；只作研究开关"),
]

CORE_TEMPLATES = [t for t in TEMPLATES if not t.deferred]
DEFERRED_TEMPLATES = [t for t in TEMPLATES if t.deferred]


def get_template(tid):
    return next((t for t in TEMPLATES if t.tid == tid), None)
