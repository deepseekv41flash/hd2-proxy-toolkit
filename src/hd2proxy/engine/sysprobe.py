"""本机系统探针：网卡枚举 / 端口占用 / 游戏进程 / 证书存储 / 管理员身份。

这一层只做「给 GUI 与安装流程看状态」的只读探测，三条硬规矩：

  1. **只用标准库**（subprocess / socket / ctypes / csv / ipaddress），不引入 psutil 之类；
  2. **外部命令一律 8 秒超时**，失败返回空列表 / False / 空串，绝不抛异常把主流程打崩；
  3. **「跑命令」和「解析输出」分开**：``_parse_ipconfig`` / ``_parse_netstat`` 是纯函数，
     离线测试直接喂真实格式的文本，不依赖本机网卡与进程状态。

复用自 legacy_proxy.py 已验证的做法（M0 基线）：
  * 端口占用 = ``netstat -ano -p TCP`` 过滤 LISTENING + ``tasklist`` 查进程名
    （面板侧经验：只有一行「端口被占了」看不出是旧代理还是加速器，必须拿到 PID/进程名）；
  * 证书存储 = ``certutil -store Root <指纹>``（用户级加 ``-user``）；
  * 中文 Windows 的命令输出是 GBK/CP936，解析前统一按「本机首选编码 > UTF-8 > GBK > ANSI」解码。

测试注入点：
  * ``HD2PROXY_CERTUTIL``：覆盖 certutil 可执行文件路径（指向 .py 桩时自动套 ``sys.executable``）；
  * 解析/探测函数都留了 ``_xxx`` 内部函数，monkeypatch 它即可离线复现各种现场输出。
"""

import csv
import io
import ipaddress
import locale
import os
import re
import socket
import subprocess
import sys
import time

# 外部命令统一超时（秒）：netstat / tasklist / ipconfig / certutil 都够用
CMD_TIMEOUT = 8.0
# 端口占用缓存：GUI 每秒轮询也不该每秒都 spawn 两个进程
PORT_CACHE_TTL = 3.0

_IPV4_RE = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")

# ipconfig 适配器标题的中英文前缀（解析时剥掉，只留网卡名）
_ADAPTER_PREFIXES = (
    "以太网适配器", "无线局域网适配器", "隧道适配器", "未知适配器",
    "Ethernet adapter", "Wireless LAN adapter", "Tunnel adapter", "Unknown adapter",
)
# 「媒体已断开」的中英文标记：断开的网卡不采它的 IPv4（否则会拿到陈旧/占位地址）
_DISCONNECTED_MARKS = ("媒体已断开", "media disconnected", "已断开连接")
# 虚拟网卡关键词：默认监听地址要避开它们（VMware / Hyper-V / WSL / VPN / 代理 TUN 等）
_VIRTUAL_MARKS = (
    "vmware", "virtualbox", "virtual box", "hyper-v", "vethernet", "default switch",
    "wsl", "docker", "vmnet", "tap-", "tap adapter", "tap-windows", "tun",
    "tailscale", "zerotier", "radmin", "openvpn", "wireguard", "clash", "vpn",
    "npcap", "loopback", "teredo", "isatap", "6to4", "bluetooth", "pseudo-interface",
    "wi-fi direct", "virtual", "虚拟", "本地连接*", "local area connection*",
)

_PORT_CACHE: dict[int, tuple[float, list[dict]]] = {}
# 进程名缓存（PID->名字）与全量监听表缓存：一次 netstat 覆盖 TCP/TCPv6 所有端口。
# 为什么做全局缓存：总览页一次刷新要查 3 个端口，逐端口 spawn netstat/tasklist 会：
#   ① 每个子进程弹一个控制台窗口（GUI 无控制台时）；② tasklist 冷启动实测 ~570ms。
_NAMES_CACHE = None
_LISTENERS_CACHE = None
# 证书信任缓存：(指纹, 存储范围) -> (采样时间, 是否受信)。
# 为什么缓存：查一次要 spawn certutil；总览诊断/自检会反复调（证书续期后最容易踩到）。
_CERT_TRUST_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}


