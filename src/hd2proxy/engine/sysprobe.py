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


# --------------------------------------------------------------------------- #
# 命令执行 / 解码
# --------------------------------------------------------------------------- #
def _run(argv: list[str], timeout: float = CMD_TIMEOUT) -> subprocess.CompletedProcess | None:
    """跑一条只读外部命令；超时 / 找不到程序 / 其它 OSError 一律返回 None。"""
    try:
        return subprocess.run([str(a) for a in argv], capture_output=True, timeout=timeout)
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


def _tasklist_names() -> dict[int, str]:
    """PID -> 进程名（tasklist CSV 一次拿全，避免按 PID 逐个查进程）。"""
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


def _query_port_owners(port: int) -> list[dict]:
    """netstat + tasklist 查端口占用（不做缓存）。"""
    proc = _run(["netstat", "-ano", "-p", "TCP"])
    if proc is None:
        return []
    pids = _parse_netstat(_decode(proc.stdout), port)
    if not pids:
        return []
    names = _tasklist_names()
    return [
        {"pid": pid, "name": names.get(pid, "?"), "addr": addr}
        for pid, addr in sorted(pids.items())
    ]


def port_owner(port: int) -> list[dict]:
    """谁在监听这个端口：[{"pid","name","addr"}]，3 秒缓存（GUI 会高频轮询）。"""
    port = int(port)
    now = time.monotonic()
    hit = _PORT_CACHE.get(port)
    if hit is not None and now - hit[0] < PORT_CACHE_TTL:
        return [dict(item) for item in hit[1]]
    owners = _query_port_owners(port)
    _PORT_CACHE[port] = (now, owners)
    return [dict(item) for item in owners]


def port_in_use(port: int) -> bool:
    """端口是否有监听者（含 0.0.0.0 通配绑定 —— 这正是与游戏/加速器抢 443 的典型现场）。"""
    return bool(port_owner(port))


def game_running() -> bool:
    """《Helldivers 2》是否在运行（进程名含 helldivers2，大小写不敏感）。"""
    try:
        names = _tasklist_names()
    except OSError:
        return False
    return any("helldivers2" in name.lower() for name in names.values())


def clear_caches() -> None:
    """清掉探测缓存（测试用；GUI 手动刷新时也可以调）。"""
    _PORT_CACHE.clear()


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
