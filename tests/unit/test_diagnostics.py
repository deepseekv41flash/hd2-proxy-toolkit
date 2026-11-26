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
    assert commented["comment_prefix"] == "#g_acc"
    uu = diagnostics.hosts_diag(
        "#uu_acc100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy",
        "100.67.169.17")
    assert uu["state"] == "commented" and uu["comment_prefix"] == "#uu_acc"
    wrong = diagnostics.hosts_diag(HOSTS_OK, "192.168.1.5")
    assert wrong["state"] == "wrong-ip" and wrong["expected_ip"] == "192.168.1.5"


def test_hosts_startup_advice():
    assert diagnostics.hosts_startup_advice(HOSTS_OK, "100.67.169.17") == []
    missing = diagnostics.hosts_startup_advice("", "100.67.169.17")
    assert missing and "没有本工具那一行" in missing[0]
    commented = diagnostics.hosts_startup_advice(HOSTS_COMMENTED, "100.67.169.17")
    assert commented and "#g_acc" in commented[0] and "重启引擎" in commented[0]
    wrong = diagnostics.hosts_startup_advice(HOSTS_OK, "192.168.1.5")
    assert wrong and "192.168.1.5" in wrong[0]


def test_evaluate_commented_hosts_mentions_accelerator_prefix():
    snap = _snapshot()
    snap["hosts"] = diagnostics.hosts_diag(HOSTS_COMMENTED, "100.67.169.17")
    ev = diagnostics.evaluate(snap)
    errors = " ".join(w["text"] for w in ev["errors"])
    assert "#g_acc" in errors and "重启引擎" in errors


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


def test_evaluate_untrusted_cert_is_blocking_error():
    """证书能签但 CA 不在根存储：游戏握手必被拒，必须报 error（不是 warn）。"""
    ev = diagnostics.evaluate(_snapshot(
        cert={"usable": True, "remaining_hours": 40.0, "thumbprint": "AABB",
              "trust_thumbprint": "CD4F0C7D1B7074CCD45B6529E87BADBC51FD136D",
              "trusted": False, "warnings": []}))
    joined = "".join(_texts(ev))
    assert "未受信任" in joined and "CD4F0C7D1B70" in joined
    assert ev["ok"] is False
    assert any(w["level"] == "error" and "未受信任" in w["text"] for w in ev["errors"])


def test_evaluate_trusted_cert_no_trust_error():
    ev = diagnostics.evaluate(_snapshot(
        cert={"usable": True, "remaining_hours": 40.0, "thumbprint": "AABB",
              "trusted": True, "warnings": []}))
    assert not any("未受信任" in t for t in _texts(ev))


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


def test_collect_prefers_running_engine_actual_crl_port(tmp_path, monkeypatch):
    """引擎因保留端口段换了 CRL 端口时，诊断页要以 engine.json 的实际端口为准。

    profile 里仍是旧值 8080；引擎自报 18080 —— 拿 8080 去查只会显示「空闲/冲突」，
    把人往「端口被占」的错方向引（2026-11-27 用户报障的同一处矛盾）。
    """
    state = tmp_path / "engine.json"
    state.write_text(json.dumps({"pid": 4321, "crl_port": 18080}), encoding="utf-8")
    monkeypatch.setattr(diagnostics.sysprobe, "resolve_listen_ip", lambda value: "10.0.0.2")
    seen = []

    def _port_state(ip, port, own):
        seen.append(port)
        return {"ip": ip, "port": port, "state": "ours", "wildcard": False, "owners": []}

    monkeypatch.setattr(diagnostics.sysprobe, "port_state", _port_state)
    snap = diagnostics.collect({"proxy": {"port": 443, "crl_port": 8080}},
                              cert_dir=tmp_path / "nope", state_file=state,
                              own_pids={4321})
    assert 8080 not in seen, "引擎在跑时不能拿 profile 的旧 CRL 端口去查"
    assert 18080 in seen
    crl_rows = [row for row in snap["ports"] if row["role"] == "CRL"]
    assert [row["port"] for row in crl_rows] == [18080]


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


def test_listen_candidates_never_recommend_virtual_nic(monkeypatch):
    """主网卡被占用时宁可不推荐，也不能推荐虚拟网卡（Hyper-V/VMware）—— 游戏连它不可靠。"""
    monkeypatch.setattr(diagnostics.sysprobe, "primary_ip", lambda: "192.168.1.7")
    monkeypatch.setattr(diagnostics.sysprobe, "local_ipv4_addresses", lambda: [
        {"ip": "192.168.1.7", "interface": "以太网", "is_virtual": False},
        {"ip": "172.26.64.1", "interface": "vEthernet (Default Switch)", "is_virtual": True},
    ])

    def fake_state(ip, port, own):
        if ip == "192.168.1.7":
            return {"state": "conflict", "wildcard": True, "owners": []}
        return {"state": "free", "wildcard": False, "owners": []}

    monkeypatch.setattr(diagnostics.sysprobe, "port_state", fake_state)
    rows = diagnostics.listen_candidates({"proxy": {"port": 443}}, own_pids=())
    assert rows[0]["ip"] == "192.168.1.7" and rows[0]["state"] == "conflict"
    assert all(not row["recommended"] for row in rows)


def test_port_preflight_checks_crl_control_on_loopback(monkeypatch):
    """CRL(8080)/控制面(17897) 绑的是 127.0.0.1 —— 用监听 IP 查会永远显示空闲（误报）。"""
    monkeypatch.setattr(diagnostics.sysprobe, "resolve_listen_ip", lambda value: "10.0.0.2")
    seen = []

    def fake_state(ip, port, own):
        seen.append((ip, port))
        return {"ip": ip, "port": port, "state": "free", "wildcard": False, "owners": []}

    monkeypatch.setattr(diagnostics.sysprobe, "port_state", fake_state)
    diagnostics.port_preflight({"proxy": {}}, own_pids=())
    assert ("10.0.0.2", 443) in seen
    assert ("127.0.0.1", 8080) in seen and ("127.0.0.1", 17897) in seen
