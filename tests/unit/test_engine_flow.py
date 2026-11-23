"""M1 门禁：引擎整链路（profile → 起引擎 → 控制面 → 热重载 → 验收 → 退出）。

这组测试对应 M1 的验收口径：
  `install --dry-run → engine(profile) → verify 三连 → 热改配置 → status → shutdown`
真实安装（改 hosts / 导入证书）需要 UAC，本机自动化测试只做 dry-run + 状态回读；
真安装留 M4 实机验收（见 PLAN.md）。

全部离线：假上游 + 临时证书 + 临时状态目录，不碰真实 hosts / 证书存储 / 系统代理。
"""

import gzip
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hd2proxy.engine import certs, config, paths, saves

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "src" / "hd2proxy" / "engine" / "legacy_proxy.py"
HOST = certs.DEFAULT_HOST

MISSION_END_DOC = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "fixtures" / "saves"
     / "mission_end" / "12b9a872.json").read_text(encoding="utf-8"))

STATUS_DOC = {
    "warId": 801,
    "time": 1700000000,
    "planetStatus": [{"index": 100, "owner": 2}, {"index": 200, "owner": 3}],
    "planetActiveEffects": [{"index": 100, "galacticEffectId": 1195}],
    "campaigns": [], "planetAttacks": [], "planetEvents": [],
    "jointOperations": [], "globalEvents": [], "planetRegions": [],
}


# ---------------------------------------------------------------- 工具


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Upstream:
    """假上游：Status 返回 gzip JSON，其它返回 {"id":801}。"""

    def __init__(self, port):
        self.port = port
        doc = STATUS_DOC

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if "/api/WarSeason/801/Status" in self.path:
                    body = gzip.compress(json.dumps(doc).encode())
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Encoding", "gzip")
                else:
                    body = json.dumps({"id": 801}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if "/api/Operation/Mission/end" in self.path:
                    # G3：结算响应 = 本局奖励增量（经验/物品/包进度）
                    body = json.dumps(MISSION_END_DOC).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = b'{"ok":true}'
                self.send_response(202)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def tls_get(port, path, cert_dir, timeout=20.0):
    ctx = ssl.create_default_context(cafile=str(Path(cert_dir) / "anchor.pem"))
    raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    tls = ctx.wrap_socket(raw, server_hostname=HOST)
    try:
        tls.sendall(("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
                     % (path, HOST)).encode())
        buf = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        tls.close()
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1", "replace"), body


def tls_post(port, path, payload, cert_dir, timeout=20.0):
    """走代理发一个 JSON POST（假上游按路径脚本化响应）。"""
    ctx = ssl.create_default_context(cafile=str(Path(cert_dir) / "anchor.pem"))
    raw = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    tls = ctx.wrap_socket(raw, server_hostname=HOST)
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    try:
        tls.sendall(("POST %s HTTP/1.1\r\nHost: %s\r\nContent-Type: application/json\r\n"
                     "Content-Length: %d\r\nConnection: close\r\n\r\n"
                     % (path, HOST, len(data))).encode() + data)
        buf = b""
        while True:
            chunk = tls.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        tls.close()
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.decode("latin-1", "replace"), body


def status_ids(port, cert_dir):
    head, body = tls_get(port, "/api/WarSeason/801/Status", cert_dir)
    assert " 200 " in (" " + (head.splitlines()[0] if head else "") + " "), head[:80]
    plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    doc = json.loads(plain.decode("utf-8"))
    return {e["galacticEffectId"] for e in doc.get("planetActiveEffects") or []}


def api(state_file, path, method="GET", body=None, timeout=60):
    state = json.loads(Path(state_file).read_text(encoding="utf-8"))
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"X-HD2-Token": state["token"]}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(state["url"] + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_engine(state_file, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if Path(state_file).exists():
            try:
                api(state_file, "/healthz", timeout=2)
                return json.loads(Path(state_file).read_text(encoding="utf-8"))
            except Exception:
                pass
        time.sleep(0.2)
    raise AssertionError("引擎在 %.1fs 内没起来（engine.json=%s）" % (timeout, state_file))


def _write_hosts(path: Path):
    path.write_bytes(b"127.0.0.1 localhost\r\n\r\n# pre-existing comment\r\n")


def _certutil_stub(dir_: Path) -> Path:
    """有状态桩：模拟 Root 存储里有/没有证书；-store 返回 1 表示未信任。"""
    p = dir_ / "certutil_stub.py"
    p.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "if '-addstore' in args or '-delstore' in args:\n"
        "    print('stub: ok'); sys.exit(0)\n"
        "if '-store' in args:\n"
        "    print('stub: not found'); sys.exit(1)\n"
        "sys.exit(0)\n",
        encoding="utf-8")
    return p


def engine_env(tmp_path):
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "HD2PROXY_STATE": str(tmp_path / "state"),
        "HD2PROXY_HOSTS_PATH": str(tmp_path / "hosts"),
        "HD2PROXY_CERTUTIL": str(tmp_path / "certutil_stub.py"),
        "VMOD_DATA": str(tmp_path / "run"),
    })
    return env


