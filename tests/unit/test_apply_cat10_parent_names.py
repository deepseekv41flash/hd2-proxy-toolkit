"""cat11 → cat10 反推补名单测：只补空位 / 幂等 / 不猜（无 parent 或 parent 无名跳过）/ --check 只读。

用合成快照跑工具，不依赖真实目录数据。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tool():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import apply_cat10_parent_names as mod  # noqa: PLC0415

    return mod


def _row(mix, cat, name=None, source=None, confidence=None, parent=None):
    return {"mix": mix, "item": mix, "cat": cat, "parent": parent,
            "name": name, "name_source": source, "confidence": confidence}


def _snapshot(tmp_path, rows):
    from collections import Counter

    named = sum(1 for r in rows if r.get("name"))
    counts = Counter(str(r.get("name_source")) for r in rows if r.get("name"))
    by_cat = {}
    for cat in sorted({r["cat"] for r in rows}):
        cat_rows = [r for r in rows if r["cat"] == cat]
        cat_named = sum(1 for r in cat_rows if r.get("name"))
        by_cat[str(cat)] = {
            "rows": len(cat_rows),
            "named": cat_named,
            "unresolved": len(cat_rows) - cat_named,
            "sources": dict(Counter(str(r.get("name_source")) for r in cat_rows if r.get("name"))),
        }
    doc = {
        "rows": rows,
        "coverage": {
            "total": len(rows),
            "named": named,
            "unresolved": len(rows) - named,
            "by_cat": by_cat,
            "by_source": dict(counts),
        },
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def test_propagates_permit_name_to_child(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(900, 11, name="A/M-12 Mortar Sentry", source="stratagem-client-settings", confidence="high"),
        _row(901, 10, parent=900),
    ])
    assert mod.main(["--snapshot", str(snap)]) == 0
    doc = json.loads(snap.read_text(encoding="utf-8"))
    child = next(r for r in doc["rows"] if r["mix"] == 901)
    assert child["name"] == "A/M-12 Mortar Sentry"
    assert child["name_source"] == mod.NAME_SOURCE
    assert child["confidence"] == "medium"
    cov = doc["coverage"]
    assert (cov["named"], cov["unresolved"]) == (2, 0)
    assert cov["by_source"][mod.NAME_SOURCE] == 1
    assert cov["by_cat"]["10"]["named"] == 1
    assert cov["by_cat"]["10"]["sources"][mod.NAME_SOURCE] == 1
    assert cov["name_patches"][0]["name_source"] == mod.NAME_SOURCE


def test_skips_children_without_named_parent(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(900, 11),                       # 许可行自己也没名字
        _row(901, 10, parent=900),
        _row(902, 10),                       # 没有 parent
    ])
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap)]) == 0
    assert snap.read_text(encoding="utf-8") == before, "无可补行时不应写文件"


def test_idempotent(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(900, 11, name="X", source="s", confidence="high"),
        _row(901, 10, parent=900),
    ])
    assert mod.main(["--snapshot", str(snap)]) == 0
    once = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap)]) == 0
    assert snap.read_text(encoding="utf-8") == once


def test_check_mode_does_not_write(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(900, 11, name="X", source="s", confidence="high"),
        _row(901, 10, parent=900),
    ])
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap), "--check"]) == 0
    assert snap.read_text(encoding="utf-8") == before


def test_does_not_touch_named_children(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(900, 11, name="Permit Name", source="s", confidence="high"),
        _row(901, 10, name="Existing", source="items.json", confidence="high", parent=900),
    ])
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap)]) == 0
    assert snap.read_text(encoding="utf-8") == before
