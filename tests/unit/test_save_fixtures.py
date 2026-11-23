"""存档夹具（`data/fixtures/saves/`）守门测试。

为什么需要：
  * 夹具是**真实抓包**，很容易顺手把带身份/票据的响应提进公开仓 —— 这里逐字节扫描，禁止；
  * 夹具一旦被替换，合并语义测试的"事实底"就变了 —— 这里钉住行数/大小/关键字段；
  * 顺带用真实响应验证 G2 的两个不变量：空档不虚增、earned 只抬不降。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import saves

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves"

# 身份/票据痕迹：这些字符串一出现就说明抓错了文件（或没脱敏）
LEAK_MARKERS = ("7656119", "accountId", "platformAccountId", "sessionId",
                "13887067702231565058", "Bearer ", "X-HD2-Token")

# G3 结算样本（真实 5 份；platformAccountId 已剥掉）
MISSION_END_EXPECTED = {
    "12b9a872.json": (1577, 936),
    "15998437.json": (1201, 267),
    "d0bdbe5b.json": (1213, 258),
    "dd2350f7.json": (1664, 903),
    "e899f6af.json": (560, 0),
}

EXPECTED = {
    "main": {"progression": 12921, "inventory": 69120, "customize_v2": 15853,
             "stats_profile": 730, "stats_profile_801": 730, "season_pass": 14589},
    "fresh": {"progression": 1500, "inventory": 3267, "customize_v2": 12,
              "stats_profile": 644, "stats_profile_801": 644, "season_pass": 14589},
}
INVENTORY_ROWS = {"main": 970, "fresh": 55}
CUSTOMIZE_ROWS = {"main": 74, "fresh": 0}


def _load(account, name):
    return (FIXTURES / account / ("%s.json" % name)).read_bytes()


@pytest.mark.parametrize("account", sorted(EXPECTED))
def test_fixture_sizes_and_shapes(account):
    for name, size in EXPECTED[account].items():
        raw = _load(account, name)
        assert len(raw) == size, "%s/%s 大小变了（夹具被替换？同步 README 表格）" % (account, name)
        doc = json.loads(raw.decode("utf-8"))          # 合法 JSON
        if name == "inventory":
            assert len(doc["items"]) == INVENTORY_ROWS[account]
        elif name == "customize_v2":
            assert len(doc["items"]) == CUSTOMIZE_ROWS[account]
        elif name == "progression":
            assert isinstance(doc["experience"], int)


@pytest.mark.parametrize("account", sorted(EXPECTED))
def test_fixtures_carry_no_identity(account):
    for name in EXPECTED[account]:
        text = _load(account, name).decode("utf-8", "replace")
        for marker in LEAK_MARKERS:
            assert marker not in text, "%s/%s 含身份/票据痕迹 %r" % (account, name, marker)


def test_season_pass_is_account_independent():
    """实测结论：季票元数据两账号逐字节相同（不能当"买了什么"的证据）。"""
    assert _load("main", "season_pass") == _load("fresh", "season_pass")


def test_progression_fixture_values():
    main = json.loads(_load("main", "progression"))
    fresh = json.loads(_load("fresh", "progression"))
    assert main["experience"] == 2759938 and len(main["packageProgress"]) == 52
    assert fresh["experience"] == 1 and len(fresh["packageProgress"]) == 9
    assert fresh["achievements"] == []                    # 空号没有成就


def test_empty_save_changes_nothing_on_real_bodies():
    """空档（什么都没挣到）不能改真实响应 —— 否则首装用户会看到凭空多出的进度。"""
    for account in EXPECTED:
        for name in ("progression", "inventory"):
            raw = _load(account, name)
            if name == "progression":
                out, changed = saves.apply_to_progression(raw, saves.empty_save())
            else:
                out, changed = saves.apply_to_inventory(raw, saves.empty_save())
            assert changed == 0 and out is raw


def test_earned_only_raises_on_real_progression_body():
    body = _load("main", "progression")
    doc = saves.empty_save("steam_76561198968648344")
    doc["earned"]["experience"] = 2759938 + 1000
    doc["earned"]["achievements"] = {"1": 1}
    out, changed = saves.apply_to_progression(body, doc)
    assert changed >= 1
    got = json.loads(out)
    assert got["experience"] == 2759938 + 1000
    # 别的字段原样（不许因为合并把 packageProgress/seasonPass 冲掉）
    orig = json.loads(body)
    assert got["packageProgress"] == orig["packageProgress"]
    assert got["purchasedSeasonPassItems"] == orig["purchasedSeasonPassItems"]


def test_earned_never_lowers_real_progression_body():
    """单调量只抬不降：存档 experience 小于服务端时保持服务端值（防倒退）。"""
    body = _load("main", "progression")
    doc = saves.empty_save("steam_76561198968648344")
    doc["earned"]["experience"] = 1
    out, changed = saves.apply_to_progression(body, doc)
    assert changed == 0 and json.loads(out)["experience"] == 2759938


# ---------------------------------------------------------------- G3 结算样本


def test_mission_end_fixtures_are_intact():
    """结算响应样本：大小/经验值/无身份痕迹（platformAccountId 已剥掉）。"""
    base = FIXTURES / "mission_end"
    for name, (size, exp) in MISSION_END_EXPECTED.items():
        raw = (base / name).read_bytes()
        assert len(raw) == size, "%s 大小变了（夹具被替换？同步 README）" % name
        doc = json.loads(raw.decode("utf-8"))
        assert doc["experience"] == exp
        for row in doc.get("progressionPackageUpdates") or []:
            assert "platformAccountId" not in row        # 身份痕迹已剥掉
        text = raw.decode("utf-8", "replace")
        for marker in LEAK_MARKERS:
            assert marker not in text, "mission_end/%s 含身份/票据痕迹 %r" % (name, marker)


def test_mission_end_extract_matches_real_values():
    """真实结算样本 → 本局增量（经验/入账物品/包进度）。"""
    from hd2proxy.engine.hooks import mission_end

    raw = (FIXTURES / "mission_end" / "12b9a872.json").read_bytes()
    inc = mission_end.extract_increments(raw)
    assert inc["ok"] is True and inc["has_increment"] is True
    assert inc["experience"] == 936                        # 本局增量，不是总值
    assert inc["items"] == {"897894480": 7, "3608481516": 4434}
    assert inc["item_source"] == "rewards"
    # 明细：badges 求和后被 multipliers(×3) 放大成 rewards —— 5 份样本恒成立
    assert inc["badge_items"]["3608481516"] == 1478
    assert inc["rewards_items"]["3608481516"] == 1478 * 3
    assert inc["packages"] == {"277818845": {"level": 5, "progress": 459}}
    assert inc["mission"]["operation_id"] == 1242
    assert inc["mission"]["mission_id"] == "22c690d9-51f2-4d4e-be90-22380a69d08a"


def test_mission_end_zero_increment_sample():
    """空结算（exp=0 / 无奖励）也要能解析，且 has_increment=False。"""
    from hd2proxy.engine.hooks import mission_end

    raw = (FIXTURES / "mission_end" / "e899f6af.json").read_bytes()
    inc = mission_end.extract_increments(raw)
    assert inc["ok"] is True and inc["has_increment"] is False
    assert inc["experience"] == 0 and inc["items"] == {}