def _make_profile(tmp_path, *, port, crl_port, control_port, content=True, passthrough=False):
    prof = config.default_profile(name="flow")
    prof["proxy"].update({"listen_ip": "auto", "port": port, "crl_port": crl_port,
                          "control_port": control_port, "passthrough": passthrough,
                          "verbose": False})
    prof["cert"].update({"days": 1, "min_remaining_hours": 12, "auto_renew": False})
    if content:
        prof["status"]["planet_effects"] = [{"index": 100, "ids": [1243, 1245]}]
    path = tmp_path / "profile.json"
    config.save_profile_file(path, prof)
    return path


def start_engine(tmp_path, profile_path, cert_dir, port, control_port, extra_args=()):
    env = engine_env(tmp_path)
    cmd = [sys.executable, str(ENGINE), "--profile", str(profile_path),
           "--cert-dir", str(cert_dir), "--listen-ip", "127.0.0.1", "--allow-loopback",
           "--control-port", str(control_port), "--no-auto-renew", *extra_args]
    return subprocess.Popen(cmd, cwd=str(REPO), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 主流程


def test_engine_profile_control_flow(tmp_path):
    """M1 核心链路：起引擎 → /status → /verify → 热改配置 → 直通切换 → /shutdown。"""
    state_file = tmp_path / "state" / "engine.json"
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True)
    _write_hosts(tmp_path / "hosts")
    _certutil_stub(tmp_path)

    up_port, port, crl_port, ctl_port = (free_port() for _ in range(4))
    profile_path = _make_profile(tmp_path, port=port, crl_port=crl_port,
                                 control_port=ctl_port)

    with _Upstream(up_port):
        # 把上游指到假服务器（profile 里没有 upstreamTest 字段 → 用环境变量不行，
        # 走 legacy --config 的 upstreamTest 覆盖：这里改用 cfg 文件注入）
        cfg = {"host": HOST, "upstreamTest": "127.0.0.1:%d" % up_port}
        cfg_path = tmp_path / "legacy_cfg.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        proc = start_engine(tmp_path, profile_path, cert_dir, port, ctl_port,
                            extra_args=("--config", str(cfg_path)))
        try:
            state = wait_engine(state_file)
            assert state["port"] == ctl_port

            # 1) /status：模式、profile、监听、证书
            st = api(state_file, "/status")
            assert st["mode"] == "rewrite"
            assert st["profile"] == "flow"
            assert st["listen_ip"] == "127.0.0.1" and st["port"] == port
            assert st["cert"]["usable"] is True

            # 2) /verify 三连
            v = api(state_file, "/verify", method="POST", body={})
            assert v["ok"] is True, json.dumps(v, ensure_ascii=False)
            assert len(v["checks"]) == 3

            # 3) 改写真的送达：planet 100 有 1243/1245
            ids = status_ids(port, cert_dir)
            assert {1243, 1245} <= ids and 1195 in ids

            # 4) 热改配置（不重启）：给 planet 200 加一组词条
            cfg_now = api(state_file, "/config")["profile"]
            cfg_now["status"]["planet_effects"].append({"index": 200, "ids": [1306, 1309]})
            r = api(state_file, "/config", method="PUT", body=cfg_now)
            assert r["ok"] is True and r["applied"]["hot"] is True
            ids2 = status_ids(port, cert_dir)
            assert {1306, 1309} <= ids2

            # 5) 直通切换：不再改写
            api(state_file, "/passthrough", method="POST", body={"enabled": True})
            assert api(state_file, "/status")["mode"] == "passthrough"
            ids3 = status_ids(port, cert_dir)
            assert 1243 not in ids3 and 1306 not in ids3
            api(state_file, "/passthrough", method="POST", body={"enabled": False})
            assert {1243, 1245} <= status_ids(port, cert_dir)

            # 6) 未授权请求被拒
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    urllib.request.Request(json.loads(state_file.read_text(encoding="utf-8"))["url"]
                                           + "/status"), timeout=5)
                raise AssertionError("无 token 竟然通过了")
            except urllib.error.HTTPError as e:
                assert e.code == 401

            # 7) 优雅退出
            api(state_file, "/shutdown", method="POST", body={})
            assert proc.wait(15) == 0
            assert not state_file.exists(), "退出后应清理 engine.json"
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def test_engine_save_layer_rewrites_progression(tmp_path):
    """G2 端到端：存档 earned 合并进 `/api/Progression` + 会话基准/pending + /status 暴露。"""
    state_file = tmp_path / "state" / "engine.json"
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True)
    _write_hosts(tmp_path / "hosts")
    _certutil_stub(tmp_path)

    # 预置「上次玩过的玩家」存档 + _last 指针（引擎启动会乐观预绑定它）
    saves_root = tmp_path / "run" / "runtime" / "saves"
    steam_id = "76561198968648344"
    sid = saves.save_id_for(steam_id)
    st = saves.SaveStore(sid, root=saves_root)
    doc = saves.empty_save(sid)
    doc["earned"]["experience"] = 2759938
    doc["earned"]["inventory_amounts"] = {"3901895556": 699}
    st.save(doc)
    saves.write_last(sid, steam_id, None, root=saves_root)

    up_port, port, crl_port, ctl_port = (free_port() for _ in range(4))
    profile_path = _make_profile(tmp_path, port=port, crl_port=crl_port,
                                 control_port=ctl_port)
    cfg_path = tmp_path / "legacy_cfg.json"
    cfg_path.write_text(json.dumps({"host": HOST,
                                    "upstreamTest": "127.0.0.1:%d" % up_port}),
                        encoding="utf-8")
    with _Upstream(up_port):
        proc = start_engine(tmp_path, profile_path, cert_dir, port, ctl_port,
                            extra_args=("--config", str(cfg_path)))
        try:
            wait_engine(state_file)

            # 1) 上游只给 {"id":801}，改写后首屏 experience 应该是存档里的值
            head, body = tls_get(port, "/api/Progression", cert_dir)
            assert " 200 " in (" " + (head.splitlines()[0] if head else "") + " "), head[:80]
            plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
            prog = json.loads(plain.decode("utf-8"))
            assert prog["experience"] == 2759938
            assert prog["id"] == 801                     # 其余字段原样保留

            # 2) /status 暴露存档状态（GUI 排查用）
            save_state = api(state_file, "/status")["save"]
            assert save_state["save_id"] == sid and save_state["origin"] == "last"
            assert save_state["verified"] is False      # 本局还没等到 GetMotd
            assert save_state["catalog_build"] is None

            # 3) 会话基准快照 + pending（身份未校验时保留，供下次启动回滚）
            assert saves.read_session_snapshot(sid, root=saves_root)["doc"]["earned"]["experience"] == 2759938
            assert saves.read_pending(root=saves_root)["save_id"] == sid

            # 4) G3：结算响应 → 奖励入账（真实客户端结算后不重取 Progression，
            #    这里手动再拉一次，验证"下次启动"能看到累加后的值）
            head, body = tls_post(port, "/api/Operation/Mission/end", b"{}", cert_dir)
            assert " 200 " in (" " + (head.splitlines()[0] if head else "") + " "), head[:80]
            after = saves.SaveStore(sid, root=saves_root).load()
            assert after["earned"]["experience"] == 2759938 + 936
            assert after["earned"]["inventory_amounts"]["3608481516"] == 4434
            assert after["earned"]["missions"]["count"] == 1

            head, body = tls_get(port, "/api/Progression", cert_dir)
            plain = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
            assert json.loads(plain.decode("utf-8"))["experience"] == 2759938 + 936
            save_state = api(state_file, "/status")["save"]
            assert save_state["session_dirty"] is True
            assert any(e["kind"] == "mission" for e in save_state["events"])

            api(state_file, "/shutdown", method="POST", body={})
            assert proc.wait(15) == 0
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def test_engine_legacy_mode_rejects_profile_put(tmp_path):
    """legacy 模式（无 profile）下，控制面拒绝热改配置并给出说明。"""
    state_file = tmp_path / "state" / "engine.json"
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True)
    _write_hosts(tmp_path / "hosts")
    _certutil_stub(tmp_path)
    up_port, port, crl_port, ctl_port = (free_port() for _ in range(4))
    cfg_path = tmp_path / "legacy_cfg.json"
    cfg_path.write_text(json.dumps({
        "host": HOST, "listenIp": "127.0.0.1", "allowLoopback": True, "port": port,
        "crlPort": crl_port, "upstreamTest": "127.0.0.1:%d" % up_port,
        "passthrough": True, "targets": [],
    }), encoding="utf-8")
    env = engine_env(tmp_path)
    cmd = [sys.executable, str(ENGINE), "--config", str(cfg_path),
           "--cert-dir", str(cert_dir), "--control-port", str(ctl_port), "--no-auto-renew"]
    with _Upstream(up_port):
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        try:
            wait_engine(state_file)
            st = api(state_file, "/status")
            assert st["mode"] == "passthrough"
            conf = api(state_file, "/config")
            assert conf["mode"] == "legacy"
            try:
                api(state_file, "/config", method="PUT", body=config.default_profile())
                raise AssertionError("legacy 模式不应接受 PUT /config")
            except urllib.error.HTTPError as e:
                assert e.code == 409
            api(state_file, "/shutdown", method="POST", body={})
            assert proc.wait(15) == 0
        finally:
            if proc.poll() is None:
                proc.terminate()


