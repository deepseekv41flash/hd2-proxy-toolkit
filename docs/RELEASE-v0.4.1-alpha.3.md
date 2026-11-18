# v0.4.1-alpha.3 — 战备名字补齐（wiki 已发布清单对账，cat11 73 → 95 有名）（2026-11-19）

> **alpha 预览版 · 数据补全（非新功能）**：只动 `alpha.N`（`0.4.1-alpha.2` → **`0.4.1-alpha.3`**）。

## 背景

v0.4.1-alpha.2 之后，目录 3020 行里 cat11「战备许可」仍有 35 行没有名字。
用户要求对照 wiki 的 [Stratagems](https://helldivers.wiki.gg/wiki/Stratagems) 页，
把**已发布**的战备里「我们还没建立 id↔名字对应关系」的全部找出来并补齐；
口径明确排除 `Other` / `Unavailable` 类型与 `Orbital Confetti`、`Eagle Fly By`
（Liberty Day 2026 限时，不在解锁列表）。

## 对账结论

| 项 | 数量 |
|---|---:|
| wiki 7 个 Permit 表已发布战备（去重、排除上述） | **95** |
| 其中能在本地目录找到行（id 已知） | **95 / 95** |
| 对账前已有名字 | 73 |
| **只缺名字（本版补的对象）** | **22** |
| 缺 id | **0** |

即「缺口 100% 在名字侧」。另外 13 行 cat11 不是已发布战备
（`Eagle Rearm` / `Resupply` / `Medical Supplies` / `(NOT USED) Air-to-Air Missiles` /
`(NOT USED) Additional Strafing Runs` / `Orbital Walking Barrage Smoke` /
`Orbital Confetti` / `Eagle Fly By` + 5 行 client 侧无对应哈希的疑似占位行），未动。

### 本版补的 22 条（按类别）

| 类别 | 战备 |
|---|---|
| Orbital（3） | Orbital 120mm HE Barrage、Orbital Airburst Strike、Orbital Precision Strike |
| Eagle（3） | Eagle Airstrike、Eagle Cluster Bomb、Eagle Strafing Run |
| Support Weapon（3） | B/FLAM-80 Cremator、MS-11 Solo Silo、PLAS-45 Epoch |
| Backpack（3） | AX/AR-23 Guard Dog、AX/FLAM-75 Hot Dog、SH-20 Ballistic Shield Backpack |
| Vehicle（3） | EXO-51 Lumberer Exosuit、EXO-55 Breakthrough Exosuit、TD-220 Bastion MK XVI |
| Sentry（6） | A/AC-8 Autocannon Sentry、A/FLAM-40 Flame Sentry、A/LAS-98 Laser Sentry、A/M-12 Mortar Sentry、A/MG-43 Machine Gun Sentry、A/MLS-4X Rocket Sentry |
| Emplacement（1） | E/AT-12 Anti-Tank Emplacement |

## 名字从哪来（不是 wiki 抄名）

名字来自**客户端静态表**，wiki 只用来确定「哪些是已发布、哪些还缺」：

```
cat11 mix_id --parent--> cat10 子行 item（uint32 原生哈希）
            --(+4 列)--> repo-datamined/refs/exports/stratagem_settings.csv 的 client 行
            --> client 内部名（如 "SENTRYS. AUTOCANNON"）
            --> refs/stratagem-display-names.json 的 display_name / wiki_title
```

- 列语义已验证：`+4` 列 == 旧 `data/legacy/stratagem_catalog.json` 的 `native_hash`
  （153 行里 58 条逐一对上，而那 58 条恰好就是该文件的全部战备）。
- 用该链反查 108 条 cat11 行，**100 行命中** client 名；剩余 8 行 client 侧无对应哈希
  （未发布/占位）。
- 名字取 wiki 全名（含代号前缀，与当前游戏内显示一致），同时把 client 原始
  `display_name`（旧名，可能不带代号）一并留在数据文件里便于追溯。

## 数据变化（`data/catalogs/items.json`）

| 项 | 0.4.1-alpha.2 | **0.4.1-alpha.3** |
|---|---|---|
| `items.json` 条目 | 3062 | 3062（不变） |
| 有名字 | 2383 | **2405**（目录行 2378 / 3020） |
| 未解 | 679 | **657** |
| cat11 战备行有名 | 73 / 108 | **95 / 108** |
| `name_source` 种类 | 17 种 | **18 种**：新增 `stratagem-client-settings`（high，显式 id→名字） |

## 工具与测试

- 新增 `tools/apply_stratagem_client_names.py`：把补丁数据（`data/sources/stratagem_client_names.json`）
  写进名称解析快照 —— **只补空位 / 同名幂等 / 异名报错不覆盖 / `--check` 只读**，
  并同步 `coverage` 与 `coverage.name_patches` 记录（分源归因不丢）。
- 新增 6 条单测（`tests/unit/test_apply_stratagem_client_names.py`）；2 条既有断言扩展到新来源。
- **单测 478 passed**（原 472 + 6）；`tools/check_gate.py` **GATE=PASS**。

## 已知边界

- 本轮按用户要求**只补英文名**（现有 73 条是中文名，故目录当前中英混排）；中文译名留待后续批次。
- wiki 侧 Cargo 表没有 id/hash 字段，所以「已发布清单」这一侧是名字唯一对应（92/95 另有哈希链直证，
  3 条按名字唯一对应：`S-11 Speargun` / `Eagle 110mm Rocket Pods` / `LIFT-850 Jump Pack`
  —— 这三条本地本来就有行有名字，不属于缺口）。
- 证据与逐条明细：`docs/CATALOG-NAMES-V5-2026-11-19.md`。

## 安装

同前：下载 `hd2proxy-release.zip` + `SHA256SUMS`，解压后运行 `hd2proxy_gui.exe`；
证书信任/续期流程见 README「快速开始」。
