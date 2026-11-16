"""M5 打包发布：PyInstaller（单 bundle 双 exe）+ ZIP + SHA256 + 冒烟 + 干净路径验证。

产物（一个 onedir 目录里放两个 exe，共用 _internal）：
  hd2proxy.exe       控制台 CLI（engine/install/uninstall/preview/verify/…；双击也会开 GUI）
  hd2proxy-gui.exe   windowed GUI（双击无控制台，给普通用户用）
  data/              可编辑数据（legacy / catalogs / samples / acceptance）

用法（在仓库根）：
  python tools/build_dist.py                # 构建 + 冒烟 + 打包 + 干净路径验证
  python tools/build_dist.py --skip-build   # 只做打包/验证（复用已有 dist）
  python tools/build_dist.py --no-zip       # 只构建 + 冒烟（方便反复调）

冒烟项（都用打包后的 exe）：
  * `--version` / `info` / `preview`（CLI）
  * `hd2proxy.exe` 无参数 → 应打开 GUI 并存活（v0.1.0-alpha.1 的「双击即退出」修复）
  * `hd2proxy-gui.exe` 双击等价 → GUI 窗口存活
  * zip 解压到临时目录 → 用包内 data 再跑一次 preview（干净路径）
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
from hd2proxy import __version__  # noqa: E402  （显示版本，如 0.1.0-alpha.2）

NAME = "hd2proxy"
DIST = ROOT / "dist"
BUILD = ROOT / "build" / "pyinstaller"
ZIP_NAME = "hd2proxy-toolkit-v%s-windows-x64" % __version__

SPEC = '''# -*- mode: python ; coding: utf-8 -*-
# 由 tools/build_dist.py 生成（不入库）：同一个 bundle 里构建 console CLI + windowed GUI 两个 exe。
from pathlib import Path

ROOT = Path(r"__ROOT__")
SRC = ROOT / "src"
DATA = ROOT / "data"

a_cli = Analysis(
    [str(ROOT / "tools" / "pyinstaller_entry.py")],
    pathex=[str(SRC)], binaries=[], datas=[(str(DATA), "data")],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="hd2proxy",
              debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              console=True, disable_windowed_traceback=False, argv_emulation=False,
              target_arch=None, codesign_identity=None, entitlements_file=None)

a_gui = Analysis(
    [str(ROOT / "tools" / "pyinstaller_gui_entry.py")],
    pathex=[str(SRC)], binaries=[], datas=[],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[], noarchive=False, optimize=0,
)
pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="hd2proxy-gui",
              debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
              console=False, disable_windowed_traceback=False, argv_emulation=False,
              target_arch=None, codesign_identity=None, entitlements_file=None)

coll = COLLECT(exe_cli, a_cli.binaries, a_cli.datas, exe_gui, a_gui.binaries,
               strip=False, upx=False, upx_exclude=[], name="__NAME__")
'''


def exe_path(name: str) -> Path:
    return DIST / NAME / (name + ".exe")


CLI_EXE = exe_path("hd2proxy")
GUI_EXE = exe_path("hd2proxy-gui")


def run(cmd, *, timeout=600, check=True):
    print("+ " + " ".join(str(x) for x in cmd), flush=True)
    env = dict(os.environ)
    # 打包后的 exe 也走 UTF-8 输出，否则中文在管道里会按 cp936 编码、断言取不到
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run([str(x) for x in cmd], timeout=timeout, check=check,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def _gui_env():
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _main_window_title(process_name: str) -> str:
    r = run(["powershell", "-NoProfile", "-Command",
             "(Get-Process '%s' -ErrorAction SilentlyContinue | "
             "Where-Object { $_.MainWindowTitle } | Select-Object -First 1"
             ").MainWindowTitle" % process_name], check=False, timeout=60)
    return (r.stdout or "").strip()


def _smoke_gui(label: str, exe: Path):
    """启动 exe，等 6s 确认进程存活且有主窗口，然后强杀。"""
    proc = subprocess.Popen([str(exe)], env=_gui_env())
    try:
        time.sleep(6)
        if proc.poll() is not None:
            raise SystemExit("%s 启动后退出（rc=%s）" % (label, proc.returncode))
        title = _main_window_title(exe.stem)
        if not title:
            raise SystemExit("%s 进程存活但没有主窗口（GUI 未打开）" % label)
        print("  OK  %s 窗口存活（pid=%s，标题非空）" % (label, proc.pid))
    finally:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:                          # noqa: BLE001
            pass


def build():
    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d)
    BUILD.mkdir(parents=True, exist_ok=True)
    spec = BUILD / (NAME + ".spec")
    spec.write_text(SPEC.replace("__ROOT__", ROOT.as_posix())
                   .replace("__NAME__", NAME), encoding="utf-8")
    result = run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD,
        spec,
    ])
    tail = (result.stdout or "").strip().splitlines()[-2:]
    for line in tail:
        print("  " + line)
    for exe in (CLI_EXE, GUI_EXE):
        if not exe.exists():
            raise SystemExit("构建失败：%s 不存在" % exe)


def sign_local():
    """可选：用**本机自签证书**给两个 exe 签名（仅当 HD2PROXY_SIGN=1）。

    为什么默认关：自签证书只对「本机已信任这张证书」的机器有意义（方便本地测试不被
    SmartScreen 拦），对别人下载这个 zip 没有增益；CI 也没有私钥，不该默认签。
    本机发版想免 SmartScreen：先跑一次 tools/sign_local.ps1 -Install 装信任，再
      set HD2PROXY_SIGN=1 && python tools/build_dist.py
    """
    if os.environ.get("HD2PROXY_SIGN", "").lower() not in ("1", "true", "yes"):
        print("sign: 跳过（设 HD2PROXY_SIGN=1 可用本机自签证书签名）")
        return
    script = ROOT / "tools" / "sign_local.ps1"
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not script.exists() or not shell:
        raise SystemExit("签名不可用：缺少 tools/sign_local.ps1 或 pwsh/powershell")
    r = run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-Install", "-DistDir", str(DIST / NAME)])
    # 子进程（certutil 等）可能吐出非 UTF-8 字节 → 解出来带 U+FFFD；打印前降级成 ?，
    # 否则在 GBK 控制台会再抛 UnicodeEncodeError（实测踩过）
    for line in (r.stdout or "").strip().splitlines()[-10:]:
        print("  " + line.replace("\ufffd", "?"))
    if r.returncode != 0:
        raise SystemExit("签名失败（rc=%s）\n%s"
                         % (r.returncode, (r.stderr or "").replace("\ufffd", "?")[-1500:]))


def stage_data():
    """把 data/ 复制到 exe 旁边：用户可直接改 catalogs/acceptance（便携目录）。"""
    target = DIST / NAME / "data"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT / "data", target)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print("data staged: %s (%.1f MB)" % (target, size / 1048576))


def smoke():
    """打包后 exe 冒烟：CLI 三条路径 + 两个 GUI 入口（含 alpha.1 双击退出回归）。"""
    checks = [
        (["--version"], __version__),
        (["info"], "state_dir"),
        (["preview", "--profile", ROOT / "data" / "acceptance" / "m4-b.json",
          "--fixture", "status"], "Status"),
    ]
    for args, needle in checks:
        r = run([CLI_EXE] + args, check=False)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or needle not in out:
            raise SystemExit("冒烟失败 %s（rc=%s，找不到 %r）\n%s"
                             % (args, r.returncode, needle, out[-1500:]))
        print("  OK  hd2proxy.exe %s" % " ".join(str(x) for x in args))
    # 双击 CLI exe（无参数）应当打开 GUI，而不是打印帮助后退出
    _smoke_gui("hd2proxy.exe（无参数）", CLI_EXE)
    # 专用 windowed GUI exe（双击无控制台）
    _smoke_gui("hd2proxy-gui.exe", GUI_EXE)


def make_zip():
    # 注意：base 名里带版本号（含点），路径工具会误判 suffix，必须用 make_archive 的返回值
    zip_path = Path(shutil.make_archive(str(DIST / ZIP_NAME), "zip",
                                       root_dir=str(DIST), base_dir=NAME))
    print("zip: %s (%.1f MB)" % (zip_path, zip_path.stat().st_size / 1048576))
    return zip_path


def write_sha256(zip_path):
    lines = []
    for path in (zip_path, CLI_EXE, GUI_EXE):
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
        root = tmp / NAME
        for exe in ("hd2proxy.exe", "hd2proxy-gui.exe"):
            if not (root / exe).exists():
                raise SystemExit("zip 里缺少 %s" % exe)
        profile = root / "data" / "acceptance" / "m4-b.json"
        r = run([root / "hd2proxy.exe", "preview", "--profile", profile,
                 "--fixture", "status"], check=False, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or not any(k in out for k in ("合计", "Status")):
            raise SystemExit("干净路径验证失败（rc=%s）\n%s" % (r.returncode, out[-1500:]))
        print("  OK  干净路径解压后 preview 正常（%d 字节输出）" % len(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="打包 hd2proxy（PyInstaller 单 bundle 双 exe + zip）")
    ap.add_argument("--skip-build", action="store_true", help="复用已有 dist 产物")
    ap.add_argument("--no-zip", action="store_true", help="不打包 zip/校验和/干净路径验证")
    a = ap.parse_args(argv)

    # 控制台可能是 GBK：子进程输出里偶有 U+FFFD，直接 print 会 UnicodeEncodeError 假失败
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

    t0 = time.time()
    if a.skip_build:
        for exe in (CLI_EXE, GUI_EXE):
            if not exe.exists():
                raise SystemExit("--skip-build 但 %s 不存在" % exe)
    else:
        build()
    stage_data()
    sign_local()
    smoke()
    if not a.no_zip:
        zip_path = make_zip()
        write_sha256(zip_path)
        verify_clean_path(zip_path)
    print("done: %.1fs" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
