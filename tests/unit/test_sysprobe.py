"""sysprobe 模块离线测试。

不碰真实系统：ipconfig / netstat / tasklist / certutil 全部用真实格式的**文本夹具**或
临时生成的桩脚本喂进去；``HD2PROXY_CERTUTIL`` 默认指向一个「找不到证书」的桩，
保证任何用例都不会跑去读真实证书存储。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hd2proxy.engine import sysprobe

HOST = "api.live.prod.thehelldiversgame.com"
THUMB = "AABBCCDDEEFF00112233445566778899AABBCCDD"


# 中文 Windows 的真实 ipconfig 输出（含「媒体已断开」的网卡与虚拟网卡）
IPCONFIG_ZH = """Windows IP 配置


以太网适配器 vEthernet (Default Switch):

   连接特定的 DNS 后缀 . . . . . . . : 
   IPv4 地址 . . . . . . . . . . . . : 172.26.64.1
   子网掩码  . . . . . . . . . . . . : 255.255.240.0
   默认网关. . . . . . . . . . . . . : 

以太网适配器 以太网:

   连接特定的 DNS 后缀 . . . . . . . : 
   IPv6 地址 . . . . . . . . . . . . : 240e:398:f11:8d28:2d09:2e1e:58ad:7daa
   IPv4 地址 . . . . . . . . . . . . : 100.67.169.17
   子网掩码  . . . . . . . . . . . . : 255.255.0.0
   默认网关. . . . . . . . . . . . . : 100.67.0.1

无线局域网适配器 本地连接* 9:

   媒体状态  . . . . . . . . . . . . : 媒体已断开连接
   连接特定的 DNS 后缀 . . . . . . . : 

以太网适配器 VMware Network Adapter VMnet1:

   连接特定的 DNS 后缀 . . . . . . . : 
   IPv4 地址 . . . . . . . . . . . . : 192.168.136.1
   子网掩码  . . . . . . . . . . . . : 255.255.255.0
   默认网关. . . . . . . . . . . . . : 

以太网适配器 蓝牙网络连接:

   媒体状态  . . . . . . . . . . . . : 媒体已断开连接
"""

# 英文 Windows 的输出；断开的隧道网卡留着旧 IPv4，解析时必须排除
IPCONFIG_EN = """Windows IP Configuration


Ethernet adapter Ethernet:

   Connection-specific DNS Suffix  . : 
   IPv4 Address. . . . . . . . . . . : 10.1.2.3
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 10.1.2.1

Wireless LAN adapter Wi-Fi:

   Media State . . . . . . . . . . . : Media disconnected
   Connection-specific DNS Suffix  . : 

Tunnel adapter Teredo Tunneling Pseudo-Interface:

   Media State . . . . . . . . . . . : Media disconnected
   IPv4 Address. . . . . . . . . . . : 192.168.99.1
"""

NETSTAT_443 = """活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       1234
  TCP    100.67.169.17:443      0.0.0.0:0              LISTENING       1234
  TCP    127.0.0.1:443          0.0.0.0:0              LISTENING       4321
  TCP    0.0.0.0:8443           0.0.0.0:0              LISTENING       999
  TCP    127.0.0.1:5555         127.0.0.1:5555         ESTABLISHED     7777
