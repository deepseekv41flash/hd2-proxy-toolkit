"""把一次打包产物同步到「release 产物测试区」：解包最新版 + 归档旧 zip + 写版本快照。

为什么需要：手工从 dist/ 拷 zip、再解压、再清理旧版本，容易漏步骤或留一半旧文件
（实测踩过：测试区里混着两个版本，双击到的是旧 exe）。这里一条命令做完。

目录结构（area 默认取环境变量 HD2PROXY_TEST_AREA）：

  <area>/
    README.md              说明用途（首次自动生成）
    VERSION.txt            当前版本 / zip sha256 / 同步时间 / 来源
    artifacts/             当前版本的 zip + SHA256SUMS.txt + RELEASE notes
    archive/               历史版本的 zip + SHA256SUMS.txt（默认保留最近 3 个）
    current/               最新版解压结果（双击 current/hd2proxy/hd2proxy-gui.exe 测试）
      hd2proxy/...

用法（在仓库根；测试区目录自己定，下面用相对路径举例）：
  python tools/sync_release_area.py --area ..\release-test
  python tools/sync_release_area.py --area ... --zip dist/xxx.zip --keep 3
  $env:HD2PROXY_TEST_AREA = '<测试区绝对路径>'; python tools/build_dist.py   # 构建完自动同步
"""

import argparse
import hashlib
import os
import shutil
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
- `artifacts/`：当前版本的 zip、`SHA256SUMS.txt`、Release Notes。
- `archive/`：历史版本（只保留最近几个），方便回滚对比。
- `VERSION.txt`：当前版本号 / zip sha256 / 同步时间 / 来源。

每次打包发版后更新（在仓库根）：

```powershell
python tools/sync_release_area.py --area ..\release-test
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


def archive_previous(area, keep):
    """把 artifacts/ 里不同版本的文件挪到 archive/，并只保留最近 keep 个版本。"""
    art = area / "artifacts"
    arch = area / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    for item in list(art.iterdir()):
        if item.name.startswith(NAME + "-toolkit-v") and item.name.endswith(".zip"):
            target = arch / item.name
            if target.exists():
                item.unlink()
            else:
                shutil.move(str(item), str(target))
    # 同版本的 SHA256SUMS / notes 直接覆盖，不归档
    for item in list(art.iterdir()):
        if item.name == "SHA256SUMS.txt":
            item.unlink()
    # 归档里的 sums 由 zip 名区分
    zips = sorted(arch.glob(NAME + "-toolkit-v*.zip"), key=lambda p: p.stat().st_mtime)
    for old in zips[:max(0, len(zips) - keep)]:
        old.unlink(missing_ok=True)
        (arch / (old.stem + ".SHA256SUMS.txt")).unlink(missing_ok=True)
    return zips


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


def sync(area_dir, zip_arg="", keep=DEFAULT_KEEP, quiet=False):
    """执行同步；返回 (version, zip_path, sha, area)。"""
    area = Path(area_dir).expanduser().resolve()
    area.mkdir(parents=True, exist_ok=True)
    (area / "artifacts").mkdir(exist_ok=True)
    (area / "archive").mkdir(exist_ok=True)
    readme = area / "README.md"
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")

    zip_path = find_zip(zip_arg).resolve()
    digest = sha256(zip_path)
    sums_src = zip_path.parent / "SHA256SUMS.txt"
    if sums_src.exists():
        # 校验和文件必须与我们要同步的 zip 对得上，否则说明 dist 半新半旧
        want = None
        for line in sums_src.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].endswith(zip_path.name):
                want = parts[0].lower()
        if want and want != digest:
            raise SystemExit("SHA256SUMS.txt 与 zip 不匹配：文件 %s vs 实测 %s" % (want, digest))

    archive_previous(area, keep)

    art = area / "artifacts"
    for suffix in art.glob("%s-toolkit-v*.zip" % NAME):
        suffix.unlink()
    shutil.copy2(zip_path, art / zip_path.name)
    if sums_src.exists():
        shutil.copy2(sums_src, art / "SHA256SUMS.txt")
    notes = ROOT / "docs" / ("RELEASE-v%s.md" % __version__)
    if notes.exists():
        shutil.copy2(notes, art / notes.name)

    cur, exes = extract(area, zip_path)
    (area / "VERSION.txt").write_text(
        "\n".join([
            "version   : v%s" % __version__,
            "zip       : %s" % zip_path.name,
            "sha256    : %s" % digest,
            "synced_at : %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
            "source    : %s" % zip_path.parent,
            "current   : %s" % cur,
            "",
        ]), encoding="utf-8")

    if not quiet:
        print("area      : %s" % area)
        print("version   : v%s" % __version__)
        print("zip       : %s（sha256 %s）" % (zip_path.name, digest[:16] + "…"))
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
    ap.add_argument("--zip", default="", help="指定 zip（默认取 dist/ 里最新的）")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help="archive 里保留的历史版本数（默认 %d）" % DEFAULT_KEEP)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not a.area:
        raise SystemExit("需要 --area 或环境变量 HD2PROXY_TEST_AREA")
    sync(a.area, a.zip, a.keep, quiet=a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
