"""本地控制面：GUI / CLI / 自动化统一走这个 127.0.0.1 HTTP 接口。

为什么要独立控制面（而不是 GUI 直接读文件/发信号）：
  * GUI 崩了不影响引擎；引擎也可以 headless 跑，由脚本/agent 操作同一套接口；
  * 热改配置、跑验收、看事件都有一个权威入口，不用再靠「改 JSON 等 mtime」；
  * 未来换 GUI（Web/Qt）或加托盘，接口不变。

安全（沿用研究线的克制）：
  * 只绑 127.0.0.1，只接受本机来源；
  * 每个请求要 token（`X-HD2-Token` 头或 `?token=`），常量时间比较；
  * token 与端口写在 `%LOCALAPPDATA%/HD2ProxyStudio/engine.json`（仅当前用户可读的目录）。
"""

import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as cfgmod
from . import paths
from . import verify as verify_mod
from .logutil import log

MAX_BODY = 2 << 20      # 2MB：profile 不该这么大


class _ControlHTTPServer(ThreadingHTTPServer):
    """控制面 HTTP 服务：**端口独占**，防第二个引擎实例抢占。

    为什么必须独占：Windows 上 ``SO_REUSEADDR`` 允许另一个进程「抢占」已监听的端口，
    而 Python 的 ``HTTPServer.allow_reuse_address`` 默认就是 True。实测（2026-11-20）：
    另一个引擎实例把 17897 抢走并覆盖了 engine.json，token 随之变成它的，GUI/CLI 全部
    401、GUI 误显示「引擎未运行」，而真正服务游戏的旧引擎还在跑。
    这里改 ``allow_reuse_address = False`` + ``SO_EXCLUSIVEADDRUSE``，第二个实例起控制面
    直接失败，不会劫持状态文件。
    """

    allow_reuse_address = False
    request_queue_size = 8

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class ControlServer:
    """控制面句柄：start() 起线程并写 engine.json；stop() 收摊并清理。"""

    def __init__(self, ctx, port=0, token=None):
        self.ctx = ctx
        self.token = token or secrets.token_urlsafe(24)
        self.httpd = _ControlHTTPServer(("127.0.0.1", int(port)), _make_handler(self))
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="hd2proxy-control", daemon=True)
        self.started_at = time.time()

    # ---- 生命周期 ----------------------------------------------------------
    def start(self):
        self.thread.start()
        self.write_state()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
        self.clear_state()

    # ---- engine.json（GUI/CLI 发现入口） -----------------------------------
    def state_path(self) -> Path:
        return paths.engine_state_file()

    def state(self) -> dict:
        import hd2proxy
        return {
            "version": hd2proxy.__version__,
            "pid": os.getpid(),
            "port": self.port,
            "url": "http://127.0.0.1:%d" % self.port,
            "token": self.token,
            "started_at": _now(),
        }

    def write_state(self):
        try:
            p = self.state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            self._protect_existing_state(p)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.state(), ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, p)
        except Exception as e:      # noqa: BLE001
            log("engine.json 写入失败: %r" % e)

    def _protect_existing_state(self, p: Path):
        """覆盖前看一眼旧状态文件：如果它指向**另一个仍然活着的引擎**，先备份再覆盖。

        正常情况不会发生（443 与控制面都是独占绑定），但现场出现过一次「状态文件被另一个
        实例覆盖，运行中引擎的随机 token 随之丢失、GUI/CLI 全部 401」——留个兜底：至少把
        旧文件留成 ``engine.json.bak`` 并在日志里说清楚，不至于无声丢失。
        """
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            old_pid = int(old.get("pid") or 0)
        except (OSError, ValueError, TypeError):
            return
        if not old_pid or old_pid == os.getpid():
            return
        from . import sysprobe
        if not sysprobe.pid_alive(old_pid):
            return
        backup = p.with_suffix(".json.bak")
        try:
            p.replace(backup)
            log("⚠ engine.json 原本指向仍在运行的引擎 pid=%d，已备份为 %s 后覆盖"
                % (old_pid, backup.name))
        except OSError as e:        # noqa: PERF203 - 备份失败不阻断启动
            log("⚠ engine.json 覆盖前备份失败（继续写入）：%r" % e)

    def clear_state(self):
        try:
            p = self.state_path()
            doc = json.loads(p.read_text(encoding="utf-8"))
            if int(doc.get("pid") or 0) == os.getpid():
                p.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------- HTTP 层