"""

TASKLIST_CSV = (
    '"System Idle Process","0","Services","0","8 K"\r\n'
    '"python.exe","1234","Console","1","100,000 K"\r\n'
    '"nginx.exe","4321","Services","0","5,000 K"\r\n'
)

# certutil 桩：把收到的 argv 写成 JSON，再按环境变量返回指定 exit code
ECHO_STUB = (
    "import json, os, sys\n"
    "with open(os.environ['HD2PROXY_TEST_ARGV'], 'w', encoding='utf-8') as fh:\n"
    "    json.dump(sys.argv[1:], fh)\n"
    "sys.exit(int(os.environ.get('HD2PROXY_TEST_EXIT', '0')))\n"
)


@pytest.fixture(autouse=True)
def no_real_system(tmp_path, monkeypatch):
    """兜底隔离：hosts 路径指到临时文件；certutil 指到「找不到证书」的桩。"""
    stub = tmp_path / "certutil_notfound.py"
    stub.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_CERTUTIL", str(stub))
    monkeypatch.setenv("HD2PROXY_HOSTS_PATH", str(tmp_path / "hosts"))
    sysprobe.clear_caches()
    yield
    sysprobe.clear_caches()


def _make_stub(tmp_path, monkeypatch, exit_code="0"):
    """生成会记录 argv 的 certutil 桩，返回 argv 记录文件路径。"""
    argv_file = tmp_path / "certutil-argv.json"
    stub = tmp_path / "certutil_echo.py"
    stub.write_text(ECHO_STUB, encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_CERTUTIL", str(stub))
    monkeypatch.setenv("HD2PROXY_TEST_ARGV", str(argv_file))
    monkeypatch.setenv("HD2PROXY_TEST_EXIT", exit_code)
    return argv_file


def _fake_run(stdout_map):
    """按 argv[0] 分派假命令输出；未登记的命令返回失败。

    ``**kwargs`` 必须收：``_run`` 现在会传 ``creationflags`` / ``startupinfo``（隐藏窗口）。
    """
    calls = []

    def runner(argv, timeout=sysprobe.CMD_TIMEOUT, **kwargs):
        calls.append(list(argv))
        for key, text in stdout_map.items():
            if argv[0] == key:
                return subprocess.CompletedProcess(argv, 0, stdout=text.encode("utf-8"),
                                                   stderr=b"")
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"")

    runner.calls = calls
    return runner


# 进程名固定表：离线测试绝不能去读真实进程（否则断言随机失败）
NAMES_443 = {1234: "python.exe", 4321: "nginx.exe", 5678: "other.exe"}


def _patch_probe(monkeypatch, netstat_text, names=None):
    """把 netstat 输出与进程名表都固定住；返回假命令 runner（可查 calls）。

    进程名走 ``_process_names`` 注入而不是 tasklist 文本：新版实现优先用 Toolhelp
    快照（无子进程），离线测试只有直接注入这个名字映射才不依赖本机进程。
    """
    runner = _fake_run({"netstat": netstat_text})
    monkeypatch.setattr(sysprobe, "_run", runner)
    monkeypatch.setattr(sysprobe, "_process_names",
                        lambda: dict(NAMES_443 if names is None else names))
    monkeypatch.setattr(sysprobe, "_proc_path", lambda pid: "")
    return runner


# --------------------------------------------------------------------------- #
# 回环 / 监听地址
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value, expected", [
    ("127.0.0.1", True),
    ("127.9.9.9", True),
    ("::1", True),
    ("localhost", True),
    ("192.168.1.5", False),
    ("0.0.0.0", False),
    ("", False),
    ("not-an-ip", False),
    (None, False),
])
def test_is_loopback(value, expected):
    assert sysprobe.is_loopback(value) is expected


@pytest.mark.parametrize("value, keyword", [
    ("127.0.0.1", "回环"),
    ("0.0.0.0", "0.0.0.0"),
    ("localhost", "回环"),
    ("169.254.10.1", "自动配置"),
    ("fef0::1", "不是合法"),
    ("255.255.255.255", "广播"),
])
def test_validate_listen_ip_rejects(value, keyword):
    problem = sysprobe.validate_listen_ip(value)
    assert problem is not None and keyword in problem


def test_validate_listen_ip_accepts_lan_address():
    assert sysprobe.validate_listen_ip("192.168.1.50") is None
    assert sysprobe.validate_listen_ip("100.67.169.17") is None


def test_resolve_listen_ip_explicit():
    assert sysprobe.resolve_listen_ip("192.168.1.50") == "192.168.1.50"
    assert sysprobe.resolve_listen_ip(" 10.0.0.9 ") == "10.0.0.9"


@pytest.mark.parametrize("value", ["127.0.0.1", "127.5.5.5", "0.0.0.0",
                                   "localhost", "abc", "169.254.1.2"])
def test_resolve_listen_ip_rejects_bad_values(value):
    with pytest.raises(ValueError):
        sysprobe.resolve_listen_ip(value)


@pytest.mark.parametrize("value", [None, "", "auto", "AUTO"])
def test_resolve_listen_ip_auto_uses_default_route(value, monkeypatch):
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: "100.67.169.17")
    monkeypatch.setattr(sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "100.67.169.17", "interface": "以太网", "is_loopback": False,
         "is_virtual": False},
    ])
    assert sysprobe.resolve_listen_ip(value) == "100.67.169.17"


def test_resolve_listen_ip_auto_skips_virtual_default_route(monkeypatch):
    """TUN / 路由模式代理把默认路由接管到虚拟网卡时，不能采信它（实测 Clash TUN / UU 路由）。"""
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: "198.18.0.1")
    monkeypatch.setattr(sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "198.18.0.1", "interface": "Mihomo", "is_loopback": False,
         "is_virtual": True},
        {"ip": "100.67.169.17", "interface": "以太网", "is_loopback": False,
         "is_virtual": False},
    ])
    assert sysprobe.resolve_listen_ip("auto") == "100.67.169.17"


def test_resolve_listen_ip_auto_trusts_route_when_enumeration_empty(monkeypatch):
    """网卡枚举失败（entries 为空）时保留旧行为，避免无 ipconfig 环境直接报错。"""
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: "10.1.2.3")
    monkeypatch.setattr(sysprobe, "local_ipv4_addresses", lambda: [])
    assert sysprobe.resolve_listen_ip("auto") == "10.1.2.3"


def test_resolve_listen_ip_auto_prefers_physical_nic(monkeypatch):
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: None)
    monkeypatch.setattr(sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "172.26.64.1", "interface": "vEthernet", "is_loopback": False,
         "is_virtual": True},
        {"ip": "100.67.169.17", "interface": "以太网", "is_loopback": False,
         "is_virtual": False},
    ])
    assert sysprobe.resolve_listen_ip("auto") == "100.67.169.17"


def test_resolve_listen_ip_auto_raises_when_no_candidate(monkeypatch):
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: None)
    monkeypatch.setattr(sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "127.0.0.1", "interface": "Loopback", "is_loopback": True,
         "is_virtual": False},
    ])
    with pytest.raises(ValueError):
        sysprobe.resolve_listen_ip("auto")


# --------------------------------------------------------------------------- #
# ipconfig 解析
# --------------------------------------------------------------------------- #
def test_parse_ipconfig_chinese():
    entries = sysprobe._parse_ipconfig(IPCONFIG_ZH)
    by_ip = {entry["ip"]: entry for entry in entries}
    assert set(by_ip) == {"172.26.64.1", "100.67.169.17", "192.168.136.1"}
    assert by_ip["100.67.169.17"]["interface"] == "以太网"
    assert by_ip["100.67.169.17"]["is_virtual"] is False
    assert by_ip["100.67.169.17"]["is_loopback"] is False
    assert by_ip["172.26.64.1"]["is_virtual"] is True          # vEthernet (Default Switch)
    assert by_ip["192.168.136.1"]["is_virtual"] is True        # VMware VMnet1


def test_parse_ipconfig_english_skips_disconnected():
    entries = sysprobe._parse_ipconfig(IPCONFIG_EN)
    assert [entry["ip"] for entry in entries] == ["10.1.2.3"]
    assert entries[0]["interface"] == "Ethernet"
    assert entries[0]["is_virtual"] is False


def test_local_ipv4_addresses_uses_ipconfig(monkeypatch):
    monkeypatch.setattr(sysprobe, "_ipconfig_text", lambda: IPCONFIG_ZH)
    entries = sysprobe.local_ipv4_addresses()
    assert {entry["ip"] for entry in entries} == {
        "172.26.64.1", "100.67.169.17", "192.168.136.1"}


def test_local_ipv4_addresses_falls_back_to_socket(monkeypatch):
    monkeypatch.setattr(sysprobe, "_ipconfig_text", lambda: "")
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: "100.67.169.17")

    def no_dns(*args, **kwargs):
        raise OSError("模拟主机名解析失败")

    monkeypatch.setattr(sysprobe.socket, "getaddrinfo", no_dns)
    entries = sysprobe.local_ipv4_addresses()
    assert entries == [{"ip": "100.67.169.17", "interface": "（默认路由出口）",
                        "is_loopback": False, "is_virtual": False}]


def test_local_ipv4_addresses_returns_empty_on_total_failure(monkeypatch):
    monkeypatch.setattr(sysprobe, "_ipconfig_text", lambda: "")
    monkeypatch.setattr(sysprobe, "_default_route_ip", lambda: None)
    def no_dns(*args, **kwargs):
        raise OSError("模拟主机名解析失败")

    monkeypatch.setattr(sysprobe.socket, "getaddrinfo", no_dns)
    assert sysprobe.local_ipv4_addresses() == []


@pytest.mark.parametrize("name, expected", [
    ("vEthernet (Default Switch)", True),
    ("VMware Network Adapter VMnet8", True),
    ("TAP-Windows Adapter V9", True),
    ("Tunnel adapter Teredo", True),
    ("以太网", False),
    ("Wi-Fi", False),
    ("WLAN", False),
])
def test_is_virtual_interface(name, expected):
    assert sysprobe._is_virtual_interface(name, "192.168.1.2") is expected


def test_is_virtual_interface_treats_apipa_as_virtual():
    assert sysprobe._is_virtual_interface("以太网", "169.254.7.7") is True


# --------------------------------------------------------------------------- #
# 端口占用
# --------------------------------------------------------------------------- #
def test_port_owner_netstat_and_tasklist(monkeypatch):
    _patch_probe(monkeypatch, NETSTAT_443)
    owners = sysprobe.port_owner(443)
    assert owners == [
        {"pid": 1234, "name": "python.exe", "addr": "0.0.0.0:443"},
        {"pid": 4321, "name": "nginx.exe", "addr": "127.0.0.1:443"},
    ]


def test_port_owner_unknown_process_name(monkeypatch):
    # 999 不在固定名字表里 -> 名字列 "?"（不能整条丢掉，PID 仍是关键线索）
    _patch_probe(monkeypatch, NETSTAT_443)
    owners = sysprobe.port_owner(8443)
    assert owners == [{"pid": 999, "name": "?", "addr": "0.0.0.0:8443"}]


def test_port_owner_caches_for_three_seconds(monkeypatch):
    runner = _patch_probe(monkeypatch, NETSTAT_443)
    assert sysprobe.port_owner(443)
    calls_after_first = len(runner.calls)
    assert sysprobe.port_owner(443)                 # 命中缓存，不再 spawn 进程
    assert len(runner.calls) == calls_after_first


def test_port_owner_returns_empty_when_netstat_fails(monkeypatch):
    monkeypatch.setattr(sysprobe, "_run", lambda argv, timeout=0, **kw: None)
    assert sysprobe.port_owner(443) == []


def test_port_in_use(monkeypatch):
    _patch_probe(monkeypatch, NETSTAT_443)
    assert sysprobe.port_in_use(443) is True
    assert sysprobe.port_in_use(5555) is False      # 只有 ESTABLISHED，没有 LISTENING


def test_clear_caches_forces_requery(monkeypatch):
    runner = _patch_probe(monkeypatch, NETSTAT_443)
    sysprobe.port_owner(443)
    calls_after_first = len(runner.calls)
    sysprobe.clear_caches()
    sysprobe.port_owner(443)
    assert len(runner.calls) > calls_after_first


def test_listeners_all_spawns_one_netstat_for_many_ports(monkeypatch):
    """核心回归：3 个端口共用**一条** netstat。

    修复前每端口 spawn 两条 ``netstat -p TCP`` / ``-p TCPv6``（共 6 个控制台子进程，
    每个都会弹一个窗口、约 100ms），这正是「切总览页卡一下 + 弹几个 PowerShell 窗口」。
    """
    runner = _patch_probe(monkeypatch, NETSTAT_MIXED)
    for port in (443, 8080, 17897):
        sysprobe.port_listeners(port)
    netstat_calls = [call for call in runner.calls if call and call[0] == "netstat"]
    assert netstat_calls == [["netstat", "-ano"]]


def test_clear_caches_resets_names_and_listeners(monkeypatch):
    """三张缓存都要清；只清 _PORT_CACHE 会让引擎停掉后仍显示旧占用者。"""
    runner = _fake_run({"netstat": NETSTAT_MIXED})
    monkeypatch.setattr(sysprobe, "_run", runner)
    monkeypatch.setattr(sysprobe, "_snapshot_process_names", lambda: dict(NAMES_443))
    monkeypatch.setattr(sysprobe, "_proc_path", lambda pid: "")
    sysprobe.port_listeners(443)
    assert sysprobe._NAMES_CACHE is not None
    assert sysprobe._LISTENERS_CACHE is not None
    sysprobe.clear_caches()
    assert sysprobe._PORT_CACHE == {}
    assert sysprobe._NAMES_CACHE is None
    assert sysprobe._LISTENERS_CACHE is None


def test_process_names_falls_back_to_tasklist(monkeypatch):
    """Toolhelp 快照失败时才退回 tasklist CSV（唯一还会 spawn 的降级路径）。"""
    runner = _fake_run({"tasklist": TASKLIST_CSV})
    monkeypatch.setattr(sysprobe, "_run", runner)
    monkeypatch.setattr(sysprobe, "_snapshot_process_names", lambda: {})
    sysprobe.clear_caches()
    assert sysprobe._process_names()[1234] == "python.exe"
    assert runner.calls == [["tasklist", "/NH", "/FO", "CSV"]]


def test_parse_all_listeners_multi_port_and_ipv6():
    """一条 netstat -ano 同时解析多端口 / 通配 / IPv6；不把 ESTABLISHED 当监听。"""
    text = NETSTAT_MIXED + (
        "  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       2001\n"
        "  TCP    [::]:17897              [::]:0                 LISTENING       2002\n"
        "  TCP    127.0.0.1:5555         127.0.0.1:5555         ESTABLISHED     7777\n")
    table = sysprobe._parse_all_listeners(text)
    assert sorted({item["pid"] for item in table[443]}) == [1234, 4321, 5678]
    assert table[8080] == [{"pid": 2001, "addr": "0.0.0.0:8080", "host": "0.0.0.0"}]
    assert table[17897] == [{"pid": 2002, "addr": "[::]:17897", "host": "::"}]
    assert 5555 not in table                       # ESTABLISHED 不是监听


@pytest.mark.skipif(os.name != "nt", reason="只有 Windows 需要隐藏控制台窗口")
def test_subprocess_kwargs_hides_console_window():
    """windowed GUI 里 spawn 控制台程序必须带 CREATE_NO_WINDOW，否则每个子进程弹一个窗口。"""
    kwargs = sysprobe._subprocess_kwargs()
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    info = kwargs["startupinfo"]
    assert info.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert info.wShowWindow == 0                   # SW_HIDE


def test_run_forwards_hidden_window_kwargs(monkeypatch):
    """``_run`` 必须把隐藏窗口参数真的传给 subprocess.run（不能只定义不接线）。"""
    seen = {}
    sentinel = subprocess.CompletedProcess(["x"], 0, stdout=b"", stderr=b"")

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen.update(kwargs)
        return sentinel

    monkeypatch.setattr(sysprobe.subprocess, "run", fake_run)
    assert sysprobe._run(["netstat", "-ano"]) is sentinel
    assert seen["capture_output"] is True
    if os.name == "nt":
        assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        assert "startupinfo" in seen


# --------------------------------------------------------------------------- #
# 游戏进程
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("names, expected", [
    ({100: "helldivers2.exe"}, True),
    ({100: "Helldivers2.exe"}, True),
    ({100: "chrome.exe", 200: "helldivers2.exe"}, True),
    ({100: "chrome.exe"}, False),
    ({}, False),
])
def test_game_running(names, expected, monkeypatch):
    monkeypatch.setattr(sysprobe, "_process_names", lambda: dict(names))
    assert sysprobe.game_running() is expected


# --------------------------------------------------------------------------- #
# 证书存储（certutil 桩注入）
# --------------------------------------------------------------------------- #
def test_normalize_thumbprint():
    assert sysprobe.normalize_thumbprint("aa:bb:cc:dd") == "AABBCCDD"
    assert sysprobe.normalize_thumbprint(" aa bb ") == "AABB"
    assert sysprobe.normalize_thumbprint("") == ""
    assert sysprobe.normalize_thumbprint(None) == ""


@pytest.mark.parametrize("scope, expected", [
    ("LocalMachine", []),
    ("machine", []),
    ("Local", []),
    ("CurrentUser", ["-user"]),
    ("user", ["-user"]),
    ("CU", ["-user"]),
    ("bogus", None),
])
def test_cert_scope_args(scope, expected):
    assert sysprobe.cert_scope_args(scope) == expected


def test_cert_in_store_localmachine_command(tmp_path, monkeypatch):
    argv_file = _make_stub(tmp_path, monkeypatch, exit_code="0")
    assert sysprobe.cert_in_store("aa:bb:cc", "LocalMachine") is True
    assert json.loads(argv_file.read_text(encoding="utf-8")) == ["-store", "Root", "AABBCC"]


def test_cert_in_store_currentuser_command(tmp_path, monkeypatch):
    argv_file = _make_stub(tmp_path, monkeypatch, exit_code="0")
    assert sysprobe.cert_in_store(THUMB, "CurrentUser") is True
    assert json.loads(argv_file.read_text(encoding="utf-8")) == [
        "-user", "-store", "Root", THUMB]


def test_cert_in_store_not_found(tmp_path, monkeypatch):
    _make_stub(tmp_path, monkeypatch, exit_code="1")
    assert sysprobe.cert_in_store(THUMB) is False


def test_cert_in_store_unknown_scope_returns_false(tmp_path, monkeypatch):
    argv_file = _make_stub(tmp_path, monkeypatch, exit_code="0")
    assert sysprobe.cert_in_store(THUMB, "bogus") is False
    assert not argv_file.exists()                   # 根本没调 certutil


def test_cert_in_store_empty_thumbprint_returns_false():
    assert sysprobe.cert_in_store(":::", "LocalMachine") is False


def test_certutil_argv_default(monkeypatch):
    monkeypatch.delenv("HD2PROXY_CERTUTIL", raising=False)
    assert sysprobe.certutil_argv(["-store", "Root", "AA"]) == [
        "certutil", "-store", "Root", "AA"]


def test_certutil_argv_py_stub_uses_interpreter(tmp_path, monkeypatch):
    stub = tmp_path / "stub.py"
    stub.write_text("", encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_CERTUTIL", str(stub))
    assert sysprobe.certutil_argv(["-store"]) == [sys.executable, str(stub), "-store"]


def test_certutil_argv_exe_override(tmp_path, monkeypatch):
    fake_exe = tmp_path / "certutil.exe"
    fake_exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("HD2PROXY_CERTUTIL", str(fake_exe))
    assert sysprobe.certutil_argv(["-store"]) == [str(fake_exe), "-store"]


def test_cert_trusted_caches_per_thumbprint_and_scope(monkeypatch):
    """信任检查会 spawn certutil（~60–120ms），同一指纹+范围必须走缓存。"""
    calls = []

    def fake_in_store(thumbprint, scope="LocalMachine"):
        calls.append((thumbprint, scope))
        return True

    monkeypatch.setattr(sysprobe, "cert_in_store", fake_in_store)
    sysprobe.clear_caches()
    assert sysprobe.cert_trusted("aa:bb", "LocalMachine") is True
    assert sysprobe.cert_trusted("aabb", "LocalMachine") is True     # 规范化后同一 key
    assert len(calls) == 1, "同一指纹+范围应命中缓存"
    assert sysprobe.cert_trusted("aa:bb", "CurrentUser") is True     # 不同范围另查一次
    assert len(calls) == 2
    sysprobe.clear_caches()
    assert sysprobe.cert_trusted("aa:bb", "LocalMachine") is True
    assert len(calls) == 3, "clear_caches 后应重查"


# --------------------------------------------------------------------------- #
# 输出解码 / 管理员探测
# --------------------------------------------------------------------------- #
def test_decode_output_empty():
    assert sysprobe.decode_output(None) == ""
    assert sysprobe.decode_output(b"") == ""


def test_decode_output_utf8_when_preferred_matches(monkeypatch):
    monkeypatch.setattr(sysprobe.locale, "getpreferredencoding", lambda *a: "utf-8")
    assert sysprobe.decode_output("中文".encode("utf-8")) == "中文"


def test_decode_output_falls_back_to_gbk(monkeypatch):
    monkeypatch.setattr(sysprobe.locale, "getpreferredencoding", lambda *a: "utf-8")
    assert sysprobe.decode_output("中文".encode("gbk")) == "中文"


def test_is_admin_returns_bool():
    assert isinstance(sysprobe.is_admin(), bool)


# --------------------------------------------------------------------------- #
# 端口三态 / 独占试绑 / 进程探针（2026-11-17 P0：端口诊断）
# --------------------------------------------------------------------------- #
NETSTAT_MIXED = """活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:443            0.0.0.0:0              LISTENING       1234
  TCP    127.0.0.1:443          0.0.0.0:0              LISTENING       4321
  TCP    [::]:443               [::]:0                 LISTENING       5678
  TCP    100.67.169.17:443      0.0.0.0:0              LISTENING       1234
