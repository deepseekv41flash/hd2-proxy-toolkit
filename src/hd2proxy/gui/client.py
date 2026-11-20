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

from ..engine import paths, sysprobe

SRC = Path(__file__).resolve().parents[2]        # src/
REPO = SRC.parent
ENGINE_SCRIPT = SRC / "hd2proxy" / "engine" / "legacy_proxy.py"


def _bundle_cli_exe():
    """打包模式返回同目录的 CLI exe（hd2proxy.exe）；源码模式返回 None。

    为什么必须这么做：冻结后 sys.executable 是「gui exe」，它本身没有 `engine` /
    `certs renew` 这类子命令入口语义 —— 直接把它当解释器拼 `[exe, legacy_proxy.py, …]`
    会变成「GUI exe + 一个非法参数」，windowed 版会弹 PyInstaller 错误对话框（用户看到的
    "第二个 GUI 窗口"），且证书/安装类按钮全部失效。
    """
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable)
    sibling = exe.with_name("hd2proxy.exe")
    return sibling if sibling.exists() else exe


def cli_argv(args):
    """拼「跑 CLI 子命令」的 argv：冻结走同目录 CLI exe，源码走 python -m hd2proxy。"""
    exe = _bundle_cli_exe()
    if exe is not None:
        return [str(exe)] + [str(a) for a in args]
    return [sys.executable, "-m", "hd2proxy"] + [str(a) for a in args]


def decode_output(data):
    """把子进程原始输出字节解码成文本（UTF-8 优先，回退 GBK）。

    为什么不能只用 text=True+encoding=utf-8：冻结版是 PyInstaller 引导器，它的 stdout
    编码由控制台代码页决定（中文 Windows = cp936），PYTHONUTF8 / PYTHONIOENCODING 对冻结
    进程**无效**（实测四种组合输出字节完全相同）→ 按 UTF-8 解会变成一串 ？（U+FFFD）。
    所以这里自己解：先严格 UTF-8；失败说明是 GBK 输出，用 cp936 解 ✓
    """
    if not data:
        return ""
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("gbk", "cp936", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


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
            if e.code == 401:
                # 现场踩过（2026-11-20）：状态文件被另一个引擎实例覆盖 → 引擎在跑、token 不对。
                # 不能只报 401 让用户对着「引擎未运行」猜，必须把修复动作写出来。
                raise EngineError(
                    "HTTP 401: 状态文件与运行中的引擎不匹配（engine.json 可能被另一个实例覆盖）"
                    "—— 请重启引擎（「停止引擎」→「启动引擎」）；文件 %s" % self.state_file)
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
        args = ["engine", "--profile", str(profile_path), "--cert-dir", str(cert_dir)]
        if listen_ip:
            args += ["--listen-ip", str(listen_ip)]
        if control_port is not None:
            args += ["--control-port", str(int(control_port))]
        args += list(extra)
        return cli_argv(args)

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
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._log_thread = threading.Thread(target=self._pump_log, daemon=True)
        self._log_thread.start()
        return self.proc

    def _pump_log(self):
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        # 按原始字节读、用 decode_output 逐行解（冻结版引擎输出是 GBK，见 decode_output）✓
        for raw in proc.stdout:
            line = decode_output(raw).rstrip("\r\n")
            with self._log_lock:
                self.log_lines.append(line)

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
        """跑 CLI 子命令（源码=`python -m hd2proxy`，打包=同目录 `hd2proxy.exe`）；返回 (code, output)。"""
        env = os.environ.copy()
        if _bundle_cli_exe() is None:       # 源码模式需要把 src/ 塞进 PYTHONPATH
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            # 隐藏窗口：GUI 是 windowed 程序，不隐藏的话每次「安装/证书」按钮都会闪一个
            # 控制台窗口（用户看到的是几个 PowerShell 窗口）。
            r = subprocess.run(cli_argv(args),
                               cwd=str(REPO), env=env, capture_output=True,
                               timeout=timeout, **sysprobe._subprocess_kwargs())
            return r.returncode, decode_output(r.stdout) + decode_output(r.stderr)
        except subprocess.TimeoutExpired:
            return 124, "命令超时（%ss）：%s" % (timeout, " ".join(args))
        except Exception as e:      # noqa: BLE001
            return 1, "执行失败：%r" % (e,)
