"""自建服导出（v0.7.0-alpha.1）单测：shape 保真 / 合并值 / manifest / 幂等 / 原子写 / CLI。

全部离线：基线用产品仓自带 fixtures（`data/fixtures/saves/{main,fresh}`），账本在内存里造。
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


def _main_stats():
    return json.loads((FIXTURES / "main" / "stats_profile.json").read_text(encoding="utf-8"))


def make_ledger(*, steam=STEAM, hd2=HD2, exp=210, with_identity=True):
    """造一份「打完一局」的账本（数值接近 2026-11-23 实机验收）。"""
    sid = saves.save_id_for(steam) if steam else "local"
    doc = saves.empty_save(sid)
    doc["catalog_build"] = "93e7575a/3021/1007203"
    if with_identity:
        doc["identity"] = {"hd2_account_id": hd2, "steam_id": steam,
                           "source": "getmotd", "identified_at": "2026-11-23T18:16:18"}
    e = doc["earned"]
    e["experience"] = exp
    e["achievements"] = {"6": 1680, "8": 386242, "17": 4290, "24": 2925}
    e["inventory_amounts"] = {"897894480": 1, "3608481516": 910}
    e["stats"] = {"profile": _main_stats()}
    e["missions"] = {"count": 2, "recent_ids": ["m-1", "m-2"],
                     "last": {"at": "2026-11-23T18:21:39", "experience": 210,
                              "items": dict(e["inventory_amounts"]),
                              "item_source": "rewards", "packages": {},
                              "mission": {"mission_id": "m-2", "operation_id": 1284}}}
    return doc


def _export(tmp_path, ledger, *, baseline="fresh", version="test-1.0", include_optional=True,
            name="root"):
    root = tmp_path / name
    res = sx.export_player(ledger, baseline_dir=str(FIXTURES / baseline),
                           data_root=str(root), version=version,
                           include_optional=include_optional)
    return res, root


# ---------------------------------------------------------------- 合并结果


def test_export_merges_progression_inventory_stats(tmp_path):
    """① ② ③：空号基线 + 账本 → exp 210 / 成就 4 条 / 库存补行 / 统计 23 非零。"""
    res, root = _export(tmp_path, make_ledger())
    pdir = root / "players" / STEAM
    assert res["ok"] is True and res["playerKey"] == STEAM

    prog = json.loads((pdir / "progression.json").read_text(encoding="utf-8"))
    assert prog["experience"] == 210
    assert {a["id"]: a["value"] for a in prog["achievements"]} == {6: 1680, 8: 386242,
                                                                   17: 4290, 24: 2925}
    assert len(prog["packageProgress"]) == 9          # 账本无包进度 → 保持基线值

    inv = json.loads((pdir / "inventory.json").read_text(encoding="utf-8"))
    amounts = {r["mixId"]: r["amount"] for r in inv["items"]}
    assert amounts[897894480] == 1
    assert amounts[3608481516] == 1000                # 基线 1000 > 账本 910 → 听服务端
    assert len(inv["items"]) == 56                    # 55 行 + 补 1 行

    stats = json.loads((pdir / "stats_profile.json").read_text(encoding="utf-8"))
    nonzero = {k: v for k, v in stats.items() if isinstance(v, (int, float)) and v}
    assert len(nonzero) == 23 and stats["totalEnemyKills"] == 356065  # 夹具基线值


def test_shape_fidelity_is_baseline_deepcopy(tmp_path):
    """shape 保真：顶层键集/顺序、成就元素字段、统计键集都与基线一致（只改值）。"""
    res, root = _export(tmp_path, make_ledger())
    pdir = root / "players" / STEAM
    base_prog = json.loads((FIXTURES / "fresh" / "progression.json").read_text(encoding="utf-8"))
    out_prog = json.loads((pdir / "progression.json").read_text(encoding="utf-8"))
    assert list(out_prog) == list(base_prog)                       # 键集 + 顺序
    assert set(out_prog["achievements"][0]) == set(base_prog["achievements"][0]) if base_prog.get("achievements") else True
    base_stats = json.loads((FIXTURES / "fresh" / "stats_profile.json").read_text(encoding="utf-8"))
    out_stats = json.loads((pdir / "stats_profile.json").read_text(encoding="utf-8"))
    assert list(out_stats) == list(base_stats)
    base_inv = json.loads((FIXTURES / "fresh" / "inventory.json").read_text(encoding="utf-8"))
    out_inv = json.loads((pdir / "inventory.json").read_text(encoding="utf-8"))
    assert set(out_inv) == set(base_inv)


def test_manifest_fields_and_counts(tmp_path):
    res, _root = _export(tmp_path, make_ledger(), version="9.9.9")
    m = res["manifest"]
    assert m["schema"] == 1
    assert m["saveId"] == SAVE_ID
    assert m["identity"] == {"steamId64": STEAM, "hd2AccountId": HD2}
    assert m["catalogBuild"] == "93e7575a/3021/1007203"
    assert m["engine"] == {"version": "9.9.9", "mergePolicy": sx.MERGE_POLICY}
    assert len(m["source"]["baselineSha256"]) == 64 and len(m["source"]["ledgerSha256"]) == 64
    assert m["source"]["baselineDir"].endswith("fresh")
    assert m["counts"] == {"experience": 210, "achievements": 4, "inventoryRows": 56,
                          "statsNonZero": 23, "missions": 2}


def test_index_written_and_idempotent(tmp_path):
    ledger = make_ledger()
    _export(tmp_path, ledger, name="root")
    other = make_ledger(steam="76561199881579811", hd2="13887067702231565058", exp=0)
    _export(tmp_path, other, name="root")
    root = tmp_path / "root"
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert index["schema"] == 1
    assert [p["steamId64"] for p in index["players"]] == ["76561198968648344",
                                                         "76561199881579811"]
    _export(tmp_path, ledger, name="root")            # 再导一次同一玩家 → 不重复
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    assert len(index["players"]) == 2


def test_deterministic_except_generated_at(tmp_path):
    ledger = make_ledger()
    _export(tmp_path, ledger, name="a")
    _export(tmp_path, ledger, name="b")
    for rel in ("progression.json", "inventory.json", "stats_profile.json"):
        a = (tmp_path / "a" / "players" / STEAM / rel).read_bytes()
        b = (tmp_path / "b" / "players" / STEAM / rel).read_bytes()
        assert a == b, rel
    ma = json.loads((tmp_path / "a" / "players" / STEAM / "manifest.json").read_text(encoding="utf-8"))
    mb = json.loads((tmp_path / "b" / "players" / STEAM / "manifest.json").read_text(encoding="utf-8"))
    assert ma.pop("generatedAt") and mb.pop("generatedAt")
    assert ma == mb


def test_atomic_write_no_tmp_left(tmp_path):
    _export(tmp_path, make_ledger())
    leftovers = list((tmp_path / "root").rglob("*.tmp"))
    assert leftovers == []


def test_optional_endpoints_exported_by_default(tmp_path):
    """研究线建议：可选端点默认导出（按玩家数据，缺省会让服务端回落公共数据串档）。"""
    _res, root = _export(tmp_path, make_ledger())
    pdir = root / "players" / STEAM
    assert (pdir / "stats_profile_war.json").exists()
    assert (pdir / "customize_v2.json").exists()
    _res2, root2 = _export(tmp_path, make_ledger(), include_optional=False, name="root2")
    pdir2 = root2 / "players" / STEAM
    assert not (pdir2 / "stats_profile_war.json").exists()
    assert not (pdir2 / "customize_v2.json").exists()


def test_manifest_baseline_self_description(tmp_path):
    """研究线建议：manifest 给 baselineId / baselineDirResolved / 逐文件 sha256，消费方可独立复算。"""
    res, _root = _export(tmp_path, make_ledger())
    src = res["manifest"]["source"]
    assert src["baselineId"] == "fresh"
    assert Path(src["baselineDirResolved"]).is_absolute()
    import hashlib
    for ep, info in src["baselineFiles"].items():
        raw = (FIXTURES / "fresh" / info["name"]).read_bytes()
        assert info["sha256"] == hashlib.sha256(raw).hexdigest(), ep
    assert set(src["baselineFiles"]) >= {"progression", "inventory", "stats_profile"}


def test_baseline_missing_core_endpoint_raises(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "progression.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        sx.export_player(make_ledger(), baseline_dir=str(base),
                         data_root=str(tmp_path / "root"), version="t")
    assert "缺必需端点" in str(ei.value)


def test_baseline_missing_dir_raises(tmp_path):
    with pytest.raises(ValueError) as ei:
        sx.export_player(make_ledger(), baseline_dir=str(tmp_path / "nope"),
                         data_root=str(tmp_path / "root"), version="t")
    assert "基线目录不存在" in str(ei.value)


def test_unidentified_ledger_falls_back_to_save_id_dir(tmp_path):
    ledger = make_ledger(with_identity=False, steam="", exp=5)
    res, root = _export(tmp_path, ledger)
    assert res["playerKey"] == "local"
    assert (root / "players" / "local" / "manifest.json").is_file()
    assert res["manifest"]["identity"]["steamId64"] is None


def test_ledger_file_digest_prefers_raw_bytes(tmp_path):
    ledger = make_ledger()
    f = tmp_path / "ledger.json"
    f.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    res = sx.export_player(ledger, baseline_dir=str(FIXTURES / "fresh"),
                           data_root=str(tmp_path / "root"), version="t",
                           ledger_file=str(f))
    import hashlib
    assert res["manifest"]["source"]["ledgerSha256"] == hashlib.sha256(f.read_bytes()).hexdigest()


# ---------------------------------------------------------------- v0.8.0 结算响应体


MISSION_END_DOC = json.loads((FIXTURES / "mission_end" / "12b9a872.json").read_text(encoding="utf-8"))


def test_mission_end_json_written_from_ledger(tmp_path):
    """v0.8.0：账本里有原始结算响应 → 导出 `mission_end.json`；
    v0.8.0-alpha.2：按玩家补/校正 platformAccountId（夹具脱敏剥掉了它，官方真实响应总有）。"""
    ledger = make_ledger()
    ledger["earned"]["missions"]["last_response"] = MISSION_END_DOC
    res, root = _export(tmp_path, ledger)
    pdir = root / "players" / STEAM
    got = json.loads((pdir / "mission_end.json").read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(MISSION_END_DOC))
    for row in expected.get("progressionPackageUpdates") or []:
        row["platformAccountId"] = HD2          # 玩家自己的 HD2 20 位 id
    # 键序：platformAccountId 在最前（与官方抓包一致）
    for row in got.get("progressionPackageUpdates") or []:
        assert list(row)[0] == "platformAccountId"
    assert got == expected
    assert "mission_end.json" in res["files"]


def test_mission_end_corrects_existing_platform_account_id(tmp_path):
    """上游给的是占位/别人的 id → 导出时校正为本玩家 identity（HD2 优先）。"""
    ledger = make_ledger()
    doc = json.loads(json.dumps(MISSION_END_DOC))
    for row in doc.get("progressionPackageUpdates") or []:
        row["platformAccountId"] = "76561190000000000"
    ledger["earned"]["missions"]["last_response"] = doc
    _res, root = _export(tmp_path, ledger)
    got = json.loads((root / "players" / STEAM / "mission_end.json").read_text(encoding="utf-8"))
    assert got["progressionPackageUpdates"][0]["platformAccountId"] == HD2
    assert got["progressionPackageUpdates"][0]["id32"] ==         doc["progressionPackageUpdates"][0]["id32"]


def test_mission_end_json_absent_without_raw(tmp_path):
    res, root = _export(tmp_path, make_ledger())
    assert not (root / "players" / STEAM / "mission_end.json").exists()
    assert "mission_end.json" not in res["files"]


def test_mission_end_json_disabled_with_no_optional(tmp_path):
    ledger = make_ledger()
    ledger["earned"]["missions"]["last_response"] = MISSION_END_DOC
    res, root = _export(tmp_path, ledger, include_optional=False)
    assert not (root / "players" / STEAM / "mission_end.json").exists()


# ---------------------------------------------------------------- CLI


def test_cli_save_export(tmp_path, capsys):
    from hd2proxy import __main__ as cli
    ledger = make_ledger()
    f = tmp_path / "ledger.json"
    f.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    root = tmp_path / "cli-root"
    rc = cli.main(["save-export", "--save-file", str(f),
                   "--baseline", str(FIXTURES / "fresh"),
                   "--data-root", str(root), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["playerKey"] == STEAM
    assert (root / "players" / STEAM / "manifest.json").is_file()
    assert (root / "index.json").is_file()
