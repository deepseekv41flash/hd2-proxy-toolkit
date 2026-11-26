"""hosts 模块离线测试。

原则：**绝不碰真实系统 hosts** —— 每个用例都用 autouse fixture 把
``HD2PROXY_HOSTS_PATH`` 指到 ``tmp_path``，读写只发生在临时目录里。
覆盖点：编码（UTF-8 / BOM / GBK）、换行（CRLF 不混行、LF 保持、末行无换行）、
四种起始状态（无 marker / 正确 marker / 旧 IP marker / marker 被注释）、
原子写 + 备份 + 重试、以及「只动本工具的行」。
"""

import os
from pathlib import Path

import pytest

from hd2proxy.engine import hosts

HOST = "api.live.prod.thehelldiversgame.com"
OLD_IP = "10.0.0.5"
NEW_IP = "192.168.1.50"
EXPECTED = "%s %s # hd2proxy" % (NEW_IP, HOST)


@pytest.fixture(autouse=True)
def isolated_hosts(tmp_path, monkeypatch):
    """每个用例一份独立的 hosts 文件（空文件），并让 hosts_path() 指向它。"""
    path = tmp_path / "hosts"
    path.write_bytes(b"")
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(path))
    return path


def _raw(path):
    return Path(path).read_bytes()


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def test_hosts_path_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom-hosts"
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(target))
    assert hosts.hosts_path() == target


def test_hosts_path_default_derived_from_systemroot(tmp_path, monkeypatch):
    monkeypatch.delenv("HD2PROXY_HOSTS_PATH", raising=False)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.delenv("windir", raising=False)
    assert hosts.hosts_path() == tmp_path / "System32" / "drivers" / "etc" / "hosts"


def test_hosts_path_longer_override_wins(tmp_path, monkeypatch):
    """SystemRoot 也在时，显式覆盖优先（测试/便携模式的语义）。"""
    monkeypatch.setenv("SystemRoot", str(tmp_path / "win"))
    target = tmp_path / "override"
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(target))
    assert hosts.hosts_path() == target


# --------------------------------------------------------------------------- #
# 读取 / 编码
# --------------------------------------------------------------------------- #
def test_read_hosts_utf8(isolated_hosts):
    isolated_hosts.write_bytes("127.0.0.1 localhost\r\n# 中文注释\r\n".encode("utf-8"))
    assert "# 中文注释" in hosts.read_hosts()


def test_read_hosts_utf8_bom(isolated_hosts):
    isolated_hosts.write_bytes(b"\xef\xbb\xbf" + "# 中文注释\r\n".encode("utf-8"))
    assert "中文注释" in hosts.read_hosts()


def test_read_hosts_gbk(isolated_hosts):
    isolated_hosts.write_bytes("# 中文注释\r\n".encode("gbk"))
    assert "中文注释" in hosts.read_hosts()


def test_read_hosts_missing_returns_empty(tmp_path):
    assert hosts.read_hosts(tmp_path / "no-such-hosts") == ""


# --------------------------------------------------------------------------- #
# find_marker（纯函数）
# --------------------------------------------------------------------------- #
def test_find_marker_absent():
    assert hosts.find_marker("127.0.0.1 localhost\r\n# 普通注释\r\n") is None


def test_find_marker_active():
    info = hosts.find_marker("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED)
    assert info == {"line_no": 2, "line": EXPECTED, "ip": NEW_IP, "host": HOST,
                    "commented": False}


def test_find_marker_commented_keeps_ip_and_host():
    line = "# " + EXPECTED
    info = hosts.find_marker(line + "\r\n")
    assert info["commented"] is True
    assert info["ip"] == NEW_IP
    assert info["host"] == HOST


def test_find_marker_only_marker_line():
    info = hosts.find_marker("# hd2proxy\r\n")
    assert info is not None and info["commented"] is True and info["ip"] is None


def test_find_marker_other_comment_is_not_mapping():
    """marker 前面是别人的注释文字时，不应把「注释里的词」当 IP/host 解析。"""
    info = hosts.find_marker("# 上次手工改过 10.0.0.5 这一行 # hd2proxy\r\n")
    assert info is not None
    assert info["commented"] is True
    assert info["ip"] is None
    assert info["host"] is None


def test_find_marker_double_comment_still_parses():
    info = hosts.find_marker("# # %s %s # hd2proxy\r\n" % (NEW_IP, HOST))
    assert info["commented"] is True
    assert info["ip"] == NEW_IP


# --------------------------------------------------------------------------- #
# plan_edit：四种起始状态（验收要求的实测点）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "initial_text, expected_action, expected_old",
    [
        ("127.0.0.1 localhost\r\n", "add", None),                          # ① 无 marker
        ("127.0.0.1 localhost\r\n%s\r\n" % EXPECTED, "noop", EXPECTED),    # ② 正确 marker
        ("127.0.0.1 localhost\r\n%s %s # hd2proxy\r\n" % (OLD_IP, HOST),
         "replace", "%s %s # hd2proxy" % (OLD_IP, HOST)),                  # ③ 旧 IP marker
        ("127.0.0.1 localhost\r\n# %s\r\n" % EXPECTED,
         "replace", "# " + EXPECTED),                                      # ④ marker 被注释
    ],
    ids=["no-marker", "correct-marker", "stale-ip-marker", "commented-marker"],
)
def test_plan_edit_four_start_states(isolated_hosts, initial_text, expected_action,
                                     expected_old):
    isolated_hosts.write_bytes(initial_text.encode("utf-8"))
    plan = hosts.plan_edit(NEW_IP, HOST)
    assert plan["action"] == expected_action
    assert plan["path"] == str(isolated_hosts)
    assert plan["new_line"] == EXPECTED
    assert plan["old_line"] == expected_old
    assert plan["reason"]


