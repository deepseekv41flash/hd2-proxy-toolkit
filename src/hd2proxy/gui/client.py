"""引擎客户端：GUI / 脚本统一通过“控制面 HTTP + 本地进程管理”操作引擎。

原则（与 ARCHITECTURE §4 一致）：
  * 引擎是独立进程；GUI 只做控制面客户端，崩溃不打断游戏会话；
  * 所有本机 HTTP 请求**显式绕过系统代理**（Windows 注册表代理会劫持 127.0.0.1）；
  * 引擎进程由 GUI 以子进程方式拉起，stdout 收集到环形缓冲供“日志”页展示。
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from ..engine import paths

SRC = Path(__file__).resolve().parents[2]        # src/
REPO = SRC.parent
ENGINE_SCRIPT = SRC / "hd2proxy" / "engine" / "legacy_proxy.py"


class EngineError(RuntimeError):
    pass


class EngineClient:
    def __init__(self, state_file=None):
        self.state_file = Path(state_file) if state_file else paths.engine_state_file()
        self.proc = None
        self.log_lines = deque(maxlen=400)
        self._log_thread = None
        self._log_lock = threading.Lock()

    # ---- 发现 / HTTP ---------------------------------------------------
    def state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _opener(self):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(self, path, method="GET", body=None, timeout=60):
        st = self.state()
        if not st:
            raise EngineError("引擎未运行（找不到 %s）" % self.state_file)
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"X-HD2-Token": st.get("token") or ""}
        if data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(st["url"] + path, data=data, headers=headers,
                                     method=method)
        try:
            with self._opener().open(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8"))
            except Exception:
                detail = {}
            raise EngineError("HTTP %d: %s" % (e.code, detail or e.reason))
        except urllib.error.URLError as e:
            raise EngineError("连不上引擎：%r" % (e.reason,))

    def health(self, timeout=1.5):
        try:
            return bool(self.api("/healthz", timeout=timeout).get("ok"))
        except Exception:
            return False

    def running(self):
        return self.state() is not None and self.health()

    # ---- 业务接口 ------------------------------------------------------
    def status(self):
        return self.api("/status")

    def config(self):
        return self.api("/config")

    def put_config(self, profile):
        return self.api("/config", method="PUT", body=profile)

    def verify(self):
        return self.api("/verify", method="POST", body={}, timeout=120)

    def set_passthrough(self, enabled):
        return self.api("/passthrough", method="POST", body={"enabled": bool(enabled)})

    def set_capture(self, enabled, directory=None):
        body = {"enabled": bool(enabled)}
        if directory:
            body["dir"] = str(directory)
        return self.api("/capture", method="POST", body=body)

    def shutdown(self, wait=8.0):
        try:
            self.api("/shutdown", method="POST", body={})
        except Exception:
            pass
        if self.proc is not None:
            try:
                self.proc.wait(timeout=wait)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        return True

    # ---- 进程管理 ------------------------------------------------------
    def engine_argv(self, profile_path, cert_dir, listen_ip=None, control_port=None,
                    extra=()):
        argv = [sys.executable, str(ENGINE_SCRIPT),
                "--profile", str(profile_path), "--cert-dir", str(cert_dir)]
        if listen_ip:
            argv += ["--listen-ip", str(listen_ip)]
        if control_port is not None:
            argv += ["--control-port", str(int(control_port))]
        argv += list(extra)
        return argv

    def start_engine(self, profile_path, cert_dir, listen_ip=None, control_port=None,
                     allow_loopback=False, extra=()):
        """起引擎子进程；stdout/stderr 收进 log_lines。返回 Popen。"""
        if self.proc is not None and self.proc.poll() is None:
            raise EngineError("引擎已有子进程在跑")
        argv = self.engine_argv(profile_path, cert_dir, listen_ip, control_port, extra)
        if allow_loopback:
            argv.append("--allow-loopback")
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        self.proc = subprocess.Popen(
            argv, cwd=str(REPO), env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._log_thread = threading.Thread(target=self._pump_log, daemon=True)
        self._log_thread.start()
        return self.proc

    def _pump_log(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            with self._log_lock:
                self.log_lines.append(line.rstrip("\n"))

    def wait_ready(self, timeout=25.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.running():
                return True
            time.sleep(0.3)
        return False

    def engine_alive(self):
        return self.proc is not None and self.proc.poll() is None

    # ---- CLI 桥（安装/证书等一次性动作） --------------------------------
    def run_cli(self, args, timeout=180):
        """跑 `python -m hd2proxy <args>`；返回 (code, output)。输出用于 GUI 展示。"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            r = subprocess.run([sys.executable, "-m", "hd2proxy", *args],
                               cwd=str(REPO), env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, "命令超时（%ss）：%s" % (timeout, " ".join(args))
        except Exception as e:      # noqa: BLE001
            return 1, "执行失败：%r" % (e,)