def _make_handler(srv: ControlServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "hd2proxy-control/1"
        sys_version = ""

        # ---- 基础 ------------------------------------------------------
        def log_message(self, *args):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _authorized(self) -> bool:
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return False
            gave = self.headers.get("X-HD2-Token")
            if not gave:
                q = self.path.split("?", 1)[1] if "?" in self.path else ""
                for part in q.split("&"):
                    if part.startswith("token="):
                        gave = part.split("=", 1)[1]
                        break
            return bool(gave) and hmac.compare_digest(str(gave), srv.token)

        def _read_json(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0 or n > MAX_BODY:
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return None

        # ---- 路由 ------------------------------------------------------
        def do_GET(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            path = self.path.split("?", 1)[0]
            ctx = srv.ctx
            if path in ("/healthz", "/health"):
                return self._send(200, {"ok": True, "ts": _now()})
            if path == "/status":
                return self._send(200, ctx.status())
            if path == "/events":
                return self._send(200, {"events": list(ctx.proxy.rewrites)[-200:]})
            if path == "/config":
                return self._send(200, _current_config(ctx))
            if path == "/profiles":
                return self._send(200, {"profiles": cfgmod.list_profiles()})
            if path == "/state":
                return self._send(200, srv.state())
            return self._send(404, {"error": "not found", "path": path})

        def do_PUT(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            path = self.path.split("?", 1)[0]
            ctx = srv.ctx
            if path == "/config":
                body = self._read_json()
                if not isinstance(body, dict):
                    return self._send(400, {"error": "body 必须是 profile JSON 对象"})
                try:
                    normalized, errors, warnings = cfgmod.validate(body)
                    if errors:
                        return self._send(422, {"ok": False, "errors": errors,
                                                "warnings": warnings})
                    if ctx.profile_path is None:
                        return self._send(409, {"error": "当前引擎不是 profile 模式，"
                                                         "请用 --profile 启动后再热改"})
                    cfgmod.save_profile_file(ctx.profile_path, normalized)
                    applied = _apply(ctx, normalized)
                    return self._send(200, {"ok": True, "warnings": warnings,
                                            "applied": applied})
                except ValueError as e:
                    return self._send(422, {"ok": False, "errors": [str(e)]})
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            path = self.path.split("?", 1)[0]
            ctx = srv.ctx
            body = self._read_json() or {}
            if path == "/verify":
                try:
                    return self._send(200, verify_mod.verify_all(ctx))
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            if path == "/reload":
                try:
                    doc = json.loads(Path(ctx.profile_path).read_text(encoding="utf-8")) \
                        if ctx.profile_path and Path(ctx.profile_path).exists() else None
                    if doc is None:
                        return self._send(409, {"error": "没有可重载的 profile 文件"})
                    normalized, errors, warnings = cfgmod.validate(doc)
                    if errors:
                        return self._send(422, {"ok": False, "errors": errors})
                    return self._send(200, {"ok": True, "warnings": warnings,
                                            "applied": _apply(ctx, normalized)})
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            if path == "/passthrough":
                enabled = bool(body.get("enabled"))
                try:
                    applied = _set_passthrough(ctx, enabled)
                    return self._send(200, {"ok": True, "applied": applied})
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            if path == "/capture":
                enabled = bool(body.get("enabled"))
                try:
                    applied = _toggle_capture(ctx, enabled, body.get("dir"))
                    return self._send(200, {"ok": True, "applied": applied})
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            if path == "/profiles/activate":
                name = body.get("name")
                if not isinstance(name, str) or not name:
                    return self._send(400, {"error": "需要 name"})
                try:
                    prof = cfgmod.load_profile(name)
                    if ctx.profile_path is not None:
                        cfgmod.save_profile_file(ctx.profile_path, prof)
                    applied = _apply(ctx, prof)
                    return self._send(200, {"ok": True, "applied": applied})
                except Exception as e:      # noqa: BLE001
                    return self._send(500, {"ok": False, "error": repr(e)})
            if path == "/shutdown":
                ctx.shutdown.set()
                return self._send(200, {"ok": True, "message": "engine 正在退出"})
            return self._send(404, {"error": "not found", "path": path})

    return Handler


# ---------------------------------------------------------------- 应用动作


def _current_config(ctx) -> dict:
    if ctx.profile_path and Path(ctx.profile_path).exists():
        try:
            doc = json.loads(Path(ctx.profile_path).read_text(encoding="utf-8"))
            normalized, errors, warnings = cfgmod.validate(doc)
            return {"mode": "profile", "path": str(ctx.profile_path), "name": ctx.profile_name,
                    "profile": normalized, "errors": errors, "warnings": warnings}
        except Exception as e:      # noqa: BLE001
            return {"mode": "profile", "path": str(ctx.profile_path), "error": repr(e)}
    return {"mode": "legacy",
            "profile": None,
            "note": "当前是研究线兼容模式（config.json + runtime/*.json）"}


def _apply(ctx, profile: dict) -> dict:
    """把校验后的 profile 应用到运行中的引擎（热更新，不重启、不断开游戏）。"""
    spec = ctx.reload_cb(profile) if ctx.reload_cb else None
    if isinstance(spec, dict):
        return spec
    return {"ok": True, "hot": True}


def _set_passthrough(ctx, enabled: bool) -> dict:
    if ctx.set_passthrough_cb:
        return ctx.set_passthrough_cb(enabled)
    ctx.mod.passthrough = bool(enabled)
    if ctx.proxy.spec is not None:
        ctx.proxy.spec.passthrough = bool(enabled)
    if getattr(ctx, "spec", None) is not None:
        ctx.spec.passthrough = bool(enabled)
    log("passthrough -> %s（控制面）" % bool(enabled), audit=True)
    return {"passthrough": bool(enabled)}


def _toggle_capture(ctx, enabled: bool, directory=None) -> dict:
    if ctx.capture_cb:
        return ctx.capture_cb(enabled, directory)
    spec = ctx.proxy.spec
    if spec is None:
        return {"capture": None, "note": "legacy 模式用环境变量 HD2_GWE_DUMP 控制抓包"}
    cap = dict(spec.capture or {})
    cap["enabled"] = bool(enabled)
    if directory:
        cap["dir"] = str(directory)
    cap.setdefault("paths", ["api/"])
    cap.setdefault("req_paths", [])
    cap.setdefault("max_bytes", 8 << 20)
    if enabled and not cap.get("dir"):
        cap["dir"] = str(paths.capture_default_dir())
    spec.capture = cap
    log("capture -> %s dir=%s（控制面）" % (cap["enabled"], cap.get("dir")), audit=True)
    return {"capture": {k: cap.get(k) for k in ("enabled", "dir", "paths", "req_paths")}}


def start(ctx, port=0) -> ControlServer:
    """起控制面并返回句柄（端口 0 = 随机端口）。"""
    srv = ControlServer(ctx, port=port).start()
    return srv