def test_plan_edit_noop_is_whitespace_tolerant(isolated_hosts):
    """同一映射、只是空格多几个，不该判成 replace（避免每次安装都重写文件）。"""
    isolated_hosts.write_bytes(("%s  %s   # hd2proxy\r\n" % (NEW_IP, HOST)).encode())
    assert hosts.plan_edit(NEW_IP, HOST)["action"] == "noop"


def test_plan_edit_rejects_invalid_ip(isolated_hosts):
    plan = hosts.plan_edit("not-an-ip", HOST)
    assert plan["action"] == "error" and "IP 不合法" in plan["reason"]


def test_plan_edit_rejects_empty_host(isolated_hosts):
    plan = hosts.plan_edit(NEW_IP, "   ")
    assert plan["action"] == "error" and "host 不合法" in plan["reason"]


def test_plan_edit_rejects_host_with_space(isolated_hosts):
    plan = hosts.plan_edit(NEW_IP, "a b")
    assert plan["action"] == "error"


def test_plan_edit_rejects_empty_marker(isolated_hosts):
    plan = hosts.plan_edit(NEW_IP, HOST, marker="")
    assert plan["action"] == "error"


def test_plan_edit_rejects_duplicate_markers(isolated_hosts):
    isolated_hosts.write_bytes(("%s\r\n%s\r\n" % (EXPECTED, EXPECTED)).encode())
    plan = hosts.plan_edit(NEW_IP, HOST)
    assert plan["action"] == "error" and "2 行" in plan["reason"]


def test_plan_edit_hosts_layer_does_not_police_loopback(isolated_hosts):
    """回环地址的校验属于 installer/sysprobe 层；hosts 层只负责「写对这个映射」。"""
    assert hosts.plan_edit("127.0.0.1", HOST)["action"] == "add"


# --------------------------------------------------------------------------- #
# apply_edit：原子写 / 备份 / 换行 / 只动自己的行
# --------------------------------------------------------------------------- #
def test_apply_edit_add_crlf_file_stays_crlf(isolated_hosts):
    original = "127.0.0.1 localhost\r\n\r\n# 注释行\r\n".encode("utf-8")
    isolated_hosts.write_bytes(original)
    plan = hosts.plan_edit(NEW_IP, HOST)
    assert plan["action"] == "add"

    result = hosts.apply_edit(plan)
    assert result["ok"] is True and result["error"] is None
    data = _raw(isolated_hosts)
    assert data.startswith("127.0.0.1 localhost\r\n\r\n# 注释行\r\n".encode("utf-8"))
    assert data.endswith(EXPECTED.encode() + b"\r\n")
    # 关键：CRLF 文件改写后不能出现裸 LF（行尾没混）
    assert data.count(b"\r\n") == data.count(b"\n")
    # 备份就是改前字节，且在默认备份目录
    backup = Path(result["backup"])
    assert backup.is_file() and backup.read_bytes() == original
    assert backup.parent.name == hosts.BACKUP_DIRNAME


def test_apply_edit_replace_old_ip_line(isolated_hosts):
    old_line = "%s %s # hd2proxy" % (OLD_IP, HOST)
    isolated_hosts.write_bytes(
        ("127.0.0.1 localhost\r\n" + old_line + "\r\n# tail\r\n").encode())
    plan = hosts.plan_edit(NEW_IP, HOST)
    assert plan["action"] == "replace"

    assert hosts.apply_edit(plan)["ok"] is True
    text = _raw(isolated_hosts).decode("utf-8")
    assert EXPECTED in text
    assert old_line not in text
    assert "# tail" in text
    assert hosts.plan_edit(NEW_IP, HOST)["action"] == "noop"


