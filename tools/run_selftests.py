"""离线自检总入口：一条命令跑全部 5 个自检，各自用独立临时数据目录。

为什么要它：
  * 5 个自检原本散在研究线 `variant_mod\\tools\\` 里，依赖那边的仓库根布局、真实证书目录
    和真实的 logs/runtime（跑一次会污染正在用的代理）。这里统一收口：
    - 证书：生成到 `build/test-certs/`（gitignore），**绝不碰** `certs/` 下的实机会话证书；
    - 运行数据：每个自检一个临时 `VMOD_DATA` 目录，互不影响；
    - 端口：沿用各测试固定端口（8444/8445/8446），串行跑不冲突。
  * 结果统一成 `RESULT=PASS|FAIL` 判定，退出码非 0 即门禁失败。

用法：
  python tools/run_selftests.py              # 跑全部
  python tools/run_selftests.py --only sticky
  python tools/run_selftests.py --keep       # 保留临时目录（排查失败用）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "build" / "test-certs"
GEN_CERTS = ROOT / "tools" / "gen_session_certs.py"
HOST = "api.live.prod.thehelldiversgame.com"
TIMEOUT = 180

TESTS = [
    ("basic", "tests/selftest.py", "白名单握手 / SNI 拒绝 / 改写生效"),
    ("rewrite", "tests/selftest_rewrite.py", "Status 改写 + 三战备上限 + 原有条目保留"),
    ("hot_reload", "tests/selftest_hot_reload.py", "selection.json 热重载 + 多选叠加 + 清空回落"),
    ("sticky", "tests/selftest_sticky.py", "粘性星球 + 上限 3"),
    ("faction", "tests/selftest_faction.py", "阵营隔离（纯函数，不需要证书/端口）"),
]


def ensure_test_certs(force=False):
    """准备测试证书：build/test-certs 下缺证书或快过期就重签（ca 模式，1 天）。"""
    session = CERT_DIR / "session.json"
    if session.exists() and not force:
        try:
            info = json.loads(session.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(str(info["not_after"]).replace("Z", "+00:00"))
            left = (exp - datetime.now(timezone.utc)).total_seconds()
            if info.get("mode") == "ca" and left > 3600:
                print("[certs] 复用 %s（剩余 %.1f 小时，指纹 %s）"
                      % (CERT_DIR, left / 3600, str(info.get("thumbprint_sha1"))[:12]))
                return True
        except Exception:
            pass
    if CERT_DIR.exists():
        shutil.rmtree(CERT_DIR, ignore_errors=True)
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    print("[certs] 生成测试证书 -> %s（ca 模式 1 天，不会碰 certs/ 的实机会话）" % CERT_DIR)
    r = subprocess.run([sys.executable, str(GEN_CERTS), "--out-dir", str(CERT_DIR),
                        "--host", HOST, "--mode", "ca", "--days", "1", "--force"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        print("[certs] FAIL: 证书生成失败")
        return False
    return True


def run_one(name, script, title):
    path = ROOT / script
    if not path.exists():
        return name, False, 0.0, "脚本不存在: %s" % script, "", None
    tmp = Path(tempfile.mkdtemp(prefix="hd2proxy-test-%s-" % name))
    env = os.environ.copy()
    env["VMOD_DATA"] = str(tmp)
    env["HD2PROXY_TEST_CERTS"] = str(CERT_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("HD2_GWE_EXTRA", None)      # 防止外部环境变量干扰（研究线遗留）
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, str(path)], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT)
        out = (r.stdout or "") + (r.stderr or "")
        ok = "RESULT=PASS" in out
        detail = ""
        for line in out.splitlines():
            if line.startswith("RESULT="):
                detail = line.strip()
        if not detail:
            detail = "无 RESULT 行（exit=%d）" % r.returncode
    except subprocess.TimeoutExpired:
        out, ok, detail = "", False, "超时 %ds" % TIMEOUT
    except Exception as e:      # noqa: BLE001
        out, ok, detail = "", False, repr(e)
    dur = time.time() - t0
    return name, ok, dur, detail, out, tmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑名字匹配的（如 sticky）")
    ap.add_argument("--keep", action="store_true", help="保留临时数据目录")
    ap.add_argument("--regen-certs", action="store_true", help="强制重签测试证书")
    a = ap.parse_args()

    print("=" * 72)
    print("hd2-proxy-toolkit 离线自检  |  仓库 %s" % ROOT)
    print("=" * 72)
    if not ensure_test_certs(force=a.regen_certs):
        return 2

    picked = [t for t in TESTS if not a.only or a.only in t[0]]
    if not picked:
        print("没有匹配的测试名: %r（可选：%s）" % (a.only, ", ".join(t[0] for t in TESTS)))
        return 2

    results, tmpdirs = [], []
    for name, script, title in picked:
        print("\n---- [%s] %s ----" % (name, title))
        name, ok, dur, detail, out, tmp = run_one(name, script, title)
        tmpdirs.append(tmp)
        if out:
            print(out.rstrip())
        results.append((name, ok, dur, detail))
        print("---- [%s] %s（%.1fs）----" % (name, "PASS" if ok else "FAIL", dur))

    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    bad = 0
    for name, ok, dur, detail in results:
        if not ok:
            bad += 1
        print("  %-12s %-4s %6.1fs  %s" % (name, "PASS" if ok else "FAIL", dur, detail))
    print("\nGATE=%s (%d/%d)" % ("PASS" if bad == 0 else "FAIL", len(results) - bad, len(results)))

    if a.keep:
        print("\n临时数据目录（--keep）：")
        for d in tmpdirs:
            print("  " + str(d))
    else:
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
