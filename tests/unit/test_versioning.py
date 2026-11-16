"""版本规则（docs/VERSIONING.md）的纯逻辑单测：解析 / 映射 / 阶段迁移。"""

import pytest

from hd2proxy import versioning


# ---------------------------------------------------------------- 解析与输出

@pytest.mark.parametrize("text,core,stage,num", [
    ("0.1.0", "0.1.0", versioning.GA, 0),
    ("0.1.0-alpha.4", "0.1.0", versioning.ALPHA, 4),
    ("0.2.0-rc.2", "0.2.0", versioning.RC, 2),
    ("1.0.0-alpha.1", "1.0.0", versioning.ALPHA, 1),
])
def test_parse_valid(text, core, stage, num):
    v = versioning.parse(text)
    assert v.core == core and v.stage == stage and v.num == num
    assert str(v) == text          # 往返一致


def test_pep440_mapping():
    assert versioning.parse("0.1.0-alpha.4").pep440() == "0.1.0a4"
    assert versioning.parse("0.1.0-rc.2").pep440() == "0.1.0rc2"
    assert versioning.parse("1.0.0").pep440() == "1.0.0"


@pytest.mark.parametrize("bad", [
    "", "0.1", "v0.1.0-alpha.1", "0.1.0-alpha", "0.1.0-alpha.4.1",
    "0.1.0-beta.1", "0.1.0-alpha.x", "1.0.0-rc",
])
def test_parse_invalid(bad):
    with pytest.raises(ValueError):
        versioning.parse(bad)


# ---------------------------------------------------------------- 只修 bug

def test_fix_in_alpha_bumps_only_number():
    assert str(versioning.bump("0.1.0-alpha.4", "fix")) == "0.1.0-alpha.5"


def test_fix_in_rc_bumps_only_number():
    assert str(versioning.bump("0.1.0-rc.1", "fix")) == "0.1.0-rc.2"


def test_fix_on_ga_is_refused():
    """GA 后修 bug 的策略要人工定（补丁版重走 alpha→rc，还是并进下一功能版）。"""
    with pytest.raises(ValueError):
        versioning.bump("0.1.0", "fix")


# ---------------------------------------------------------------- 阶段迁移

def test_alpha_to_rc_starts_at_rc1():
    assert str(versioning.bump("0.1.0-alpha.7", "promote-rc")) == "0.1.0-rc.1"


def test_rc_to_ga_drops_suffix():
    assert str(versioning.bump("0.1.0-rc.2", "ga")) == "0.1.0"


def test_promote_rc_only_from_alpha():
    with pytest.raises(ValueError):
        versioning.bump("0.1.0-rc.1", "promote-rc")


def test_ga_only_from_rc():
    with pytest.raises(ValueError):
        versioning.bump("0.1.0-alpha.5", "ga")


# ---------------------------------------------------------------- 功能更新 = 动 X.Y.Z

@pytest.mark.parametrize("kind,expected", [
    ("minor", "0.2.0-alpha.1"),
    ("patch", "0.1.1-alpha.1"),
    ("major", "1.0.0-alpha.1"),
])
def test_feature_resets_to_alpha1(kind, expected):
    assert str(versioning.bump("0.1.0-alpha.4", "feature", kind)) == expected
    assert str(versioning.bump("0.1.0-rc.3", "feature", kind)) == expected
    assert str(versioning.bump("0.1.0", "feature", kind)) == expected


def test_feature_rejects_unknown_kind():
    with pytest.raises(ValueError):
        versioning.bump("0.1.0-alpha.4", "feature", "huge")


def test_unknown_action_refused():
    with pytest.raises(ValueError):
        versioning.bump("0.1.0-alpha.4", "hotfix")


# ---------------------------------------------------------------- 规则自检

def test_describe_mentions_phase_semantics():
    assert "实机" in versioning.describe(versioning.parse("0.1.0-alpha.4"))
    assert "发布候选" in versioning.describe(versioning.parse("0.1.0-rc.1"))
    assert "GA" in versioning.describe(versioning.parse("1.0.0"))


def test_current_project_version_is_compliant():
    """仓库当前版本必须符合规则（门禁第 5 步也会查，这里提前在单测里咬住）。"""
    import hd2proxy

    v = versioning.parse(hd2proxy.__version__)
    assert v.stage in (versioning.ALPHA, versioning.RC, versioning.GA)
    assert v.core.count(".") == 2