def test_apply_edit_noop_does_not_touch_file(isolated_hosts):
    original = (EXPECTED + "\r\n").encode()
    isolated_hosts.write_bytes(original)
    plan = hosts.plan_edit(NEW_IP, HOST)
    assert plan["action"] == "noop"

    result = hosts.apply_edit(plan)
    assert result == {"ok": True, "backup": None, "error": None}
    assert _raw(isolated_hosts) == original
    assert not (isolated_hosts.parent / hosts.BACKUP_DIRNAME).exists()


def test_apply_edit_rejects_error_plan(isolated_hosts):
    result = hosts.apply_edit({"action": "error", "reason": "坏 IP"})
    assert result["ok"] is False and "坏 IP" in result["error"]


def test_apply_edit_lf_file_stays_lf(isolated_hosts):
    isolated_hosts.write_bytes(b"127.0.0.1 localhost\n")
    assert hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST))["ok"] is True
    data = _raw(isolated_hosts)
    assert b"\r\n" not in data
    assert data == b"127.0.0.1 localhost\n" + EXPECTED.encode() + b"\n"


def test_apply_edit_preserves_missing_final_newline(isolated_hosts):
    isolated_hosts.write_bytes(b"# only comment")
    default_newline = b"\r\n" if os.name == "nt" else b"\n"
    assert hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST))["ok"] is True
    assert _raw(isolated_hosts) == b"# only comment" + default_newline + EXPECTED.encode()


def test_apply_edit_creates_missing_file(tmp_path, monkeypatch):
    target = tmp_path / "brand-new-hosts"
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(target))
    result = hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST))
    assert result["ok"] is True
    assert result["backup"] is None                 # 原本没有文件，无需备份
    assert _raw(target) == EXPECTED.encode()


def test_apply_edit_custom_backup_dir(isolated_hosts, tmp_path):
    isolated_hosts.write_bytes(b"127.0.0.1 localhost\r\n")
    backups = tmp_path / "my-data" / "backups"
    result = hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST), backup_dir=backups)
    assert Path(result["backup"]).parent == backups


def test_apply_edit_self_heals_stale_plan(isolated_hosts):
    """plan 之后文件被别人改成目标状态：按「当前磁盘内容」重判，不重复写。"""
    isolated_hosts.write_bytes(b"127.0.0.1 localhost\r\n")
    plan = hosts.plan_edit(NEW_IP, HOST)             # 此时判定是 add
    isolated_hosts.write_bytes((EXPECTED + "\r\n").encode())
    result = hosts.apply_edit(plan)
    assert result["ok"] is True and result["backup"] is None
    assert _raw(isolated_hosts) == (EXPECTED + "\r\n").encode()


def test_apply_edit_retries_when_file_locked(isolated_hosts, monkeypatch):
    """模拟杀软/加速器短暂锁住 hosts：前两次替换失败，第三次成功。"""
    isolated_hosts.write_bytes(b"127.0.0.1 localhost\r\n")
    monkeypatch.setattr(hosts, "WRITE_RETRY_INTERVAL", 0)
    real_replace = hosts._replace_file
    calls = {"n": 0}

    def flaky_replace(src, dst):
        if Path(dst).name == "hosts":               # 只锁 hosts 本身，备份照常写
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError("模拟 hosts 被独占")
        return real_replace(src, dst)

    monkeypatch.setattr(hosts, "_replace_file", flaky_replace)
    result = hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST))
    assert result["ok"] is True
    assert calls["n"] == 3
    assert hosts.plan_edit(NEW_IP, HOST)["action"] == "noop"


def test_apply_edit_gives_up_after_retries_keeps_original(isolated_hosts, monkeypatch):
    original = b"127.0.0.1 localhost\r\n"
    isolated_hosts.write_bytes(original)
    monkeypatch.setattr(hosts, "WRITE_RETRY_INTERVAL", 0)

    def always_locked(src, dst):
        if Path(dst).name == "hosts":
            raise PermissionError("模拟 hosts 一直被杀软占用")
        return os.replace(src, dst)

    monkeypatch.setattr(hosts, "_replace_file", always_locked)
    result = hosts.apply_edit(hosts.plan_edit(NEW_IP, HOST))
    assert result["ok"] is False and "重试" in result["error"]
    assert _raw(isolated_hosts) == original
    leftovers = [p.name for p in isolated_hosts.parent.iterdir()
                 if p.name.endswith(".hd2proxy.tmp")]
    assert leftovers == []


