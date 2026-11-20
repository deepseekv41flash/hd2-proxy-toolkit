"""控制面状态文件 / 端口独占回归（2026-11-20 现场缺陷）。

背景：另一个引擎实例在 Windows 上「抢占」了 17897（``SO_REUSEADDR`` 默认允许），
覆盖 ``engine.json`` 后运行中引擎的随机 token 丢失 → GUI/CLI 全部 401、
GUI 误显示「引擎未运行」，而真正服务游戏的引擎还在跑。这里锁两条：
  1. 控制面端口独占：第二个实例必须起不来；
  2. 覆盖状态文件前，若旧文件指向另一个**活着**的引擎，先备份成 ``engine.json.bak``。
"""

import json
import os

import pytest

from hd2proxy.engine import control, paths, sysprobe


def test_control_server_refuses_second_instance_on_same_port():
    first = control.ControlServer(None, port=0)
    try:
        with pytest.raises(OSError):
            control.ControlServer(None, port=first.port)
    finally:
        first.httpd.server_close()


def test_write_state_backs_up_state_owned_by_other_live_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    monkeypatch.setenv("VMOD_DATA", str(tmp_path / "runtime"))
    state = paths.engine_state_file()
    state.write_text(json.dumps({"pid": 4242, "token": "old",
                                "url": "http://127.0.0.1:1"}), encoding="utf-8")
    monkeypatch.setattr(sysprobe, "pid_alive", lambda pid: True)
    srv = control.ControlServer(None, port=0)
    try:
        srv.write_state()
        doc = json.loads(state.read_text(encoding="utf-8"))
        assert doc["pid"] == os.getpid()
        backup = state.with_suffix(".json.bak")
        assert backup.exists()
        assert json.loads(backup.read_text(encoding="utf-8"))["pid"] == 4242
    finally:
        srv.httpd.server_close()


def test_write_state_skips_backup_when_old_engine_is_dead(tmp_path, monkeypatch):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    monkeypatch.setenv("VMOD_DATA", str(tmp_path / "runtime"))
    state = paths.engine_state_file()
    state.write_text(json.dumps({"pid": 4242, "token": "old",
                                "url": "http://127.0.0.1:1"}), encoding="utf-8")
    monkeypatch.setattr(sysprobe, "pid_alive", lambda pid: False)
    srv = control.ControlServer(None, port=0)
    try:
        srv.write_state()
        assert json.loads(state.read_text(encoding="utf-8"))["pid"] == os.getpid()
        assert not state.with_suffix(".json.bak").exists()
    finally:
        srv.httpd.server_close()
