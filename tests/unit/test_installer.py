"""installer + elevation 的离线测试。

两条铁律：

  1. **绝不真提权**：``HD2PROXY_ELEVATION_STUB=1`` 走「用户取消」分支；
     「提权后成功」分支由 monkeypatch ``elevation.run_elevated`` 模拟子进程完成；
  2. **绝不碰真实系统**：hosts 用 ``tmp_path`` + ``HD2PROXY_HOSTS_PATH``；
     证书存储用 ``HD2PROXY_CERTUTIL`` 指向现场生成的有状态桩脚本
     （用状态文件模拟 Root 存储的 add / del / query）。

elevation 模块的测试也放在本文件（提权只被安装流程使用，放在一起便于看「父子进程契约」）。
"""

import json
import sys
from pathlib import Path

import pytest

from hd2proxy.engine import elevation, hosts, installer, sysprobe

HOST = "api.live.prod.thehelldiversgame.com"
IP = "192.168.1.50"
OLD_IP = "10.0.0.5"
THUMB = "AABBCCDDEEFF00112233445566778899AABBCCDD"
EXPECTED_LINE = "%s %s # hd2proxy" % (IP, HOST)

# certutil 桩：用状态文件模拟受信任根存储（-store / -addstore / -delstore）
CERTUTIL_STUB = r'''# -*- coding: utf-8 -*-
"""certutil 测试桩：状态文件里的每一行代表一张已信任证书（SHA-1 指纹）。"""
import os
import sys

state_path = os.environ["HD2PROXY_TEST_CERT_STATE"]
args = sys.argv[1:]


def load():
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError:
        return []


def save(values):
    with open(state_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(values) + "\n")


items = load()
if "-store" in args:
    pos = args.index("-store")
    thumb = args[pos + 2].upper() if len(args) > pos + 2 else ""
    sys.exit(0 if thumb in [x.upper() for x in items] else 1)
if "-addstore" in args:
    if os.environ.get("HD2PROXY_TEST_FAIL_ADDSTORE") == "1":
        sys.exit(4)
    if os.environ.get("HD2PROXY_TEST_ADD_NOOP") != "1":
        target = args[-1]
        try:
            with open(target, "r", encoding="utf-8") as fh:
                thumb = fh.read().strip().split()[0].upper()
        except OSError:
            sys.exit(2)
        if thumb not in [x.upper() for x in items]:
            items.append(thumb)
            save(items)
    sys.exit(0)
if "-delstore" in args:
    if os.environ.get("HD2PROXY_TEST_FAIL_DELSTORE") == "1":
        sys.exit(5)
    thumb = args[-1].upper()
    save([x for x in items if x.upper() != thumb])
    sys.exit(0)
sys.exit(3)
'''


class FakeSystem:
    """一套「假系统」的路径集合：假 hosts + 有状态的 certutil 桩。"""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.hosts_file = tmp_path / "hosts"
        self.cert_state = tmp_path / "cert-state.txt"
        self.cert_stub = tmp_path / "certutil_stub.py"
        self.hosts_file.write_bytes(b"127.0.0.1 localhost\r\n")
        self.cert_stub.write_text(CERTUTIL_STUB, encoding="utf-8")

    def write_hosts(self, text: str) -> None:
        self.hosts_file.write_bytes(text.encode("utf-8"))

    def hosts_text(self) -> str:
        return self.hosts_file.read_bytes().decode("utf-8")

    def trust_cert(self, thumb: str = THUMB) -> None:
        self.cert_state.write_text(thumb + "\n", encoding="utf-8")

    def trusted_thumbs(self) -> list[str]:
        if not self.cert_state.exists():
            return []
        return [line.strip() for line in self.cert_state.read_text(encoding="utf-8").splitlines()
                if line.strip()]