# --------------------------------------------------------------------------- #
# remove_marker：还原
# --------------------------------------------------------------------------- #
def test_remove_marker_removes_active_and_commented(isolated_hosts):
    active = EXPECTED
    commented = "# " + active
    original = ("127.0.0.1 localhost\r\n%s\r\n%s\r\n\r\n# 别人的注释\r\n"
                % (active, commented)).encode()
    isolated_hosts.write_bytes(original)
    assert hosts.count_marker() == 2

    result = hosts.remove_marker()
    assert result == {"ok": True, "removed": 2, "error": None}
    expected = "127.0.0.1 localhost\r\n\r\n# 别人的注释\r\n".encode("utf-8")
    assert _raw(isolated_hosts) == expected
    backups = list((isolated_hosts.parent / hosts.BACKUP_DIRNAME).glob("*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == original


def test_remove_marker_noop_when_absent(isolated_hosts):
    original = b"127.0.0.1 localhost\r\n"
    isolated_hosts.write_bytes(original)
    assert hosts.remove_marker() == {"ok": True, "removed": 0, "error": None}
    assert _raw(isolated_hosts) == original
    assert not (isolated_hosts.parent / hosts.BACKUP_DIRNAME).exists()


def test_remove_marker_keeps_gbk_encoding(isolated_hosts):
    isolated_hosts.write_bytes(("# 中文注释\r\n%s\r\n" % EXPECTED).encode("gbk"))
    result = hosts.remove_marker()
    assert result["removed"] == 1
    assert _raw(isolated_hosts) == "# 中文注释\r\n".encode("gbk")


def test_remove_marker_rejects_empty_marker(isolated_hosts):
    assert hosts.remove_marker(marker="")["ok"] is False


# --------------------------------------------------------------------------- #
# 自定义 marker（避免「只有默认 marker 能删」的隐性耦合）
# --------------------------------------------------------------------------- #
def test_custom_marker_roundtrip(isolated_hosts):
    marker = "# my-tool-marker"
    isolated_hosts.write_bytes(b"127.0.0.1 localhost\r\n")
    plan = hosts.plan_edit(NEW_IP, HOST, marker=marker)
    assert plan["marker"] == marker
    assert hosts.apply_edit(plan)["ok"] is True
    assert hosts.find_marker(hosts.read_hosts()) is None       # 默认 marker 认不到
    assert hosts.count_marker(marker=marker) == 1
    assert hosts.remove_marker(marker=marker)["removed"] == 1


# ---------------------------------------------------------------- CLI：hosts status/on/off（2026-11-26）
#
# 研究线不开代理时要能"恢复直连"：hosts off 只删我们那一行，**不碰证书信任**。


def _cli_args(**kw):
    class A:
        hosts_cmd = "status"
        elevated = False
        ip = ""
        host = ""
    a = A()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_cli_hosts_status_and_off(tmp_path, monkeypatch, capsys):
    from hd2proxy import __main__ as cli
    from hd2proxy.engine import sysprobe

    # CI runner 本身就是管理员（GitHub windows-latest 以 admin 跑），
    # 不强制"非管理员"的话会直接走写入分支，测不到 UAC 取消路径。
    monkeypatch.setattr(sysprobe, "is_admin", lambda: False)

    hp = tmp_path / "hosts"
    hp.write_text("127.0.0.1  localhost\n"
                  "100.10.10.10 api.live.prod.thehelldiversgame.com # hd2proxy\n",
                  encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(hp))

    assert cli.cmd_hosts(_cli_args()) == 0
    out = capsys.readouterr().out
    assert "生效中" in out and "100.10.10.10" in out

    # 非管理员且用户拒绝 UAC → 不改动、返回失败
    monkeypatch.setenv("HD2PROXY_ELEVATION_STUB", "1")
    assert cli.cmd_hosts(_cli_args(hosts_cmd="off")) == cli.FAIL
    assert "hd2proxy" in hp.read_text(encoding="utf-8")

    # 已在管理员进程里 → 真的删掉我们那一行，别人的行原样保留
    assert cli.cmd_hosts(_cli_args(hosts_cmd="off", elevated=True)) == 0
    text = hp.read_text(encoding="utf-8")
    assert "hd2proxy" not in text
    assert "127.0.0.1  localhost" in text

    # 还原后再查状态：未劫持
    capsys.readouterr()
    assert cli.cmd_hosts(_cli_args()) == 0
    assert "未劫持" in capsys.readouterr().out


def test_cli_hosts_on_writes_marker(tmp_path, monkeypatch, capsys):
    from hd2proxy import __main__ as cli

    hp = tmp_path / "hosts"
    hp.write_text("127.0.0.1  localhost\n", encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(hp))

    assert cli.cmd_hosts(_cli_args(hosts_cmd="on", elevated=True,
                                   ip="100.20.30.40")) == 0
    text = hp.read_text(encoding="utf-8")
    assert "100.20.30.40 api.live.prod.thehelldiversgame.com # hd2proxy" in text
    assert "127.0.0.1  localhost" in text
    info = hosts.find_marker(text)
    assert info and info["ip"] == "100.20.30.40"
