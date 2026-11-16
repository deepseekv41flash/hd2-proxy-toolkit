"""Status 响应的结构化改写（M1 从 legacy_proxy.py 抽出）。

`apply_extra(doc, spec)` 是研究线 `HD2_GWE_EXTRA` 的全 schema 实现，键：
campaigns / attacks / events / globalEffects / regions / planet_nodes / planet_effects / owner。
所有键都做去重（重复执行安全），异常一律吞掉并记一行日志，返回改动条数。
"""

import json
import os

from ..logutil import log, log_throttled


def load_spec():
    """旧行为：从环境变量 HD2_GWE_EXTRA 读结构化 spec（JSON 字符串）。空 = 不启用。"""
    return (os.environ.get("HD2_GWE_EXTRA") or "").strip()


def apply_extra(doc, spec=None):
    """按环境变量 HD2_GWE_EXTRA 对 Status 做额外改写：追加战役 / 改星球归属。

    格式（JSON 字符串）：
        {"campaigns": [{"planet": 139, "id": 51999, "type": 0, "count": 1, "race": 1}],
         "owner":     {"139": 1}}

    只动目标条目，不删不改其它星球；异常一律吞掉并记一行日志。
    返回改动条数（0 = 没动，调用方据此决定要不要重发 body）。
    """
    if spec is None:
        spec = load_spec()
    if not spec:
        return 0
    if isinstance(spec, str):
        try:
            cfg = json.loads(spec)
        except Exception as e:
            log_throttled("extra-json", "gwe-extra: 解析失败 %r" % e, every=600)
            return 0
    else:
        cfg = spec
    if not isinstance(cfg, dict):
        return 0
    changed = 0
    camps = doc.get("campaigns")
    if isinstance(camps, list):
        for c in cfg.get("campaigns") or []:
            try:
                pidx = int(c.get("planet"))
            except (TypeError, ValueError):
                continue
            if any(isinstance(x, dict) and x.get("planetIndex") == pidx for x in camps):
                log_throttled("extra-camp-dup", "gwe-extra: 星球 %d 已有战役，跳过" % pidx, every=3600)
                continue
            entry = {
                "id": int(c.get("id") or 51999),
                "planetIndex": pidx,
                "type": int(c.get("type") or 0),
                "count": int(c.get("count") or 1),
                "race": int(c.get("race") if c.get("race") is not None else 1),
            }
            camps.append(entry)
            changed += 1
            log("REWRITE-EXTRA 追加战役 %s" % json.dumps(entry))
    # 追加攻击边：{source, target}。线上 63 条全是「人类星球 -> 敌星」，
    # 防守如果要成立，很可能需要「敌星 -> 我方星球」这个反向边。
    atk = doc.get("planetAttacks")
    if isinstance(atk, list):
        for a in cfg.get("attacks") or []:
            try:
                src, dst = int(a.get("source")), int(a.get("target"))
            except (TypeError, ValueError):
                continue
            if any(isinstance(x, dict) and x.get("source") == src and x.get("target") == dst
                   for x in atk):
                log_throttled("extra-atk-dup",
                              "gwe-extra: 攻击边 %d->%d 已存在，跳过" % (src, dst), every=3600)
                continue
            atk.append({"source": src, "target": dst})
            changed += 1
            log("REWRITE-EXTRA 追加攻击边 %d -> %d" % (src, dst))
    # 追加星球事件（限时战役）：eventType 1=防守 / 2=进攻（源自社区 API 模型 PlanetEvent）。
    # startTime/expireTime 与 Status.time 同一时钟，这里用 startOffset/endOffset 相对算，
    # 免得手写绝对值写错。
    ev = doc.get("planetEvents")
    if isinstance(ev, list):
        now = int(doc.get("time") or 0)
        # 本 spec 里注入的 campaign：{planetIndex: id}，给事件当 campaignId 兜底
        _camp_id_of = {}
        for _c in cfg.get("campaigns") or []:
            try:
                _camp_id_of[int(_c.get("planet"))] = int(_c.get("id"))
            except (TypeError, ValueError):
                continue
        for e in cfg.get("events") or []:
            try:
                pidx = int(e.get("planet"))
            except (TypeError, ValueError):
                continue
            et = int(e.get("eventType") or 1)
            if any(isinstance(x, dict) and x.get("planetIndex") == pidx
                   and x.get("eventType") == et for x in ev):
                log_throttled("extra-ev-dup", "gwe-extra: 星球 %d 已有 eventType=%d 事件，跳过"
                              % (pidx, et), every=3600)
                continue
            entry = {
                "id": int(e.get("id") or 9001),
                "planetIndex": pidx,
                "eventType": et,
                "race": int(e.get("race") or 1),
                "health": int(e.get("health") or 1000000),
                "maxHealth": int(e.get("maxHealth") or 1000000),
                "startTime": now + int(e.get("startOffset") or -60),
                "expireTime": now + int(e.get("endOffset") or 86400),
                "campaignId": int(e.get("campaignId") or _camp_id_of.get(pidx) or 0),
                # 真实样本里这里是 [事件自己的 id]，不是空数组；空数组会让客户端解析失败
                "jointOperationIds": [int(e.get("id") or 9001)],
                # 真实样本里有这一格（值 0），缺了客户端可能不认这条事件
                "potentialBuildUp": int(e.get("potentialBuildUp") or 0),
            }
            ev.append(entry)
            changed += 1
            log("REWRITE-EXTRA 追加星球事件 %s" % json.dumps(entry))
            # 配套的 jointOperations 条目：真实样本里每个 planetEvent 都有一条同 id 记录
            jo = doc.get("jointOperations")
            eid = entry["id"]
            if isinstance(jo, list) and not any(isinstance(x, dict) and x.get("id") == eid
                                                for x in jo):
                jo.append({
                    "id": eid,
                    "planetIndex": pidx,
                    "hqNodeIndex": int(e.get("hqNodeIndex") or 1),
                })
                changed += 1
                log("REWRITE-EXTRA 追加联合作战 id=%d planet=%d" % (eid, pidx))
    # 全局事件效果：{eventId: [effectId...]}。globalEvents[].effectIds 是"全局效果"通道
    # （武器实验就是这么挂的），不依赖星球。
    ge = doc.get("globalEvents")
    if isinstance(ge, list):
        for ev in ge:
            if not isinstance(ev, dict):
                continue
            key = str(ev.get("eventId"))
            for eid in (cfg.get("globalEffects") or {}).get(key) or []:
                ids = ev.get("effectIds")
                if not isinstance(ids, list):
                    ids = ev["effectIds"] = []
                if int(eid) not in ids:
                    ids.append(int(eid))
                    changed += 1
                    log("REWRITE-EXTRA 全局事件 %s += effect %d" % (key, int(eid)))
