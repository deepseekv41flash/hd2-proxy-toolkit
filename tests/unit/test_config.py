"""配置面（schema v2）单测：校验 / 归一化 / profile 存取 / 迁移 / 引擎 spec 映射。"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import config, paths

REPO = Path(__file__).resolve().parents[2]
LEGACY_CATALOG = REPO / "data" / "legacy" / "variant_catalog.json"


def _catalog():
    return json.loads(LEGACY_CATALOG.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 校验


def test_default_profile_is_valid():
    doc, errors, warnings = config.validate(config.default_profile())
    assert errors == []
    assert doc["schema"] == 2
    assert doc["proxy"]["passthrough"] is True
    assert any("没有任何改写内容" in w for w in warnings)


def test_unknown_top_key_warns_not_errors():
    doc, errors, warnings = config.validate({**config.default_profile(), "mystery": 1})
    assert errors == []
    assert any("mystery" in w for w in warnings)


def test_internal_underscore_keys_are_not_unknown():
    """load_profile_file 会挂 `_warnings`；再次 validate 不能把它当用户拼错的键报出来。"""
    prof = config.default_profile()
    prof["_warnings"] = ["来自上一次校验"]
    _, errors, warnings = config.validate(prof)
    assert errors == []
    assert not any("_warnings" in w for w in warnings)


@pytest.mark.parametrize("mutate,needle", [
    (lambda p: p.update(schema=1), "schema"),
    (lambda p: p["proxy"].update(listen_ip="127.0.0.1"), "回环"),
    (lambda p: p["proxy"].update(port=0), "proxy.port"),
    (lambda p: p["cert"].update(days=5), "cert.days"),
    (lambda p: p["cert"].update(auto_renew="yes"), "auto_renew"),
    (lambda p: p["status"].update(planet_effects=[{"index": 999, "ids": [1]}]), "planet_effects"),
    (lambda p: p["status"].update(variants=[{"name": "", "planets": []}]), "status.variants"),
    (lambda p: p["status"].update(owner={"x": 1}), "status.owner"),
    (lambda p: p["capture"].update(max_bytes=0), "max_bytes"),
])
def test_validation_errors(mutate, needle):
    prof = config.default_profile()
    mutate(prof)
    _, errors, _ = config.validate(prof)
    assert any(needle in e for e in errors), errors


def test_inventory_rows_coerced_to_objects():
    prof = config.default_profile()
    prof["inventory"]["weapons"] = [2112173638, {"mixId": 123, "amount": 3}]
    doc, errors, _ = config.validate(prof)
    assert errors == []
    assert doc["inventory"]["weapons"] == [
        {"mixId": 2112173638, "amount": 1, "isDiscovered": False},
        {"mixId": 123, "amount": 3},
    ]


def test_status_plan_resolution_with_catalog():
    prof = config.default_profile()
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [100, 268]},
                                  {"name": "掠食", "planets": [200]},        # 别名
                                  {"name": "不存在的变种", "planets": [1]}]
    prof["status"]["trials"] = [1227, 1263]
    doc, errors, _ = config.validate(prof)
    assert errors == []
    plan, warnings = config.build_status_plan(doc, _catalog())
    assert sorted(plan) == [100, 200, 268]
    assert plan[100]["variants"][0]["ids"] == [1243, 1245]
    assert plan[100]["variants"][0]["faction"] == "terminid"
    assert plan[100]["trials"] == [1227, 1263]
    assert plan[200]["variants"][0]["name"] == "掠食变种"     # 别名解析回正式名
    assert any("不存在的变种" in w for w in warnings)


def test_to_engine_spec_mapping():
    prof = config.default_profile(name="映射测试")
    prof["proxy"].update(port=443, passthrough=False, verbose=True, control_port=0)
    prof["cert"].update(days=2, min_remaining_hours=6, auto_renew=False)
    prof["warinfo"]["settings_hash"] = {"76": 2995599666}
    prof["status"]["planet_effects"] = [{"index": 76, "ids": [1243, 1245]}]
    prof["status"]["globalEffects"] = {"1501113": [1346]}
    prof["status"]["owner"] = {"158": 1}
    prof["status"]["variants"] = [{"name": "掠食变种", "planets": [100]}]
    prof["inventory"]["weapons"] = [{"mixId": 2112173638}]
    prof["items"]["add"] = [2112173638]
    prof["capture"].update(enabled=False)
    doc, errors, _ = config.validate(prof)
    assert errors == []
    spec = config.to_engine_spec(doc, _catalog())
    assert spec.passthrough is False and spec.verbose is True
    assert spec.cert_days == 2 and spec.cert_min_remaining_hours == 6.0
    assert spec.cert_auto_renew is False
    assert spec.warinfo == {"settings_hash": {"76": 2995599666}, "planet_infos": []}
    assert spec.status_extra["planet_effects"] == [{"index": 76, "ids": [1243, 1245]}]
    assert spec.status_extra["globalEffects"] == {"1501113": [1346]}
    assert spec.status_extra["owner"] == {"158": 1}
    assert spec.status_plan == {100: {"variants": [{"name": "掠食变种", "ids": [1243, 1245],
                                                     "faction": "terminid"}],
                                      "trials": []}}
    assert spec.inventory["enabled"] is True
    assert spec.inventory["items"] == [{"mixId": 2112173638, "amount": 1,
                                        "isDiscovered": False}]
    assert spec.items == {"enabled": True, "template": None, "add": [2112173638]}
    assert spec.capture["enabled"] is False


def test_capture_planet_settings_hooks_into_warinfo(monkeypatch, tmp_path):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    prof = config.default_profile()
    prof["capture"]["planet_settings"] = True
    doc, errors, _ = config.validate(prof)
    assert errors == []
    spec = config.to_engine_spec(doc)
    assert spec.warinfo is not None
    assert spec.warinfo["record_planet_settings"] == str(tmp_path / "planet_settings.json")


# ---------------------------------------------------------------- 存取


def test_profile_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path / "state"))
    prof = config.default_profile(name="往返")
    prof["status"]["trials"] = [1227]
    p = config.save_profile("往返", prof)
    assert p.exists()
    loaded = config.load_profile("往返")
    assert loaded["name"] == "往返"
    assert loaded["status"]["trials"] == [1227]
    assert any("往返.json" in x["path"] for x in config.list_profiles())
    # 非法 profile 不允许写盘
    bad = config.default_profile(name="bad")
    bad["proxy"]["listen_ip"] = "127.0.0.1"
    with pytest.raises(ValueError):
        config.save_profile("bad", bad)


def test_profile_path_sanitizes_name(monkeypatch, tmp_path):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path))
    p = config.profile_path('a/b:c*?"<>|')
    assert p.parent == tmp_path / "profiles"
    assert "/" not in p.name and ":" not in p.name


# ---------------------------------------------------------------- 旧配置迁移


def test_from_legacy_migrates_core_content(monkeypatch, tmp_path):
    rt = tmp_path / "runtime"
    rt.mkdir()
    (rt / "selection.json").write_text(json.dumps(
        {"enabled": True, "variants": ["掠食变种"]}, ensure_ascii=False), encoding="utf-8")
    (rt / "stratagems.json").write_text(json.dumps(
        {"enabled": True, "ids": [1227, 1263, 1254, 1152]}), encoding="utf-8")
    (rt / "inventory_inject.json").write_text(json.dumps(
        {"enabled": True, "items": [{"mixId": 2112173638, "amount": 1}]}), encoding="utf-8")
    (rt / "items_inject.json").write_text(json.dumps(
        {"enabled": True, "template": 200, "add": [2112173638]}), encoding="utf-8")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "host": "api.live.prod.thehelldiversgame.com", "listenIp": "192.168.1.50",
        "port": 443, "crlPort": 8080, "passthrough": False, "verbose": True,
        "targets": [{"planet": 100, "variant": "掠食"}],
    }), encoding="utf-8")
    extra = json.dumps({"globalEffects": {"1501113": [1346]},
                        "settings_hash": {"76": 2995599666}})
    prof, notes = config.from_legacy(cfg, rt, extra)
    doc, errors, _ = config.validate(prof)
    assert errors == []
    assert doc["proxy"]["listen_ip"] == "192.168.1.50"
    assert doc["proxy"]["passthrough"] is False and doc["proxy"]["verbose"] is True
    assert doc["status"]["variants"] == [{"name": "掠食变种", "planets": [100]}]
    assert doc["status"]["trials"] == [1227, 1263, 1254, 1152]
    assert doc["status"]["globalEffects"] == {"1501113": [1346]}
    assert doc["warinfo"]["settings_hash"] == {"76": 2995599666}
    assert doc["inventory"]["weapons"] == [{"mixId": 2112173638, "amount": 1,
                                           "isDiscovered": False}]
    assert doc["items"] == {"template": 200, "add": [2112173638]}
    assert any("最多 3 条" in n for n in notes)      # 4 条战备会提示旧上限
    assert notes                                            # 迁移一定有说明


def test_from_legacy_without_selection_uses_targets(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"host": "api.live.prod.thehelldiversgame.com",
                               "targets": [{"planet": 158, "variant": "生化人"}]}),
                   encoding="utf-8")
    prof, _ = config.from_legacy(cfg, tmp_path / "no-runtime", None)
    doc, errors, _ = config.validate(prof)
    assert errors == []
    assert doc["status"]["variants"] == [{"name": "生化人", "planets": [158]}]


def test_paths_state_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HD2PROXY_STATE", str(tmp_path / "s"))
    assert paths.state_dir() == tmp_path / "s"
    assert paths.profile_dir() == tmp_path / "s" / "profiles"
    assert paths.engine_state_file() == tmp_path / "s" / "engine.json"


def test_planet_infos_position_keeps_float():
    """休眠星四件套的 warinfo 坐标是浮点：校验后不能被截成 0（GUI 曾踩到）。"""
    prof = config.default_profile()
    prof["warinfo"]["planet_infos"] = [{
        "index": 300, "settingsHash": 2995599666,
        "position": {"x": 0.3, "y": -0.55},
    }]
    doc, errors, _ = config.validate(prof)
    assert errors == []
    pos = doc["warinfo"]["planet_infos"][0]["position"]
    assert abs(pos["x"] - 0.3) < 1e-9 and abs(pos["y"] + 0.55) < 1e-9


def test_planet_effects_on_super_earth_warns():
    """靶星 0 = SUPER EARTH（母星无卡面/战役）：不阻止保存，但必须给 warning。

    2026-11-20 实机：profile 里靶星存成 0，注入下发成功但卡面永远看不到。
    """
    prof = config.default_profile()
    prof["status"]["planet_effects"] = [{"index": 0, "ids": [1243, 1245]}]
    doc, errors, warnings = config.validate(prof)
    assert errors == []
    assert doc["status"]["planet_effects"] == [{"index": 0, "ids": [1243, 1245]}]
    assert any("SUPER EARTH" in w for w in warnings)


def test_saves_preverify_merge_validation():
    """v0.6.0-alpha.3：首屏合并策略 safe/full/off 三档；默认 safe（防换号回声污染）。"""
    prof = config.default_profile()
    doc, errors, _ = config.validate(prof)
    assert errors == [] and doc["saves"]["preverify_merge"] == "safe"
    spec = config.to_engine_spec(doc)
    assert spec.saves["preverify_merge"] == "safe"

    for mode in ("full", "off"):
        p = config.default_profile()
        p["saves"]["preverify_merge"] = mode
        d, errs, _ = config.validate(p)
        assert errs == [] and d["saves"]["preverify_merge"] == mode
        assert config.to_engine_spec(d).saves["preverify_merge"] == mode

    p = config.default_profile()
    p["saves"]["preverify_merge"] = "bogus"
    _, errs, _ = config.validate(p)
    assert errs and "preverify_merge" in errs[0]
