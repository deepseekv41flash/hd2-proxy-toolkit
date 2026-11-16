"""UAC 提权（ShellExecuteExW "runas"）：只在「装 hosts + 信任证书」时弹一次。

设计约束（对应 PLAN §3.2 与产品形态）：

  * 日常运行引擎**不需要管理员**；只有 install / uninstall 需要，所以提权逻辑独立成一层；
  * 提权就是「用管理员身份重新启动自己 + 一组参数」，子进程跑完把 exit code 带回来，
    父进程再**回读系统状态**确认 —— 不信任 exit code 单独作为成功依据；
  * 用户点「否」不是错误而是**预期分支**：返回 ``cancelled=True``（Win32 ``ERROR_CANCELLED=1223``），
    调用方据此给出「已取消，系统未被改动」的文案，而不是抛异常；
  * 开发态入口用 ``sys.argv[0]``（``python -m hd2proxy`` 时它就是 ``__main__.py`` 的绝对路径），
    打包后（``sys.frozen``）直接重启自身 exe。

测试注入点（**绝不真弹 UAC**）：
  * ``HD2PROXY_ELEVATION_STUB=1``：``run_elevated`` 立即返回「用户取消」的固定结果；
  * 需要模拟「提权后成功」时，monkeypatch ``run_elevated``（安装器里是模块属性调用，好替换）；
  * ``build_elevation_argv`` 可单独测：monkeypatch ``sys.frozen`` / ``sys.argv`` 即可覆盖两条分支。
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from . import sysprobe

# UAC 被用户取消时 ShellExecuteEx 的 GetLastError
ERROR_CANCELLED = 1223
# ShellExecuteEx 的 fMask 位
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
# 等待提权子进程的默认超时（秒）：install 里要写 hosts + 导证书，180s 足够
ELEVATE_TIMEOUT = 180.0


class _ShellExecuteInfoW(ctypes.Structure):
    """SHELLEXECUTEINFOW（x64 下 cbSize=112）。

    只用 ctypes 基础类型，避免依赖 ``ctypes.wintypes`` 的平台差异；
    ``hIcon`` 与 ``hMonitor`` 在 Windows 头文件里是 union，两者都是指针，尺寸一致。
    """

    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("fMask", ctypes.c_uint32),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _result(launched: bool, cancelled: bool, exit_code: int | None,
            error: str | None) -> dict:
    return {
        "launched": launched,
        "cancelled": cancelled,
        "exit_code": exit_code,
        "error": error,
    }


def can_elevate() -> bool:
    """当前是否还能提权：非管理员时 True（管理员本来就能直接干，无需再弹 UAC）。"""
    return not sysprobe.is_admin()


def _entry_script() -> str:
    """开发态入口脚本路径：优先 ``sys.argv[0]``（``python -m hd2proxy`` 时是 __main__.py）。

    ``sys.argv[0]`` 为空或以 ``-`` 开头（``python -c``）时退回包内的 ``__main__.py``。
    """
    raw = ""
    try:
        raw = str(sys.argv[0] or "").strip()
    except (IndexError, TypeError):
        raw = ""
    if raw and not raw.startswith("-"):
        try:
            path = Path(raw)
            if path.exists():
                return str(path.resolve())
        except OSError:
            pass
        return raw
    return str(Path(__file__).resolve().parents[1] / "__main__.py")


def build_elevation_argv(args: list[str]) -> list[str]:
    """拼「提权后要执行的完整 argv」。

    * 打包后（``getattr(sys, "frozen", False)``）：``[sys.executable, *args]``
    * 开发态：``[sys.executable, <入口脚本>, *args]``
    """
    args = [str(a) for a in (args or [])]
    if getattr(sys, "frozen", False):
        return [sys.executable] + args
    return [sys.executable, _entry_script()] + args


def _looks_like_full_argv(args: list[str]) -> bool:
    """判断传入的是「完整 argv」还是「子命令参数」。

    约定 ``run_elevated`` 收「子命令参数」（如 ``["install","--plan",...]``）并自动补解释器；
    也兼容直接给完整 argv（首元素是当前解释器或 *.exe 时不再补）。
    """
    if not args:
        return False
    first = str(args[0])
    if first == sys.executable:
        return True
    return first.lower().endswith(".exe")


def _win_error_text(code: int) -> str:
    try:
        return "%s（代码 %d）" % (ctypes.FormatError(code), code)
    except Exception:                                   # noqa: BLE001 - 非 Windows 没 FormatError
        return "代码 %d" % code


def _runas_and_wait(argv: list[str], *, wait: bool, timeout: float) -> dict:
    """真正调 ShellExecuteExW("runas") 并（可选）等 exit code。仅 Windows 可用。"""
    exe = argv[0]
    parameters = subprocess.list2cmdline(argv[1:]) if len(argv) > 1 else None
    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = parameters
    info.lpDirectory = None
    info.nShow = 1                                      # SW_SHOWNORMAL

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (OSError, AttributeError) as e:              # 非 Windows / 异常精简系统
        return _result(False, False, None, "当前平台无法调用 ShellExecuteExW：%r" % (e,))

    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfoW)]
    shell32.ShellExecuteExW.restype = ctypes.c_int
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == ERROR_CANCELLED:
            return _result(False, True, None, None)     # 用户点了「否」：预期分支，不是错误
        return _result(False, False, None,
                       "创建提权进程失败：%s" % _win_error_text(err))

    handle = info.hProcess
    if not wait:
        if handle:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        return _result(True, False, None, None)
    if not handle:
        return _result(True, False, None, "提权进程已启动，但拿不到进程句柄（无法等待 exit code）")

    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    millis = int(max(0.0, float(timeout)) * 1000)
    try:
        waited = kernel32.WaitForSingleObject(ctypes.c_void_p(handle), millis)
        if waited == 0:                                 # WAIT_OBJECT_0
            code = ctypes.c_uint32(0)
            okay = kernel32.GetExitCodeProcess(ctypes.c_void_p(handle),
                                               ctypes.byref(code))
            exit_code = int(code.value) if okay else None
            return _result(True, False, exit_code, None)
        if waited == 258:                               # WAIT_TIMEOUT
            return _result(True, False, None, "等待提权进程超时（%.0f 秒）" % timeout)
        return _result(True, False, None, "等待提权进程失败（WaitForSingleObject=%d）" % waited)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def run_elevated(args: list[str], *, wait: bool = True,
                 timeout: float = ELEVATE_TIMEOUT) -> dict:
    """以管理员身份运行（必要时弹 UAC），返回::

        {"launched": bool, "cancelled": bool, "exit_code": int|None, "error": str|None}

    * ``cancelled=True``：用户点了「否」（``ERROR_CANCELLED``），系统未被改动；
    * ``launched=True, exit_code=0``：子进程正常结束（**是否真的生效还要调用方回读验证**）；
    * ``HD2PROXY_ELEVATION_STUB=1`` 时直接返回「用户取消」，用于离线测试绝不弹 UAC。
    """
    argv = [str(a) for a in (args or [])]
    if (os.environ.get("HD2PROXY_ELEVATION_STUB") or "").strip() == "1":
        return _result(False, True, None, None)
    if not argv:
        return _result(False, False, None, "没有要执行的命令")
    if not _looks_like_full_argv(argv):
        argv = build_elevation_argv(argv)
    if os.name != "nt":
        return _result(False, False, None, "UAC 提权仅在 Windows 上可用")
    try:
        return _runas_and_wait(argv, wait=wait, timeout=timeout)
    except Exception as e:                              # noqa: BLE001 - 提权失败必须落成返回值
        return _result(False, False, None, "提权调用异常：%r" % (e,))


def relaunch_self(command: str, *rest: str, wait: bool = True,
                  timeout: float = ELEVATE_TIMEOUT) -> dict:
    """便捷封装：以管理员身份重新启动自己并执行 ``command`` 子命令。

    例：``relaunch_self("install", "--plan", str(tmp), "--elevated")``。
    """
    return run_elevated([command, *rest], wait=wait, timeout=timeout)
