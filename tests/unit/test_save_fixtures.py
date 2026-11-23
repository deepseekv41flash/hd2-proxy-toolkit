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
LEAK_MARKERS = ("7656119", "accountId", "sessionId", "13887067702231565058",
                "Bearer ", "X-HD2-Token")

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
