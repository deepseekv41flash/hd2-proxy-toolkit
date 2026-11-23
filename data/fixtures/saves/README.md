# 存档夹具（G2 存档系统离线样本）

两套真实抓包的**响应体**（6 个存档端点），用于离线验证存档合并语义、G3–G5 的写回路径，
以及避免把未脱敏的原始抓包目录整份拷进产品仓（见交接档死路清单）。

## 来源与日期

| 目录 | 账号 | 抓包日期 | 方式 |
|---|---|---|---|
| `main/`  | 主号（老玩家，有完整进度） | 2026-11-18 | 本工具只读抓包钩子 `engine/hooks/capture.py` |
| `fresh/` | 空号（新建账号，经验 1） | 2026-11-17 | 同上 |

* 只保留 **body**：没有 header / token / sessionId / accountId / SteamID64。
  `tests/unit/test_save_fixtures.py` 有守门断言，防止以后误把带身份的响应提进来。
* `Progression` 里的 `shipName` 是整数代号、`location` 是 `{warId, planetIndex, …}`，都不是身份信息。

## 文件

| 文件 | 端点 | main | fresh |
|---|---|---|---|
| `progression.json` | `GET /api/Progression` | 12 921 B · `experience=2759938` | 1 500 B · `experience=1` |
| `inventory.json` | `GET /api/Progression/inventory` | 69 120 B · 970 行 | 3 267 B · 55 行 |
| `customize_v2.json` | `GET /api/Progression/Items/Customize/v2` | 15 853 B · 74 行 | 12 B · 0 行 |
| `stats_profile.json` | `GET /api/Stats/profile/summary` | 730 B | 644 B |
| `stats_profile_801.json` | `GET /api/Stats/profile/801/summary` | 730 B | 644 B |
| `season_pass.json` | `GET /api/SeasonPass/1929468580` | 14 589 B | 14 589 B |

## 结算样本（G3）

`mission_end/`：**5 份真实 `POST /api/Operation/Mission/end` 响应**（2026-11-18 主号会话），
G3 的奖励入账就吃这些字段：

| 文件 | 大小 | `experience`（本局增量） | badges | `rewards` 条数 | 备注 |
|---|---|---|---|---|---|
| `12b9a872.json` | 1 577 B | 936 | 9 | 2 | 典型一局 |
| `15998437.json` | 1 201 B | 267 | 6 | 2 | |
| `d0bdbe5b.json` | 1 213 B | 258 | 6 | 2 | |
| `dd2350f7.json` | 1 664 B | 903 | 10 | 2 | |
| `e899f6af.json` | 560 B | 0 | 1 | 0 | 空结算（exp=0 / 无奖励）|

已剥掉 `progressionPackageUpdates[].platformAccountId`（研究线占位是全 0，但字段名就是身份痕迹）。

**口径实据**：5 份里恒有 `rewards[3608481516] == sum(badges[].itemRewards[3608481516]) × 3`
（1478→4434 / 346→1038 / 334→1002 / 1534→4602，倍数来自响应里的 `multipliers.factor`），
而 `rewards[897894480]` 与明细相同 ⇒ `rewards` 是**最终入账**、`badges` 是明细。
G3 默认按 `rewards` 入账（`hooks/mission_end.ITEM_SOURCE`），实机对一次账若不符可一处切回 `badges`。

## `Progression/items` 目录签名（文件不入仓）

目录每份 560 KB，只用于 G2 的 `catalog_build`（口径 `<items_sha8>/<items_rows>/<clientVersion>`），
所以只记签名、不存正文：

| 账号 | items sha256 前 8 | 行数 | 大小 |
|---|---|---|---|
| main  | `93e7575a` | 3021 | 560 112 B |
| fresh | `d71655e6` | 3020 | 559 950 B |

11-16 / 11-17 两个账号的目录逐字节相同（`d71655e6` / 3020 行）；11-18 主号多一行
（`itemId=2688443218`）⇒ 目录随 build 漂移，这正是 `catalog_build` 要记录它的原因。
需要重算时从对应抓包目录 `*_api_Progression_items.json` 取原始 body 算 sha256 + 行数。

## 两条实测结论（夹具里能看到）

* `season_pass.json` 两账号**逐字节相同**（`039ff10e` / 14 589 B）⇒ 季票元数据是账号无关的
  静态数据，不能当"这个号买了什么"的证据；
* `stats_profile.json` 与 `stats_profile_801.json` 同账号内容相同（同一份 summary 两路径都返回）。
* `fresh/customize_v2.json` 是 `{"items":[]}` —— 空号还没有任何改装槽快照，
  G2/G5 的"补条目"路径要能处理空数组。

## 用法

```python
import json
from pathlib import Path
from hd2proxy.engine import saves

body = (Path("data/fixtures/saves/main/progression.json")).read_bytes()
out, changed = saves.apply_to_progression(body, saves.empty_save())     # 空档 → 0 处改动
```

守门测试：`tests/unit/test_save_fixtures.py`（行数/大小/无身份字段/空档不虚增）+
`tests/unit/test_mission_end.py`（结算解析/口径/坏 body）。
新增或替换夹具时请同步更新上面的表格。