# --------------------------------------------------------------------------- #
# 命令执行 / 解码
# --------------------------------------------------------------------------- #
def _subprocess_kwargs() -> dict:
    """子进程「隐藏窗口」参数。

    为什么必须有：冻结版 GUI 是 windowed 程序（没有自己的控制台），它 spawn 的每个控制台
    子进程（netstat / tasklist / hd2proxy.exe CLI）都会**新开一个黑色控制台窗口** ——
    用户报「切总览页弹出几个 PowerShell 窗口」就是这个（Windows Terminal 是默认宿主，
    看起来像 PowerShell）。CREATE_NO_WINDOW 让子进程完全无窗口。
    """
    if os.name != "nt":
        return {}
    try:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0                      # SW_HIDE
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                "startupinfo": info}
    except Exception:                             # noqa: BLE001 - 平台差异时退回无参数
        return {}


def _run(argv: list[str], timeout: float = CMD_TIMEOUT) -> subprocess.CompletedProcess | None:
    """跑一条只读外部命令；超时 / 找不到程序 / 其它 OSError 一律返回 None。

    子进程一律隐藏窗口（见 ``_subprocess_kwargs``）。
    """
    try:
        return subprocess.run([str(a) for a in argv], capture_output=True, timeout=timeout,
                              **_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None


def decode_output(raw: bytes | None) -> str:
    """公开的命令输出解码入口（installer 拼 certutil 诊断信息时用）。"""
    return _decode(raw)


def _decode(raw: bytes | None) -> str:
    """把命令输出解码成文本：本机首选编码（中文 Windows=GBK）优先，其次 UTF-8/GBK/ANSI。"""
    if not raw:
        return ""
    candidates: list[str] = []
    try:
        candidates.append(locale.getpreferredencoding(False))
    except Exception:                                   # noqa: BLE001 - 缺 locale 就跳过
        pass
    candidates.extend(["utf-8", "gbk", "mbcs", "latin-1"])
    seen: set[str] = set()
    for enc in candidates:
        if not enc or enc.lower() in seen:
            continue
        seen.add(enc.lower())
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", "replace")


# --------------------------------------------------------------------------- #
# 网卡与监听地址
# --------------------------------------------------------------------------- #
def is_loopback(ip: str) -> bool:
    """是否回环地址（127.0.0.0/8、::1、localhost）。非法输入返回 False。"""
    value = "" if ip is None else str(ip).strip()
    if not value:
        return False
    if value.lower() in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_listen_ip(ip: str) -> str | None:
    """校验「能不能拿来当监听地址」：可以返回 None，不可以返回中文错误说明。

    新版客户端（19411+）拒绝回环连接，所以 127.x / 0.0.0.0 / localhost 都必须拦下来；
    自动配置地址（169.254.x.x）与组播/广播也不是真实网卡出口。
    """
    raw = "" if ip is None else str(ip).strip()
    if not raw:
        return "监听地址为空"
    if raw.lower() in ("localhost", "localhost."):
        return "不能用 localhost：新版客户端拒绝回环连接，请用本机网卡 IP 或 'auto'"
    try:
        addr = ipaddress.IPv4Address(raw)
    except ValueError:
        return "不是合法的 IPv4 地址：%r" % (raw,)
    if addr.is_loopback:
        return "不能用回环地址 %s：新版客户端拒绝 127.x 连接，请用本机网卡 IP 或 'auto'" % raw
    if addr.is_unspecified:
        return "不能用 0.0.0.0：必须绑到具体网卡 IP（客户端拒绝回环/未指定地址）"
    if addr.is_multicast:
        return "%s 是组播地址，不能监听" % raw
    if addr.is_link_local:
        return "%s 是自动配置地址（169.254.x.x），不可用" % raw
    if str(addr) == "255.255.255.255":
        return "不能用广播地址 255.255.255.255"
    return None


def _is_virtual_interface(interface: str, ip: str) -> bool:
    """按网卡名判断是否虚拟网卡；APIPA（169.254.x.x）也算不可用出口。"""
    name = (interface or "").lower()
    if ip.startswith("169.254."):
        return True
    return any(mark in name for mark in _VIRTUAL_MARKS)


def _parse_ipconfig(text: str) -> list[dict]:
    """解析 ipconfig 文本 -> [{"ip","interface","is_loopback","is_virtual"}]。

    中英文输出都能解析：适配器标题是「顶格 + 以冒号结尾」的行；IPv4 只认带 ``IPv4``
    字样的行（中文「IPv4 地址」与英文「IPv4 Address」都含这个 ASCII 词）。
    """
    entries: list[dict] = []
    if not text:
        return entries
    interface: str | None = None
    disconnected = False
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if not line[:1].isspace() and stripped.endswith(":") and len(stripped) > 1:
            name = stripped[:-1].strip()
            low = name.lower()
            for prefix in _ADAPTER_PREFIXES:
                if low.startswith(prefix.lower()):
                    name = name[len(prefix):].strip() or name
                    break
            interface = name
            disconnected = False
            continue
        if interface is None:
            continue
        low = stripped.lower()
        if any(mark.lower() in low for mark in _DISCONNECTED_MARKS):
            disconnected = True
            continue
        if "ipv4" not in low:
            continue
        match = _IPV4_RE.search(stripped)
        if not match or disconnected:
            continue
        ip = match.group(0)
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        key = (ip, interface)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "ip": ip,
            "interface": interface,
            "is_loopback": is_loopback(ip),
            "is_virtual": _is_virtual_interface(interface, ip),
        })
    return entries


