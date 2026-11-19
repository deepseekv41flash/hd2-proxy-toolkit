"""CLI 参数转发单测（M4 现场问题回归）。

`hd2proxy engine/selftest/gate` 要把后续参数原样交给子进程；argparse 的 REMAINDER 遇到
以 `--` 开头的参数会在本轮就报 unknown option（`hd2proxy engine --profile X` 直接 usage error），
所以 main() 对这三个命令走「先识别命令、再整体转发」的短路径。
"""

import pytest

from hd2proxy import __main__ as cli


@pytest.fixture()
def captured(monkeypatch):
    calls = {}

    def fake(name):
        def _run(a):
            calls[name] = list(getattr(a, "rest", []) or [])
            return 0
        return _run

    for name, func_name in (("engine", "cmd_engine"), ("selftest", "cmd_selftest"),
                            ("gate", "cmd_gate")):
        monkeypatch.setattr(cli, func_name, fake(name))
    return calls


@pytest.mark.parametrize("cmd,rest", [
    ("engine", ["--profile", "m4-b.json", "--cert-dir", "certs", "--port", "443"]),
    ("selftest", ["--only", "sticky"]),
    ("gate", ["--no-tests"]),
    ("engine", ["--help"]),
])
def test_forwarding_commands_pass_through_all_args(captured, cmd, rest):
    assert cli.main([cmd] + rest) == 0
    assert captured[cmd] == rest


def test_no_args_opens_gui(monkeypatch):
    """双击 exe（无参数）应打开 GUI；alpha.1 的行为是打印帮助后 exit 2。"""
    calls = []
    monkeypatch.setattr(cli, "cmd_gui", lambda a: calls.append(a.profile) or 0)
    assert cli.main([]) == 0
    assert calls == [""]

# ---------------------------------------------------------------- install 上下文

def test_install_context_falls_back_to_default_profile(tmp_path, monkeypatch):
    """不传 --profile 时也要读默认 profile 的 listen_ip（否则 TUN/加速器下 auto 会选虚拟网卡）。"""
    import argparse
    import json

    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    doc = {
        "name": "默认",
        "proxy": {"host": "api.live.prod.thehelldiversgame.com", "listen_ip": "192.168.1.77"},
        "cert": {"days": 2},
    }
    (profiles / "default.json").write_text(json.dumps(doc), encoding="utf-8")
    a = argparse.Namespace(profile="", listen_ip="", host="",
                           cert_dir=str(tmp_path / "certs"), scope="")
    ctx = cli._install_context(a)
    assert ctx["listen_ip"] == "192.168.1.77"
    assert ctx["host"] == "api.live.prod.thehelldiversgame.com"


def test_install_context_explicit_listen_ip_wins(tmp_path, monkeypatch):
    import argparse
    import json

    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    doc = {"name": "默认", "proxy": {"host": "h", "listen_ip": "192.168.1.77"},
           "cert": {"days": 2}}
    (profiles / "default.json").write_text(json.dumps(doc), encoding="utf-8")
    a = argparse.Namespace(profile="", listen_ip="10.9.8.7", host="",
                           cert_dir=str(tmp_path / "certs"), scope="")
    assert cli._install_context(a)["listen_ip"] == "10.9.8.7"
