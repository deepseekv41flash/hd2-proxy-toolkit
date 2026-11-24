"""结算事件流 `settlements.jsonl`（契约形态 3，v0.9.0-alpha.1）。

口径来源：研究线 2026-11-24（样例 PASS 9/9 + 六条确认）：
  * 每玩家 `players/<steamId64>/settlements.jsonl`，append-only、UTF-8/LF/无 BOM、一行一对象（紧凑）；
  * 必填 11 字段 + `source`（mission_end / ledger-only）；`itemSource` 限定枚举 rewards|badges|both|none；
  * `ts` 必须带显式时区；`packages` 是**结算后绝对值** + `platformAccountId`=本玩家；
  * 按 `(saveId, missionId)`（该玩家文件内）去重，重复导出幂等；
  * manifest 带 `settlements{ledgerOnly}` 与 `settlementsCursor{lines,lastMissionId,lastTs}`。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import save_export as sx, saves

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "data" / "fixtures" / "saves"
STEAM = "76561198968648344"
HD2 = "11893343864225233967"
SAVE_ID = "steam_" + STEAM
REQUIRED = ("schema", "event", "ts", "saveId", "steamId64", "hd2AccountId",
            "missionId", "experience", "items", "packages", "catalogBuild", "source")


def make_ledger(*, mission_id="m-1", exp=936, items=None, packages=None, at="2026-11-24T13:39:43",
                raw=True, item_source="rewards"):
    doc = saves.empty_save(SAVE_ID)
    doc["catalog_build"] = "93e7575a/3021/1007203"
    doc["identity"] = {"hd2_account_id": HD2, "steam_id": STEAM,
                       "source": "getmotd", "identified_at": "2026-11-23T18:16:18"}
    e = doc["earned"]
    e["missions"] = {
        "count": 1, "recent_ids": [mission_id],
        "last": {"at": at, "experience": exp,
                 "items": dict(items or {"897894480": 7, "3608481516": 4434}),
                 "item_source": item_source,
                 "packages": dict(packages or {"277818845": {"level": 5, "progress": 459}}),
                 "mission": {"operation_id": 1242, "mission_index": 2, "mission_id": mission_id}},
    }
    if raw:
        e["missions"]["last_response"] = {"experience": exp, "missionId": mission_id}
        e["missions"]["last_response_at"] = at
    return doc


def export(tmp_path, ledger, *, optional=True, name="root"):
    root = tmp_path / name
    res = sx.export_player(ledger, baseline_dir=str(FIXTURES / "fresh"),
                           data_root=str(root), version="test", include_optional=optional)
    return res, root / "players" / STEAM


def read_lines(p):
    """只返回可解析的合法行（消费端容忍坏行的同款行为）。"""
    out = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- 字段与语义


def test_settlement_event_mission_end_fields(tmp_path):
    _res, pdir = export(tmp_path, make_ledger())
    lines = read_lines(pdir / "settlements.jsonl")
    assert len(lines) == 1
    ev = lines[0]
    for key in REQUIRED:
        assert key in ev, key
    assert ev["schema"] == 1 and ev["event"] == "settlement"
    assert ev["saveId"] == SAVE_ID and ev["steamId64"] == STEAM and ev["hd2AccountId"] == HD2
    assert ev["missionId"] == "m-1" and ev["experience"] == 936
    assert ev["items"] == {"897894480": 7, "3608481516": 4434}
    assert ev["packages"] == {"277818845": {"platformAccountId": HD2, "level": 5, "progress": 459}}
    assert ev["itemSource"] == "rewards" and ev["source"] == "mission_end"
    assert ev["ts"] == "2026-11-24T13:39:43+08:00"        # 显式时区


def test_settlement_event_ledger_only_variant(tmp_path):
    ledger = make_ledger(raw=False, mission_id="old-1", at="2026-11-23T18:21:39")
    _res, pdir = export(tmp_path, ledger)
    ev = read_lines(pdir / "settlements.jsonl")[0]
    assert ev["source"] == "ledger-only"
    assert ev["packages"] == {}                              # 老局无原始响应 → 空
    assert ev["missionIndex"] == 2 and ev["experience"] == 936
    assert ev["ts"] == "2026-11-23T18:21:39+08:00"


def test_item_source_limited_enum(tmp_path):
    _res, pdir = export(tmp_path, make_ledger(item_source="whatever"))
    assert read_lines(pdir / "settlements.jsonl")[0]["itemSource"] == "none"


# ---------------------------------------------------------------- 追加 / 去重 / 游标


def test_repeated_export_is_idempotent(tmp_path):
    ledger = make_ledger()
    export(tmp_path, ledger)
    res, pdir = export(tmp_path, ledger)
    assert len(read_lines(pdir / "settlements.jsonl")) == 1
    assert res["settlements"]["appended"] == 0 and res["settlements"]["skipped"] is True
    m = res["manifest"]
    assert m["settlementsCursor"]["lines"] == 1
    assert m["settlementsCursor"]["lastMissionId"] == "m-1"
    assert m["settlementsCursor"]["lastTs"].endswith("+08:00")


def test_new_mission_appends_and_cursor_moves(tmp_path):
    export(tmp_path, make_ledger(mission_id="m-1", at="2026-11-24T13:39:43"))
    ledger2 = make_ledger(mission_id="m-2", at="2026-11-24T14:10:00", exp=500)
    res, pdir = export(tmp_path, ledger2)
    lines = read_lines(pdir / "settlements.jsonl")
    assert [x["missionId"] for x in lines] == ["m-1", "m-2"]
    assert res["manifest"]["settlementsCursor"]["lines"] == 2
    assert res["manifest"]["settlementsCursor"]["lastMissionId"] == "m-2"


def test_manifest_counts_ledger_only(tmp_path):
    _res, pdir = export(tmp_path, make_ledger(raw=False, mission_id="old-1"))
    m = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    assert m["settlements"] == {"ledgerOnly": 1}
    assert m["settlementsCursor"]["lastMissionId"] == "old-1"


def test_no_optional_disables_settlements(tmp_path):
    res, pdir = export(tmp_path, make_ledger(), optional=False)
    assert not (pdir / "settlements.jsonl").exists()
    m = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    assert "settlements" not in m and "settlementsCursor" not in m
    assert "settlements.jsonl" not in res["files"]


# ---------------------------------------------------------------- 文件格式 / 容错


def test_jsonl_compact_utf8_lf_no_bom(tmp_path):
    _res, pdir = export(tmp_path, make_ledger())
    raw = (pdir / "settlements.jsonl").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")               # 无 BOM
    assert b"\r\n" not in raw                                # LF
    assert raw.endswith(b"\n")
    text = raw.decode("utf-8")
    line = text.strip()
    assert line.count("\n") == 0
    assert ", " not in line                                  # 紧凑分隔符（",": 无空格）


def test_bad_line_tolerated_and_append_survives(tmp_path):
    """已有坏行/半截行：不删、可继续追加；游标只数合法行。"""
    ledger = make_ledger(mission_id="m-1")
    _res, pdir = export(tmp_path, ledger)
    p = pdir / "settlements.jsonl"
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{bad json\n")                              # 坏行
        fh.write('{"partial":')                              # 半截行（无换行）
    ledger2 = make_ledger(mission_id="m-2", at="2026-11-24T15:00:00")
    res, _ = export(tmp_path, ledger2)
    text = p.read_text(encoding="utf-8")
    assert "{bad json" in text                              # 不改写历史行
    valid = read_lines(p)
    assert [x["missionId"] for x in valid] == ["m-1", "m-2"]
    assert res["manifest"]["settlementsCursor"]["lines"] == 2


# ---------------------------------------------------------------- 不变量


def test_invariant_mission_end_platform_account_matches_identity(tmp_path):
    """研究线建议的不变量：任何导出路径的 mission_end.json 元素 platformAccountId == 玩家 identity。"""
    ledger = make_ledger()
    foreign = json.loads((FIXTURES / "mission_end" / "12b9a872.json").read_text(encoding="utf-8"))
    ledger["earned"]["missions"]["last_response"] = foreign
    for row in foreign.get("progressionPackageUpdates") or []:
        row["platformAccountId"] = "76561190000000000"       # 别人的/占位
    _res, pdir = export(tmp_path, ledger)
    doc = json.loads((pdir / "mission_end.json").read_text(encoding="utf-8"))
    for row in doc.get("progressionPackageUpdates") or []:
        assert row.get("platformAccountId") == HD2
    # 事件流里的 packages 也必须一致
    ev = read_lines(pdir / "settlements.jsonl")[0]
    for _id32, row in ev["packages"].items():
        assert row["platformAccountId"] == HD2
