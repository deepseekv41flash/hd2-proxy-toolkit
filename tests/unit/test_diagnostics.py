"""engine/diagnostics 单测：hosts 判定 / 端口快照结论 / 候选 IP 排序 / 快照采集。

全部离线：`evaluate()` 是纯函数直接喂快照；`collect()` 的探测依赖用 monkeypatch 打桩，
不读本机真实 hosts、不跑 netstat。
"""

import json
import sys
from pathlib import Path

import pytest

from hd2proxy.engine import diagnostics

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- hosts 判定
HOSTS_OK = ("127.0.0.1 localhost\r\n"
            "\r\n"
            "100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy\r\n")
HOSTS_COMMENTED = ("127.0.0.1 localhost\r\n"
                   "#g_acc100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy\r\n")


def test_hosts_diag_states():
    assert diagnostics.hosts_diag("", "100.67.169.17")["state"] == "missing"
    ok = diagnostics.hosts_diag(HOSTS_OK, "100.67.169.17")
    assert ok["state"] == "ok" and ok["ip"] == "100.67.169.17"
    commented = diagnostics.hosts_diag(HOSTS_COMMENTED, "100.67.169.17")
    assert commented["state"] == "commented" and commented["commented"] is True
    wrong = diagnostics.hosts_diag(HOSTS_OK, "192.168.1.5")
    assert wrong["state"] == "wrong-ip" and wrong["expected_ip"] == "192.168.1.5"


# ---------------------------------------------------------------- 快照结论
def _snapshot(**overrides):
    snap = {
        "listen_setting": "auto",
        "listen_ip": "100.67.169.17",
        "listen_error": None,
        "primary_ip": "100.67.169.17",
        "ports": [],
        "engine_running": True,
        "engine_pids": [111],
        "hosts": {"state": "ok", "line": "100.67.169.17 api… # hd2proxy",
                  "ip": "100.67.169.17", "commented": False,
                  "expected_ip": "100.67.169.17"},
        "cert": {"usable": True, "remaining_hours": 40.0, "thumbprint": "AABB", "warnings": []},
        "game_running": False,
        "admin": False,
    }
    snap.update(overrides)
    return snap


def _texts(evaluation):
    return [w["text"] for w in evaluation["warnings"]]


def test_evaluate_clean_snapshot_has_no_error():
    ev = diagnostics.evaluate(_snapshot())
    assert ev["ok"] is True and ev["errors"] == []


def test_evaluate_engine_not_running_but_hosts_pointing_is_error():
    ev = diagnostics.evaluate(_snapshot(engine_running=False, engine_pids=[]))
    assert ev["ok"] is False
    joined = "".join(_texts(ev))
    assert "hosts 已把游戏指向本机" in joined and "引擎没在运行" in joined


def test_evaluate_hosts_commented_mentions_accelerator():
    ev = diagnostics.evaluate(_snapshot(hosts={"state": "commented",
                                               "line": "#g_acc… # hd2proxy",
                                               "ip": "", "commented": True,
                                               "expected_ip": "100.67.169.17"}))
    joined = "".join(_texts(ev))
    assert "被注释" in joined and "加速器" in joined


def test_evaluate_wrong_ip_and_port_conflict():
    ev = diagnostics.evaluate(_snapshot(
        hosts={"state": "wrong-ip", "line": "1.2.3.4 api… # hd2proxy",
               "ip": "1.2.3.4", "commented": False, "expected_ip": "100.67.169.17"},
        ports=[{"role": "代理", "ip": "100.67.169.17", "port": 443, "state": "conflict",
                "wildcard": True,
                "owners": [{"pid": 9, "name": "old.exe", "addr": "0.0.0.0:443",
                            "path": "C" + ":" + chr(92) + "old" + chr(92) + "old.exe",
                            "wildcard": True}]}]))
    joined = "".join(_texts(ev))
    assert "hosts 指向 1.2.3.4" in joined
    assert "0.0.0.0" in joined and "换监听 IP 无效" in joined and "old.exe" in joined


