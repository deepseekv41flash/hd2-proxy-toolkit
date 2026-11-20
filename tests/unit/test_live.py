"""战况快照（engine/live.py）+ CLI `live` 单测。

网络路径不在单测里真连：纯函数（摘要 / 靶星 / 落盘 / 文本）用 `data/samples/status.json`
当夹具；``fetch`` 用桩替换。真实网络拉取在 CLI/集成层验证（2026-11-20 已实拉成功）。
"""

import argparse
import json
from pathlib import Path

import pytest

from hd2proxy import __main__ as cli
from hd2proxy.engine import live

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "samples" / "status.json"


def _status():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _snap(status=None, gwe=None):
    status = status if status is not None else _status()
    gwe = gwe if gwe is not None else [{"id": 1}]
    return {
        "schema": 1, "host": live.DEFAULT_HOST, "ip": "1.2.3.4", "war_id": 801,
        "fetched_at": "2026-11-20T13:00:00+08:00", "elapsed": 0.1,
        "status": status, "gwe": gwe,
        "summary": live.summarize(status, gwe),
        "targets": live.campaign_targets(status),
    }


# ---------------------------------------------------------------- 纯函数

def test_summarize_sample():
    st = _status()
    s = live.summarize(st, [{"id": i} for i in range(5)])
    assert s["war_id"] == 801
    assert s["planets"] == len(st.get("planetStatus") or [])
    assert s["campaigns"] == len(st.get("campaigns") or [])
    assert s["gwe_effects"] == 5


def test_campaign_targets_carry_faction_and_skip_zero():
    st = _status()
    rows = live.campaign_targets(st)
    assert rows, "sample 里应该有至少一条战役"
    for r in rows:
        assert isinstance(r["index"], int) and r["index"] > 0
        assert r["faction"] in set(live.FACTION_NAMES.values())
    # 母星 0 不在 planetStatus 的战役里；即便被写进 campaigns 也不该被当成「人类」靶星推荐
    assert all(r["index"] != 0 for r in live.suggest_targets(st))


def test_suggest_targets_prefers_frontline_and_filters_faction():
    st = {
        "planetStatus": [{"index": 5, "owner": 2}, {"index": 6, "owner": 3},
                         {"index": 7, "owner": 1}],
        "campaigns": [{"planetIndex": 5, "id": 11}, {"planetIndex": 6, "id": 12},
                      {"planetIndex": 7, "id": 13}],
    }
    assert [r["index"] for r in live.suggest_targets(st, faction="terminid")] == [5]
    assert [r["index"] for r in live.suggest_targets(st, faction="automaton")] == [6]
    # 敌方前线优先（owner=1 的人类星排后面）
    rows = live.suggest_targets(st)
    assert [r["index"] for r in rows] == [5, 6, 7]
    # 该阵营没有战役时返回空，而不是硬塞别的阵营
    assert live.suggest_targets(st, faction="illuminate") == []
    assert live.suggest_targets(st, limit=1)[0]["index"] == 5


def test_annotate_and_format_text():
    st = {"planetStatus": [{"index": 269, "owner": 2}],
          "campaigns": [{"planetIndex": 269, "id": 51778}]}
    snap = {"host": "h", "ip": "1.2.3.4", "elapsed": 1.0, "fetched_at": "t",
            "summary": live.summarize(st, []), "status": st}
    rows = live.annotate(live.suggest_targets(st), {269: "BRILLIANCE"})
    assert rows[0]["name"] == "BRILLIANCE"
    text = live.format_text(snap)
    assert "BRILLIANCE" in text
    assert "SUPER EARTH" in text            # 提示里必须写明母星不显示
    assert "campaign=51778" in text


def test_save_snapshot(tmp_path):
    saved = live.save_snapshot(_snap(), tmp_path)
    assert set(saved["files"]) == {"status.json", "gwe.json", "meta.json"}
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["war_id"] == 801 and isinstance(meta["targets"], list)


# ---------------------------------------------------------------- 网络边界

def test_fetch_war_id_accepts_object_and_scalar(monkeypatch):
    monkeypatch.setattr(live, "https_get", lambda *a, **k: {"id": 801})
    assert live.fetch_war_id() == 801
    monkeypatch.setattr(live, "https_get", lambda *a, **k: 802)
    assert live.fetch_war_id() == 802
    monkeypatch.setattr(live, "https_get", lambda *a, **k: {"nope": 1})
    with pytest.raises(live.LiveError):
        live.fetch_war_id()


def test_resolve_host_raises_when_doh_fails(monkeypatch):
    monkeypatch.setattr(live.upstream, "doh_resolve", lambda host: None)
    with pytest.raises(live.LiveError, match="DoH"):
        live.resolve_host()


def test_planets_name_map_reads_catalog():
    names = live.planet_name_map()
    assert names.get(269) == "BRILLIANCE"
    assert names.get(0) == "SUPER EARTH"     # 索引里保留 0（标签解析用），只是不进选择器


# ---------------------------------------------------------------- CLI

def test_cli_live_json(monkeypatch, capsys):
    monkeypatch.setattr(live, "fetch", lambda *a, **k: _snap())
    code = cli.cmd_live(argparse.Namespace(war=0, host="", faction="all", limit=0,
                                           out="", timeout=5.0, json=True))
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["snapshot"]["war_id"] == 801
    assert out["targets"] and "name" in out["targets"][0]


def test_cli_live_text_and_save(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(live, "fetch", lambda *a, **k: _snap())
    out_dir = tmp_path / "live"
    code = cli.cmd_live(argparse.Namespace(war=0, host="", faction="terminid", limit=0,
                                           out=str(out_dir), timeout=5.0, json=False))
    assert code == 0
    text = capsys.readouterr().out
    assert "战况快照（无需游戏）" in text
    assert (out_dir / "status.json").exists()


def test_cli_live_reports_failure(monkeypatch, capsys):
    def boom(*a, **k):
        raise live.LiveError("DoH 解析失败")
    monkeypatch.setattr(live, "fetch", boom)
    code = cli.cmd_live(argparse.Namespace(war=0, host="", faction="all", limit=0,
                                           out="", timeout=5.0, json=False))
    assert code == cli.FAIL
    assert "拉取战况失败" in capsys.readouterr().out