"""


def test_parse_netstat_listeners_keeps_every_binding():
    """IPv4/IPv6 两条表都认；同一 PID 的多个地址都保留（判断通配绑定靠它）。"""
    rows = sysprobe._parse_netstat_listeners(NETSTAT_MIXED, 443)
    assert {"pid": 1234, "addr": "0.0.0.0:443", "host": "0.0.0.0"} in rows
    assert {"pid": 1234, "addr": "100.67.169.17:443", "host": "100.67.169.17"} in rows
    assert {"pid": 4321, "addr": "127.0.0.1:443", "host": "127.0.0.1"} in rows
    assert {"pid": 5678, "addr": "[::]:443", "host": "::"} in rows


def test_port_listeners_marks_wildcard_and_path(monkeypatch):
    _patch_probe(monkeypatch, NETSTAT_MIXED)
    monkeypatch.setattr(sysprobe, "_proc_path",
                        lambda pid: "C" + ":" + chr(92) + "x" + chr(92) + "python.exe")
    sysprobe.clear_caches()
    listeners = sysprobe.port_listeners(443)
    assert any(item["wildcard"] for item in listeners)          # 0.0.0.0 / ::
    assert all(item["path"].endswith("python.exe") for item in listeners)
    # port_owner 仍按 PID 去重（GUI 列占用者用），只列一次 1234
    owners = sysprobe.port_owner(443)
    assert [o["pid"] for o in owners] == [1234, 4321, 5678]


def test_bindable_exclusive_probe():
    import socket as _socket

    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        assert sysprobe.bindable("127.0.0.1", port) is False   # 已被占（同进程也算）
    finally:
        probe.close()
    assert sysprobe.bindable("127.0.0.1", port) is True        # 释放后可用


def test_port_state_free_ours_conflict(monkeypatch):
    listeners = [{"pid": 1234, "name": "hd2proxy.exe", "addr": "0.0.0.0:443",
                  "host": "0.0.0.0", "path": "x", "wildcard": True},
                 {"pid": 4321, "name": "nginx.exe", "addr": "0.0.0.0:443",
                  "host": "0.0.0.0", "path": "y", "wildcard": True}]
    monkeypatch.setattr(sysprobe, "port_listeners", lambda port: listeners)
    monkeypatch.setattr(sysprobe, "bindable", lambda ip, port: True)
    state = sysprobe.port_state("100.67.169.17", 443, own_pids=[1234])
    assert state["state"] == "free"
    monkeypatch.setattr(sysprobe, "bindable", lambda ip, port: False)
    assert sysprobe.port_state("100.67.169.17", 443, own_pids=[1234])["state"] == "conflict"
    monkeypatch.setattr(sysprobe, "port_listeners", lambda port: listeners[:1])
    state = sysprobe.port_state("100.67.169.17", 443, own_pids=[1234])
    assert state["state"] == "ours" and state["wildcard"] is True


def test_pid_alive_self_and_bogus():
    assert sysprobe.pid_alive(os.getpid()) is True
    assert sysprobe.pid_alive(99999999) is False
    assert sysprobe.pid_alive(0) is False


def test_primary_ip_returns_string_or_empty():
    value = sysprobe.primary_ip()
    assert isinstance(value, str)
    assert value == "" or sysprobe.validate_listen_ip(value) is None

def test_is_virtual_interface_marks_accelerator_adapters():
    assert sysprobe._is_virtual_interface("Mihomo", "198.18.0.1") is True
    assert sysprobe._is_virtual_interface("UU Wintun Tunnel", "172.19.84.5") is True
    assert sysprobe._is_virtual_interface("UU", "172.19.84.5") is True
    assert sysprobe._is_virtual_interface("以太网", "100.67.169.17") is False
