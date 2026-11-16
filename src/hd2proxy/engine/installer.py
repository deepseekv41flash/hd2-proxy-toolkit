"""安装 / 卸载编排：改 hosts + 信任证书，必要时弹一次 UAC。

职责边界（谁干什么）：

  * ``certs.py``（M1 另一模块）负责**签证书**、写会话文件；本模块只负责「把已有的
    ``certs/anchor.cer`` 导入受信任根存储」以及「从存储里删掉它」；
  * **不删证书文件**：``installer.uninstall`` 只撤 hosts 行与证书存储条目，
    ``certs/`` 下的文件由调用方（CLI/GUI 的数据目录管理）决定要不要清 —— 见
    :func:`uninstall` 文档字符串；
  * 需要管理员的两件事（hosts、证书存储）如果当前不是管理员，就**用管理员身份重启自己**
    （``install --plan <临时 json> --elevated``），等子进程结束后**回读系统状态**再判定成败。

执行顺序刻意是「先证书、后 hosts」：反过来的话，hosts 已经指向本机代理、但证书还没被信任，
游戏在这一小段窗口里会撞上不可信证书；先信任证书不会产生任何副作用（没人用就不生效）。

四种 hosts 起始状态（无 marker / 正确 marker / 旧 IP marker / marker 被注释）都由
:mod:`hd2proxy.engine.hosts` 的 ``plan_edit`` 判定，本模块只负责把判定结果翻译成人话并执行。
"""

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import elevation, hosts, sysprobe

# 提权子进程的等待上限（秒）
ELEVATE_TIMEOUT = elevation.ELEVATE_TIMEOUT
# 期望的命令行退出码
OK = 0


@dataclass
class InstallPlan:
    """一次安装/卸载的完整输入（可 JSON 序列化后在提权子进程里复原）。"""

    host: str
    listen_ip: str
    cert_dir: Path
    anchor_cer: Path
    thumbprint: str
    scope: str = "LocalMachine"
    marker: str = hosts.MARKER
    backup_dir: Path | None = None


@dataclass
class ActionResult:
    ok: bool
    steps: list[str]
    changed: bool
    error: str | None = None


# --------------------------------------------------------------------------- #
# 计划
# --------------------------------------------------------------------------- #
def build_plan(*, host: str, listen_ip: str, cert_dir: Path, thumbprint: str,
               scope: str = "LocalMachine",
               backup_dir: Path | None = None) -> InstallPlan:
    """构造安装计划：规范监听 IP / 指纹 / 证书路径，参数不合法直接抛 ``ValueError``。"""
    host_value = "" if host is None else str(host).strip()
    if not host_value or any(ch.isspace() for ch in host_value):
        raise ValueError("host 不合法：%r" % (host,))
    resolved_ip = sysprobe.resolve_listen_ip(listen_ip)
    scope_args = sysprobe.cert_scope_args(scope)
    if scope_args is None:
        raise ValueError("证书存储范围不合法：%r（只支持 LocalMachine / CurrentUser）" % (scope,))
    normalized_scope = "LocalMachine" if not scope_args else "CurrentUser"
    normalized_thumb = sysprobe.normalize_thumbprint(thumbprint)
    if len(normalized_thumb) != 40:
        raise ValueError(
            "证书指纹应为 40 位十六进制（SHA-1 thumbprint），当前是 %r" % (thumbprint,))
    cert_dir_path = Path(cert_dir)
    return InstallPlan(
        host=host_value,
        listen_ip=resolved_ip,
        cert_dir=cert_dir_path,
        anchor_cer=cert_dir_path / "anchor.cer",
        thumbprint=normalized_thumb,
        scope=normalized_scope,
        marker=hosts.MARKER,
        backup_dir=Path(backup_dir) if backup_dir is not None else None,
    )


def plan_to_dict(plan: InstallPlan) -> dict:
    """计划 -> 可 JSON 序列化的 dict（Path 变字符串，供提权子进程读）。"""
    doc = dataclasses.asdict(plan)
    doc["cert_dir"] = str(plan.cert_dir)
    doc["anchor_cer"] = str(plan.anchor_cer)
    doc["backup_dir"] = str(plan.backup_dir) if plan.backup_dir is not None else None
    return doc


