"""生成 golden 基准：用 **M0 引擎** 的钩子函数跑固定输入，把输出固化成测试基准。

为什么要有它：
  M1 把 1846 行的 `legacy_proxy.py` 拆成模块、并给每个钩子加了 `spec` 参数，
  拆分/加参数都可能悄悄改变行为。所以基准必须来自**重构前的已验证实现**。

M0 的实现现在只存在于 git 历史里（`src/hd2proxy/engine/legacy_proxy.py` 已变成兼容入口），
所以本脚本默认从 git 里取出 M0 版本（`M0_REF` 可覆盖），落到临时文件后 import 执行：

  python tests/fixtures/make_golden.py                 # 从 git 取 M0 实现（默认 commit 826ba04）
  python tests/fixtures/make_golden.py --legacy <file> # 指定 M0 实现文件

产物：
  tests/fixtures/inputs/*.json     固定输入（Status / warinfo / inventory / items / customize）
  tests/fixtures/configs/*.json    每种钩子的配置（重构后作为 spec 显式传入）
  tests/fixtures/golden/*.json     {"output": <改写后的 JSON>, "counts": {...}} 期望值

注意：把 VMOD_DATA 指到临时目录再 import 引擎（引擎在 import 时就算好路径），跑完即删。
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
INPUTS, CONFIGS, GOLDEN = FIX / "inputs", FIX / "configs", FIX / "golden"
M0_REF = "826ba04"
M0_PATH = "src/hd2proxy/engine/legacy_proxy.py"

# ---------------------------------------------------------------- 固定输入

STATUS_INPUT = {
    "warId": 801,
    "time": 1700000000,
    "planetStatus": [
        {"index": 100, "owner": 2},
        {"index": 76, "owner": 1},
        {"index": 200, "owner": 3},
        {"index": 300, "owner": 4},
        {"index": 158, "owner": 2},
    ],
    "planetActiveEffects": [
        {"index": 100, "galacticEffectId": 1195},
        {"index": 76, "galacticEffectId": 1243},
    ],
    "campaigns": [{"id": 500, "planetIndex": 76, "type": 0, "count": 1, "race": 1}],
    "planetAttacks": [{"source": 76, "target": 100}],
    "planetEvents": [{
        "id": 7001, "planetIndex": 200, "eventType": 1, "race": 3,
        "health": 100, "maxHealth": 200, "startTime": 1, "expireTime": 2,
        "campaignId": 500, "jointOperationIds": [7001], "potentialBuildUp": 0,
    }],
    "jointOperations": [{"id": 7001, "planetIndex": 200, "hqNodeIndex": 1}],
    "globalEvents": [{"eventId": 1501113, "effectIds": [1, 2]}],
    "planetRegions": [{
        "planetIndex": 76, "regionIndex": 0, "owner": 1, "health": 1, "players": 0,
        "regerPerSecond": 0, "isAvailable": True, "availabilityFactor": 1,
    }],
}

STATUS_PLAN = {
    "100": {"variants": [{"name": "掠食变种", "ids": [1243, 1245], "faction": "terminid"}],
            "trials": [1227, 1263, 1254, 1152]},
    "200": {"variants": [{"name": "生化人", "ids": [1360, 1361], "faction": "automaton"}],
            "trials": []},
    "300": {"variants": [{"name": "重兵部署", "ids": [1401, 1400], "faction": "universal"}],
            "trials": []},
    "301": {"variants": [{"name": "灼热部队", "ids": [1248, 1249], "faction": "automaton"}],
            "trials": []},
}

STATUS_EXTRA = {
    "campaigns": [{"planet": 300, "id": 51999, "type": 4, "count": 2, "race": 1}],
    "attacks": [{"source": 100, "target": 300}],
    "events": [{"planet": 300, "eventType": 2, "race": 2, "health": 900000,
                "maxHealth": 1000000, "startOffset": -30, "endOffset": 7200}],
    "globalEffects": {"1501113": [1346]},
    "regions": [{"planet": 200, "regionIndex": 1, "owner": 3, "maxHealth": 400000}],
    "planet_nodes": [{"index": 301, "owner": 1, "health": 800000,
                      "regenPerSecond": 4.5, "players": 3,
                      "position": {"x": 0.11, "y": -0.22}}],
    "planet_effects": [{"index": 76, "ids": [1306, 1309]}],
    "owner": {"158": 1},
}

WARINFO_INPUT = {
    "planetInfos": [
        {"index": 76, "settingsHash": 111, "position": {"x": 0.1, "y": 0.2},
         "maxHealth": 1000, "initialOwner": 1},
        {"index": 100, "settingsHash": 222},
    ]
}

WARINFO_SPEC = {
    "settings_hash": {"76": 2995599666},
    "planet_infos": [{
        "index": 301, "settingsHash": 2995599666,
        "position": {"x": 0.3, "y": -0.55},
        "maxHealth": 1000000, "initialOwner": 2, "sector": 20, "waypoints": [180, 7],
    }],
}

INVENTORY_INPUT = {
    "items": [
        {"mixId": 1000, "amount": 1, "isDiscovered": True},
        {"mixId": 2000, "amount": 2},
    ],
    "customization": [{
        "mixId32": 3000, "index": 0, "activeIndex": 0,
        "slots": [1, 2, 3, 4, 5, 6, 7, 8], "modes": [0, 0, 0, 0],
    }],
}

INVENTORY_SPEC = {
    "enabled": True,
    "items": [
        {"mixId": 2112173638, "amount": 1, "isDiscovered": False},
        {"mixId": 1000, "amount": 5},
    ],
    "remove": [2000],
    "customization": [{
        "mixId32": 4161086429, "index": 1, "activeIndex": 0,
        "slots": [9, 10], "modes": [1],
    }],
}

ITEMS_INPUT = [
    {"itemId": 100, "mixId": 100, "progressionCategory": 0, "tags": [], "buyPrice": []},
    {"itemId": 200, "mixId": 200, "progressionCategory": 3, "tags": ["x"]},
]

ITEMS_SPEC = {
    "enabled": True,
    "template": 200,
    "add": [
        2112173638,
        {"id": 300, "template": 200, "progressionCategory": 2, "parentId": 200},
    ],
}

CUSTOMIZE_INPUT = {
    "items": [{
        "mixId32": 2112173638, "modes": [0, 0, 0, 0], "activeIndex": 0,
        "customizations": [
            {"index": 0, "slots": [0, 0, 0, 0, 0, 0, 0, 0]},
            {"index": 1, "slots": [1, 1, 1, 1, 1, 1, 1, 1]},
        ],
    }]
}

CUSTOMIZE_SPEC = {
    "enabled": True,
    "logEdits": False,
    "edits": [
        {"mixId": 2112173638, "slots": {"1": 3905063732}, "allIndexes": False},
        {"mixId": 999, "slots": {"0": 5}, "createIfMissing": True,
         "baseSlots": [7, 7, 7, 7, 7, 7, 7, 7]},
    ],
}


def dump(path: Path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    print("wrote %s" % path.relative_to(ROOT))


def load_m0(legacy_path=None):
    """载入 M0 实现。默认从 git 取固定 commit 的版本，保证基准可复现。"""
    if legacy_path:
        src = Path(legacy_path)
        code = src.read_text(encoding="utf-8")
    else:
        code = subprocess.run(
            ["git", "show", "%s:%s" % (M0_REF, M0_PATH)],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        ).stdout
        if not code.strip():
            raise RuntimeError("git show 取不到 M0 实现（%s:%s）" % (M0_REF, M0_PATH))
    tmpdir = Path(tempfile.mkdtemp(prefix="hd2proxy-m0-"))
    py = tmpdir / "legacy_m0.py"
    py.write_text(code, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("legacy_m0", py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, tmpdir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", default="", help="M0 legacy_proxy.py 路径（默认从 git 取）")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="hd2proxy-golden-"))
    os.environ["VMOD_DATA"] = str(tmp)
    runtime = tmp / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "inventory_inject.json").write_text(
        json.dumps(INVENTORY_SPEC, ensure_ascii=False), encoding="utf-8")
    (runtime / "items_inject.json").write_text(
        json.dumps(ITEMS_SPEC, ensure_ascii=False), encoding="utf-8")
    (runtime / "customize_inject.json").write_text(
        json.dumps(CUSTOMIZE_SPEC, ensure_ascii=False), encoding="utf-8")

    m0, m0dir = load_m0(a.legacy or None)
    try:
        # ---- 固定输入与配置（重构后作为显式 spec 传入） ----
        dump(INPUTS / "status.json", STATUS_INPUT)
        dump(CONFIGS / "status_plan.json", STATUS_PLAN)
        dump(CONFIGS / "status_extra.json", STATUS_EXTRA)
        dump(INPUTS / "warinfo.json", WARINFO_INPUT)
        dump(CONFIGS / "warinfo_spec.json", WARINFO_SPEC)
        dump(INPUTS / "inventory.json", INVENTORY_INPUT)
        dump(CONFIGS / "inventory_spec.json", INVENTORY_SPEC)
        dump(INPUTS / "items.json", ITEMS_INPUT)
        dump(CONFIGS / "items_spec.json", ITEMS_SPEC)
        dump(INPUTS / "customize.json", CUSTOMIZE_INPUT)
        dump(CONFIGS / "customize_spec.json", CUSTOMIZE_SPEC)

        # ---- 用 M0 实现生成期望值（每个钩子用各自的环境变量输入） ----
        os.environ["HD2_GWE_EXTRA"] = json.dumps(STATUS_EXTRA, ensure_ascii=False)
        status_body, status_added = m0.rewrite_status(
            json.dumps(STATUS_INPUT).encode(), STATUS_PLAN)
        dump(GOLDEN / "status.json", {
            "counts": {"added": status_added},
            "output": json.loads(status_body.decode("utf-8")),
        })

        os.environ["HD2_GWE_EXTRA"] = json.dumps(WARINFO_SPEC, ensure_ascii=False)
        warinfo_body, warinfo_n = m0._warinfo_apply_extra(
            json.dumps(WARINFO_INPUT).encode())
        dump(GOLDEN / "warinfo.json", {
            "counts": {"changed": warinfo_n},
            "output": json.loads(warinfo_body.decode("utf-8")),
        })

        inv_body, inv_added, inv_removed = m0._gwe_inventory_rewrite(
            json.dumps(INVENTORY_INPUT).encode())
        dump(GOLDEN / "inventory.json", {
            "counts": {"added": inv_added, "removed": inv_removed},
            "output": json.loads(inv_body.decode("utf-8")),
        })

        items_body, items_added = m0._gwe_items_rewrite(
            json.dumps(ITEMS_INPUT).encode())
        dump(GOLDEN / "items.json", {
            "counts": {"added": items_added},
            "output": json.loads(items_body.decode("utf-8")),
        })

        cz_body, cz_changed = m0._gwe_customize_rewrite(
            json.dumps(CUSTOMIZE_INPUT).encode())
        dump(GOLDEN / "customize.json", {
            "counts": {"changed": cz_changed},
            "output": json.loads(cz_body.decode("utf-8")),
        })

        print("\nGOLDEN OK（来源：M0 实现 %s）" % ("--legacy 指定" if a.legacy
                                                else "git %s" % M0_REF))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(m0dir, ignore_errors=True)
        os.environ.pop("VMOD_DATA", None)
        os.environ.pop("HD2_GWE_EXTRA", None)


if __name__ == "__main__":
    main()