# ---------------------------------------------------------------- 安装 dry-run


def test_install_dry_run_plan_changes_nothing(tmp_path):
    """install --dry-run：打印计划、不改 hosts、不碰证书存储。"""
    cert_dir = tmp_path / "certs"
    certs.generate_session(cert_dir, host=HOST, days=1, force=True)
    hosts = tmp_path / "hosts"
    _write_hosts(hosts)
    _certutil_stub(tmp_path)
    before = hosts.read_bytes()
    env = engine_env(tmp_path)
    env["PYTHONPATH"] = str(REPO / "src")
    r = subprocess.run(
        [sys.executable, "-m", "hd2proxy", "install", "--dry-run",
         "--host", HOST, "--listen-ip", "192.168.1.50", "--cert-dir", str(cert_dir)],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    assert "安装计划" in out
    assert "hosts 判定" in out
    assert hosts.read_bytes() == before, "dry-run 不允许改 hosts"
    assert "当前系统状态" in out
    # 证书不应被导入存储（桩 certutil 未收到 addstore）：桩本身无状态，这里验证计划里标注未信任
    assert "未信任" in out or "需要导入" in out


def test_cli_reports_and_status_without_engine(tmp_path):
    env = engine_env(tmp_path)
    env["PYTHONPATH"] = str(REPO / "src")
    r = subprocess.run([sys.executable, "-m", "hd2proxy", "info"], cwd=str(REPO), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["engine_running"] is False

    r = subprocess.run([sys.executable, "-m", "hd2proxy", "status"], cwd=str(REPO), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 2
    assert "没有发现运行中的引擎" in (r.stdout + r.stderr)