# DSH-CITY-REGIONS-V1
    # 分区状态：按原生 WarInfo 定义补齐缺失的 (planetIndex, regionIndex)。
    # 现有同编号条目一律保留（社区文档 §3.2：只补缺失）。
    regs = doc.get("planetRegions")
    if isinstance(regs, list):
        have = {(r.get("planetIndex"), r.get("regionIndex"))
                for r in regs if isinstance(r, dict)}
        for rg in cfg.get("regions") or []:
            try:
                pidx = int(rg.get("planet"))
                ridx = int(rg.get("regionIndex"))
                maxhp = int(rg.get("maxHealth"))
                own = int(rg.get("owner"))
            except (TypeError, ValueError):
                continue
            if (pidx, ridx) in have:
                continue
            entry = {
                "planetIndex": pidx,
                "regionIndex": ridx,
                "owner": own,
                "health": maxhp // 2,
                "players": 0,
                "regerPerSecond": 0,
                "isAvailable": True,
                "availabilityFactor": 1,
            }
            regs.append(entry)
            have.add((pidx, ridx))
            changed += 1
            log("REWRITE-EXTRA 补分区状态 %s" % json.dumps(entry))
    # DSH-PLANET-NODE-V1
    # 追加星球节点：休眠星（本地 planet_data 有、Status 里没有）星图上连节点都不会画，
    # 必须先补一条 planetStatus（坐标 position 只能由 Status 提供），再追加 campaigns。
    # 格式：{"planet_nodes": [{"index":300,"owner":1,"health":1000000,
    #                          "regenPerSecond":4.1666665,"players":0,"position":{"x":0.3,"y":-0.55}}]}
    ps = doc.get("planetStatus")
    if isinstance(ps, list):
        have_ix = {r.get("index") for r in ps if isinstance(r, dict)}
        for n in cfg.get("planet_nodes") or []:
            try:
                nidx = int(n.get("index"))
            except (TypeError, ValueError):
                continue
            if nidx in have_ix:
                log_throttled("extra-node-dup",
                              "gwe-extra: 星球 %d 已有节点，跳过" % nidx, every=3600)
                continue
            pos = n.get("position") or {}
            entry = {
                "index": nidx,
                "owner": int(n.get("owner") if n.get("owner") is not None else 1),
                "health": int(n.get("health") or 1000000),
                "regenPerSecond": float(n.get("regenPerSecond")
                                        if n.get("regenPerSecond") is not None else 4.1666665),
                "players": int(n.get("players") or 0),
                "position": {"x": float(pos.get("x") or 0.0), "y": float(pos.get("y") or 0.0)},
            }
            ps.append(entry)
            have_ix.add(nidx)
            changed += 1
            log("REWRITE-EXTRA 追加星球节点 %s" % json.dumps(entry))
    # DS H-PLANET-EFFECTS-V1：直接往 planetActiveEffects 追加（绕过阵营过滤）。
    # 用途：把 terminid 词条挂到人类星（如 TERREK = 76，正被虫族防守事件 5743 攻击）上做实验。
    # 格式：{"planet_effects": [{"index": 76, "ids": [1243, 1245]}]}
    pe = doc.get("planetActiveEffects")
    if isinstance(pe, list):
        have_pe = {(e.get("index"), e.get("galacticEffectId")) for e in pe if isinstance(e, dict)}
        for item in cfg.get("planet_effects") or []:
            if not isinstance(item, dict):
                continue
            try:
                pidx = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            for raw_eid in item.get("ids") or []:
                try:
                    eid = int(raw_eid)
                except (TypeError, ValueError):
                    continue
                if (pidx, eid) in have_pe:
                    continue
                pe.append({"index": pidx, "galacticEffectId": eid})
                have_pe.add((pidx, eid))
                changed += 1
                log("REWRITE-EXTRA 星球 %d += effect %d（raw，绕阵营过滤）" % (pidx, eid))
    for k, v in (cfg.get("owner") or {}).items():
        for r in doc.get("planetStatus") or []:
            if not isinstance(r, dict):
                continue
            if str(r.get("index")) == str(k):
                try:
                    nv = int(v)
                except (TypeError, ValueError):
                    continue
                if r.get("owner") != nv:
                    log("REWRITE-EXTRA 星球 %s owner %s -> %s" % (k, r.get("owner"), nv))
                    r["owner"] = nv
                    changed += 1
                break
    return changed
