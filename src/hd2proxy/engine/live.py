"""战况快照：**不启动游戏**也能拉当前 Status / GWE，并推荐可点的靶星。

为什么能做：这几个端点在官方 API 上是**免登录的公共只读接口**（不需要 Steam 票据 /
sessionId）。2026-11-20 实测：直拉到的 `GalacticWarEffects` 与游戏内经过引擎抓包的
同一份数据 sha256 完全一致；`Status` 也是准实时。

关键技术点：
  * **必须 DoH 解析**：hosts 里把该域名指到了本机引擎，普通系统解析会自环；
  * 再用 **SNI = 域名 + 真实 IP** 直连（官方证书有效，正常校验，不跳过）；
  * 不发 `Accept-Encoding`（拿明文 JSON，省掉 gzip 分支作为主路径）；
  * 只读 GET、响应上限 8 MiB、默认 15 s 超时；失败一律抛 ``LiveError``（不吞）。

靶星规则（与实机结论一致，见 docs/ACCEPTANCE-M4.md §2.1/§7）：
  * 只有**有战役**的星球卡面才可点 —— 母星 SUPER EARTH(0) 与没有战役的星球都不显示效果；
  * 优先选「敌方占有（owner 2/3/4）+ 有战役」的前线星；可按阵营过滤。
"""

from __future__ import annotations

import gzip
import http.client
import json
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path

from . import paths, upstream

DEFAULT_HOST = "api.live.prod.thehelldiversgame.com"
MAX_BYTES = 8 << 20
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "hd2proxy-live/1"

# Status / campaigns 里的 owner 枚举（与 GUI 战况改写页一致：0 无主 1 人类 2 虫族 3 机器人 4 光能者）
FACTION_NAMES = {0: "无主", 1: "人类", 2: "虫族", 3: "机器人", 4: "光能者"}
FACTION_KEYS = {"human": 1, "terminid": 2, "automaton": 3, "illuminate": 4}
ENEMY_OWNERS = (2, 3, 4)


class LiveError(RuntimeError):
    """拉取失败（网络 / DoH / HTTP / JSON 任一环节）。"""


# --------------------------------------------------------------------------- #
# 网络：DoH + SNI 直连
# --------------------------------------------------------------------------- #
def resolve_host(host: str = DEFAULT_HOST) -> str:
    """DoH 解析真实 IP（绕过 hosts）。"""
    ip = upstream.doh_resolve(host)
    if not ip:
        raise LiveError("DoH 解析失败：%s（检查网络 / DoH 可用性）" % host)
    return ip


