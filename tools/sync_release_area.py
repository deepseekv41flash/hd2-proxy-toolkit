"""把一次打包产物同步到「release 产物测试区」：解包最新版 + 归档旧 zip + 写版本快照。

为什么需要：手工从 dist/ 拷 zip、再解压、再清理旧版本，容易漏步骤或留一半旧文件
（实测踩过：测试区里混着两个版本，双击到的是旧 exe）。这里一条命令做完。

**默认优先从 GitHub Release 下载当前版本的资产**，而不是拿本地 dist/ 的 zip 重拷：
每次重新打 zip 的时间戳不同 → 字节不同 → 哈希不同（同一个 exe 内容相同），测试区应该
与「用户实际下载到的东西」一致，才谈得上验证发布产物。

目录结构（area 默认取环境变量 HD2PROXY_TEST_AREA）：

  <area>/
    README.md              说明用途（首次自动生成）
    VERSION.txt            当前版本 / zip sha256 / 同步时间 / 来源（release 或 dist）
    artifacts/             当前版本的 zip + SHA256SUMS.txt + RELEASE notes
    archive/               历史版本的 zip + SHA256SUMS.txt（默认保留最近 3 个）
    current/               最新版解压结果（双击 current/hd2proxy/hd2proxy-gui.exe 测试）
      hd2proxy/...

用法（在仓库根；测试区目录自己定，下面用相对路径举例）：
  python tools/sync_release_area.py --area ..\\release-test             # 优先用 Release 资产
  python tools/sync_release_area.py --area ..\\release-test --source dist
  python tools/sync_release_area.py --area ... --zip dist/xxx.zip --keep 3
  $env:HD2PROXY_TEST_AREA = '<测试区绝对路径>'; python tools/build_dist.py   # 构建完自动同步
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hd2proxy import __version__  # noqa: E402

DIST = ROOT / "dist"
NAME = "hd2proxy"
DEFAULT_KEEP = 3

README_TEXT = """# release 产物测试区

这个目录只用来**验证发布产物**，不是源码仓库的一部分。

- `current/`：最新发布版的解压结果 —— 测试时直接双击 `current/hd2proxy/hd2proxy-gui.exe`。
- `artifacts/`：当前版本的 zip、`SHA256SUMS.txt`、Release Notes（优先取自 GitHub Release）。
- `archive/`：历史版本（只保留最近几个），方便回滚对比。
- `VERSION.txt`：当前版本号 / zip sha256 / 同步时间 / 来源。

每次打包发版后更新（在仓库根）：

```powershell
python tools/sync_release_area.py --area ..\\release-test
# 或者构建时直接同步：
$env:HD2PROXY_TEST_AREA = '<测试区绝对路径>'
python tools/build_dist.py
```
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def version_of_zip(name: str) -> str:
    """hd2proxy-toolkit-v0.1.0-alpha.4-windows-x64.zip -> 0.1.0-alpha.4"""
    try:
        return Path(name).name.split("-toolkit-v", 1)[1].split("-windows-x64", 1)[0]
    except IndexError:
        return ""


def find_zip(explicit=""):
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise SystemExit("找不到 --zip 指定的文件：%s" % p)
        return p
    zips = sorted(DIST.glob("%s-toolkit-v*-windows-x64.zip" % NAME),
                  key=lambda p: p.stat().st_mtime)
    if not zips:
        raise SystemExit("dist/ 里没有分发包 zip，先跑 python tools/build_dist.py")
    return zips[-1]


