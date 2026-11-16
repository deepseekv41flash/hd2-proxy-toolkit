"""M0 门禁脚本：一条命令复现"能不能提交"的判定。

三项检查：
  1. 语法：src/ tests/ tools/ 下所有 .py 都能 py_compile 通过；
  2. 不写死本机路径：代码里不得出现 `D:\\` / `D:/` 这类绝对路径（docs / research 除外，
     那里是证据与说明，允许出现）；
  3. 离线自检：调用 tools/run_selftests.py，要求 GATE=PASS。

用法：
  python tools/check_gate.py                 # 1+2+3
  python tools/check_gate.py --no-tests      # 只跑 1+2（快速）
"""

import argparse
import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ["src", "tests", "tools"]
ABS_PATH_RE = re.compile(r"""["'](?:[A-Za-z]:[\\/]|\\\\)""")


def check_compile():
    bad = []
    count = 0
    for d in CODE_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            count += 1
            try:
                py_compile.compile(str(p), doraise=True, cfile=None)
            except py_compile.PyCompileError as e:
                bad.append((p.relative_to(ROOT), str(e).splitlines()[0]))
    for p, msg in bad:
        print("  [FAIL] %s: %s" % (p, msg))
    print("  py_compile: %d 个文件, %d 失败" % (count, len(bad)))
    return len(bad) == 0


def check_no_abs_paths():
    bad = []
    for d in CODE_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if ABS_PATH_RE.search(line):
                    bad.append((p.relative_to(ROOT), i, line.strip()[:110]))
    for p, i, line in bad:
        print("  [FAIL] %s:%d  %s" % (p, i, line))
    print("  绝对路径: %d 处（说明：代码里只允许环境变量/相对仓库根的路径）" % len(bad))
    return len(bad) == 0


def check_tests():
    env_note = "（输出见下方 run_selftests.py 汇总）"
    print("  运行离线自检 " + env_note)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "run_selftests.py")],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (r.stdout or "")[-1800:]
    print(tail.rstrip())
    ok = "GATE=PASS" in (r.stdout or "")
    if not ok and (r.stderr or "").strip():
        print("  stderr:", (r.stderr or "")[-800:])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tests", action="store_true", help="跳过离线自检")
    a = ap.parse_args()

    print("=" * 72)
    print("hd2-proxy-toolkit M0 门禁  |  %s" % ROOT)
    print("=" * 72)
    results = []
    print("\n[1/3] 语法检查")
    results.append(("py_compile", check_compile()))
    print("\n[2/3] 绝对路径检查")
    results.append(("no-abs-paths", check_no_abs_paths()))
    if not a.no_tests:
        print("\n[3/3] 离线自检")
        results.append(("selftests", check_tests()))

    print("\n" + "=" * 72)
    bad = [n for n, ok in results if not ok]
    for n, ok in results:
        print("  %-14s %s" % (n, "PASS" if ok else "FAIL"))
    print("\nGATE=%s" % ("PASS" if not bad else "FAIL(%s)" % ",".join(bad)))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
