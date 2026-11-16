"""阵营隔离自检：三个敌对阵营的词条不得串到其他星球。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "hd2proxy" / "engine"))
import legacy_proxy as war_proxy  # noqa: E402


def entry(catalog, meta, name):
    return {
        "name": name,
        "ids": list(catalog[name]),
        "faction": war_proxy.variant_faction(meta[name]),
    }


def main():
    doc = json.loads((ROOT / "data" / "legacy" / "variant_catalog.json").read_text(encoding="utf-8"))
    catalog, meta = doc["variants"], doc["meta"]
    variants = [
        entry(catalog, meta, "掠食变种"),
        entry(catalog, meta, "生化人"),
        entry(catalog, meta, "入侵舰队"),
        entry(catalog, meta, "重兵部署"),
    ]
    candidate = {
        planet: {"variants": variants, "trials": [1276]}
        for planet in (100, 200, 300, 400)
    }
    status = {
        "warId": 801,
        "planetStatus": [
            {"index": 100, "owner": 2},
            {"index": 200, "owner": 3},
            {"index": 300, "owner": 4},
            {"index": 400, "owner": 0},
        ],
        "planetActiveEffects": [],
    }
    resolved, filtered = war_proxy.resolve_plan(status, candidate)
    body, added = war_proxy.rewrite_status(json.dumps(status).encode(), candidate)
    result = json.loads(body)
    actual = {}
    for row in result["planetActiveEffects"]:
        actual.setdefault(row["index"], set()).add(row["galacticEffectId"])

    expected = {
        100: {1243, 1245, 1401, 1400, 1276},
        200: {1360, 1361, 1401, 1400, 1276},
        300: {1413, 1414, 1401, 1400, 1276},
        400: {1401, 1400, 1276},
    }
    ok = actual == expected and len(filtered) == 9 and added == sum(map(len, expected.values()))
    print("resolved:", json.dumps({str(k): sorted(v) for k, v in resolved.items()}, ensure_ascii=False))
    print("filtered:", len(filtered), "entries")
    print("RESULT=%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
