"""hosts 文件读写：只增删/替换本工具自己那一行。

为什么自己写而不装第三方库：项目约束是「只允许标准库」；hosts 是纯文本，按行处理足够。
下面几条都是现场踩过或必然踩到的坑，逐条兜住：

  1. **杀软 / 加速器会短暂锁住 hosts**：``os.replace`` 失败重试 12 次 × 300ms（合计约 3.6s），
     仍失败就明确报错，绝不留半截文件（先写同目录临时文件，成功后才替换）。
  2. **编码**：中文 Windows 的 hosts 可能是 ANSI(GBK)、也可能是带 BOM 的 UTF-8。
     读的时候探测，写回时用**原编码**（UTF-8 BOM 原样写回），绝不把中文注释写坏。
  3. **换行**：CRLF 文件改写后不能出现混行 —— 逐行保留原行尾；新行用文件里检测到的主流行尾。
  4. **不碰别人的行**：只增删/替换「带 marker」的行，其余行（含空行、注释、行尾空格）整行原样保留。

marker 约定：本工具写的那一行形如 ``<ip> <host> # hd2proxy``，靠行尾注释 ``# hd2proxy`` 认亲。
被 ``#`` 注释掉的同一行也算「本工具的行」（``commented=True``），这样安装/还原都能幂等处理
「用户手工注释过」「旧 IP 残留」这些现场状态。

对外接口见本文件末尾的函数；``find_marker`` 是纯函数（不碰文件系统），其余读写函数
都支持 ``path=None`` 走默认路径（``HD2PROXY_HOSTS_PATH`` 环境变量可覆盖，测试用）。
"""

import ipaddress
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# 本工具在 hosts 里写的注释标记（也是认亲的唯一依据）
MARKER = "# hd2proxy"
# 默认备份目录名（与 hosts 同目录；调用方可改到数据目录）
BACKUP_DIRNAME = ".hd2proxy-backups"
# 原子写重试策略：Windows 上 hosts 可能被杀软 / 加速器 / 系统备份短暂独占
WRITE_ATTEMPTS = 12
WRITE_RETRY_INTERVAL = 0.3          # 秒

_LINE_END_RE = re.compile(r"(\r\n|\n|\r)$")
_HOSTNAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
_LEADING_COMMENT_RE = re.compile(r"^[#\s]+")


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def hosts_path() -> Path:
    """返回 hosts 文件路径：``%SystemRoot%\\System32\\drivers\\etc\\hosts``。

    优先级：``HD2PROXY_HOSTS_PATH``（测试/便携模式）> ``%SystemRoot%``（或 ``%windir%``）
    > Windows API ``GetWindowsDirectoryW`` > POSIX ``/etc/hosts``。
    代码里不写死任何盘符（门禁规则），路径一律从环境变量推导。
    """
    override = os.environ.get("HD2PROXY_HOSTS_PATH")
    if override and override.strip():
        return Path(override.strip())
    root = os.environ.get("SystemRoot") or os.environ.get("windir")
    if root and root.strip():
        return Path(root.strip()) / "System32" / "drivers" / "etc" / "hosts"
    if os.name == "nt":
        try:                                    # 环境变量缺失时问系统要 Windows 目录
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            n = ctypes.windll.kernel32.GetWindowsDirectoryW(buf, 260)
            if n:
                return Path(buf.value) / "System32" / "drivers" / "etc" / "hosts"
        except Exception:                       # noqa: BLE001 - 兜底路径失败就报错
            pass
        raise OSError("无法确定 SystemRoot，也就找不到 hosts 文件（可设 HD2PROXY_HOSTS_PATH）")
    return Path("/etc/hosts")


# --------------------------------------------------------------------------- #
# 读取 / 解析
# --------------------------------------------------------------------------- #
@dataclass
class _HostsDoc:
    """一份 hosts 的内存快照：原始字节 + 解码文本 + 编码 + 行（内容, 行尾）列表。"""

    path: Path
    raw: bytes
    text: str
    encoding: str
    newline: str
    lines: list[tuple[str, str]]
    missing: bool = False


