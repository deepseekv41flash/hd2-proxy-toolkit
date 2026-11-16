"""钩子等价性回归：重构后的模块必须和 M0 引擎的输出**逐字段一致**。

基准来自 `tests/fixtures/golden/`（由 M0 的 legacy_proxy.py 生成，见 make_golden.py）。
每种钩子测两条路径：
  * `spec=<dict>`（schema v2 / 单元测试用显式配置）；
  * `spec=None`（研究线旧行为：读环境变量 / runtime/*.json）—— 保证兼容与可回退。

任何一条与 golden 不一致，就说明重构改变了行为，必须修到绿再继续。
"""

import json
from pathlib import Path

import pytest

from hd2proxy.engine import model
from hd2proxy.engine.hooks import capture, inventory, items, warinfo

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _load(kind, name):
    return json.loads((FIX / kind / (name + ".json")).read_text(encoding="utf-8"))


def _golden(name):
    return _load("golden", name)


def _parse(body):
    return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------- status


def test_status_explicit_spec():
    inp = _load("inputs", "status")
    plan = _load("configs", "status_plan")
    extra = _load("configs", "status_extra")
    body, added = model.rewrite_status(json.dumps(inp).encode(), plan, extra)
    g = _golden("status")
    assert _parse(body) == g["output"]
    assert added == g["counts"]["added"]


def test_status_legacy_env(monkeypatch):
    inp = _load("inputs", "status")
    plan = _load("configs", "status_plan")
    extra = _load("configs", "status_extra")
    monkeypatch.setenv("HD2_GWE_EXTRA", json.dumps(extra, ensure_ascii=False))
    body, added = model.rewrite_status(json.dumps(inp).encode(), plan)
    g = _golden("status")
    assert _parse(body) == g["output"]
    assert added == g["counts"]["added"]


# ---------------------------------------------------------------- warinfo


def test_warinfo_explicit_spec():
    inp = _load("inputs", "warinfo")
    spec = _load("configs", "warinfo_spec")
    body, n = warinfo.apply(json.dumps(inp).encode(), spec=spec)
    g = _golden("warinfo")
    assert _parse(body) == g["output"]
    assert n == g["counts"]["changed"]


def test_warinfo_legacy_env(monkeypatch):
    inp = _load("inputs", "warinfo")
    spec = _load("configs", "warinfo_spec")
    monkeypatch.setenv("HD2_GWE_EXTRA", json.dumps(spec, ensure_ascii=False))
    body, n = warinfo.apply(json.dumps(inp).encode())
    g = _golden("warinfo")
    assert _parse(body) == g["output"]
    assert n == g["counts"]["changed"]


def test_warinfo_records_live_settings_hash(tmp_path):
    """capture.planet_settings=true 时把 live settingsHash 落盘（能力 6 的数据来源）。"""
    inp = {"planetInfos": [{"index": 5, "settingsHash": 111}, {"index": 6, "settingsHash": 222}]}
    target = tmp_path / "planet_settings.json"
    body, n = warinfo.apply(json.dumps(inp).encode(),
                            spec={"record_planet_settings": str(target)})
    assert n == 0
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["source"] == "live-warinfo"
    assert doc["items"] == {"5": 111, "6": 222}


# ---------------------------------------------------------------- inventory


def test_inventory_explicit_spec():
    inp = _load("inputs", "inventory")
    spec = _load("configs", "inventory_spec")
    body, added, removed = inventory.inventory_rewrite(json.dumps(inp).encode(), spec=spec)
    g = _golden("inventory")
    assert _parse(body) == g["output"]
    assert (added, removed) == (g["counts"]["added"], g["counts"]["removed"])


def test_inventory_legacy_runtime_files(monkeypatch, tmp_path):
    inp = _load("inputs", "inventory")
    spec = _load("configs", "inventory_spec")
    state = tmp_path / "inventory_inject.json"
    state.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    # 其余四类开关文件不存在 => 视作 {}，只有 inventory_inject 生效
    monkeypatch.setattr(inventory, "INV_STATE", state)
    for name in ("ATTACH_STATE", "COSMETIC_STATE", "STRATAGEM_STATE", "PROBE_STATE"):
        monkeypatch.setattr(inventory, name, tmp_path / ("missing_" + name.lower()))
    body, added, removed = inventory.inventory_rewrite(json.dumps(inp).encode())
    g = _golden("inventory")
    assert _parse(body) == g["output"]
    assert (added, removed) == (g["counts"]["added"], g["counts"]["removed"])


def test_customize_explicit_spec():
    inp = _load("inputs", "customize")
    spec = _load("configs", "customize_spec")
    body, changed = inventory.customize_rewrite(json.dumps(inp).encode(), spec=spec)
    g = _golden("customize")
    assert _parse(body) == g["output"]
    assert changed == g["counts"]["changed"]


def test_customize_legacy_runtime_file(monkeypatch, tmp_path):
    inp = _load("inputs", "customize")
    spec = _load("configs", "customize_spec")
    state = tmp_path / "customize_inject.json"
    state.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(inventory, "CUSTOMIZE_STATE", state)
    body, changed = inventory.customize_rewrite(json.dumps(inp).encode())
    g = _golden("customize")
    assert _parse(body) == g["output"]
    assert changed == g["counts"]["changed"]


# ---------------------------------------------------------------- items


def test_items_explicit_spec():
    inp = _load("inputs", "items")
    spec = _load("configs", "items_spec")
    body, added = items.items_rewrite(json.dumps(inp).encode(), spec=spec)
    g = _golden("items")
    assert _parse(body) == g["output"]
    assert added == g["counts"]["added"]


def test_items_legacy_runtime_file(monkeypatch, tmp_path):
    inp = _load("inputs", "items")
    spec = _load("configs", "items_spec")
    state = tmp_path / "items_inject.json"
    state.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(items, "ITEMS_STATE", state)
    body, added = items.items_rewrite(json.dumps(inp).encode())
    g = _golden("items")
    assert _parse(body) == g["output"]
    assert added == g["counts"]["added"]


# ---------------------------------------------------------------- capture


def test_capture_spec_writes_files(tmp_path):
    body = b'{"warId": 801}'
    capture.capture_response("/api/WarSeason/801/Status", body, {},
                             spec={"enabled": True, "dir": str(tmp_path),
                                   "paths": ["api/"], "max_bytes": 1 << 20})
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1, files
    assert files[0].read_bytes() == body
    index = (tmp_path / "index.txt").read_text(encoding="utf-8")
    assert "/api/WarSeason/801/Status" in index


def test_capture_spec_disabled_and_filter(tmp_path):
    capture.capture_response("/api/WarSeason/801/Status", b"{}", {},
                             spec={"enabled": False, "dir": str(tmp_path),
                                   "paths": ["api/"], "max_bytes": 1 << 20})
    capture.capture_response("/api/Account/Login", b"{}", {},
                             spec={"enabled": True, "dir": str(tmp_path),
                                   "paths": ["api/WarSeason/"], "max_bytes": 1 << 20})
    assert list(tmp_path.glob("*.json")) == []


def test_capture_legacy_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HD2_GWE_DUMP", str(tmp_path))
    monkeypatch.setenv("HD2_GWE_PATHS", "/api/WarSeason/801/Status")
    capture.capture_response("/api/WarSeason/801/Status", b'{"warId": 801}', {})
    assert len(list(tmp_path.glob("*.json"))) == 1


# ---------------------------------------------------------------- 兜底


@pytest.mark.parametrize("name", ["status", "warinfo", "inventory", "items", "customize"])
def test_golden_fixture_shape(name):
    g = _golden(name)
    assert "output" in g and "counts" in g
