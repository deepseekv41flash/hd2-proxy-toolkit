"""win_integrity 的跨平台行为：非 Windows 必须 no-op，Windows 上返回 bool。"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("win_integrity", ROOT / "tools" / "win_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_set_medium_is_noop_on_non_windows(monkeypatch):
    """非 Windows（CI 常见）不能去调用 icacls，也不能抛异常。"""
    mod = _load()
    monkeypatch.setattr(mod.os, "name", "posix")
    assert mod.set_medium("irrelevant") is False
    assert "失败" in mod.describe("irrelevant")


def test_set_medium_returns_bool(tmp_path):
    mod = _load()
    assert isinstance(mod.set_medium(tmp_path), bool)