def https_get(host: str, path: str, *, ip: str | None = None,
              timeout: float = DEFAULT_TIMEOUT) -> object:
    """向 ``host`` 发一个只读 GET 并解析 JSON；``ip`` 可复用上一次解析结果。"""
    ip = ip or resolve_host(host)
    ctx = ssl.create_default_context()
    raw = None
    sock = None
    try:
        raw = socket.create_connection((ip, 443), timeout=timeout)
        sock = ctx.wrap_socket(raw, server_hostname=host)
        req = ("GET %s HTTP/1.1\r\n"
               "Host: %s\r\n"
               "Accept: application/json\r\n"
               "Accept-Language: en-US\r\n"
               "User-Agent: %s\r\n"
               "Connection: close\r\n\r\n" % (path, host, USER_AGENT))
        sock.sendall(req.encode("ascii"))
        resp = http.client.HTTPResponse(sock, method="GET")
        resp.begin()
        body = resp.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise LiveError("响应过大（> %d B）：%s" % (MAX_BYTES, path))
        if resp.status != 200:
            raise LiveError("HTTP %d：%s" % (resp.status, path))
        enc = (resp.getheader("Content-Encoding") or "").strip().lower()
        if enc == "gzip":
            body = gzip.decompress(body)
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError as e:
            raise LiveError("响应不是合法 JSON（%s）：%r" % (path, e)) from None
    except LiveError:
        raise
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        raise LiveError("请求 %s 失败：%r" % (path, e)) from None
    finally:
        for s in (sock, raw):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def fetch_war_id(host: str = DEFAULT_HOST, *, ip: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> int:
    doc = https_get(host, "/api/WarSeason/current/WarId", ip=ip, timeout=timeout)
    if isinstance(doc, dict):
        doc = doc.get("id") or doc.get("warId")
    if isinstance(doc, bool) or not isinstance(doc, (int, str)):
        raise LiveError("current/WarId 返回无法解析：%r" % (doc,))
    try:
        return int(doc)
    except (TypeError, ValueError):
        raise LiveError("current/WarId 返回无法解析：%r" % (doc,)) from None


# --------------------------------------------------------------------------- #
# 拉取 / 快照
# --------------------------------------------------------------------------- #
def fetch(war_id: int | None = None, *, host: str = DEFAULT_HOST,
          timeout: float = DEFAULT_TIMEOUT, ip: str | None = None) -> dict:
    """拉一份完整战况快照：{schema, host, ip, war_id, fetched_at, elapsed, status, gwe, summary, targets}。"""
    started = time.time()
    ip = ip or resolve_host(host)
    war = int(war_id) if war_id else fetch_war_id(host, ip=ip, timeout=timeout)
    status = https_get(host, "/api/WarSeason/%d/Status" % war, ip=ip, timeout=timeout)
    gwe = https_get(host, "/api/WarSeason/GalacticWarEffects", ip=ip, timeout=timeout)
    if not isinstance(status, dict):
        raise LiveError("Status 响应不是对象")
    if not isinstance(gwe, list):
        raise LiveError("GalacticWarEffects 响应不是数组")
    return {
        "schema": 1,
        "host": host,
        "ip": ip,
        "war_id": war,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "elapsed": round(time.time() - started, 3),
        "status": status,
        "gwe": gwe,
        "summary": summarize(status, gwe),
        "targets": campaign_targets(status),
    }


# --------------------------------------------------------------------------- #
# 纯函数：摘要 / 靶星（离线可测）
# --------------------------------------------------------------------------- #
def summarize(status: dict, gwe: list | None = None) -> dict:
    """战况计数摘要（纯函数）。"""
    st = status or {}

    def _n(key):
        v = st.get(key)
        return len(v) if isinstance(v, list) else 0

    return {
        "war_id": st.get("warId"),
        "status_time": st.get("time"),
        "planets": _n("planetStatus"),
        "campaigns": _n("campaigns"),
        "planet_effects": _n("planetActiveEffects"),
        "attacks": _n("planetAttacks"),
        "events": _n("planetEvents"),
        "gwe_effects": len(gwe) if isinstance(gwe, list) else 0,
    }


def campaign_targets(status: dict) -> list[dict]:
    """所有「有战役」的星球（= 卡面可点，能当靶星）。纯函数。

    返回 ``[{index, owner, faction, campaign_id, count}]``，按 (owner, index) 排序。
    """
    st = status or {}
    owners = {}
    for p in st.get("planetStatus") or []:
        if isinstance(p, dict) and p.get("index") is not None:
            owners[int(p["index"])] = p.get("owner")
    rows: list[dict] = []
    seen: set[int] = set()
    for c in st.get("campaigns") or []:
        if not isinstance(c, dict):
            continue
        try:
            idx = int(c.get("planetIndex"))
        except (TypeError, ValueError):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        owner = owners.get(idx)
        rows.append({
            "index": idx,
            "owner": owner,
            "faction": FACTION_NAMES.get(owner, "?"),
            "campaign_id": c.get("id"),
            "count": c.get("count"),
        })
    rows.sort(key=lambda r: (r["owner"] is None, r["owner"] if r["owner"] is not None else 99,
                             r["index"]))
    return rows


def suggest_targets(status: dict, faction: str | None = None,
                    limit: int | None = None) -> list[dict]:
    """推荐靶星：返回**所有有战役的星球**（卡面可点），前线（敌方占有）排前面；可过滤阵营。

    ``faction``：``terminid`` / ``automaton`` / ``illuminate`` / ``human`` / ``all`` / ``None``。
    返回顺序：先「敌方占有（owner 2/3/4）」，再按游戏索引升序 —— 前线通常是玩家想要的靶星，
    但人类星的防守战役也是可点的，不静默丢弃。
    """
    want = FACTION_KEYS.get((faction or "").strip().lower())
    rows = campaign_targets(status or {})
    if want is not None:
        rows = [r for r in rows if r.get("owner") == want]
    rows.sort(key=lambda r: (r.get("owner") not in ENEMY_OWNERS, r.get("index") or 0))
    return rows[:limit] if limit else rows


# --------------------------------------------------------------------------- #
# 名称 / 落盘 / 文本
# --------------------------------------------------------------------------- #
def planet_name_map() -> dict[int, str]:
    """游戏索引 -> 星球名（读 data/catalogs/planets.json；读不到就返回空表）。"""
    path = Path(paths.CATALOGS_DIR) / "planets.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = doc.get("items") if isinstance(doc, dict) else doc
    out: dict[int, str] = {}
    for p in rows or []:
        if not isinstance(p, dict):
            continue
        try:
            idx = int(p.get("game_index"))
        except (TypeError, ValueError):
            continue
        out[idx] = str(p.get("name") or "?")
    return out


def annotate(targets: list[dict], names: dict[int, str] | None = None) -> list[dict]:
    """给靶星行补上名字（不修改入参）。"""
    names = names if names is not None else planet_name_map()
    out = []
    for r in targets or []:
        row = dict(r)
        row["name"] = names.get(row.get("index")) or "?"
        out.append(row)
    return out


def save_snapshot(snapshot: dict, out_dir: str | Path) -> dict:
    """把快照落盘成 status.json / gwe.json / meta.json；返回写入清单。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, key in (("status.json", "status"), ("gwe.json", "gwe")):
        p = d / name
        p.write_text(json.dumps(snapshot.get(key), ensure_ascii=False), encoding="utf-8")
        files[name] = str(p)
    meta = {k: snapshot.get(k) for k in
            ("schema", "host", "ip", "war_id", "fetched_at", "elapsed", "summary")}
    meta["targets"] = annotate(snapshot.get("targets") or [])
    p = d / "meta.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    files["meta.json"] = str(p)
    return {"out_dir": str(d), "files": files}


def format_text(snapshot: dict, *, faction: str | None = None,
                limit: int | None = None) -> str:
    """人读文本（CLI 默认输出）。"""
    s = snapshot.get("summary") or {}
    lines = [
        "战况快照（无需游戏）",
        "  主机 %s · 出口 %s · 用时 %ss · %s" % (
            snapshot.get("host"), snapshot.get("ip"), snapshot.get("elapsed"),
            snapshot.get("fetched_at")),
        "  战局 war %s · status time %s" % (s.get("war_id"), s.get("status_time")),
        "  %s 星球 / %s 战役 / %s 个星球效果 / %s 条攻击边 / GWE %s 条" % (
            s.get("planets"), s.get("campaigns"), s.get("planet_effects"),
            s.get("attacks"), s.get("gwe_effects")),
    ]
    rows = annotate(suggest_targets(snapshot.get("status") or {}, faction=faction, limit=limit))
    if rows:
        lines.append("")
        lines.append("推荐靶星（有战役=卡面可点，按阵营）：")
        for r in rows:
            lines.append("  · %s %-18s index=%-3s campaign=%s" % (
                r.get("faction") or "?", (r.get("name") or "?")[:18],
                r.get("index"), r.get("campaign_id")))
    else:
        lines.append("")
        lines.append("推荐靶星：当前没有「有战役」的星球（换个 --faction 或看全量 targets）。")
    lines.append("")
    lines.append("提示：靶星必须卡面可点（有战役）；0 号 SUPER EARTH 母星永远不显示。")
    return "\n".join(lines)
