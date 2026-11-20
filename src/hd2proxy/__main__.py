"""CLI 入口（M1）：引擎 / 安装 / 还原 / 证书 / profile / 运行期状态 / 验收。

设计：GUI（M2）只是这些能力的图形壳，**所有动作都能在命令行完成**，便于脚本、CI 与排障。

常用：
  python -m hd2proxy gui                              # 打开图形界面（M2/M3）
  python -m hd2proxy info                             # 版本与路径
  python -m hd2proxy profiles                         # 列出本机 profile
  python -m hd2proxy profiles list                    # 列出本机 profile
  python -m hd2proxy migrate                          # 旧 config.json/runtime -> profile
  python -m hd2proxy certs status                     # 证书状态（有效期/指纹/告警）
  python -m hd2proxy certs renew                      # 重新签发（ca 模式，≤2 天）
  python -m hd2proxy install --profile <p> --dry-run   # 只打印将改动什么（安全）
  python -m hd2proxy install --profile <p>             # 真安装（需要一次 UAC）
  python -m hd2proxy preview --profile <p>             # 离线预演：不开游戏看会改什么
  python -m hd2proxy live                              # 拉当前战况（无需游戏）+ 推荐可点靶星
  python -m hd2proxy engine --profile <p>              # 起引擎（前台）
  python -m hd2proxy status                            # 读运行中引擎状态
  python -m hd2proxy verify                            # 三连验收（TLS/CRL/Status）
  python -m hd2proxy shutdown                          # 让引擎优雅退出
  python -m hd2proxy uninstall --dry-run               # 还原（先看计划）

注意：源码树内使用需 `set PYTHONPATH=src`（或用 `pip install -e .`）。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
ROOT = SRC.parent
ENGINE = SRC / "hd2proxy" / "engine" / "legacy_proxy.py"
TOOLS = ROOT / "tools"

from hd2proxy.engine import (certs, config as cfgmod, installer,  # noqa: E402
                             live as live_mod, paths,
                             preview as preview_mod, sysprobe)

OK, FAIL = 0, 2


# ---------------------------------------------------------------- 小工具


def _out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _state():
    p = paths.engine_state_file()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _api(path, method="GET", body=None, token=None, url=None, timeout=90):
    state = _state() or {}
    base = (url or state.get("url") or "").rstrip("/")
    token = token or state.get("token")
    if not base:
        raise RuntimeError("没有发现运行中的引擎（%s 不存在）；先启动 engine" % paths.engine_state_file())
    data = None
    headers = {"X-HD2-Token": token or ""}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    # 本机控制面必须绕过系统代理（Windows 上 urllib 会读注册表里的代理设置）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # 现场踩过（2026-11-20）：另一个引擎实例覆盖了 engine.json，运行中引擎的随机 token
            # 随之丢失 —— GUI/CLI 全部 401，但引擎其实还在正常服务游戏。把「怎么办」写清楚。
            raise RuntimeError(
                "控制面拒绝鉴权（HTTP 401）：状态文件里的 token 与运行中的引擎不匹配。"
                "常见原因是另一个引擎实例覆盖了 %s。请重启引擎（GUI「停止引擎」→「启动引擎」），"
                "或删除该文件后重启引擎。" % paths.engine_state_file()) from None
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:                       # noqa: BLE001 - 读错误体失败不影响报错
            pass
        raise RuntimeError("控制面请求失败（HTTP %d）：%s"
                           % (e.code, detail.strip() or e.reason)) from None


def _run_script(path, extra):
    cmd = [sys.executable, str(path)] + list(extra)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def _load_profile(path):
    if not path:
        return None
    return cfgmod.load_profile_file(path)


def _default_profile_doc():
    """没有显式 ``--profile`` 时，尽量读**默认 profile**（GUI 用的那份）。

    为什么：install 是独立进程，以前不传 --profile 就直接 ``listen_ip="auto"``；
    而 TUN / 路由模式加速器会把默认路由转到虚拟网卡，auto 会解析成 198.18.x / 172.19.x，
    hosts 被写成那个地址 → 游戏连不到引擎（实测见 RELEASE-v0.4.1-alpha.5）。
    默认 profile 里通常已有显式 listen_ip（或至少是同一份配置口径），优先用它。
    """
    path = cfgmod.profile_path("default")
    if not path.is_file():
        return None
    try:
        return cfgmod.load_profile_file(path)
    except Exception:                           # noqa: BLE001 - 坏 profile 不该拦住 install
        return None


def _install_context(a):
    """组装 install/uninstall 需要的 host / listenIp / cert_dir / days / scope。"""
    profile = _load_profile(getattr(a, "profile", ""))
    if profile is None and not getattr(a, "profile", ""):
        profile = _default_profile_doc()
    if profile:
        proxy = profile["proxy"]
        host = proxy["host"]
        listen_value = proxy.get("listen_ip") or "auto"
        days = profile["cert"]["days"]
        scope = a.scope or "LocalMachine"
    else:
        host = certs.DEFAULT_HOST
        listen_value = "auto"
        days = 2
        scope = a.scope or "LocalMachine"
    if getattr(a, "listen_ip", ""):
        listen_value = a.listen_ip
    if getattr(a, "host", ""):
        host = a.host
    listen_ip = sysprobe.resolve_listen_ip(listen_value)
    cert_dir = Path(a.cert_dir) if getattr(a, "cert_dir", "") else (paths.state_dir() / "certs")
    return {"profile": profile, "host": host, "listen_ip": listen_ip,
            "cert_dir": cert_dir, "days": days, "scope": scope}


def _cli_hint():
    """提示语里该写的命令前缀：打包版是 hd2proxy.exe，源码树是 python -m hd2proxy。

    为什么需要：冻结版里 CLI 自己也打「python -m hd2proxy install …」，用户照抄会失败
    （打包版没有 python 环境/源码树）—— 实测打包 GUI 的「证书签发」弹窗就是这条 ✓
    """
    return "hd2proxy.exe" if getattr(sys, "frozen", False) else "python -m hd2proxy"


def _build_plan(ctx):
    cert_dir = ctx["cert_dir"]
    session = cert_dir / "session.json"
    if not session.exists():
        raise RuntimeError("没有会话证书（%s）；先跑 `%s certs renew --cert-dir %s`"
                           % (session, _cli_hint(), cert_dir))
    info = json.loads(session.read_text(encoding="utf-8"))
    thumbprint = info.get("thumbprint_sha1") or ""
    if len(thumbprint.replace(" ", "")) != 40:
        raise RuntimeError("session.json 里没有有效指纹，请重新签发证书")
    return installer.build_plan(
        host=ctx["host"], listen_ip=ctx["listen_ip"], cert_dir=cert_dir,
        thumbprint=thumbprint, scope=ctx["scope"],
        backup_dir=paths.state_dir() / "hosts-backups",
    )


def _print_action(title, result):
    print("== %s：%s ==" % (title, "OK" if result.ok else "FAIL"))
    for i, step in enumerate(result.steps, 1):
        print("  %d. %s" % (i, step))
    if result.error:
        print("  error: %s" % result.error)


# ---------------------------------------------------------------- 命令


def cmd_info(_a):
    import hd2proxy
    state = _state()
    _out({
        "version": hd2proxy.__version__,
        "repo": str(ROOT),
        "engine_script": str(ENGINE),
        "data_dir": str(paths.DATA_DIR),
        "state_dir": str(paths.state_dir()),
        "certs(repo)": str(paths.CERT_DIR),
        "certs(install default)": str(paths.state_dir() / "certs"),
        "legacy_config": str(paths.LEGACY_DIR / "config.example.json"),
        "catalogs": str(paths.CATALOGS_DIR),
        "profiles": len(cfgmod.list_profiles()),
        "engine_running": bool(state),
        "engine": state,
    })
    return OK


def cmd_engine(a):
    """起引擎。打包版（frozen）没有 src/ 树，直接在进程内调 server.main。"""
    if getattr(sys, "frozen", False):
        from hd2proxy.engine import server
        return server.main(a.rest)
    return _run_script(ENGINE, a.rest)


def _dev_only(name):
    """selftest / gate 是源码树工具，打包版不含；明确提示而不是报文件找不到。"""
    if getattr(sys, "frozen", False):
        print("%s 是源码树里的开发工具，打包版不含；请在仓库里跑 "
              "`python -m hd2proxy %s`" % (name, name))
        return True
    return False


def cmd_selftest(a):
    if _dev_only("selftest"):
        return FAIL
    return _run_script(TOOLS / "run_selftests.py", a.rest)


def cmd_gate(a):
    if _dev_only("gate"):
        return FAIL
    return _run_script(TOOLS / "check_gate.py", a.rest)


def cmd_profiles(a):
    if a.action == "list":
        _out({"profiles": cfgmod.list_profiles(), "dir": str(cfgmod.profile_dir()),
              "active_hint": str(paths.engine_state_file())})
        return OK
    if a.action == "path":
        print(cfgmod.profile_dir())
        return OK
    if a.action == "show":
        p = cfgmod.profile_path(a.name)
        if not p.exists():
            print("不存在：%s" % p)
            return FAIL
        _out(cfgmod.load_profile_file(p))
        return OK
    if a.action == "new":
        p = cfgmod.profile_path(a.name)
        if p.exists() and not a.force:
            print("已存在：%s（加 --force 覆盖）" % p)
            return FAIL
        cfgmod.save_profile(a.name, cfgmod.default_profile(name=a.name))
        print("已创建：%s" % p)
        return OK
    print("未知操作：%s" % a.action)
    return FAIL


def cmd_migrate(a):
    cfg_path = Path(a.config) if a.config else (paths.LEGACY_DIR / "config.example.json")
    runtime = Path(a.runtime) if a.runtime else paths.RUNTIME
    extra = os.environ.get("HD2_GWE_EXTRA")
    profile, notes = cfgmod.from_legacy(cfg_path, runtime, extra)
    out = Path(a.out) if a.out else cfgmod.profile_path(a.name or "migrated")
    cfgmod.save_profile_file(out, profile)
    print("已迁移 -> %s" % out)
    for note in notes:
        print("  · %s" % note)
    return OK


def cmd_certs(a):
    cert_dir = Path(a.cert_dir) if a.cert_dir else (paths.state_dir() / "certs")
    if a.action == "status":
        # 一次性命令：顺手查一次根存储（certutil 约 60–120ms），否则 ``trusted`` 恒为 null，
        # 现场会误读成「信任状态不明」。控制面 /status 是 GUI 轮询热路径，仍保持默认不查。
        _out(certs.cert_status(cert_dir, check_trust=True))
        return OK
    if a.action == "renew":
        try:
            report = certs.generate_session(cert_dir, host=a.host, days=a.days,
                                            force=True, mode="ca")
        except Exception as e:      # noqa: BLE001
            print("签发失败：%r" % (e,))
            return FAIL
        _out({k: report.get(k) for k in ("mode", "host", "not_before", "not_after",
                                         "thumbprint_sha1", "self_check", "stray_keys")})
        print("证书目录：%s" % cert_dir)
        print("下一步：%s install --cert-dir %s（安装 hosts + 信任证书）"
              % (_cli_hint(), cert_dir))
        return OK
    print("未知操作：%s" % a.action)
    return FAIL


def cmd_install(a):
    # 提权子进程分支：父进程写好 plan 后以管理员重跑本命令
    if a.plan:
        if not sysprobe.is_admin():
            print("错误：--elevated 子进程必须以管理员身份运行")
            return FAIL
        plan = installer.plan_from_dict(json.loads(Path(a.plan).read_text(encoding="utf-8")))
        result = installer.run_install_as_admin(plan)
        _print_action("安装（提权）", result)
        return OK if result.ok else FAIL

    ctx = _install_context(a)
    print("目标：host=%s listenIp=%s certDir=%s scope=%s"
          % (ctx["host"], ctx["listen_ip"], ctx["cert_dir"], ctx["scope"]))
    session = ctx["cert_dir"] / "session.json"
    if not session.exists():
        print("没有会话证书，先签发（ca 模式 %d 天）..." % ctx["days"])
        try:
            certs.generate_session(ctx["cert_dir"], host=ctx["host"], days=ctx["days"],
                                   force=True, mode="ca")
        except Exception as e:      # noqa: BLE001
            print("签发失败：%r" % (e,))
            return FAIL
    plan = _build_plan(ctx)
    if a.dry_run:
        print("\n== 安装计划（dry-run，不改系统）==")
        for i, step in enumerate(installer.plan_steps(plan), 1):
            print("  %d. %s" % (i, step))
        state = installer.verify_system_state(plan)
        print("\n== 当前系统状态 ==")
        _out(state)
        return OK
    result = installer.install(plan)
    _print_action("安装", result)
    if result.ok:
        print("\n下一步：%s engine --profile <profile> --cert-dir %s"
              % (_cli_hint(), ctx["cert_dir"]))
    return OK if result.ok else FAIL


def cmd_uninstall(a):
    if a.plan:
        if not sysprobe.is_admin():
            print("错误：--elevated 子进程必须以管理员身份运行")
            return FAIL
        plan = installer.plan_from_dict(json.loads(Path(a.plan).read_text(encoding="utf-8")))
        result = installer.run_uninstall_as_admin(plan)
        _print_action("还原（提权）", result)
        return OK if result.ok else FAIL

    ctx = _install_context(a)
    plan = _build_plan(ctx)
    if a.dry_run:
        print("== 还原计划（dry-run，不改系统）==")
        state = installer.verify_system_state(plan)
        _out(state)
        print("将执行：删 hosts 里 `# hd2proxy` 行 + 从证书存储删除指纹 %s"
              % plan.thumbprint)
        return OK
    result = installer.uninstall(plan)
    _print_action("还原", result)
    if result.ok:
        print("提示：certs 文件仍在 %s，如需彻底清理请自行删除该目录" % ctx["cert_dir"])
    return OK if result.ok else FAIL


def cmd_status(a):
    try:
        _out(_api("/status", url=a.url, token=a.token))
        return OK
    except Exception as e:      # noqa: BLE001
        print("读取引擎状态失败：%r" % (e,))
        return FAIL


def cmd_verify(a):
    try:
        result = _api("/verify", method="POST", body={}, url=a.url, token=a.token)
    except Exception as e:      # noqa: BLE001
        print("验收请求失败：%r" % (e,))
        return FAIL
    _out(result)
    return OK if result.get("ok") else FAIL


def cmd_preview(a):
    """离线预演：把 profile 套到 data/samples 的样本响应上，看会改客户端什么。

    不开游戏、不装证书、不改 hosts —— 纯读文件计算；退出码只表示「profile 能不能读」，
    不表示「会不会生效」（那要看增量与 warnings）。
    """
    if a.profile:
        path = Path(a.profile)
    elif a.name:
        path = cfgmod.profile_path(a.name)
    else:
        print("需要 --profile <路径> 或 --name <profile 名>。现有 profile：")
        for row in cfgmod.list_profiles():
            print("  · %s  (%s)" % (row.get("title") or row.get("name"), row.get("path")))
        return FAIL
    if not path.exists():
        print("profile 不存在：%s" % path)
        return FAIL
    try:
        profile = cfgmod.load_profile_file(path)
    except Exception as e:      # noqa: BLE001
        print("profile 读取失败：%r" % (e,))
        return FAIL
    fixtures = None if a.fixture == "all" else [a.fixture]
    result = preview_mod.preview(profile, samples_dir=(a.samples or None), fixtures=fixtures)
    if a.json:
        _out(result)
    else:
        print(preview_mod.format_text(result))
    return OK


def cmd_live(a):
    """拉取当前战况（无需游戏）：Status + GWE，并推荐可点靶星。

    为什么能做：这三个端点在官方 API 上是免登录的公共只读接口（不需要 Steam 票据 / sessionId）；
    直拉到的 GWE 与游戏内经引擎抓到的数据逐字节相同（2026-11-20 实测）。
    host 会被 DoH 解析成真实 IP（绕 hosts），再 SNI 直连，正常校验证书。
    """
    faction = None if (a.faction or "all") == "all" else a.faction
    try:
        snap = live_mod.fetch(war_id=(a.war or None),
                              host=(a.host or live_mod.DEFAULT_HOST),
                              timeout=float(a.timeout or live_mod.DEFAULT_TIMEOUT))
    except live_mod.LiveError as e:
        print("拉取战况失败：%s" % e)
        return FAIL
    rows = live_mod.annotate(live_mod.suggest_targets(
        snap["status"], faction=faction, limit=(a.limit or None)))
    if a.json:
        payload = {"ok": True,
                   "snapshot": {k: snap.get(k) for k in ("schema", "host", "ip", "war_id",
                                                         "fetched_at", "elapsed", "summary")},
                   "targets": rows}
        if a.out:
            payload["saved"] = live_mod.save_snapshot(snap, a.out)
        _out(payload)
        return OK
    print(live_mod.format_text(snap, faction=faction, limit=(a.limit or None)))
    if a.out:
        saved = live_mod.save_snapshot(snap, a.out)
        print("")
        print("已保存快照：%s" % saved["out_dir"])
        for name, path in saved["files"].items():
            print("  · %s  %s" % (name, path))
    return OK


def cmd_gui(a):
    """打开图形界面（Tk）。GUI 只是控制面客户端，关窗不会停引擎。"""
    import tkinter as tk

    from hd2proxy.gui.app import App
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print("无法创建窗口（无图形环境？）：%r" % (e,))
        return FAIL
    profile = Path(a.profile) if a.profile else None
    App(root, profile_path=profile)
    root.mainloop()
    return OK


def cmd_shutdown(a):
    try:
        _out(_api("/shutdown", method="POST", body={}, url=a.url, token=a.token))
        return OK
    except Exception as e:      # noqa: BLE001
        print("请求退出失败：%r" % (e,))
        return FAIL


# ---------------------------------------------------------------- parser


def build_parser():
    ap = argparse.ArgumentParser(prog="hd2proxy",
                                 description="HD2 本机代理工具箱（M1 CLI）")
    ap.add_argument("--version", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("gui", help="打开图形界面（Tk；控制面客户端）")
    p.add_argument("--profile", default="", help="profile 文件路径（默认 state 目录下的 default）")

    sub.add_parser("info", help="版本与路径")

    p = sub.add_parser("engine", help="起代理引擎（前台；参数转发给引擎）")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("selftest", help="跑 5 个离线自检")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("gate", help="跑门禁（语法 + 绝对路径 + 自检）")
    p.add_argument("rest", nargs=argparse.REMAINDER)

    p = sub.add_parser("profiles", help="profile 管理")
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "show", "new", "path"])
    p.add_argument("name", nargs="?", default="")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("migrate", help="旧 config.json/runtime 迁移成 profile")
    p.add_argument("--config", default="")
    p.add_argument("--runtime", default="")
    p.add_argument("--out", default="")
    p.add_argument("--name", default="")

    p = sub.add_parser("certs", help="会话证书（ca 模式，≤2 天）")
    p.add_argument("action", nargs="?", default="status", choices=["status", "renew"])
    p.add_argument("--cert-dir", default="")
    p.add_argument("--host", default=certs.DEFAULT_HOST)
    p.add_argument("--days", type=int, default=2)

    p = sub.add_parser("install", help="安装：hosts 指向本机 + 信任会话证书（需要一次 UAC）")
    p.add_argument("--profile", default="")
    p.add_argument("--host", default="")
    p.add_argument("--listen-ip", default="")
    p.add_argument("--cert-dir", default="")
    p.add_argument("--scope", choices=["LocalMachine", "CurrentUser"], default="")
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不改系统")
    p.add_argument("--plan", default="", help="（内部）提权子进程用的计划文件")
    p.add_argument("--elevated", action="store_true", help="（内部）以管理员身份执行")

    p = sub.add_parser("uninstall", help="还原：删 hosts 行 + 删证书信任（需要一次 UAC）")
    p.add_argument("--profile", default="")
    p.add_argument("--host", default="")
    p.add_argument("--listen-ip", default="")
    p.add_argument("--cert-dir", default="")
    p.add_argument("--scope", choices=["LocalMachine", "CurrentUser"], default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--plan", default="")
    p.add_argument("--elevated", action="store_true")

    p = sub.add_parser("preview", help="离线预演：套 data/samples 看 profile 会改什么（不开游戏）")
    p.add_argument("--profile", default="", help="profile 文件路径")
    p.add_argument("--name", default="", help="state 目录下的 profile 名（与 --profile 二选一）")
    p.add_argument("--fixture", default="all", choices=["all"] + list(preview_mod.FIXTURE_NAMES),
                   help="只跑某一类响应（默认 all）")
    p.add_argument("--samples", default="", help="样本目录（默认 data/samples）")
    p.add_argument("--json", action="store_true", help="输出结构化 JSON（默认人读文本）")

    p = sub.add_parser("live", help="拉取当前战况（无需游戏）：Status + GWE，并推荐可点靶星")
    p.add_argument("--war", type=int, default=0, help="战局号（默认自动取 current/WarId）")
    p.add_argument("--host", default="", help="API 主机（默认官方）")
    p.add_argument("--faction", default="all",
                   choices=["all", "terminid", "automaton", "illuminate", "human"],
                   help="只看某个阵营的推荐靶星（默认全部）")
    p.add_argument("--limit", type=int, default=0, help="最多推荐几个（0=不限）")
    p.add_argument("--out", default="", help="保存快照目录（status.json/gwe.json/meta.json）")
    p.add_argument("--timeout", type=float, default=live_mod.DEFAULT_TIMEOUT,
                   help="单请求超时秒数（默认 %.0f）" % live_mod.DEFAULT_TIMEOUT)
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")

    for name, helptext in (("status", "读运行中引擎的状态"),
                           ("verify", "三连验收（TLS/CRL/Status）"),
                           ("shutdown", "让引擎优雅退出")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--url", default="")
        p.add_argument("--token", default="")
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # engine / selftest / gate 是「转发型」命令：要把后续参数原样交给子命令（引擎/脚本）。
    # 不能靠 argparse 的 REMAINDER —— 它以 `--` 开头的参数会在本轮就被 argparse 当成未知选项
    # 报错（M4 实测：`hd2proxy engine --profile X` 直接 usage error）。
    if argv and argv[0] in ("engine", "selftest", "gate"):
        handler = {"engine": cmd_engine, "selftest": cmd_selftest, "gate": cmd_gate}[argv[0]]
        return handler(argparse.Namespace(cmd=argv[0], rest=argv[1:]))
    if not argv:
        # 双击 exe / 无参数：默认打开 GUI（CLI 用法显式 --help）
        try:
            return cmd_gui(argparse.Namespace(profile=""))
        except Exception as e:      # noqa: BLE001 —— 无图形环境时退回帮助
            print("无法打开图形界面（%r）；CLI 用法见 --help" % (e,))
            build_parser().print_help()
            return FAIL
    if argv[0] in ("-h", "--help"):
        build_parser().print_help()
        return OK
    a = build_parser().parse_args(argv)
    if a.version:
        import hd2proxy
        print(hd2proxy.__version__)
        return OK
    if not a.cmd:
        build_parser().print_help()
        return 2
    handler = {
        "info": cmd_info, "engine": cmd_engine, "selftest": cmd_selftest,
        "gate": cmd_gate, "profiles": cmd_profiles, "migrate": cmd_migrate,
        "certs": cmd_certs, "install": cmd_install, "uninstall": cmd_uninstall,
        "status": cmd_status, "verify": cmd_verify, "shutdown": cmd_shutdown,
        "gui": cmd_gui, "preview": cmd_preview, "live": cmd_live,
    }[a.cmd]
    return handler(a)


if __name__ == "__main__":
    sys.exit(main())
