"""按版本规则计算下一版本号并改两处版本串（docs/VERSIONING.md 的实现）。

规则：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动 `alpha.N` / `rc.N`。

用法（在仓库根）：
  python tools/bump_version.py fix              # 只修 bug：alpha.4 -> alpha.5（rc 同理）
  python tools/bump_version.py fix --dry-run    # 只看结果，不写文件
  python tools/bump_version.py promote-rc       # alpha.N -> rc.1（用户实机验收通过后）
  python tools/bump_version.py ga               # rc.N -> X.Y.Z
  python tools/bump_version.py feature --minor  # 功能更新：0.1.0 -> 0.2.0-alpha.1
  python tools/bump_version.py feature --patch  # 小幅功能扩展
  python tools/bump_version.py feature --major  # 破坏性改动
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hd2proxy  # noqa: E402
from hd2proxy import versioning  # noqa: E402

INIT = ROOT / "src" / "hd2proxy" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"


def read_pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def write_versions(new: str) -> None:
    # 1) __version__
    text = INIT.read_text(encoding="utf-8")
    new_text, n = re.subn(r'(?m)^__version__\s*=\s*"[^"]+"',
                          '__version__ = "%s"' % new, text, count=1)
    if n != 1:
        raise SystemExit("没能在 %s 里找到 __version__ 行" % INIT)
    INIT.write_text(new_text, encoding="utf-8")

    # 2) pyproject 的 PEP 440
    pep = versioning.parse(new).pep440()
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, n = re.subn(r'(?m)^version\s*=\s*"[^"]+"',
                          'version = "%s"' % pep, text, count=1)
    if n != 1:
        raise SystemExit("没能在 %s 里找到 version 行" % PYPROJECT)
    PYPROJECT.write_text(new_text, encoding="utf-8")


def print_next_steps(old: str, new: str) -> None:
    v = versioning.parse(new)
    print("")
    print("接下来还要做的事（工具只管版本串）：")
    print("  1) CHANGELOG.md 顶部加一条：## v%s（2026-MM-DD）— <一句话>" % new)
    print("  2) 新建 docs/RELEASE-v%s.md（Release Notes，标题写 v%s）" % (new, new))
    print("  3) README 里的版本引用/下载链接（若已发版）：%s → %s" % (old, new))
    if v.stage != versioning.GA:
        print("  4) 发 GitHub prerelease：gh release create v%s --prerelease …" % new)
    else:
        print("  4) 发 GitHub 正式 release（GA 不带 prerelease）")
    print("  5) 发完 release 后同步测试区：python tools/sync_release_area.py --area <测试区>")
    print("")
    print("阶段说明：%s" % versioning.describe(v))
    if v.stage == versioning.RC:
        print("提醒：转 rc 前应有用户实机验收记录（docs/ACCEPTANCE-*.md）。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="按版本规则计算并应用下一版本号")
    ap.add_argument("action", choices=["fix", "promote-rc", "ga", "feature"],
                    help="fix=只修 bug；promote-rc=alpha→rc；ga=rc→正式；feature=功能更新")
    ap.add_argument("--kind", choices=["major", "minor", "patch"], default="",
                    help="feature 时改哪一位（默认 minor）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    a = ap.parse_args(argv)

    current = hd2proxy.__version__
    kind = a.kind or ("minor" if a.action == "feature" else "")
    try:
        new = str(versioning.bump(current, a.action, kind))
    except ValueError as e:
        print("拒绝执行：%s" % e)
        return 2

    py_ver = read_pyproject_version()
    want_pep = versioning.parse(current).pep440()
    print("当前版本 : %s（pyproject: %s%s）"
          % (current, py_ver, "" if py_ver == want_pep else "  ← 与规则不一致，建议先修"))
    print("动作     : %s%s" % (a.action, (" (%s)" % kind) if kind else ""))
    print("下一版本 : %s（PEP 440: %s）" % (new, versioning.parse(new).pep440()))

    if a.dry_run:
        print("\n[dry-run] 未写文件。")
        print_next_steps(current, new)
        return 0

    write_versions(new)
    print("已更新：%s、%s" % (INIT.relative_to(ROOT), PYPROJECT.relative_to(ROOT)))
    print_next_steps(current, new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
