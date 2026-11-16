"""M5 打包发布：PyInstaller onedir + ZIP + SHA256 + 冒烟 + 干净路径验证。

用法（在仓库根）：
  python tools/build_dist.py                # 构建 + 冒烟 + 打包 + 干净路径验证
  python tools/build_dist.py --skip-build   # 只做打包/验证（复用已有 dist）
  python tools/build_dist.py --no-zip       # 只构建 + 冒烟（方便反复调 spec）

产物：
  dist/hd2proxy/                                    onedir 目录（exe + _internal/data）
  dist/hd2proxy-toolkit-v<版本>-windows-x64.zip    分发包
  dist/SHA256SUMS.txt                               校验和（zip + exe）

设计要点：
  * `data/` 打进去（legacy / catalogs / samples / acceptance），保证解压即用；
  * 冒烟用**打包后的 exe**（不是源码），验证 --version / info / preview 三条路径；
  * 干净路径验证：把 zip 解到临时目录再跑 preview，证明不依赖仓库/本机路径。
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hd2proxy import __version__  # noqa: E402  （显示版本，如 0.1.0-alpha.1）

NAME = "hd2proxy"
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "pyinstaller"
ZIP_NAME = "hd2proxy-toolkit-v%s-windows-x64" % __version__
EXE = DIST / NAME / (NAME + ".exe")


def run(cmd, *, timeout=600, check=True):
    print("+ " + " ".join(str(x) for x in cmd), flush=True)
    env = dict(os.environ)
    # 打包后的 exe 也走 UTF-8 输出，否则中文在管道里会按 cp936 编码、断言取不到
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run([str(x) for x in cmd], timeout=timeout, check=check,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def build():
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)
    result = run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir",
        "--name", NAME,
        "--paths", ROOT / "src",
        "--add-data", "%s;data" % (ROOT / "data"),
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        ROOT / "tools" / "pyinstaller_entry.py",
    ])
    tail = (result.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("  " + line)
    if not EXE.exists():
        raise SystemExit("构建失败：%s 不存在" % EXE)


def stage_data():
    """把 data/ 复制到 exe 旁边：用户可直接改 catalogs/acceptance（便携目录）。

    _internal/data 里也有一份（双保险）；paths.py 在冻结模式下优先用 exe 旁那份。
    """
    target = DIST / NAME / "data"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "data", target)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print("data staged: %s (%.1f MB)" % (target, size / 1048576))


def smoke():
    """用打包后的 exe 跑三条最关键的路径（版本 / 路径 / 离线预演）。"""
    checks = [
        (["--version"], __version__),
        (["info"], "state_dir"),
        # 中文输出在不同控制台编码下会变乱码；用 ASCII 稳定串（脚本仍会打印全文）
        (["preview", "--profile", ROOT / "data" / "acceptance" / "m4-b.json",
          "--fixture", "status"], "Status"),
    ]
    for args, needle in checks:
        r = run([EXE] + args, check=False)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or needle not in out:
            raise SystemExit("冒烟失败 %s（rc=%s，找不到 %r）\n%s"
                             % (args, r.returncode, needle, out[-1500:]))
        print("  OK  hd2proxy.exe %s" % " ".join(str(x) for x in args))


def make_zip():
    # 注意：base 名里带版本号（含点），路径工具会误判 suffix，必须用 make_archive 的返回值
    zip_path = Path(shutil.make_archive(str(DIST / ZIP_NAME), "zip",
                                       root_dir=str(DIST), base_dir=NAME))
    print("zip: %s (%.1f MB)" % (zip_path, zip_path.stat().st_size / 1048576))
    return zip_path


def write_sha256(zip_path):
    lines = []
    for path in (zip_path, EXE):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append("%s  %s" % (digest, path.relative_to(DIST).as_posix()))
    out = DIST / "SHA256SUMS.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("sha256: %s" % out)
    for line in lines:
        print("  " + line)
    return out


def verify_clean_path(zip_path):
    """解压到临时目录，只用包内的 data 跑 preview（不碰仓库路径）。"""
    tmp = Path(tempfile.mkdtemp(prefix="hd2proxy-dist-"))
    try:
        shutil.unpack_archive(str(zip_path), str(tmp))
        exe = tmp / NAME / (NAME + ".exe")
        profile = tmp / NAME / "data" / "acceptance" / "m4-b.json"
        r = run([exe, "preview", "--profile", profile, "--fixture", "status"],
                check=False, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or not any(k in out for k in ("合计", "Status")):
            raise SystemExit("干净路径验证失败（rc=%s）\n%s" % (r.returncode, out[-1500:]))
        print("  OK  干净路径解压后 preview 正常（%d 字节输出）" % len(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="打包 hd2proxy（PyInstaller onedir + zip）")
    ap.add_argument("--skip-build", action="store_true", help="复用已有 dist 产物")
    ap.add_argument("--no-zip", action="store_true", help="不打包 zip/校验和/干净路径验证")
    a = ap.parse_args(argv)

    t0 = time.time()
    if a.skip_build:
        if not EXE.exists():
            raise SystemExit("--skip-build 但 %s 不存在" % EXE)
    else:
        build()
    stage_data()
    smoke()
    if not a.no_zip:
        zip_path = make_zip()
        write_sha256(zip_path)
        verify_clean_path(zip_path)
    print("done: %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