def test_evaluate_free_port_while_engine_claims_running_warns():
    ev = diagnostics.evaluate(_snapshot(ports=[{
        "role": "代理", "ip": "100.67.169.17", "port": 443, "state": "free",
        "wildcard": False, "owners": []}]))
    joined = "".join(_texts(ev))
    assert "空闲" in joined and "显示在运行" in joined
    assert ev["ok"] is True                      # 只是 warn，不阻塞


def test_evaluate_cert_expiring_and_game_running_notes():
    ev = diagnostics.evaluate(_snapshot(
        cert={"usable": True, "remaining_hours": 3.5, "thumbprint": "AABB", "warnings": []},
        game_running=True))
    joined = "".join(_texts(ev))
    assert "只剩 3.5 小时" in joined and "游戏正在运行" in joined


def test_format_text_has_sections():
    snap = _snapshot(ports=[{"role": "代理", "ip": "100.67.169.17", "port": 443,
                             "state": "ours", "wildcard": False,
                             "owners": [{"pid": 111, "name": "hd2proxy.exe",
                                         "addr": "100.67.169.17:443",
                                         "path": "", "wildcard": False}]}])
    text = diagnostics.format_text(snap)
    for section in ("系统诊断", "-- 端口 --", "-- hosts --", "-- 证书 --", "-- 结论 --"):
        assert section in text
    assert "本工具占用（正常）" in text


# ---------------------------------------------------------------- 采集 / 候选
def test_own_engine_pids_reads_state_and_checks_alive(tmp_path, monkeypatch):
    state = tmp_path / "engine.json"
    state.write_text(json.dumps({"pid": 4321, "control_pid": 8765}), encoding="utf-8")
    monkeypatch.setattr(diagnostics.sysprobe, "pid_alive", lambda pid: pid == 4321)
    assert diagnostics.own_engine_pids(state) == {4321}
    state.write_text("not json", encoding="utf-8")
    assert diagnostics.own_engine_pids(state) == set()


def test_collect_degrades_when_listen_ip_invalid(monkeypatch):
    monkeypatch.setattr(diagnostics.sysprobe, "resolve_listen_ip",
                        lambda value: (_ for _ in ()).throw(ValueError("不能用回环地址")))
    snap = diagnostics.collect({"proxy": {"listen_ip": "127.0.0.1"}}, cert_dir=REPO / "nope")
    assert snap["listen_error"] and "回环" in snap["listen_error"]
    assert snap["ports"] == []


def test_listen_candidates_sorted_and_recommended(monkeypatch):
    monkeypatch.setattr(diagnostics.sysprobe, "primary_ip", lambda: "192.168.1.7")
    monkeypatch.setattr(diagnostics.sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "192.168.1.7", "interface": "以太网", "is_virtual": False},
        {"ip": "172.26.64.1", "interface": "vEthernet (Default Switch)", "is_virtual": True},
    ])
    monkeypatch.setattr(diagnostics.sysprobe, "port_state",
                        lambda ip, port, own: {"state": "free", "wildcard": False, "owners": []})
    rows = diagnostics.listen_candidates({"proxy": {"port": 443}}, own_pids=())
    assert [row["ip"] for row in rows] == ["192.168.1.7", "172.26.64.1"]
    assert rows[0]["recommended"] is True and rows[1]["is_virtual"] is True


def test_port_preflight_reports_conflicts(monkeypatch):
    monkeypatch.setattr(diagnostics.sysprobe, "resolve_listen_ip", lambda value: "10.0.0.2")
    monkeypatch.setattr(diagnostics.sysprobe, "port_state", lambda ip, port, own: {
        "ip": ip, "port": port,
        "state": "conflict" if port == 443 else "free",
        "wildcard": port == 443, "owners": [{"pid": 1, "name": "x", "addr": "0.0.0.0:443"}]})
    pre = diagnostics.port_preflight({"proxy": {}}, own_pids=())
    assert [entry["port"] for entry in pre["conflicts"]] == [443]
    assert pre["wildcard"] is True
    assert [entry["role"] for entry in pre["ports"]] == ["代理", "CRL", "控制面"]