@pytest.fixture(autouse=True)
def fake_system(tmp_path, monkeypatch):
    fs = FakeSystem(tmp_path)
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(fs.hosts_file))
    monkeypatch.setenv("HD2PROXY_CERTUTIL", str(fs.cert_stub))
    monkeypatch.setenv("HD2PROXY_TEST_CERT_STATE", str(fs.cert_state))
    for name in ("HD2PROXY_ELEVATION_STUB", "HD2PROXY_TEST_FAIL_ADDSTORE",
                 "HD2PROXY_TEST_FAIL_DELSTORE", "HD2PROXY_TEST_ADD_NOOP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sysprobe, "is_admin", lambda: True)     # 默认走管理员路径
    sysprobe.clear_caches()
    return fs


@pytest.fixture
def cert_dir(tmp_path):
    """假证书目录：anchor.cer 里写的就是指纹（桩脚本据此知道导入了哪张）。"""
    path = tmp_path / "certs"
    path.mkdir()
    (path / "anchor.cer").write_text(THUMB + "\n", encoding="utf-8")
    return path


def build_plan(cert_dir, *, scope: str = "LocalMachine", backup_dir=None):
    return installer.build_plan(host=HOST, listen_ip=IP, cert_dir=cert_dir,
                                thumbprint=THUMB, scope=scope, backup_dir=backup_dir)


def joined(result) -> str:
    return "\n".join(result.steps)


# --------------------------------------------------------------------------- #
# build_plan / 序列化
# --------------------------------------------------------------------------- #
def test_build_plan_defaults(cert_dir):
    plan = build_plan(cert_dir)
    assert plan.host == HOST
    assert plan.listen_ip == IP
    assert plan.anchor_cer == cert_dir / "anchor.cer"
    assert plan.scope == "LocalMachine"
    assert plan.marker == hosts.MARKER
    assert plan.thumbprint == THUMB
    assert plan.backup_dir is None


def test_build_plan_normalizes_scope_and_thumbprint(cert_dir):
    messy = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd"
    plan = installer.build_plan(host=HOST, listen_ip=" 192.168.1.50 ", cert_dir=cert_dir,
                                thumbprint=messy, scope="user")
    assert plan.scope == "CurrentUser"
    assert plan.thumbprint == THUMB
    assert plan.listen_ip == IP


def test_build_plan_rejects_loopback_listen_ip(cert_dir):
    with pytest.raises(ValueError):
        installer.build_plan(host=HOST, listen_ip="127.0.0.1", cert_dir=cert_dir,
                             thumbprint=THUMB)


def test_build_plan_rejects_short_thumbprint(cert_dir):
    with pytest.raises(ValueError):
        installer.build_plan(host=HOST, listen_ip=IP, cert_dir=cert_dir, thumbprint="abcd")


def test_build_plan_rejects_bad_scope(cert_dir):
    with pytest.raises(ValueError):
        installer.build_plan(host=HOST, listen_ip=IP, cert_dir=cert_dir,
                             thumbprint=THUMB, scope="Somewhere")


def test_build_plan_resolves_auto_listen_ip(cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "resolve_listen_ip", lambda value: "100.67.169.17")
    plan = installer.build_plan(host=HOST, listen_ip="auto", cert_dir=cert_dir,
                                thumbprint=THUMB)
    assert plan.listen_ip == "100.67.169.17"


def test_plan_dict_roundtrip(cert_dir, tmp_path):
    plan = build_plan(cert_dir, scope="CurrentUser", backup_dir=tmp_path / "data")
    doc = installer.plan_to_dict(plan)
    assert isinstance(doc["cert_dir"], str)
    assert json.loads(json.dumps(doc, ensure_ascii=False))["anchor_cer"] == str(plan.anchor_cer)
    assert installer.plan_from_dict(json.loads(json.dumps(doc))) == plan


# --------------------------------------------------------------------------- #
# plan_steps：四种 hosts 起始状态的 dry-run
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("initial_text, expected_action, expect_phrase", [
    ("127.0.0.1 localhost\r\n", "add", "追加"),
    ("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED_LINE, "noop", "无需改动"),
    ("127.0.0.1 localhost\r\n%s %s # hd2proxy\r\n" % (OLD_IP, HOST), "replace", "替换"),
    ("127.0.0.1 localhost\r\n# %s\r\n" % EXPECTED_LINE, "replace", "注释"),
], ids=["no-marker", "correct-marker", "stale-ip-marker", "commented-marker"])
def test_plan_steps_four_states(fake_system, cert_dir, initial_text,
                                expected_action, expect_phrase):
    fake_system.write_hosts(initial_text)
    before = fake_system.hosts_file.read_bytes()
    plan = build_plan(cert_dir)
    steps = installer.plan_steps(plan)
    text = "\n".join(steps)
    assert ("hosts 判定：%s" % expected_action) in text
    assert expect_phrase in text
    assert "证书信任：未信任" in text
    assert "锚证书文件：" in text and "存在" in text
    assert fake_system.hosts_file.read_bytes() == before       # dry-run 绝不写文件


def test_plan_steps_reports_correct_marker_as_noop(fake_system, cert_dir):
    fake_system.write_hosts("%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    text = "\n".join(installer.plan_steps(build_plan(cert_dir)))
    assert "hosts 判定：noop" in text
    assert "证书信任：已在受信任根存储" in text
    assert "无需改动" in text


def test_plan_steps_reports_missing_anchor(fake_system, cert_dir):
    (cert_dir / "anchor.cer").unlink()
    text = "\n".join(installer.plan_steps(build_plan(cert_dir)))
    assert "锚证书文件：" in text and "缺失" in text


# --------------------------------------------------------------------------- #
# verify_system_state
# --------------------------------------------------------------------------- #
def test_verify_system_state_all_good(fake_system, cert_dir):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    state = installer.verify_system_state(build_plan(cert_dir))
    assert state == {"hosts_ok": True, "hosts_line": EXPECTED_LINE,
                     "cert_trusted": True, "listen_ip_ok": True, "admin": True}


def test_verify_system_state_stale_and_untrusted(fake_system, cert_dir):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s %s # hd2proxy\r\n" % (OLD_IP, HOST))
    state = installer.verify_system_state(build_plan(cert_dir))
    assert state["hosts_ok"] is False
    assert state["hosts_line"] == "%s %s # hd2proxy" % (OLD_IP, HOST)
    assert state["cert_trusted"] is False


def test_verify_system_state_flags_loopback_listen_ip(fake_system, cert_dir):
    plan = installer.InstallPlan(
        host=HOST, listen_ip="127.0.0.1", cert_dir=cert_dir,
        anchor_cer=cert_dir / "anchor.cer", thumbprint=THUMB)
    state = installer.verify_system_state(plan)
    assert state["listen_ip_ok"] is False


# --------------------------------------------------------------------------- #
# install：管理员路径
# --------------------------------------------------------------------------- #
def test_install_admin_writes_hosts_and_trusts_cert(fake_system, cert_dir):
    original = fake_system.hosts_file.read_bytes()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is True and result.error is None
    assert result.changed is True
    text = fake_system.hosts_text()
    assert EXPECTED_LINE in text
    assert fake_system.trusted_thumbs() == [THUMB]
    backups = list((fake_system.hosts_file.parent / hosts.BACKUP_DIRNAME).glob("*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert "证书导入" in joined(result) and "hosts 写入成功" in joined(result)


def test_install_second_run_is_noop(fake_system, cert_dir):
    assert installer.install(build_plan(cert_dir)).ok is True
    snapshot = fake_system.hosts_file.read_bytes()
    again = installer.install(build_plan(cert_dir))
    assert again.ok is True and again.changed is False
    assert fake_system.hosts_file.read_bytes() == snapshot
    assert "无需改动" in joined(again)


def test_install_replaces_stale_ip_marker(fake_system, cert_dir):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s %s # hd2proxy\r\n" % (OLD_IP, HOST))
    fake_system.trust_cert()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is True and result.changed is True
    text = fake_system.hosts_text()
    assert EXPECTED_LINE in text
    assert OLD_IP not in text
    assert "127.0.0.1 localhost" in text


def test_install_replaces_commented_marker(fake_system, cert_dir):
    fake_system.write_hosts("127.0.0.1 localhost\r\n# %s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is True
    text = fake_system.hosts_text()
    assert EXPECTED_LINE in text
    assert ("# " + EXPECTED_LINE) not in text


def test_install_missing_anchor_cer_fails(fake_system, cert_dir):
    (cert_dir / "anchor.cer").unlink()
    before = fake_system.hosts_file.read_bytes()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "锚证书文件不存在" in result.error
    assert fake_system.hosts_file.read_bytes() == before


def test_install_rejects_loopback_plan(fake_system, cert_dir):
    plan = installer.InstallPlan(
        host=HOST, listen_ip="127.0.0.1", cert_dir=cert_dir,
        anchor_cer=cert_dir / "anchor.cer", thumbprint=THUMB)
    before = fake_system.hosts_file.read_bytes()
    result = installer.install(plan)
    assert result.ok is False and "回环" in result.error
    assert fake_system.hosts_file.read_bytes() == before


def test_install_certutil_addstore_failure(fake_system, cert_dir, monkeypatch):
    monkeypatch.setenv("HD2PROXY_TEST_FAIL_ADDSTORE", "1")
    before = fake_system.hosts_file.read_bytes()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False
    assert "certutil -addstore 失败" in result.error
    assert fake_system.hosts_file.read_bytes() == before      # 证书失败就不改 hosts


def test_install_certutil_success_but_store_missing(fake_system, cert_dir, monkeypatch):
    monkeypatch.setenv("HD2PROXY_TEST_ADD_NOOP", "1")
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "查不到该指纹" in result.error


def test_install_hosts_write_failure(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(hosts, "apply_edit",
                        lambda plan, backup_dir=None: {"ok": False, "backup": None,
                                                       "error": "模拟写入失败"})
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "hosts 写入失败" in result.error
    assert fake_system.trusted_thumbs() == [THUMB]        # 证书已先导入（改动为部分）


def test_install_currentuser_uses_user_flag(cert_dir):
    plan = build_plan(cert_dir, scope="CurrentUser")
    assert installer._addstore_args(plan) == [
        "-user", "-addstore", "Root", str(plan.anchor_cer)]
    assert installer._delstore_args(plan) == ["-user", "-delstore", "Root", THUMB]


# --------------------------------------------------------------------------- #
# install：非管理员 + UAC
# --------------------------------------------------------------------------- #
def test_install_non_admin_without_elevate_fails(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    before = fake_system.hosts_file.read_bytes()
    result = installer.install(build_plan(cert_dir), allow_elevate=False)
    assert result.ok is False and "禁止提权" in result.error
    assert fake_system.hosts_file.read_bytes() == before
    assert fake_system.trusted_thumbs() == []


def test_install_non_admin_uac_cancelled_changes_nothing(fake_system, cert_dir, monkeypatch):
    """HD2PROXY_ELEVATION_STUB=1：真实 run_elevated 返回「用户取消」，绝不弹 UAC。"""
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setenv("HD2PROXY_ELEVATION_STUB", "1")
    before = fake_system.hosts_file.read_bytes()
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and result.changed is False
    assert "取消" in result.error
    assert fake_system.hosts_file.read_bytes() == before
    assert fake_system.trusted_thumbs() == []


def _fake_child(*, exit_code: int = 0, do_work: bool = True, command: str = "install"):
    """造一个「模拟提权子进程」：按 --plan 读回计划，并在『管理员身份』下执行。"""

    def runner(args, *, wait=True, timeout=180.0):
        assert args[0] == command
        assert "--elevated" in args
        plan_path = Path(args[args.index("--plan") + 1])
        if do_work:
            child_plan = installer.plan_from_dict(
                json.loads(plan_path.read_text(encoding="utf-8")))
            if command == "install":
                hosts.apply_edit(hosts.plan_edit(child_plan.listen_ip, child_plan.host,
                                                 marker=child_plan.marker),
                                 backup_dir=child_plan.backup_dir)
                sysprobe.run_certutil(installer._addstore_args(child_plan))
            else:
                hosts.remove_marker(marker=child_plan.marker, backup_dir=child_plan.backup_dir)
                sysprobe.run_certutil(installer._delstore_args(child_plan))
        return {"launched": True, "cancelled": False, "exit_code": exit_code, "error": None}

    return runner


def test_install_non_admin_elevated_success(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    seen_plan_paths = []
    inner = _fake_child(command="install")

    def runner(args, *, wait=True, timeout=180.0):
        seen_plan_paths.append(Path(args[args.index("--plan") + 1]))
        return inner(args, wait=wait, timeout=timeout)

    monkeypatch.setattr(elevation, "run_elevated", runner)
    result = installer.install(build_plan(cert_dir))
    assert result.ok is True and result.changed is True
    assert EXPECTED_LINE in fake_system.hosts_text()
    assert fake_system.trusted_thumbs() == [THUMB]
    assert "提权进程结束：exit_code=0" in joined(result)
    assert seen_plan_paths and not seen_plan_paths[0].exists()   # 临时计划文件已清理


def test_install_non_admin_elevated_nonzero_exit(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setattr(elevation, "run_elevated",
                        _fake_child(exit_code=2, do_work=False, command="install"))
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "exit_code=2" in result.error


def test_install_non_admin_elevated_but_no_effect(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setattr(elevation, "run_elevated",
                        _fake_child(do_work=False, command="install"))
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "回读校验未通过" in result.error


def test_install_non_admin_elevation_launch_error(fake_system, cert_dir, monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setattr(elevation, "run_elevated",
                        lambda args, *, wait=True, timeout=180.0: {
                            "launched": False, "cancelled": False, "exit_code": None,
                            "error": "模拟 ShellExecuteExW 失败"})
    result = installer.install(build_plan(cert_dir))
    assert result.ok is False and "提权进程未能启动" in result.error


# --------------------------------------------------------------------------- #
# uninstall
# --------------------------------------------------------------------------- #
def test_uninstall_removes_hosts_and_cert(fake_system, cert_dir):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    result = installer.uninstall(build_plan(cert_dir))
    assert result.ok is True and result.changed is True
    assert hosts.count_marker() == 0
    assert fake_system.trusted_thumbs() == []
    assert "由本函数删除" in joined(result)        # 明确「证书文件不在这里删」
    assert (cert_dir / "anchor.cer").exists()      # 证书文件也确实没被删


def test_uninstall_noop_when_system_clean(fake_system, cert_dir):
    before = fake_system.hosts_file.read_bytes()
    result = installer.uninstall(build_plan(cert_dir))
    assert result.ok is True and result.changed is False
    assert fake_system.hosts_file.read_bytes() == before


def test_uninstall_non_admin_uac_cancelled(fake_system, cert_dir, monkeypatch):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setenv("HD2PROXY_ELEVATION_STUB", "1")
    result = installer.uninstall(build_plan(cert_dir))
    assert result.ok is False and "取消" in result.error
    assert hosts.count_marker() == 1               # 什么都没动
    assert fake_system.trusted_thumbs() == [THUMB]


def test_uninstall_non_admin_without_elevate_fails(fake_system, cert_dir, monkeypatch):
    fake_system.write_hosts("%s\r\n" % EXPECTED_LINE)
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    result = installer.uninstall(build_plan(cert_dir), allow_elevate=False)
    assert result.ok is False and "禁止提权" in result.error


def test_uninstall_non_admin_elevated_success(fake_system, cert_dir, monkeypatch):
    fake_system.write_hosts("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    monkeypatch.setattr(elevation, "run_elevated",
                        _fake_child(command="uninstall"))
    result = installer.uninstall(build_plan(cert_dir))
    assert result.ok is True and result.changed is True
    assert hosts.count_marker() == 0
    assert fake_system.trusted_thumbs() == []


def test_uninstall_certutil_delstore_failure(fake_system, cert_dir, monkeypatch):
    fake_system.write_hosts("%s\r\n" % EXPECTED_LINE)
    fake_system.trust_cert()
    monkeypatch.setenv("HD2PROXY_TEST_FAIL_DELSTORE", "1")
    result = installer.uninstall(build_plan(cert_dir))
    assert result.ok is False and "certutil -delstore 失败" in result.error


# --------------------------------------------------------------------------- #
# elevation：argv 构造两种分支 / 提权结果语义（不真弹 UAC）
# --------------------------------------------------------------------------- #
def test_build_elevation_argv_dev_mode(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    entry = tmp_path / "entry.py"                  # 故意不创建：argv[0] 原样保留
    monkeypatch.setattr(sys, "argv", [str(entry), "x"])
    assert elevation.build_elevation_argv(["install", "--plan", "p"]) == [
        sys.executable, str(entry), "install", "--plan", "p"]


def test_build_elevation_argv_frozen(monkeypatch):
    """打包后（PyInstaller 会设 sys.frozen）：直接重启自身 exe，不再带入口脚本。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert elevation.build_elevation_argv(["install", "--plan", "p"]) == [
        sys.executable, "install", "--plan", "p"]


def test_build_elevation_argv_falls_back_to_main_module(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", [""])
    argv = elevation.build_elevation_argv(["info"])
    assert argv[0] == sys.executable
    assert Path(argv[1]).name == "__main__.py" and Path(argv[1]).is_file()
    assert argv[2:] == ["info"]


def test_run_elevated_stub_returns_cancelled(monkeypatch):
    monkeypatch.setenv("HD2PROXY_ELEVATION_STUB", "1")
    assert elevation.run_elevated(["install"]) == {
        "launched": False, "cancelled": True, "exit_code": None, "error": None}


def test_run_elevated_rejects_empty_args(monkeypatch):
    monkeypatch.delenv("HD2PROXY_ELEVATION_STUB", raising=False)
    result = elevation.run_elevated([])
    assert result["launched"] is False and result["cancelled"] is False
    assert result["error"]


def test_run_elevated_accepts_full_argv(tmp_path):
    assert elevation._looks_like_full_argv([sys.executable, "install"]) is True
    assert elevation._looks_like_full_argv([str(tmp_path / "tool.exe"), "install"]) is True
    assert elevation._looks_like_full_argv(["install", "--plan", "p"]) is False
    assert elevation._looks_like_full_argv([]) is False


def test_relaunch_self_builds_subcommand_args(monkeypatch):
    captured = {}

    def fake_run(args, *, wait=True, timeout=180.0):
        captured["args"] = args
        return {"launched": True, "cancelled": False, "exit_code": 0, "error": None}

    monkeypatch.setattr(elevation, "run_elevated", fake_run)
    result = elevation.relaunch_self("install", "--plan", "p", "--elevated")
    assert captured["args"] == ["install", "--plan", "p", "--elevated"]
    assert result["exit_code"] == 0


def test_can_elevate_reflects_admin_flag(monkeypatch):
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)
    assert elevation.can_elevate() is True
    monkeypatch.setattr(sysprobe, "is_admin", lambda: True)
    assert elevation.can_elevate() is False
