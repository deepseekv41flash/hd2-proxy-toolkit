"""变种目录与阵营逻辑（M1 从 legacy_proxy.py 抽出）。

阵营只用于**过滤**：客户端并不拒绝跨阵营词条（研究线实测），过滤是我们自己加的保护。
"""

MAX_STRATAGEMS = 3

FACTION_TERMINID = "terminid"
FACTION_AUTOMATON = "automaton"
FACTION_ILLUMINATE = "illuminate"
FACTION_UNIVERSAL = "universal"
OWNER_FACTIONS = {
    2: FACTION_TERMINID,
    3: FACTION_AUTOMATON,
    4: FACTION_ILLUMINATE,
}


def variant_faction(meta):
    """返回词条阵营；旧目录缺少 faction 时按 presence 前缀兼容。"""
    meta = meta or {}
    faction = str(meta.get("faction") or "").lower()
    if faction in (FACTION_TERMINID, FACTION_AUTOMATON, FACTION_ILLUMINATE, FACTION_UNIVERSAL):
        return faction
    presence = str(meta.get("presence") or "").lower()
    if presence.startswith("bugs_"):
        return FACTION_TERMINID
    if presence.startswith("bots_") or presence.startswith("elite_bot_"):
        return FACTION_AUTOMATON
    if presence.startswith("illuminate_"):
        return FACTION_ILLUMINATE
    return FACTION_UNIVERSAL


def owner_faction(value):
    try:
        return OWNER_FACTIONS.get(int(value))
    except (TypeError, ValueError):
        return None