def fetch_release(dest: Path, version: str) -> bool:
    """从 GitHub Release 拉当前版本的 zip + SHA256SUMS 到 dest；失败返回 False。"""
    if not shutil.which("gh"):
        return False
    tag = "v%s" % version
    try:
        probe = subprocess.run(["gh", "release", "view", tag, "--json", "assets"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=60)
        if probe.returncode != 0:
            return False
        dest.mkdir(parents=True, exist_ok=True)
        got = subprocess.run(
            ["gh", "release", "download", tag,
             "--pattern", "*-windows-x64.zip", "--pattern", "SHA256SUMS.txt",
             "--dir", str(dest), "--clobber"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        return got.returncode == 0 and any(dest.glob("*-windows-x64.zip"))
    except (OSError, subprocess.SubprocessError):
        return False


def archive_previous(area, keep):
    """把 artifacts/ 里**旧版本**的 zip 挪到 archive/，同版本的旧文件直接删（会被覆盖）。"""
    art = area / "artifacts"
    arch = area / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    for item in list(art.iterdir()):
        if not (item.name.startswith(NAME + "-toolkit-v") and item.name.endswith(".zip")):
            continue
        if version_of_zip(item.name) == __version__:
            item.unlink(missing_ok=True)          # 同版本旧包，稍后放新的
            continue
        target = arch / item.name
        target.unlink(missing_ok=True)
        shutil.move(str(item), str(target))
    (art / "SHA256SUMS.txt").unlink(missing_ok=True)
    zips = sorted(arch.glob(NAME + "-toolkit-v*.zip"), key=lambda p: p.stat().st_mtime)
    for old in zips[:max(0, len(zips) - keep)]:
        old.unlink(missing_ok=True)
    return zips


def check_sums(zip_path: Path, sums_path: Path):
    """SHA256SUMS 里若有这个 zip 的条目，必须与实测一致（防止 dist 半新半旧）。"""
    if not sums_path.exists():
        return None
    want = None
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].endswith(zip_path.name):
            want = parts[0].lower()
    digest = sha256(zip_path)
    if want and want != digest:
        raise SystemExit("SHA256SUMS.txt 与 zip 不匹配：%s vs %s" % (want, digest))
    return digest


def extract(area, zip_path):
    cur = area / "current"
    if cur.exists():
        shutil.rmtree(cur)
    cur.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cur)
    exes = list(cur.rglob("*.exe"))
    if not exes:
        raise SystemExit("解压后没找到 exe：%s" % cur)
    return cur, exes


def sync(area_dir, zip_arg="", keep=DEFAULT_KEEP, source="auto", quiet=False):
    """执行同步；返回 (version, zip_path, sha, area)。"""
    area = Path(area_dir).expanduser().resolve()
    area.mkdir(parents=True, exist_ok=True)
    art = area / "artifacts"
    art.mkdir(exist_ok=True)
    (area / "archive").mkdir(exist_ok=True)
    readme = area / "README.md"
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")

    archive_previous(area, keep)

    zip_path = None
    origin = ""
    if zip_arg:
        zip_path = Path(zip_arg).resolve()
        origin = "指定文件"
    elif source in ("auto", "release") and fetch_release(art, __version__):
        zips = sorted(art.glob("*-windows-x64.zip"), key=lambda p: p.stat().st_mtime)
        if zips:
            zip_path = zips[-1]
            origin = "GitHub release v%s" % __version__
    if zip_path is None:
        if source == "release":
            raise SystemExit("从 GitHub Release 取资产失败（v%s）" % __version__)
        zip_path = find_zip("")
        origin = "dist/"
        print("  （Release 资产不可用或指定 --source dist，改用本地 dist/ zip）")

    digest = check_sums(zip_path, zip_path.parent / "SHA256SUMS.txt") or sha256(zip_path)

    # 统一放到 artifacts/
    if zip_path.parent != art:
        for suffix in art.glob(NAME + "-toolkit-v*.zip"):
            suffix.unlink(missing_ok=True)
        shutil.copy2(zip_path, art / zip_path.name)
        sums_src = zip_path.parent / "SHA256SUMS.txt"
        if sums_src.exists():
            shutil.copy2(sums_src, art / "SHA256SUMS.txt")
        zip_path = art / zip_path.name
    else:
        if not (art / "SHA256SUMS.txt").exists():
            sums_src = zip_path.parent / "SHA256SUMS.txt"
            if sums_src.exists():
                shutil.copy2(sums_src, art / "SHA256SUMS.txt")
    notes = ROOT / "docs" / ("RELEASE-v%s.md" % __version__)
    if notes.exists():
        shutil.copy2(notes, art / notes.name)

    cur, exes = extract(area, zip_path)

    # 关键：本工具常常跑在 Low 完整性上下文（DSH shell 等），解压出的文件会继承 Low 标签 →
    # 用户双击 exe 也会只有 Low IL，写不了 %LOCALAPPDATA%（Medium），表现为 GUI 里
    # 「保存配置 / 证书签发 / 启动引擎」PermissionError(13)。这里把测试区标回 Medium ✓
    sys.path.insert(0, str(ROOT / "tools"))
    from win_integrity import describe as _integrity_note
    area_note = _integrity_note(area)
    if not quiet:
        print("  " + area_note)

    (area / "VERSION.txt").write_text(
        "\n".join([
            "version   : v%s" % __version__,
            "zip       : %s" % zip_path.name,
            "sha256    : %s" % digest,
            "source    : %s" % origin,
            "synced_at : %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
            "current   : %s" % cur,
            "",
        ]), encoding="utf-8")

    if not quiet:
        print("area      : %s" % area)
        print("version   : v%s（来源：%s）" % (__version__, origin))
        print("zip       : %s" % zip_path.name)
        print("sha256    : %s" % digest)
        print("current   : %s（%d 个 exe）" % (cur, len(exes)))
        for exe in sorted(exes):
            print("  · %s" % exe.relative_to(area))
        arch = sorted((area / "archive").glob(NAME + "-toolkit-v*.zip"))
        print("archive   : %d 个历史版本" % len(arch))
    return __version__, zip_path, digest, area


def main(argv=None):
    ap = argparse.ArgumentParser(description="把打包产物同步到 release 产物测试区")
    ap.add_argument("--area", default=os.environ.get("HD2PROXY_TEST_AREA", ""),
                    help="测试区目录（默认取 HD2PROXY_TEST_AREA）")
    ap.add_argument("--zip", default="", help="指定 zip（默认取 Release 资产或 dist/ 最新）")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help="archive 里保留的历史版本数（默认 %d）" % DEFAULT_KEEP)
    ap.add_argument("--source", choices=["auto", "release", "dist"], default="auto",
                    help="auto=优先 Release 资产；dist=用本地 dist/ 的 zip")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not a.area:
        raise SystemExit("需要 --area 或环境变量 HD2PROXY_TEST_AREA")
    sync(a.area, a.zip, a.keep, source=a.source, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
