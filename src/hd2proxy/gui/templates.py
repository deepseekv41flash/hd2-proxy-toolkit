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

# ---- 研究线已验证的原值（改动前先核对） -------------------------------------
VARIANT_NAME = "掠食变种"          # 虫族双 id 词条：1243 tag + 1245 PREDATOR STRAIN
GLOBAL_EVENT_ID = "1501113"       # 全局效果通道：globalEvents 里已存在的实验事件
GLOBAL_EFFECT_ID = 1346           # INCENDIARY GATLING BARRAGE（type94，局内轨道加特林变燃烧）
TRIAL_IDS = (1227, 1263)          # MG-43 机枪 / M-105 盟友（type32 临时配发，上限 3）
UNLOCK_WEAPON_ID = 2112173638     # 研究线未发布武器候选（库存键 mixId）
DORMANT_INDEX = 300               # BICEP（休眠星，可点可结算）
DORMANT_HASH = 694418289          # BICEP 模板 settingsHash（研究线值；build 变更后要抓 live 核对）
DORMANT_POS = {"x": 0.3, "y": -0.55}
DORMANT_SECTOR = 20
DORMANT_CAMP_ID = 51999
BORROW_HASH = 2995599666          # 落叶林：研究线「TRANDOR 变落叶林」实测值
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
    """变种词条：掠食变种（虫族双 id）挂到指定星球。"""
    planet = _need_planet(planet)
    rows = _rows(_status(profile), "variants")
    target = next((r for r in rows
                   if isinstance(r, dict) and r.get("name") == VARIANT_NAME), None)
    if target is None:
        target = {"name": VARIANT_NAME, "planets": []}
        rows.append(target)
    planets = target.get("planets")
    if not isinstance(planets, list):
        planets = target["planets"] = []
    if planet not in planets:
        planets.append(planet)
    return [
        "变种词条：%s → 星球 %d（ids 1243 + 1245，faction=terminid）" % (VARIANT_NAME, planet),
        "这是虫族词条：挂到人类/机器人控制的星球上会被引擎按 owner 过滤掉"
        "（离线预演会提示「不同阵营」）",
    ]


def apply_global_effect(profile, planet=None):
    """全局效果：往已存在的实验事件挂 type94 效果。"""
    ge = _rows(_status(profile), "globalEffects", dict_like=True)
    ids = ge.get(GLOBAL_EVENT_ID)
    if not isinstance(ids, list):
        ids = ge[GLOBAL_EVENT_ID] = []
    if GLOBAL_EFFECT_ID not in ids:
        ids.append(GLOBAL_EFFECT_ID)
    return [
        "全局效果：事件 %s += effect %d（INCENDIARY GATLING BARRAGE，type94）"
        % (GLOBAL_EVENT_ID, GLOBAL_EFFECT_ID),
        "只有游戏里确实存在事件 %s 时才会改写；样本 data/samples/status.json 里有这个事件",
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
    """物品解锁：把研究线验证过的未发布武器加进库存。"""
    inv = _inventory(profile)
    rows = _rows(inv, "weapons")
    if not any(isinstance(r, dict) and _as_int(r.get("mixId")) == UNLOCK_WEAPON_ID for r in rows):
        rows.append({"mixId": UNLOCK_WEAPON_ID, "amount": 1, "isDiscovered": False})
    return [
        "物品解锁：库存 weapons += mixId %d（研究线未发布武器候选）" % UNLOCK_WEAPON_ID,
        "「目录上架」（items.add）需要同族模板 itemId；研究线原始配置未固化进本仓，"
        "需要上架请到「物品与战备」页手动填模板 id",
    ]


def apply_dormant_star(profile, planet=None):
    """休眠星四件套：warinfo 身份 + status 节点 + 战役 + 归属，必须同 index 全齐。"""
    index = _need_planet(planet) if planet is not None else DORMANT_INDEX
    pos = dict(DORMANT_POS)
    wi = _warinfo(profile)
    infos = _rows(wi, "planet_infos")
    _replace_row(infos, {
        "index": index, "settingsHash": DORMANT_HASH,
        "position": pos, "waypoints": [], "sector": DORMANT_SECTOR,
        "maxHealth": MAX_HEALTH, "initialOwner": 1, "disabled": False,
    })
    st = _status(profile)
    _replace_row(_rows(st, "planet_nodes"), {
        "index": index, "owner": 1, "health": MAX_HEALTH,
        "regenPerSecond": REGEN_PER_SECOND, "players": 0, "position": dict(pos),
    })
    _replace_row(_rows(st, "campaigns"), {
        "planet": index, "id": DORMANT_CAMP_ID, "type": 0, "count": 1, "race": 1,
    }, key="planet")
    owners = _rows(st, "owner", dict_like=True)
    owners[str(index)] = 1
    return [
        "休眠星四件套（星球 %d）：warinfo.planet_infos + status.planet_nodes + campaigns + owner"
        % index,
        "坐标 (%.2f, %.2f)、settingsHash %d 是研究线模板值；换星/换 build 请先用抓包页导入 "
        "live warinfo 再核对（坐标不能是 0,0）" % (pos["x"], pos["y"], DORMANT_HASH),
    ]


def apply_ecosystem_borrow(profile, planet=None):
    """生态借用：把落叶林的 settingsHash 写到目标星球（改生态/地形/天气）。"""
    planet = _need_planet(planet)
    wi = _warinfo(profile)
    sh = _rows(wi, "settings_hash", dict_like=True)
    sh[str(planet)] = BORROW_HASH
    return [
        "生态借用：星球 %d 的 settingsHash → %d（落叶林，研究线「TRANDOR 变落叶林」实测值）"
        % (planet, BORROW_HASH),
        "改的是客户端拿到的星球生成设置；目标星建议选人类控制星，且只在局内可见",
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
             "把虫族变种「掠食变种」（双 id 1243+1245）挂到一颗星球上，星图出 PREDATOR STRAIN。",
             apply_variant_trial, needs_planet=True),
    Template("global_effect", "全局效果试用",
             "给实验事件 1501113 挂 type94 效果 1346：局内轨道加特林变燃烧。",
             apply_global_effect),
    Template("stratagem_trial", "战备试用",
             "往目标星球的临时配发栏加 MG-43 机枪 / M-105 盟友（type32，上限 3 条）。",
             apply_stratagem_trial, needs_planet=True),
    Template("item_unlock", "物品解锁",
             "把研究线验证过的未发布武器（mixId 2112173638）加进库存。",
             apply_item_unlock),
    Template("dormant_star", "休眠星可玩化",
             "给休眠星补身份四件套：warinfo.planet_infos + status 节点 + 战役 + 归属，星图上可点可结算。",
             apply_dormant_star),
    Template("ecosystem_borrow", "生态借用",
             "把落叶林的 settingsHash（2995599666）写到目标星球，改星球生态/地形/天气。",
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