def _detect_encoding(raw: bytes) -> str:
    """探测 hosts 编码：UTF-8 BOM > UTF-8 > GBK > ANSI(mbcs) > latin-1。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ("utf-8", "gbk", "mbcs", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def _dominant_newline(raw: bytes) -> str:
    """主流行尾：有 CRLF 就用 CRLF；只有 LF 就用 LF；空文件按平台默认。"""
    if b"\r\n" in raw:
        return "\r\n"
    if b"\n" in raw:
        return "\n"
    if b"\r" in raw:
        return "\r"
    return "\r\n" if os.name == "nt" else "\n"


def _split_lines(text: str) -> list[tuple[str, str]]:
    """按行拆成 (内容, 行尾) 列表；行尾保持原样（CRLF/LF/CR 各自保留）。"""
    out: list[tuple[str, str]] = []
    for chunk in text.splitlines(keepends=True):
        m = _LINE_END_RE.search(chunk)
        if m:
            out.append((chunk[: m.start()], m.group(1)))
        else:
            out.append((chunk, ""))
    return out


def _join_lines(lines: list[tuple[str, str]]) -> str:
    return "".join(content + end for content, end in lines)


def _load(path: Path) -> _HostsDoc:
    """读一份 hosts 快照；文件不存在时返回空快照（missing=True）。"""
    p = Path(path)
    missing = False
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        raw, missing = b"", True
    encoding = _detect_encoding(raw)
    text = raw.decode(encoding)
    return _HostsDoc(
        path=p,
        raw=raw,
        text=text,
        encoding=encoding,
        newline=_dominant_newline(raw),
        lines=_split_lines(text),
        missing=missing,
    )


def read_hosts(path: Path | None = None) -> str:
    """读 hosts 文本（按探测到的编码解码）。文件不存在或读不了时返回空串。"""
    try:
        return _load(Path(path) if path is not None else hosts_path()).text
    except OSError:
        return ""


def _parse_marker_line(line: str, marker: str) -> dict | None:
    """解析单行：含 marker 则返回 {line, ip, host, commented}，否则 None。

    ``commented`` 的判定：marker 之前（映射部分）是空的、或第一个非空字符是 ``#``
    —— 即这一行整体被注释掉了。这样 ``# 127.0.0.1 host # hd2proxy`` 和
    孤零零的 ``# hd2proxy`` 都能被认出来。
    """
    idx = line.find(marker)
    if idx < 0:
        return None
    body = line[:idx].strip()
    commented = (body == "") or body.startswith("#")
    cleaned = _LEADING_COMMENT_RE.sub("", body)     # 去掉前面的 # 与空白（含 `# # ip host`）
    tokens = cleaned.split()
    ip: str | None = None
    host: str | None = None
    if tokens:
        try:
            ipaddress.IPv4Address(tokens[0])
            ip = tokens[0]
        except ValueError:
            if _HOSTNAME_RE.fullmatch(tokens[0]):
                host = tokens[0]
        if ip is not None and len(tokens) > 1:
            host = tokens[1]
    return {"line": line, "ip": ip, "host": host, "commented": commented}


def _marker_infos(text: str, marker: str) -> list[dict]:
    """返回文本里所有 marker 行的信息（1-based 行号，行内容不含行尾）。"""
    infos: list[dict] = []
    for line_no, (content, _end) in enumerate(_split_lines(text or ""), 1):
        info = _parse_marker_line(content, marker)
        if info is not None:
            info["line_no"] = line_no
            infos.append(info)
    return infos


def find_marker(text: str) -> dict | None:
    """在 hosts 文本里找本工具的标记行（纯函数，不碰文件系统）。

    返回 ``{"line_no": int(1-based), "line": str, "ip": str|None,
    "host": str|None, "commented": bool}``；没有则 ``None``。
    ``line`` 不含行尾；``commented=True`` 表示这一行的映射部分被 ``#`` 注释掉了。
    """
    infos = _marker_infos(text or "", MARKER)
    return infos[0] if infos else None


def count_marker(path: Path | None = None, marker: str = MARKER) -> int:
    """统计 hosts 里带 marker 的行数（含被注释的）；读不了算 0。"""
    try:
        text = _load(Path(path) if path is not None else hosts_path()).text
    except OSError:
        return 0
    return len(_marker_infos(text, marker))


# --------------------------------------------------------------------------- #
# 规划
# --------------------------------------------------------------------------- #
def _norm_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.IPv4Address((value or "").strip()))
    except ValueError:
        return None


def _plan_error(path: Path, new_line: str, marker: str, reason: str) -> dict:
    return {
        "action": "error",
        "path": str(path),
        "old_line": None,
        "new_line": new_line,
        "reason": reason,
        "marker": marker,
    }


def plan_edit(ip: str, host: str, path: Path | None = None, marker: str = MARKER) -> dict:
    """规划一次 hosts 改写（**只读文件，不写**）。

    返回 ``{"action": "add"|"replace"|"noop"|"error", "path": str, "old_line": str|None,
    "new_line": str, "reason": str}``。额外带一个 ``"marker"`` 键供 :func:`apply_edit`
    在自定义 marker 时复用（调用方按需忽略即可）。

    判定顺序：
      * 没有 marker 行                        -> ``add``（追加到末尾）
      * 有且仅有一行，被注释 / IP 或 host 不符 -> ``replace``
      * 有且仅有一行且映射正确               -> ``noop``
      * 多于一行（历史重复写入）             -> ``error``（需先清理，避免越写越乱）
    """
    target = Path(path) if path is not None else hosts_path()
    ip_s = "" if ip is None else str(ip).strip()
    host_s = "" if host is None else str(host).strip()
    new_line = "%s %s %s" % (ip_s, host_s, marker)
    if not marker or not marker.strip():
        return _plan_error(target, new_line, marker, "marker 为空，拒绝操作")
    canonical = _norm_ip(ip_s)
    if canonical is None:
        return _plan_error(target, new_line, marker,
                           "IP 不合法：%r（只接受 IPv4 字面量，如 192.168.1.50）" % (ip_s,))
    if not host_s or any(ch.isspace() for ch in host_s) or host_s.startswith("#"):
        return _plan_error(target, new_line, marker,
                           "host 不合法：%r（不能为空、不能含空白、不能以 # 开头）" % (host_s,))
    new_line = "%s %s %s" % (canonical, host_s, marker)

    text = read_hosts(target)
    infos = _marker_infos(text, marker)
    if not infos:
        return {
            "action": "add",
            "path": str(target),
            "old_line": None,
            "new_line": new_line,
            "reason": "hosts 里没有 %s 标记行 -> 追加到文件末尾" % marker,
            "marker": marker,
        }
    if len(infos) > 1:
        return _plan_error(
            target, new_line, marker,
            "hosts 里有 %d 行 %s 标记（行号：%s）—— 可能是历史重复写入，"
            "请先手工清理，或先跑一次 uninstall 再装"
            % (len(infos), marker, "、".join(str(x["line_no"]) for x in infos)),
        )
    info = infos[0]
    base = {
        "path": str(target),
        "old_line": info["line"],
        "new_line": new_line,
        "marker": marker,
    }
    if info["commented"]:
        base.update(action="replace",
                    reason="第 %d 行的标记被注释掉了（%r）-> 替换为有效映射"
                           % (info["line_no"], info["line"]))
        return base
    cur_ip = _norm_ip(info["ip"])
    cur_host = info["host"] or ""
    if cur_ip == canonical and cur_host == host_s:
        base.update(action="noop",
                    reason="第 %d 行已是目标映射（%r）-> 无需改动"
                           % (info["line_no"], info["line"]))
        return base
    base.update(action="replace",
                reason="第 %d 行当前是 %r -> 替换为 %r"
                       % (info["line_no"], info["line"], new_line))
    return base


def _effective_action(text: str, marker: str, new_line: str) -> str:
    """以磁盘上的**当前**内容为准，重新推导要做什么（自愈：计划后被别人改过也不写错）。"""
    parts = new_line.split()
    exp_ip = _norm_ip(parts[0]) if parts else None
    exp_host = parts[1] if len(parts) > 1 else ""
    infos = _marker_infos(text, marker)
    if not infos:
        return "add"
    if len(infos) > 1:
        return "error"
    info = infos[0]
    if info["commented"]:
        return "replace"
    if _norm_ip(info["ip"]) == exp_ip and (info["host"] or "") == exp_host:
        return "noop"
    return "replace"


# --------------------------------------------------------------------------- #
# 写入（原子 + 重试 + 备份）
# --------------------------------------------------------------------------- #
def _replace_file(src: str, dst: str) -> None:
    """单独抽出来，方便测试注入「替换失败」的故障。"""
    os.replace(src, dst)


def _write_atomic(target: Path, data: bytes) -> str | None:
    """同目录临时文件 -> os.replace；失败重试。成功返回 None，失败返回错误说明。

    为什么必须同目录：``os.replace`` 只在同一卷内保证原子；跨卷会退化成拷贝。
    """
    target = Path(target)
    if not target.parent.is_dir():
        return "目录不存在：%s" % target.parent
    last: BaseException | None = None
    for attempt in range(1, WRITE_ATTEMPTS + 1):
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix="." + target.name + ".",
                suffix=".hd2proxy.tmp",
                dir=str(target.parent),
            )
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            _replace_file(tmp_name, str(target))
            return None
        except OSError as e:
            last = e
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
            if attempt < WRITE_ATTEMPTS:
                time.sleep(WRITE_RETRY_INTERVAL)
    return "写入 %s 失败（已重试 %d 次，间隔 %.0f ms）：%r" % (
        target, WRITE_ATTEMPTS, WRITE_RETRY_INTERVAL * 1000, last)


def _backup(path: Path, raw: bytes, backup_dir: Path | None) -> tuple[Path | None, str | None]:
    """把改前的原始字节备份一份；返回 (备份路径, 错误说明)。"""
    target_dir = Path(backup_dir) if backup_dir is not None else (Path(path).parent / BACKUP_DIRNAME)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return None, "无法创建备份目录 %s：%r" % (target_dir, e)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base_name = Path(path).name or "hosts"
    candidate = target_dir / ("%s.%s.bak" % (base_name, stamp))
    n = 1
    while candidate.exists():
        candidate = target_dir / ("%s.%s-%d.bak" % (base_name, stamp, n))
        n += 1
    err = _write_atomic(candidate, raw)
    if err:
        return None, err
    return candidate, None


def _append_line(doc: _HostsDoc, new_line: str) -> list[tuple[str, str]]:
    """在末尾追加一行；原文件末行没有换行时先给它补上，避免两行粘一起。"""
    lines = list(doc.lines)
    nl = doc.newline
    if not lines:
        return [(new_line, "")]
    last_content, last_end = lines[-1]
    if last_end == "":
        # 原文件末尾没有换行：补一个主流换行，新加的这行保持「文件末尾无换行」的风格
        lines[-1] = (last_content, nl)
        lines.append((new_line, ""))
    else:
        lines.append((new_line, nl))
    return lines


def _replace_marker_line(doc: _HostsDoc, marker: str, new_line: str) -> list[tuple[str, str]]:
    """替换第一行 marker 行的内容，保留它原来的行尾（CRLF 不会被改成 LF）。"""
    lines = list(doc.lines)
    for i, (content, end) in enumerate(lines):
        if marker in content:
            lines[i] = (new_line, end)
            break
    return lines


def apply_edit(plan: dict, *, backup_dir: Path | None = None) -> dict:
    """执行 :func:`plan_edit` 的结果：原子写 + 首次改动前备份 + 重试。

    返回 ``{"ok": bool, "backup": str|None, "error": str|None}``。

    注意：真正写之前会**重读磁盘**再判一次（自愈），所以即使文件在 plan 之后被
    别人改过，也不会写坏内容；plan 是 ``error`` 状态时直接拒绝。
    """
    if not isinstance(plan, dict):
        return {"ok": False, "backup": None, "error": "plan 必须是 dict"}
    if plan.get("action") == "error":
        return {"ok": False, "backup": None,
                "error": str(plan.get("reason") or "plan 处于 error 状态")}
    new_line = str(plan.get("new_line") or "").strip()
    if not new_line:
        return {"ok": False, "backup": None, "error": "plan 缺少 new_line"}
    marker = str(plan.get("marker") or MARKER)
    target = Path(str(plan.get("path") or hosts_path()))
    try:
        doc = _load(target)
    except OSError as e:
        return {"ok": False, "backup": None, "error": "读取 hosts 失败：%r" % (e,)}

    action = _effective_action(doc.text, marker, new_line)
    if action == "error":
        return {"ok": False, "backup": None,
                "error": "hosts 里有多行 %s 标记，请先清理后再装" % marker}
    if action == "noop":
        return {"ok": True, "backup": None, "error": None}

    lines = _append_line(doc, new_line) if action == "add" else _replace_marker_line(
        doc, marker, new_line)
    backup_path: Path | None = None
    if not doc.missing:
        backup_path, backup_err = _backup(target, doc.raw, backup_dir)
        if backup_err:
            return {"ok": False, "backup": None, "error": "备份 hosts 失败：%s" % backup_err}
    try:
        data = _join_lines(lines).encode(doc.encoding)
    except UnicodeEncodeError as e:
        return {"ok": False, "backup": str(backup_path) if backup_path else None,
                "error": "按原编码 %s 写回失败：%r" % (doc.encoding, e)}

    err = _write_atomic(target, data)
    if err:
        return {"ok": False, "backup": str(backup_path) if backup_path else None, "error": err}
    try:
        check = _load(target).text
        if _effective_action(check, marker, new_line) != "noop":
            return {"ok": False, "backup": str(backup_path) if backup_path else None,
                    "error": "写入后回读校验失败（hosts 可能被杀软/加速器改回）"}
    except OSError as e:
        return {"ok": False, "backup": str(backup_path) if backup_path else None,
                "error": "写入后回读失败：%r" % (e,)}
    return {"ok": True, "backup": str(backup_path) if backup_path else None, "error": None}


def remove_marker(path: Path | None = None, marker: str = MARKER, *,
                  backup_dir: Path | None = None) -> dict:
    """删除所有带 marker 的行（含被注释的），返回 ``{"ok","removed","error"}``。

    只删本工具的行；其余行（空行、注释、别人写的映射、行尾空格）逐字节保留原样。
    没有可删的行时不做任何写入、也不产生备份。
    """
    if not marker or not marker.strip():
        return {"ok": False, "removed": 0, "error": "marker 为空，拒绝操作"}
    target = Path(path) if path is not None else hosts_path()
    try:
        doc = _load(target)
    except OSError as e:
        return {"ok": False, "removed": 0, "error": "读取 hosts 失败：%r" % (e,)}
    kept: list[tuple[str, str]] = []
    removed = 0
    for content, end in doc.lines:
        if marker in content:
            removed += 1
            continue
        kept.append((content, end))
    if removed == 0:
        return {"ok": True, "removed": 0, "error": None}

    backup_path: Path | None = None
    if not doc.missing:
        backup_path, backup_err = _backup(target, doc.raw, backup_dir)
        if backup_err:
            return {"ok": False, "removed": 0, "error": "备份 hosts 失败：%s" % backup_err}
    try:
        data = _join_lines(kept).encode(doc.encoding)
    except UnicodeEncodeError as e:
        return {"ok": False, "removed": 0, "error": "按原编码 %s 写回失败：%r" % (doc.encoding, e)}
    err = _write_atomic(target, data)
    if err:
        return {"ok": False, "removed": 0, "error": err}
    try:
        if marker in _load(target).text:
            return {"ok": False, "removed": removed,
                    "error": "写入后回读校验失败：hosts 里仍有 marker 行"}
    except OSError as e:
        return {"ok": False, "removed": removed, "error": "写入后回读失败：%r" % (e,)}
    return {"ok": True, "removed": removed, "error": None}