def _ipconfig_text() -> str:
    """跑 ipconfig 取原始文本（GBK/UTF-8 自动解码）；失败返回空串。"""
    proc = _run(["ipconfig"])
    if proc is None or proc.returncode != 0:
        return ""
    return _decode(proc.stdout)


def _default_route_ip() -> str | None:
    """默认路由出口 IP：UDP connect 一个公网地址（不真发包）后读 getsockname。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.connect(("223.5.5.5", 80))
        ip = str(sock.getsockname()[0])
        return ip if validate_listen_ip(ip) is None else None
    except OSError:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _socket_fallback_entries() -> list[dict]:
    """ipconfig 不可用时的兜底：默认路由出口 + 主机名解析到的 IPv4。"""
    found: dict[str, dict] = {}
    route_ip = _default_route_ip()
    if route_ip:
        found[route_ip] = {
            "ip": route_ip,
            "interface": "（默认路由出口）",
            "is_loopback": False,
            "is_virtual": False,
        }
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        ip = str(info[4][0])
        if ip in found:
            continue
        found[ip] = {
            "ip": ip,
            "interface": "（主机名解析）",
            "is_loopback": is_loopback(ip),
            "is_virtual": False,
        }
    return list(found.values())


def local_ipv4_addresses() -> list[dict]:
    """本机所有 IPv4 地址：[{"ip","interface","is_loopback","is_virtual"}]。

    优先 ipconfig（能拿到网卡名与媒体状态），失败再退回 socket（至少有个出口 IP）。
    探测本身失败时返回空列表，不抛异常。
    """
    entries = _parse_ipconfig(_ipconfig_text())
    if entries:
        return entries
    try:
        return _socket_fallback_entries()
    except OSError:
        return []


def resolve_listen_ip(value: str | None) -> str:
    """把用户配置的监听地址解析成具体 IPv4。

    * ``None`` / 空串 / ``"auto"``：优先默认路由出口，其次物理网卡，最后任意非回环；
    * 显式 IPv4：校验后返回规范化字符串；
    * 回环 / 0.0.0.0 / localhost / 非法值：抛 ``ValueError``（新版客户端拒绝回环）。
    """
    raw = "" if value is None else str(value).strip()
    if raw == "" or raw.lower() == "auto":
        route_ip = _default_route_ip()
        if route_ip and validate_listen_ip(route_ip) is None:
            return route_ip
        entries = local_ipv4_addresses()
        for want_physical in (True, False):
            for entry in entries:
                if entry.get("is_loopback"):
                    continue
                if want_physical and entry.get("is_virtual"):
                    continue
                if validate_listen_ip(entry.get("ip")) is None:
                    return str(ipaddress.IPv4Address(entry["ip"]))
        raise ValueError("找不到可用的非回环 IPv4 地址：请检查网卡/网络连接，或显式指定监听 IP")
    problem = validate_listen_ip(raw)
    if problem:
        raise ValueError(problem)
    return str(ipaddress.IPv4Address(raw))


# --------------------------------------------------------------------------- #
# 端口与进程
# --------------------------------------------------------------------------- #
def _parse_netstat(text: str, port: int) -> dict[int, str]:
    """从 netstat 文本里找出监听指定端口的 PID -> 本地地址（一行多绑定时取第一个）。"""
    pids: dict[int, str] = {}
    suffix = ":%d" % int(port)
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[3].upper() != "LISTENING":
            continue
        local = fields[1]
        if not local.endswith(suffix):
            continue
        try:
            pid = int(fields[4])
        except ValueError:
            continue
        pids.setdefault(pid, local)
    return pids


def _snapshot_process_names() -> dict[int, str]:
    """PID -> 进程名：Windows 用 Toolhelp 快照（纯 ctypes，无子进程、无窗口，几毫秒级）。"""
    if os.name != "nt":
        return {}
    names: dict[int, str] = {}
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)   # TH32CS_SNAPPROCESS
        if not snapshot or int(snapshot) == -1:
            return {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                names[int(entry.th32ProcessID)] = str(entry.szExeFile)
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:                             # noqa: BLE001 - 快照失败走 tasklist 兜底
        return {}
    return names


def _process_names() -> dict[int, str]:
    """PID -> 进程名（3 秒缓存）：Toolhelp 快照优先，失败才退回 tasklist（慢且弹窗）。"""
    global _NAMES_CACHE
    now = time.monotonic()
    if _NAMES_CACHE is not None and now - _NAMES_CACHE[0] < PORT_CACHE_TTL:
        return dict(_NAMES_CACHE[1])
    names = _snapshot_process_names()
    if not names:
        names = _tasklist_csv_names()
    _NAMES_CACHE = (now, names)
    return dict(names)


def _tasklist_names() -> dict[int, str]:
    """兼容旧名字：等价 ``_process_names``（测试与调用方不必区分实现）。"""
    return _process_names()


def _tasklist_csv_names() -> dict[int, str]:
    """PID -> 进程名（旧路径：tasklist CSV；只在 Toolhelp 快照失败时用）。"""
    proc = _run(["tasklist", "/NH", "/FO", "CSV"])
    if proc is None:
        return {}
    names: dict[int, str] = {}
    try:
        rows = csv.reader(io.StringIO(_decode(proc.stdout)))
        for row in rows:
            if len(row) < 2:
                continue
            name = (row[0] or "").strip()
            try:
                pid = int((row[1] or "").strip())
            except ValueError:
                continue
            if name:
                names[pid] = name
    except csv.Error:
        return names
    return names


def _parse_all_listeners(text: str) -> dict[int, list[dict]]:
    """一条 ``netstat -ano`` 输出 -> {port: [{pid, addr, host}]}（TCP/TCPv6 都认）。

    用不带 ``-p`` 的 netstat：一次调用同时列出 IPv4+IPv6 监听，避免「每端口两次 spawn」。
    """
    out: dict[int, list[dict]] = {}
    seen: set[tuple[int, int, str]] = set()
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[0].upper() not in ("TCP", "TCPV6"):
            continue
        try:
            state_idx = next(i for i, f in enumerate(fields) if f.upper() == "LISTENING")
        except StopIteration:
            continue
        local = fields[1]
        try:
            port = int(local.rsplit(":", 1)[1])
            pid = int(fields[state_idx + 1])
        except (IndexError, ValueError):
            continue
        if port <= 0 or pid <= 0:
            continue
        host = local.rsplit(":", 1)[0].strip("[]")
        key = (port, pid, local)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(port, []).append({"pid": pid, "addr": local, "host": host})
    return out


def _listeners_all() -> dict[int, list[dict]]:
    """全量监听表（3 秒缓存）：一次 netstat 覆盖所有端口/协议。

    为什么全局缓存：总览页一次刷新要查 443/8080/17897 三个端口，逐端口 spawn 会把
    「一个窗口 + 一次冷启动」放大三倍（用户实测切总览会卡一下并弹几个窗口）。
    """
    global _LISTENERS_CACHE
    now = time.monotonic()
    if _LISTENERS_CACHE is not None and now - _LISTENERS_CACHE[0] < PORT_CACHE_TTL:
        return _LISTENERS_CACHE[1]
    proc = _run(["netstat", "-ano"])
    listeners = {} if proc is None else _parse_all_listeners(_decode(proc.stdout))
    _LISTENERS_CACHE = (now, listeners)
    return listeners


def _query_port_owners(port: int) -> list[dict]:
    """查指定端口的监听者（走全量监听缓存；不额外 spawn netstat/tasklist）。

    返回条目带 ``path``（进程完整路径）——现场排查时「哪个目录下的 python.exe」是关键信息
    （旧代理没退干净 vs 加速器占用，靠路径区分）。
    """
    port = int(port)
    raw = _listeners_all().get(port) or []
    if not raw:
        return []
    names = _process_names()
    return [
        {"pid": item["pid"], "name": names.get(item["pid"], "?"),
         "addr": item["addr"], "host": item["host"],
         "path": _proc_path(item["pid"]),
         "wildcard": _is_wildcard_addr(item["host"])}
        for item in sorted(raw, key=lambda x: (x["addr"], x["pid"]))
    ]


def _parse_netstat_listeners(text: str, port: int) -> list[dict]:
    """从 netstat 文本里找出监听指定端口的**全部** (pid, 本地地址) 对（IPv4/IPv6 都认）。

    与 ``_parse_netstat`` 的区别：那个按 PID 去重只留一个地址（GUI 列占用者用），
    这个一行一条、保留 ``0.0.0.0`` / ``[::]`` 通配绑定 —— 判断「换监听 IP 有没有用」靠它。
    """
    out: list[dict] = []
    suffix = ":%d" % int(port)
    seen: set[tuple[int, str]] = set()
    for line in (text or "").splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[0].upper() not in ("TCP", "TCPV6"):
            continue
        try:
            state_idx = next(i for i, f in enumerate(fields) if f.upper() == "LISTENING")
        except StopIteration:
            continue
        local = fields[1]
        if not local.endswith(suffix):
            continue
        try:
            pid = int(fields[state_idx + 1])
        except (IndexError, ValueError):
            continue
        host = local.rsplit(":", 1)[0].strip("[]") or local.rsplit(":", 1)[0]
        key = (pid, local)
        if key in seen:
            continue
        seen.add(key)
        out.append({"pid": pid, "addr": local, "host": host})
    return out


_WILDCARD_ADDRS = ("0.0.0.0", "::", "[::]", "*")


def _is_wildcard_addr(host: str) -> bool:
    """是不是通配绑定（0.0.0.0 / ::）—— 这种占用换任何监听 IP 都躲不开。"""
    return str(host or "").strip().strip("[]") in ("0.0.0.0", "::", "*")


def port_listeners(port: int) -> list[dict]:
    """谁在监听这个端口（带 name/path/wildcard），3 秒缓存（GUI 会高频轮询）。"""
    port = int(port)
    now = time.monotonic()
    hit = _PORT_CACHE.get(port)
    if hit is not None and now - hit[0] < PORT_CACHE_TTL:
        return [dict(item) for item in hit[1]]
    owners = _query_port_owners(port)
    _PORT_CACHE[port] = (now, owners)
    return [dict(item) for item in owners]


def port_owner(port: int) -> list[dict]:
    """谁在监听这个端口：[{"pid","name","addr"}]，按 PID 去重（一个进程多地址只列一次）。

    3 秒缓存（GUI 会高频轮询）；要看通配绑定/完整路径用 ``port_listeners``。
    """
    seen: set[int] = set()
    out: list[dict] = []
    for item in port_listeners(port):
        pid = int(item["pid"])
        if pid in seen:
            continue
        seen.add(pid)
        out.append({"pid": pid, "name": item["name"], "addr": item["addr"]})
    out.sort(key=lambda item: item["pid"])
    return out


def port_in_use(port: int) -> bool:
    """端口是否有监听者（含 0.0.0.0 通配绑定 —— 这正是与游戏/加速器抢 443 的典型现场）。"""
    return bool(port_listeners(port))


def bindable(ip: str, port: int) -> bool:
    """能否在 ``ip:port`` 上**独占**绑定（Windows 必须用 SO_EXCLUSIVEADDRUSE 才测得准）。

    用 SO_REUSEADDR 时「别人正在监听、我们也能绑定成功」，检测会误报空闲 ——
    这正是第三方工具踩过、我们沿用下来的结论。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((str(ip), int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def port_state(ip: str, port: int, own_pids=()) -> dict:
    """端口三态：``free`` / ``ours``（本工具引擎占用，正常）/ ``conflict``（别人占用）。

    判定顺序：先独占试绑（free 的唯一权威），失败再按占用者 PID 区分 ours / conflict。
    通配绑定（0.0.0.0 / ::）单独标记 —— 这时换监听 IP 没用，必须关掉占用者。
    """
    owners = port_listeners(int(port))
    free = bindable(ip, int(port))
    own = {int(pid) for pid in (own_pids or ()) if int(pid) > 0}
    mine = [item for item in owners if item["pid"] in own]
    others = [item for item in owners if item["pid"] not in own]
    if free:
        state = "free"
    elif mine and not others:
        state = "ours"
    else:
        state = "conflict"
    return {
        "ip": str(ip),
        "port": int(port),
        "state": state,
        "wildcard": any(bool(item.get("wildcard")) for item in owners),
        "owners": owners,
    }


def ports_state(ip: str, ports, own_pids=()) -> list[dict]:
    """一次查多个端口（441/8080/控制面这类组合）；顺序与传入一致。"""
    return [port_state(ip, int(port), own_pids) for port in ports]


def _proc_path(pid: int) -> str:
    """PID -> 进程完整路径（只为现场排查用；拿不到返回空串）。"""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception:                                   # noqa: BLE001 - 探测失败当没有路径
        return ""
    return ""


def pid_alive(pid: int) -> bool:
    """PID 是否还活着（不启子进程：Windows 走 kernel32，其它平台 os.kill(pid, 0)）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            synchronize = 0x00100000
            handle = kernel32.OpenProcess(synchronize, False, pid)
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) != 0
            finally:
                kernel32.CloseHandle(handle)
        except Exception:                               # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def primary_ip() -> str:
    """当前默认路由出口 IP（空串 = 探测失败）。公开包装，GUI 用来对 hosts 里的 IP。"""
    return _default_route_ip() or ""


def game_running() -> bool:
    """《Helldivers 2》是否在运行（进程名含 helldivers2，大小写不敏感）。"""
    try:
        names = _process_names()
    except OSError:
        return False
    return any("helldivers2" in name.lower() for name in names.values())


def clear_caches() -> None:
    """清掉全部探测缓存（引擎启停后由 App 主动调用；测试也用它强制重查）。

    三张缓存都要清：端口→占用者（``_PORT_CACHE``）、PID→进程名（``_NAMES_CACHE``）、
    全量监听表（``_LISTENERS_CACHE``）。只清第一张会让后两张继续返回过期数据
    （引擎刚好停掉时仍显示「被自己占用」）。
    """
    global _NAMES_CACHE, _LISTENERS_CACHE
    _PORT_CACHE.clear()
    _NAMES_CACHE = None
    _LISTENERS_CACHE = None
    _CERT_TRUST_CACHE.clear()


# --------------------------------------------------------------------------- #
# 证书存储
# --------------------------------------------------------------------------- #
def normalize_thumbprint(thumbprint: str) -> str:
    """指纹规范化：去掉空格/冒号等分隔符，统一大写（certutil 只认十六进制）。"""
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", "" if thumbprint is None else str(thumbprint))
    return cleaned.upper()


def cert_scope_args(scope: str = "LocalMachine") -> list[str] | None:
    """证书存储范围 -> certutil 参数前缀。

    LocalMachine -> ``[]``（``certutil -store ...``）
    CurrentUser  -> ``["-user"]``（``certutil -user -store ...``）
    未知范围返回 None（调用方按失败处理）。
    """
    value = (scope or "LocalMachine").strip().lower()
    if value in ("localmachine", "local_machine", "machine", "local", "computer"):
        return []
    if value in ("currentuser", "current_user", "user", "cu"):
        return ["-user"]
    return None


def certutil_argv(args: list[str]) -> list[str]:
    """拼 certutil 命令行；``HD2PROXY_CERTUTIL`` 可覆盖可执行文件（测试注入桩用）。

    *.py 桩会自动套 ``sys.executable``（Windows 上 .py 不能直接执行）；
    这里只支持单一可执行文件路径，不支持带参数的命令行。
    """
    override = (os.environ.get("HD2PROXY_CERTUTIL") or "").strip().strip('"')
    if override:
        if override.lower().endswith(".py"):
            base = [sys.executable, override]
        else:
            base = [override]
    else:
        base = ["certutil"]
    return base + [str(a) for a in args]


def run_certutil(args: list[str], timeout: float = CMD_TIMEOUT) -> subprocess.CompletedProcess | None:
    """跑一次 certutil（参数不含程序名）；超时/失败返回 None。"""
    return _run(certutil_argv(args), timeout=timeout)


def cert_in_store(thumbprint: str, scope: str = "LocalMachine") -> bool:
    """证书是否已在受信任根存储里。

    ``certutil -store Root <指纹>``（本机） / ``certutil -user -store Root <指纹>``（当前用户）。
    certutil 找到返回 0、找不到返回非 0；这里把「跑不起来」也当 False（调用方会走导入流程）。
    """
    normalized = normalize_thumbprint(thumbprint)
    if not normalized:
        return False
    scope_args = cert_scope_args(scope)
    if scope_args is None:
        return False
    proc = run_certutil(scope_args + ["-store", "Root", normalized])
    return proc is not None and proc.returncode == 0


def cert_trusted(thumbprint: str, scope: str = "LocalMachine") -> bool:
    """``cert_in_store`` 的带缓存版本（GUI 诊断会反复查，cache 3 秒）。

    **为什么必须缓存**：一次证书信任检查要 spawn ``certutil``（约 60–120ms，且是控制台子进程）。
    总览「现场检查」/「系统自检」会在切页、续期证书后连续调用；不缓存就会重复 spawn。
    """
    key = (normalize_thumbprint(thumbprint), str(scope or "LocalMachine"))
    now = time.monotonic()
    hit = _CERT_TRUST_CACHE.get(key)
    if hit is not None and now - hit[0] < PORT_CACHE_TTL:
        return hit[1]
    trusted = cert_in_store(key[0], key[1])
    _CERT_TRUST_CACHE[key] = (now, trusted)
    return trusted


def is_admin() -> bool:
    """当前进程是否管理员（Windows 用 shell32.IsUserAnAdmin；其它平台看 euid）。"""
    try:
        if os.name == "nt":
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:                                   # noqa: BLE001 - 探测失败当非管理员
        pass
    try:
        return os.geteuid() == 0                        # type: ignore[attr-defined]
    except AttributeError:
        return False
