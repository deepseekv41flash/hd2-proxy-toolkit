"""CLI 入口（M0 最小版）。

M0 只提供「跑引擎 / 跑自检 / 跑门禁 / 看路径」四件事，目的是让 clone 下来的人不用记脚本路径；
M1 会扩成 `gui / engine / install / uninstall / verify / config` 全套。

用法（源码树内，未安装时）：
  set PYTHONPATH=src
  python -m hd2proxy info
  python -m hd2proxy engine --help
  python -m hd2proxy selftest
  python -m hd2proxy gate
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # 仓库根（src/hd2proxy/__main__.py 往上两级）
ENGINE = ROOT / "src" / "hd2proxy" / "engine" / "legacy_proxy.py"
TOOLS = ROOT / "tools"

COMMANDS = ("engine", "selftest", "gate", "info")


def _run_script(path, extra):
    cmd = [sys.executable, str(path)] + list(extra)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def info():
    import hd2proxy
    print("hd2-proxy-toolkit %s" % hd2proxy.__version__)
    print("repo        : %s" % ROOT)
    print("engine      : %s%s" % (ENGINE, "" if ENGINE.exists() else "  (缺失!)"))
    print("legacy data : %s" % (ROOT / "data" / "legacy"))
    print("catalogs    : %s" % (ROOT / "data" / "catalogs"))
    certs = ROOT / "certs" / "session.json"
    print("会话证书    : %s" % (certs if certs.exists() else "（未生成，M1 会由安装流程负责）"))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("用法: python -m hd2proxy <%s> [参数...]" % "|".join(COMMANDS))
        print("  engine    起代理引擎（参数同 legacy_proxy.py）")
        print("  selftest  跑 5 个离线自检（tools/run_selftests.py）")
        print("  gate      跑 M0 门禁（tools/check_gate.py）")
        print("  info      打印版本与路径")
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "info":
        return info()
    if cmd == "engine":
        return _run_script(ENGINE, rest)
    if cmd == "selftest":
        return _run_script(TOOLS / "run_selftests.py", rest)
    if cmd == "gate":
        return _run_script(TOOLS / "check_gate.py", rest)
    print("未知子命令: %r（可选：%s）" % (cmd, ", ".join(COMMANDS)))
    return 2


if __name__ == "__main__":
    sys.exit(main())
