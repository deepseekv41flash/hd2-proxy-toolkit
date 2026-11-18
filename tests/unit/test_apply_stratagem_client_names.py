"""战备 client 静态表补名工具单测：补空位 / 幂等 / 拒绝覆盖 / --check 只读 / 统计自洽。

用合成快照 + 合成补丁数据跑工具，不依赖真实抓包、游戏与本机研究仓。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tool():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import apply_stratagem_client_names as mod  # noqa: PLC0415

    return mod


def _row(mix, name=None, source=None, confidence=None, cat=11):
    return {"mix": mix, "item": mix, "cat": cat, "parent": None,
            "name": name, "name_source": source, "confidence": confidence}


def _snapshot(tmp_path, rows):
    snap = {
        "note": "合成快照",
        "build": "test",
        "rows": rows,
        "coverage": {
            "total": len(rows),
            "named": sum(1 for r in rows if r.get("name")),
            "unresolved": sum(1 for r in rows if not r.get("name")),
            "by_cat": {
                "11": {
                    "rows": len(rows),
                    "named": sum(1 for r in rows if r.get("name")),
                    "unresolved": sum(1 for r in rows if not r.get("name")),
                    "sources": {},
                }
            },
            "by_source": {},
        },
    }
    _refresh_sources(snap)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _refresh_sources(snap):
    from collections import Counter

    rows = snap["rows"]
    counts = Counter(str(r.get("name_source")) for r in rows if r.get("name"))
    snap["coverage"]["by_source"] = dict(counts)
    snap["coverage"]["by_cat"]["11"]["sources"] = dict(counts)


def _source(tmp_path, pairs):
    doc = {
        "note": "合成补丁数据",
        "build": "test",
        "count": len(pairs),
        "rows": [
            {
                "mix_id": mix,
                "name": name,
                "client_display_name": name,
                "client_internal_name": f"TABLE. {name.upper()}",
                "native_hash": "%08x" % (mix & 0xFFFFFFFF),
                "wiki_title": name,
                "wiki_type": "Sentry",
            }
            for mix, name in pairs
        ],
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def test_patch_fills_only_empty_slots(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [
        _row(101, name="已存在", source="stratagem-permit-child", confidence="medium"),
        _row(102),
    ])
    src = _source(tmp_path, [(102, "A/AC-8 Autocannon Sentry")])
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 0

    doc = json.loads(snap.read_text(encoding="utf-8"))
    rows = {r["mix"]: r for r in doc["rows"]}
    assert rows[101]["name"] == "已存在" and rows[101]["name_source"] == "stratagem-permit-child"
    assert rows[102]["name"] == "A/AC-8 Autocannon Sentry"
    assert rows[102]["name_source"] == mod.NAME_SOURCE
    assert rows[102]["confidence"] == "high"
    cov = doc["coverage"]
    assert (cov["named"], cov["unresolved"]) == (2, 0)
    assert cov["by_source"][mod.NAME_SOURCE] == 1
    assert cov["by_cat"]["11"]["sources"][mod.NAME_SOURCE] == 1
    assert cov["name_patches"][0]["name_source"] == mod.NAME_SOURCE
    assert cov["name_patches"][0]["added"] == 1


def test_second_run_is_idempotent(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [_row(102)])
    src = _source(tmp_path, [(102, "Sentry")])
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 0
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 0
    assert snap.read_text(encoding="utf-8") == before, "幂等运行不应改动文件"


def test_refuses_to_overwrite_existing_different_name(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [_row(101, name="别的名字", source="stratagem-permit-child",
                                     confidence="medium")])
    src = _source(tmp_path, [(101, "New Name")])
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 2
    assert snap.read_text(encoding="utf-8") == before, "冲突时不应写文件"


def test_check_mode_does_not_write(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [_row(102)])
    src = _source(tmp_path, [(102, "Sentry")])
    before = snap.read_text(encoding="utf-8")
    assert mod.main(["--snapshot", str(snap), "--source", str(src), "--check"]) == 0
    assert snap.read_text(encoding="utf-8") == before


def test_rejects_missing_evidence_fields(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [_row(102)])
    src = tmp_path / "source.json"
    src.write_text(json.dumps({"count": 1, "rows": [{"mix_id": 102, "name": "Sentry"}]}),
                   encoding="utf-8")
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 2


def test_rejects_wrong_category(tmp_path):
    mod = _tool()
    snap = _snapshot(tmp_path, [_row(102, cat=3)])
    src = _source(tmp_path, [(102, "Sentry")])
    assert mod.main(["--snapshot", str(snap), "--source", str(src)]) == 2
