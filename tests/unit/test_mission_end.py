"""G3 结算奖励解析（`hooks/mission_end.py`）单测。

用 `data/fixtures/saves/mission_end/` 里 5 份**真实** Mission/end 响应当事实底，
外加构造场景（rewards 缺失 / 字段缺失 / 坏 body）。
"""

import json
from pathlib import Path

from hd2proxy.engine.hooks import mission_end

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves" / "mission_end"


def _real(name):
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------- 路径判定


def test_is_mission_end():
    assert mission_end.is_mission_end("/api/Operation/Mission/end")
    assert mission_end.is_mission_end("/api/Operation/Mission/end?x=1")
    assert not mission_end.is_mission_end("/api/Operation/Mission/start")
    assert not mission_end.is_mission_end("/api/Mission/Session")
    assert not mission_end.is_mission_end("")


# ---------------------------------------------------------------- 真实样本


def test_all_real_samples_parse():
    for path in sorted(FIXTURES.glob("*.json")):
        inc = mission_end.extract_increments(path.read_bytes())
        assert inc["ok"] is True, path.name
        assert isinstance(inc["experience"], int) and inc["experience"] >= 0
        assert inc["item_source"] in ("rewards", "badges", "none")
        # 结算响应里的战果展示字段不算未知（它们只是我们不消费）
        assert "multipliers" in inc["unknown_keys"]


def test_experience_is_mission_increment_not_total():
    """`experience` 是本局增量（936），不是账号总值 —— 存档要累加。"""
    inc = mission_end.extract_increments(_real("12b9a872.json"))
    assert inc["experience"] == 936


def test_rewards_wins_over_badges_by_multiplier():
    """5 份样本恒成立：rewards[medals] = badges 明细 × multipliers(3)。默认按 rewards 入账。"""
    for name in ("12b9a872.json", "15998437.json", "d0bdbe5b.json", "dd2350f7.json"):
        inc = mission_end.extract_increments(_real(name))
        assert inc["item_source"] == "rewards", name
        rewards = inc["rewards_items"]
        badges = inc["badge_items"]
        assert rewards and badges
        # 战备点（3608481516）受 difficulty multiplier 影响 ×3；征用单（897894480）不变
        assert rewards["3608481516"] == badges["3608481516"] * 3, name
        assert rewards["897894480"] == badges["897894480"], name
        assert inc["items"] == rewards


def test_badges_mode_switch(monkeypatch):
    """口径可切换：ITEM_SOURCE='badges' 时按明细求和入账（一处开关，实机对账不符时用）。"""
    monkeypatch.setattr(mission_end, "ITEM_SOURCE", "badges")
    inc = mission_end.extract_increments(_real("12b9a872.json"))
    assert inc["item_source"] == "badges"
    assert inc["items"] == inc["badge_items"]
    assert inc["items"]["3608481516"] == 1478


def test_fallback_to_badges_when_rewards_missing():
    doc = json.loads(_real("12b9a872.json").decode("utf-8"))
    doc.pop("rewards")
    inc = mission_end.extract_increments(json.dumps(doc).encode())
    assert inc["item_source"] == "badges"
    assert inc["items"]["3608481516"] == 1478


def test_other_reward_lists_are_collected():
    doc = {
        "experience": 100,
        "badges": [{"itemRewards": [{"mixId": 1, "amount": 2}]}],
        "lootedItemRewards": [{"mixId": 2, "amount": 3}],
        "lootedHeavyItemRewards": [{"mixId": 2, "amount": 4}],
        "levelUpRewards": [{"mixId": 3, "amount": 5}],
        "missionId": "m1",
    }
    inc = mission_end.extract_increments(doc)
    assert inc["item_source"] == "badges"       # 无 rewards → 明细
    assert inc["items"] == {"1": 2, "2": 7, "3": 5}
    assert inc["other_items"] == {"2": 7, "3": 5}


def test_packages_shape_and_invalid_rows():
    doc = {"experience": 0, "progressionPackageUpdates": [
        {"id32": 5, "level": 3, "progress": 10, "platformAccountId": "x"},
        {"level": 1},                        # 无 id32 → 跳过
        "bad-row",
    ]}
    inc = mission_end.extract_increments(doc)
    assert inc["packages"] == {"5": {"level": 3, "progress": 10}}


def test_missing_fields():
    inc = mission_end.extract_increments({"missionId": "m"})
    assert inc["ok"] is True and inc["has_increment"] is False
    assert inc["items"] == {} and inc["packages"] == {}
    assert inc["mission"]["mission_id"] == "m"


def test_bad_bodies():
    for body in (b"not json", "", None, 123, json.dumps([1, 2]).encode()):
        inc = mission_end.extract_increments(body)
        assert inc["ok"] is False and inc["has_increment"] is False


def test_summarize_is_one_line():
    text = mission_end.summarize(mission_end.extract_increments(_real("12b9a872.json")))
    assert "+936 exp" in text and "2 种物品" in text and "包进度" in text
    assert "\n" not in text
    assert "不可解析" in mission_end.summarize({"ok": False})
