"""版本一致性检查（门禁第 5 步，规则见 docs/VERSIONING.md）。

检查项：
  1. `__version__` 符合 X.Y.Z / X.Y.Z-alpha.N / X.Y.Z-rc.N；
  2. `pyproject.toml` 的 PEP 440 写法与 `__version__` 一致（0.1.0-alpha.4 ↔ 0.1.0a4）；
  3. `CHANGELOG.md` 里有对应 `## v<version>` 条目；
  4. 该版本若已打 git tag，则 `docs/RELEASE-v<version>.md` 必须存在。

退出码：0=GATE=PASS，2=GATE=FAIL。用法：python tools/check_version.py
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hd2proxy  # noqa: E402
from hd2proxy import versioning  # noqa: E402


def _pep440_pyproject() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data.get("project", {}).get("version", ""))


def _has_tag(tag: str) -> bool:
    try:
        r = subprocess.run(["git", "tag", "--list", tag], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == tag


def main() -> int:
    version = hd2proxy.__version__
    problems = []
    notes = []

    # 1) 格式
    try:
        parsed = versioning.parse(version)
    except ValueError as e:
        print("  [FAIL] 版本格式：%s" % e)
        print("\nGATE=FAIL")
        return 2
    print("  版本      : %s（阶段 %s，PEP 440 %s）"
          % (version, parsed.stage, parsed.pep440()))

    # 2) pyproject 一致性
    py_ver = _pep440_pyproject()
    if py_ver != parsed.pep440():
        problems.append("pyproject.toml 版本 %r != 期望 %r（按规则应为 %s 的 PEP 440 写法）"
                        % (py_ver, parsed.pep440(), version))
    print("  pyproject : %s" % (py_ver or "(缺失)"))

    # 3) CHANGELOG 条目
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    entry_re = re.compile(r"(?m)^##\s+v%s\b" % re.escape(version))
    if not entry_re.search(changelog):
        problems.append("CHANGELOG.md 里没有 `## v%s` 条目（bump 后会提示补）" % version)
    print("  CHANGELOG : %s" % ("有 v%s 条目" % version if entry_re.search(changelog) else "缺条目"))

    # 4) 已打 tag 就必须有 Release Notes
    tag = "v%s" % version
    notes_path = ROOT / "docs" / ("RELEASE-%s.md" % tag)
    if _has_tag(tag):
        if not notes_path.exists():
            problems.append("已打 tag %s，但缺 %s" % (tag, notes_path.relative_to(ROOT)))
        else:
            notes.append("docs/RELEASE-%s.md 存在" % tag)
    else:
        notes.append("未打 tag %s（发版前 Release Notes 可稍后补）" % tag)
    for n in notes:
        print("  备注      : %s" % n)

    if problems:
        for p in problems:
            print("  [FAIL] %s" % p)
        print("\nGATE=FAIL")
        return 2
    print("\nGATE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