def plan_from_dict(doc: dict) -> InstallPlan:
    """dict -> 计划（与 :func:`plan_to_dict` 配对的复原函数，提权子进程用）。"""
    backup_dir = doc.get("backup_dir")
    return InstallPlan(
        host=str(doc["host"]),
        listen_ip=str(doc["listen_ip"]),
        cert_dir=Path(str(doc["cert_dir"])),
        anchor_cer=Path(str(doc["anchor_cer"])),
        thumbprint=str(doc["thumbprint"]),
        scope=str(doc.get("scope") or "LocalMachine"),
        marker=str(doc.get("marker") or hosts.MARKER),
        backup_dir=Path(str(backup_dir)) if backup_dir else None,
    )


def _hosts_plan(plan: InstallPlan) -> dict:
    return hosts.plan_edit(plan.listen_ip, plan.host, marker=plan.marker)


def _cert_trusted(plan: InstallPlan) -> bool:
    return sysprobe.cert_in_store(plan.thumbprint, plan.scope)


def _addstore_args(plan: InstallPlan) -> list[str]:
    scope_args = sysprobe.cert_scope_args(plan.scope) or []
    return scope_args + ["-addstore", "Root", str(plan.anchor_cer)]


def _delstore_args(plan: InstallPlan) -> list[str]:
    scope_args = sysprobe.cert_scope_args(plan.scope) or []
    return scope_args + ["-delstore", "Root", plan.thumbprint]


def _proc_tail(proc, limit: int = 400) -> str:
    try:
        raw = (proc.stdout or b"") + (proc.stderr or b"")
    except Exception:                                   # noqa: BLE001 - 诊断信息失败不影响判定
        return ""
    text = sysprobe.decode_output(raw).strip()
    return text[-limit:]


def plan_steps(plan: InstallPlan) -> list[str]:
    """dry-run：把「要动哪个文件、写哪一行、导入哪张证书、当前什么状态」讲清楚（不写入）。"""
    steps: list[str] = []
    problem = sysprobe.validate_listen_ip(plan.listen_ip)
    steps.append("监听地址：%s（%s）" % (
        plan.listen_ip, "可用" if problem is None else "不可用：" + problem))
    host_plan = _hosts_plan(plan)
    steps.append("hosts 文件：%s" % host_plan.get("path"))
    steps.append("hosts 判定：%s —— %s" % (host_plan.get("action"), host_plan.get("reason")))
    if host_plan.get("action") in ("add", "replace"):
        steps.append("hosts 将写入：%s" % host_plan.get("new_line"))
    steps.append("证书指纹：%s（存储范围 %s）" % (plan.thumbprint, plan.scope))
    steps.append("锚证书文件：%s（%s）" % (
        plan.anchor_cer, "存在" if plan.anchor_cer.exists() else "缺失"))
    trusted = _cert_trusted(plan)
    steps.append("证书信任：%s" % (
        "已在受信任根存储" if trusted else "未信任，安装时会 certutil -addstore"))
    steps.append("当前权限：%s" % (
        "管理员（可直接执行）" if sysprobe.is_admin() else "普通用户（安装时会弹一次 UAC）"))
    changed = host_plan.get("action") in ("add", "replace") or not trusted
    steps.append("预计改动：%s" % ("需要改动系统（hosts / 证书存储）" if changed else "无需改动（已是目标状态）"))
    return steps


# --------------------------------------------------------------------------- #
# 状态回读
# --------------------------------------------------------------------------- #
def verify_system_state(plan: InstallPlan) -> dict:
    """回读真实系统状态（安装是否真的生效，以它为准）。"""
    host_plan = _hosts_plan(plan)
    hosts_ok = host_plan.get("action") == "noop"
    return {
        "hosts_ok": bool(hosts_ok),
        "hosts_line": host_plan.get("old_line"),
        "cert_trusted": bool(_cert_trusted(plan)),
        "listen_ip_ok": sysprobe.validate_listen_ip(plan.listen_ip) is None,
        "admin": bool(sysprobe.is_admin()),
    }


def _verify_uninstalled(plan: InstallPlan) -> dict:
    return {
        "hosts_clean": hosts.count_marker(marker=plan.marker) == 0,
        "cert_removed": not _cert_trusted(plan),
    }


