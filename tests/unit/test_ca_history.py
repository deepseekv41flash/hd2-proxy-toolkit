"""CA 变更历史（`certs.ca_history`）单测：续期换 CA 时留痕，排查 Error 60 用。"""

import json

from hd2proxy.engine import certs


def test_ensure_session_records_ca_history(tmp_path):
    host = certs.DEFAULT_HOST
    first = certs.ensure_session(tmp_path, host=host, days=1, min_remaining_hours=0)
    assert first["action"] == "generated"
    history = certs.ca_history(tmp_path)
    assert len(history) == 1                     # 首次签发也留痕（old=None）
    assert history[0]["old"] is None and history[0]["new"]
    old_thumb = history[0]["new"]

    # 强制重签 → 新 CA → 历史追加一条，且 old 指向上一次的 thumbprint
    second = certs.ensure_session(tmp_path, host=host, days=1,
                                  min_remaining_hours=0, force=True)
    assert second["action"] == "generated"
    new_thumb = second["report"].get("thumbprint_sha1") or ""
    history = certs.ca_history(tmp_path)
    assert len(history) == 2
    assert history[1]["old"] == old_thumb
    assert history[1]["new"] == new_thumb and new_thumb != old_thumb
    # 落盘文件可读且是 list
    doc = json.loads((tmp_path / certs.CA_HISTORY_FILE).read_text(encoding="utf-8"))
    assert isinstance(doc, list) and len(doc) == 2


def test_ca_history_missing_and_broken(tmp_path):
    assert certs.ca_history(tmp_path) == []
    (tmp_path / certs.CA_HISTORY_FILE).write_text("{bad json", encoding="utf-8")
    assert certs.ca_history(tmp_path) == []
    (tmp_path / certs.CA_HISTORY_FILE).write_text('{"not": "list"}', encoding="utf-8")
    assert certs.ca_history(tmp_path) == []
