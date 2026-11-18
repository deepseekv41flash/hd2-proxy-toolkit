"""store/season 抓包结构提取单测：端点盘点 / 布局映射 / name 字段检测 / 无名行对账。

用合成抓包目录（index.txt + `<sha8>_<slug>.json`）跑分析器，不依赖真实抓包与游戏。
"""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _tool():
    tools = str(REPO / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import extract_store_season_layout as mod  # noqa: PLC0415

    return mod


def _write_capture(capture_dir: Path, path: str, doc) -> None:
    """按抓包钩子的落盘格式写一个响应：`<sha8>_<slug>.json` + index.txt 行。"""
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    slug = "".join(c if c.isalnum() else "_" for c in path).strip("_")[-60:]
    (capture_dir / ("%s_%s.json" % (sha[:8], slug))).write_bytes(raw)
    with (capture_dir / "index.txt").open("a", encoding="utf-8") as fh:
        fh.write("20261118T000000Z\t%s\t%d\t%s\tjson\n" % (path, len(raw), sha))


def test_extract_layout_and_coverage(tmp_path):
    mod = _tool()
    cap = tmp_path / "raw"
    cap.mkdir()
    _write_capture(cap, "/api/StoreFront", [
        {"id32": 111, "layoutType": 0, "layoutSize": {"x": 0, "y": 2},
         "sections": [{"id32": 222, "bannerId32": 0, "items": [
             {"salesId": "s1", "mixId": 1001, "position": {"x": 0, "y": 1},
              "size": {"x": 1, "y": 1}},
             {"salesId": "s2", "mixId": 1002, "position": {"x": 1, "y": 0},
              "size": {"x": 1, "y": 1}},
         ]}]},
    ])
    _write_capture(cap, "/api/SeasonPass", [
        {"id32": 900, "itemIds": [1, 2], "premiumTokenMixIds": [3001, 3002]},
    ])
    _write_capture(cap, "/api/SeasonPass/900", {
        "id32": 900, "seasonPassPages": [
            {"totalMedalsRequired": 0, "seasonPassItems": [
                {"seasonPassItemId": 1, "itemMixId": 2001, "medalCost": 1,
                 "gridPosition": {"x": 0, "y": 0}, "isPremium": False},
                {"seasonPassItemId": 2, "itemMixId": 2002, "medalCost": 5,
                 "gridPosition": {"x": 1, "y": 0}, "isPremium": True},
            ]},
        ]})
    _write_capture(cap, "/api/Progression/ItemPackages", [
        {"itemMixId32": 4000, "items": [{"mixId": 4001, "amount": 3000}]},
    ])
    _write_capture(cap, "/api/Progression/ProgressionPackages", [
        {"id32": 5000, "type": 3, "requiredItems": [], "levels": [
            {"level": 1, "rewards": [{"type": 1, "id32": 5001, "amount": 1}],
             "unlockableItems": [5002], "cost": [], "assignmentSetting": {}},
        ]},
    ])
    _write_capture(cap, "/api/WarSeason/GalacticWarEffects", [
        {"effect_id": 1, "nameHash": 1234567890, "target": "stratagem:foo"},
    ])
    # 目录：1001/1002/2001/2002/3001/3002/4001/5001/5002 都没名字；1001 在目录里无名
    catalog = tmp_path / "items.json"
    cat_rows = []
    for mix in (1001, 1002, 2001, 2002, 3001, 3002, 4001, 5001, 5002, 9999):
        cat_rows.append({"mix_id": mix, "item_id": mix, "name": None,
                         "in_catalog": True, "catalog_category": 9})
    catalog.write_text(json.dumps({"items": cat_rows, "count": len(cat_rows)},
                                  ensure_ascii=False), encoding="utf-8")

    result = mod.analyze(cap, catalog)
    roles = result["roles"]
    assert "storefront:111/section:222/pos(0,1)" in roles["1001"]
    assert "storefront:111/section:222/pos(1,0)" in roles["1002"]
    assert any("seasonpass:900/page:0" in r for r in roles["2001"])
    assert any("/premium" in r for r in roles["2002"])
    assert any("premium-token" in r for r in roles["3001"])
    assert "itempackage:4000" in roles["4001"]
    assert "progression:5000/reward" in roles["5001"]
    assert "progression:5000/unlockable" in roles["5002"]
    # 覆盖：9 条有映射 + 9999 无映射
    cov = result["coverage"]
    assert cov["total"] == 10 and cov["covered"] == 9
    # name/locid 字段检测：GalacticWarEffects 的 nameHash 必须被抓到
    nameish = {row["path"]: row["hits"] for row in result["nameish"]}
    assert "/api/WarSeason/GalacticWarEffects" in nameish
    assert any(h["field"].endswith("nameHash") for h in nameish["/api/WarSeason/GalacticWarEffects"])
    # 商店/赛季响应本身没有名字字段（这是当前事实，未来若出现会在这里暴露）
    assert "/api/StoreFront" not in nameish
    # report 渲染不应崩
    report = mod.render_report(result)
    assert "商店货架" in report and "对账" in report


def test_report_flags_missing_name_sources(tmp_path):
    mod = _tool()
    cap = tmp_path / "raw"
    cap.mkdir()
    _write_capture(cap, "/api/StoreFront", [])
    catalog = tmp_path / "items.json"
    catalog.write_text(json.dumps({"items": []}), encoding="utf-8")
    result = mod.analyze(cap, catalog)
    assert result["coverage"]["total"] == 0
    report = mod.render_report(result)
    assert "截图 + OCR" in report or "截图" in report