# --------------------------------------------------------------------------- #
# 提权子进程
# --------------------------------------------------------------------------- #
def _write_plan_temp(plan: InstallPlan) -> Path:
    fd, name = tempfile.mkstemp(prefix="hd2proxy-plan-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(plan_to_dict(plan), fh, ensure_ascii=False, indent=2)
    return Path(name)


def _safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        Path(path).unlink()
    except OSError:
        pass


def _run_elevated_phase(plan: InstallPlan, command: str, steps: list[str]) -> dict:
    """请求 UAC 并以管理员身份重跑自己；返回 ``{"proceed": bool, "changed": bool, "error": str|None}``。

    ``proceed=True`` 只代表「子进程正常结束」，**是否真的生效必须回读系统状态**。
    """
    tmp_plan = None
    try:
        tmp_plan = _write_plan_temp(plan)
        args = [command, "--plan", str(tmp_plan), "--elevated"]
        steps.append("请求 UAC 提权：%s" % " ".join(elevation.build_elevation_argv(args)))
        result = elevation.run_elevated(args, wait=True, timeout=ELEVATE_TIMEOUT)
    except OSError as e:
        return {"proceed": False, "changed": False, "error": "写临时计划文件失败：%r" % (e,)}
    finally:
        _safe_unlink(tmp_plan)

    if result.get("cancelled"):
        message = "用户取消了 UAC 提权，系统未被改动"
        steps.append(message)
        return {"proceed": False, "changed": False, "error": message}
    if not result.get("launched"):
        message = "提权进程未能启动：%s" % (result.get("error") or "未知错误")
        steps.append(message)
        return {"proceed": False, "changed": False, "error": message}
    exit_code = result.get("exit_code")
    steps.append("提权进程结束：exit_code=%s" % (exit_code,))
    if exit_code not in (OK, None):
        message = "提权进程失败（exit_code=%s）%s" % (
            exit_code, ("：" + str(result.get("error"))) if result.get("error") else "")
        return {"proceed": False, "changed": True, "error": message}
    return {"proceed": True, "changed": True, "error": None}


# --------------------------------------------------------------------------- #
# 安装
# --------------------------------------------------------------------------- #
def install(plan: InstallPlan, *, allow_elevate: bool = True) -> ActionResult:
    """执行安装：校验监听地址 -> hosts 规划 -> 证书信任检测 -> （必要时提权）写入。

    幂等：已经是目标状态时返回 ``ok=True, changed=False`` 且不写任何东西。
    任何一步失败都返回 ``ok=False`` 并在 ``error`` 里说清楚（``steps`` 保留已完成的步骤，
    ``changed`` 表示系统是否已被部分改动）。
    """
    steps: list[str] = []
    problem = sysprobe.validate_listen_ip(plan.listen_ip)
    if problem:
        steps.append("① 监听地址 %s 不可用：%s" % (plan.listen_ip, problem))
        return ActionResult(ok=False, steps=steps, changed=False, error=problem)
    steps.append("① 监听地址 %s：非回环、非通配，通过" % plan.listen_ip)

    host_plan = _hosts_plan(plan)
    if host_plan.get("action") == "error":
        steps.append("② hosts 规划失败：%s" % host_plan.get("reason"))
        return ActionResult(False, steps, False, str(host_plan.get("reason")))
    steps.append("② hosts 规划：%s —— %s" % (host_plan.get("action"), host_plan.get("reason")))

    trusted = _cert_trusted(plan)
    steps.append("③ 证书信任：%s（%s）" % (
        "已在受信任根存储" if trusted else "未信任，需要导入", plan.thumbprint))
    need_cert = not trusted
    need_hosts = host_plan.get("action") in ("add", "replace")
    if need_cert and not plan.anchor_cer.exists():
        message = "锚证书文件不存在：%s（先跑签证书流程再安装）" % plan.anchor_cer
        steps.append("④ " + message)
        return ActionResult(False, steps, False, message)
    if not (need_cert or need_hosts):
        steps.append("④ 已经是目标状态：无需改动")
        return ActionResult(True, steps, False)

    admin = sysprobe.is_admin()
    steps.append("④ 当前权限：%s" % ("管理员（直接执行）" if admin else "普通用户（需要一次 UAC）"))
    if not admin:
        if not allow_elevate:
            message = "需要管理员权限（改 hosts / 写证书存储），但调用方禁止提权"
            steps.append("⑤ 跳过提权：allow_elevate=False")
            return ActionResult(False, steps, False, message)
        phase = _run_elevated_phase(plan, "install", steps)
        if not phase["proceed"]:
            return ActionResult(False, steps, bool(phase["changed"]), str(phase["error"]))
        state = verify_system_state(plan)
        steps.append("⑤ 回读校验：hosts=%s 证书=%s" % (
            "OK" if state["hosts_ok"] else "未生效",
            "OK" if state["cert_trusted"] else "未生效"))
        ok = state["hosts_ok"] and state["cert_trusted"] and state["listen_ip_ok"]
        return ActionResult(bool(ok), steps, True,
                            None if ok else "提权完成，但回读校验未通过（hosts 或证书未生效）")
    return _install_as_admin(plan, host_plan, steps, need_cert=need_cert, need_hosts=need_hosts)


def _install_as_admin(plan: InstallPlan, host_plan: dict, steps: list[str], *,
                      need_cert: bool, need_hosts: bool) -> ActionResult:
    changed = False
    # 先导证书、后改 hosts：避免「hosts 已指向代理但证书未信任」的窗口期
    if need_cert:
        argv = _addstore_args(plan)
        proc = sysprobe.run_certutil(argv)
        if proc is None:
            message = "无法执行 certutil（可用 HD2PROXY_CERTUTIL 覆盖路径）"
            steps.append("⑤ 证书导入失败：%s" % message)
            return ActionResult(False, steps, changed, message)
        steps.append("⑤ 证书导入：certutil %s -> rc=%d" % (" ".join(argv), proc.returncode))
        if proc.returncode != OK:
            message = "certutil -addstore 失败（rc=%d）：%s" % (proc.returncode, _proc_tail(proc))
            return ActionResult(False, steps, changed, message)
        changed = True
        if not _cert_trusted(plan):
            message = "certutil 返回成功，但受信任根存储里查不到该指纹"
            steps.append("⑥ " + message)
            return ActionResult(False, steps, changed, message)
    if need_hosts:
        result = hosts.apply_edit(host_plan, backup_dir=plan.backup_dir)
        if not result.get("ok"):
            message = "hosts 写入失败：%s" % result.get("error")
            steps.append("⑥ " + message)
            return ActionResult(False, steps, changed, message)
        backup = result.get("backup")
        steps.append("⑥ hosts 写入成功%s" % (("（备份：%s）" % backup) if backup else "（无备份：文件原本不存在）"))
        changed = True
    state = verify_system_state(plan)
    steps.append("⑦ 回读校验：hosts=%s 证书=%s" % (
        "OK" if state["hosts_ok"] else "未生效",
        "OK" if state["cert_trusted"] else "未生效"))
    ok = state["hosts_ok"] and state["cert_trusted"] and state["listen_ip_ok"]
    return ActionResult(bool(ok), steps, changed,
                        None if ok else "回读校验未通过（hosts 或证书未生效）")


# --------------------------------------------------------------------------- #
# 卸载
# --------------------------------------------------------------------------- #
def uninstall(plan: InstallPlan, *, allow_elevate: bool = True) -> ActionResult:
    """还原：删 hosts 里的 marker 行 + 从证书存储删掉该指纹。

    **不删证书文件**：``certs/``（``plan.cert_dir``）下的 ``anchor.cer`` / 私钥 / 会话文件
    由调用方按自己的数据目录策略清理，本函数只负责「系统状态」的还原。
    """
    steps: list[str] = []
    marker_count = hosts.count_marker(marker=plan.marker)
    trusted = _cert_trusted(plan)
    steps.append("① hosts 标记行：%d 行" % marker_count)
    steps.append("② 证书信任：%s（%s）" % (
        "在受信任根存储中" if trusted else "不在受信任根存储中", plan.thumbprint))
    if marker_count == 0 and not trusted:
        steps.append("③ 没有需要还原的系统状态")
        return ActionResult(True, steps, False)

    admin = sysprobe.is_admin()
    steps.append("③ 当前权限：%s" % ("管理员（直接执行）" if admin else "普通用户（需要一次 UAC）"))
    if not admin:
        if not allow_elevate:
            message = "需要管理员权限（改 hosts / 写证书存储），但调用方禁止提权"
            steps.append("④ 跳过提权：allow_elevate=False")
            return ActionResult(False, steps, False, message)
        phase = _run_elevated_phase(plan, "uninstall", steps)
        if not phase["proceed"]:
            return ActionResult(False, steps, bool(phase["changed"]), str(phase["error"]))
        state = _verify_uninstalled(plan)
        steps.append("⑤ 回读校验：hosts=%s 证书=%s" % (
            "已清理" if state["hosts_clean"] else "仍有残留",
            "已移除" if state["cert_removed"] else "仍在存储中"))
        ok = state["hosts_clean"] and state["cert_removed"]
        return ActionResult(bool(ok), steps, True,
                            None if ok else "提权完成，但回读校验未通过（hosts 或证书仍有残留）")
    return _uninstall_as_admin(plan, steps, marker_count=marker_count, trusted=trusted)


def _uninstall_as_admin(plan: InstallPlan, steps: list[str], *,
                        marker_count: int, trusted: bool) -> ActionResult:
    changed = False
    if marker_count:
        result = hosts.remove_marker(marker=plan.marker, backup_dir=plan.backup_dir)
        if not result.get("ok"):
            message = "hosts 还原失败：%s" % result.get("error")
            steps.append("④ " + message)
            return ActionResult(False, steps, changed, message)
        steps.append("④ hosts 移除 %d 行（备份目录：%s）" % (
            result.get("removed", 0), plan.backup_dir or "hosts 同目录 " + hosts.BACKUP_DIRNAME))
        changed = changed or result.get("removed", 0) > 0
    if trusted:
        argv = _delstore_args(plan)
        proc = sysprobe.run_certutil(argv)
        if proc is None:
            message = "无法执行 certutil（可用 HD2PROXY_CERTUTIL 覆盖路径）"
            steps.append("⑤ 证书移除失败：%s" % message)
            return ActionResult(False, steps, changed, message)
        steps.append("⑤ 证书移除：certutil %s -> rc=%d" % (" ".join(argv), proc.returncode))
        if proc.returncode != OK:
            message = "certutil -delstore 失败（rc=%d）：%s" % (proc.returncode, _proc_tail(proc))
            return ActionResult(False, steps, changed, message)
        changed = True
    state = _verify_uninstalled(plan)
    steps.append("⑥ 回读校验：hosts=%s 证书=%s" % (
        "已清理" if state["hosts_clean"] else "仍有残留",
        "已移除" if state["cert_removed"] else "仍在存储中"))
    steps.append("说明：证书文件（%s）不由本函数删除，调用方按需清理" % plan.cert_dir)
    ok = state["hosts_clean"] and state["cert_removed"]
    return ActionResult(bool(ok), steps, changed,
                        None if ok else "回读校验未通过（hosts 或证书仍有残留）")


# --------------------------------------------------------------------------- #
# 提权子进程入口（由本工具自己以管理员身份重跑时调用）
# --------------------------------------------------------------------------- #
def run_install_as_admin(plan: InstallPlan) -> ActionResult:
    """以**管理员**身份直接执行安装；不做提权判断，不弹 UAC。

    CLI 契约：父进程写临时 plan JSON → 提权执行 `install --plan <json> --elevated`；
    子进程走本函数，退出码 0=成功 / 2=失败。父进程仍以 `verify_system_state` 回读为准。
    """
    steps = ["(elevated) 以管理员身份执行安装"]
    host_plan = _hosts_plan(plan)
    if host_plan.get("action") == "error":
        steps.append("hosts 规划失败：%s" % host_plan.get("reason"))
        return ActionResult(False, steps, False, str(host_plan.get("reason")))
    need_cert = not _cert_trusted(plan)
    need_hosts = host_plan.get("action") in ("add", "replace")
    if not (need_cert or need_hosts):
        steps.append("已是目标状态：无需改动")
        return ActionResult(True, steps, False)
    return _install_as_admin(plan, host_plan, steps,
                             need_cert=need_cert, need_hosts=need_hosts)


def run_uninstall_as_admin(plan: InstallPlan) -> ActionResult:
    """以**管理员**身份直接执行还原（契约同 run_install_as_admin）。"""
    steps = ["(elevated) 以管理员身份执行还原"]
    marker_count = hosts.count_marker(marker=plan.marker)
    trusted = _cert_trusted(plan)
    if marker_count == 0 and not trusted:
        steps.append("没有需要还原的系统状态")
        return ActionResult(True, steps, False)
    return _uninstall_as_admin(plan, steps, marker_count=marker_count, trusted=trusted)
