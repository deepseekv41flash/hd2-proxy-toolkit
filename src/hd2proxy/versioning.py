"""版本号规则与 PEP 440 映射（docs/VERSIONING.md 的代码实现）。

规则一句话：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动 `alpha.N` / `rc.N`。

  X.Y.Z-alpha.N   alpha 阶段（新功能刚落地）
  X.Y.Z-rc.N      发布候选（用户实机验收过，已知问题不影响正常使用）
  X.Y.Z           GA

PEP 440（pyproject）：0.1.0-alpha.4 -> 0.1.0a4；0.1.0-rc.2 -> 0.1.0rc2；0.1.0 -> 0.1.0
"""

import re

VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(alpha|rc)\.(\d+))?$")
STAGES = ("alpha", "rc")

ALPHA = "alpha"
RC = "rc"
GA = "ga"


class Version:
    """解析后的版本号；`stage` 为 'alpha' / 'rc' / 'ga'。"""

    def __init__(self, major, minor, patch, stage=GA, num=0):
        self.major = int(major)
        self.minor = int(minor)
        self.patch = int(patch)
        self.stage = stage
        self.num = int(num)

    # ---- 解析 / 输出 ---------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "Version":
        m = VER_RE.match(str(text).strip())
        if not m:
            raise ValueError(
                "版本号不合法：%r（允许 X.Y.Z / X.Y.Z-alpha.N / X.Y.Z-rc.N）" % (text,))
        major, minor, patch, stage, num = m.groups()
        return cls(major, minor, patch, stage or GA, num or 0)

    @property
    def core(self) -> str:
        return "%d.%d.%d" % (self.major, self.minor, self.patch)

    def __str__(self):
        if self.stage == GA:
            return self.core
        return "%s-%s.%d" % (self.core, self.stage, self.num)

    def pep440(self) -> str:
        if self.stage == ALPHA:
            return "%sa%d" % (self.core, self.num)
        if self.stage == RC:
            return "%src%d" % (self.core, self.num)
        return self.core

    # ---- 下一版本（规则核心） ------------------------------------------
    def next_fix(self) -> "Version":
        """只修 bug：同 X.Y.Z，阶段内序号 +1。GA 阶段没有这个动作。"""
        if self.stage == GA:
            raise ValueError(
                "当前是 GA 版（%s）：GA 之后修 bug 的版本策略要先定（补丁版重走 alpha→rc，"
                "还是并进下一个功能版），请人工确认后用 feature --patch 或手动改。" % self)
        return Version(self.major, self.minor, self.patch, self.stage, self.num + 1)

    def next_rc(self) -> "Version":
        """用户实机验收通过：alpha.N -> rc.1。"""
        if self.stage != ALPHA:
            raise ValueError("只有 alpha 阶段能转 rc（当前 %s）" % self)
        return Version(self.major, self.minor, self.patch, RC, 1)

    def next_ga(self) -> "Version":
        """rc.N -> GA。"""
        if self.stage != RC:
            raise ValueError("只有 rc 阶段能发 GA（当前 %s）" % self)
        return Version(self.major, self.minor, self.patch, GA, 0)

    def next_feature(self, kind: str = "minor") -> "Version":
        """功能/能力更新：动 X.Y.Z，阶段重置为 alpha.1。"""
        if kind == "major":
            return Version(self.major + 1, 0, 0, ALPHA, 1)
        if kind == "minor":
            return Version(self.major, self.minor + 1, 0, ALPHA, 1)
        if kind == "patch":
            return Version(self.major, self.minor, self.patch + 1, ALPHA, 1)
        raise ValueError("未知的功能位：%r（major/minor/patch）" % (kind,))


def parse(text: str) -> Version:
    return Version.parse(text)


def bump(current: str, action: str, kind: str = "minor") -> Version:
    """按规则算下一版本。action: fix / promote-rc / ga / feature。"""
    cur = Version.parse(current)
    if action == "fix":
        return cur.next_fix()
    if action == "promote-rc":
        return cur.next_rc()
    if action == "ga":
        return cur.next_ga()
    if action == "feature":
        return cur.next_feature(kind)
    raise ValueError("未知动作：%r（fix/promote-rc/ga/feature）" % (action,))


def describe(v: Version) -> str:
    """给人看的一句话说明（bump 工具打印用）。"""
    if v.stage == ALPHA:
        return "alpha 阶段：新功能刚落地，允许有 bug；用户实机验收通过后再转 rc"
    if v.stage == RC:
        return "rc 阶段（发布候选）：用户已实机验证，后续只修 bug；再改功能请回 alpha"
    return "GA 正式版：功能集完成，bug 收敛"
