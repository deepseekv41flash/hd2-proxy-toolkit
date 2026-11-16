# data/catalogs — 数据目录

由 `tools/gen_catalogs.py` 从三个**只读**研究仓一次性生成并固化进本仓库；运行时不再依赖旧仓。
全部文件 UTF-8（无 BOM）、`ensure_ascii=False`、`indent=1`、主键排序，同源重跑字节一致。
条目数为 2026-11-16 生成快照（`build.json.game_build = 26568081`）。

## 文件与来源

| 文件 | 条目 | 逻辑来源 | 说明 |
|---|---:|---|---|
| `build.json` | 5 字段 | 手工常量 + `variant_mod/variant_catalog.json` 的 build | `game_build=26568081`、`war_id=warseason=801`；`generated_from.variant_mod` 记录旧变种目录的 build（25988413） |
| `variants.json` | 25 变种 / 5 组 | `variant_mod/variant_catalog.json` | 分组保留 `exclusive`；`items` 覆盖目录全部变种（含未分组的实验项），保留 `tag`/`mechanic`/`help`；`aliases` 为简称→正式名，供界面搜索 |
| `stratagems.json` | 58 | `variant_mod/stratagem_catalog.json` | type32「临时配发战备」；每项保留 `id/name/key/native_hash/effect_hash/group` 全部原字段 |
| `effects.json` | 312 | `variant-net/out/effects-full.csv` + `variant-net/out/effect-menu.csv` | 两表 `effect_id` 完全对齐；数值/解码字段取 effects-full，`presence`/`race`/`display_name` 等展示字段取 effect-menu |
| `planets.json` | 438（273 有游戏索引） | `repo-datamined/out/planet/planet-index.json` + `index-names-801.json` | 主键 `index` = **planet_data 行号**；`game_index` = 游戏索引（Status/warinfo/写 profile 用），休眠星为 null；附 `x`/`y` 星图坐标；`settings_hash` 全为 null（见下） |
| `items.json` | 1671 | `variant-net/refs/{armor_rows_parsed,store-cosmetics-20261106,unreleased_candidates}.json` + `variant-net/configs/` 与 `variant_mod/runtime/` 的 `inventory_*.json`、`items_inject.json` | 物品解锁搜索用；`mix_id` 为库存键、`item_id` 为目录内容 id |

## 口径与已知坑

- **items.json 的两套 id**：外观表（`armor_rows_parsed.json`）行 id 是目录 **itemId**；商店表/库存配置的 id 是 **mixId**。同一数值同时出现在两套 id 时按同一物品合并（依据 `variant-net/docs/UNLOCK-MAP-2026-11-06.md` §8.2：外观表简单件 `itemId == mixId`；本次 2 例：`1808786641`、`1513263450`）。
  - 排序：先按 `mix_id` 升序；只有 `item_id` 的记录排在最后、按 `item_id` 升序。
  - `source`：单来源写字符串，多来源合并为去重数组（逻辑名，不含绝对路径）。
  - `name`：只取源里已解出的名字（外观表/商店表），没有就是 null（不编造）；优先 Title-Case 写法。
  - `category`：按来源文件的粗分类（`weapon` / `attachment` / `cosmetic` / `stratagem`），**不是**游戏内 `progressionCategory` 原字段；`inventory_probe` 混多个 cat，记 null。
- **effects.json**：`live_planets` 保留 effects-full 的原始文本（可能被截断，如「…共9」），未解析成 index 列表。
- **planets.json**：`repo-datamined/out/planet/planet-data.json` 中**没有** `settingsHash` / `settings_hash` 字段（438 条已递归确认键名），因此 `settings_hash` 全部为 null；每次生成日志都会打印该结论。
- **`index` 是行号，不是游戏索引（M4 实机踩坑）✗**：`planet_data` 行按名字字母序排列、共 438 行，只有 273 颗在战场上；游戏里的 `planetStatus.index` / `planetActiveEffects.index` 是**压缩后的游戏索引**，行号与它偏移不是常数（如行 79 = TERREK = 游戏 76；行 180 = GACRUX = 游戏 171）。权威映射来自 `repo-datamined/out/planet/index-names-801.json`（`warinfo planetInfos + planet_data tail hashmap` 对齐产物），生成时按 `row` 合并进 `game_index`，文件头写 `game_index_source`。
  - **写 profile / 调引擎一律用 `game_index`**；`index` 只用于回查离线资料（名称/生态/坐标）。
  - 休眠星（165 行）没有游戏索引：`game_index` 为 null，休眠星模板用自选节点号（如 BICEP=300）+ 目标行自己的 `settingsHash` 补身份。
  - 星球身份（星图名字/生态）由 **`settingsHash`** 决定，不是 `index`：拿错行的 hash 会把节点显示成另一颗星（M4 实机：300 号注 TRANDOR 的 hash → 显示 BALDRICK PRIME）。
- **variants.json**：`faction` 原样保留（含跨阵营实验项，如 `gloom_cross`）；仅当源里缺 `faction` 时才按 `presence` 前缀推断。

## 生成命令

```bash
python tools/gen_catalogs.py
# 换机器复现（源路径可覆盖；默认值由脚本按仓库位置推导，见脚本顶部注释）：
python tools/gen_catalogs.py --variant-mod <variant_mod> --variant-net <variant-net> --datamined <repo-datamined> --out <out-dir>
```

缺任何必需源文件时脚本**报错退出（exit 1）**，不会静默产出空表；全部构建成功后才统一落盘。
脚本每个输出打印一行 `wrote <path> entries=<N>`（`build.json` 的 entries 为顶层字段数）。

## 更新时机

游戏 build 变化时（`build.json.game_build` 或 `variants.json.build` 变化）重跑本脚本并复查 diff；
研究仓产物更新（effects CSV / planet-index / refs / 库存配置）同样重跑，`README` 中的条目数随之刷新。

## 已知缺口（M1/M3 补齐，不影响 M0 门禁）

| # | 缺口 | 影响 | 补法（已定方向） |
|---|---|---|---|
| 1 | `planets.settings_hash` 全 null | 能力 6「生态借用」需要「源星球的 settingsHash」 | **产品侧以运行时为准**：代理可见 `warinfo.planetInfos[].settingsHash`，GUI 导入一次 live warinfo 即可得到当前 build 的合法 hash；离线 dl_bin 路线只作研究参考 —— `refs/dlbin/plaintext-26251122/generated_planet_data.dl_bin` 可解（438 行 / 438 个非零 hash，行号=index），当前 build `baseline-26568081` 是封包态，需先解封才能直读 |
| 2 | `items.name` 仅约 391/1671 有名字 | 物品解锁界面搜索只能按 id/部分名字 | M1 数据管道补名称表：外观/商店表已有；武器/附件/战备名需从研究仓命名与本地化产物补 |
| 3 | `effects.live_planets` 保留原始文本 | 不能按「当前在线星球」过滤效果 | 解析成 index 列表（effects-full 文本可能被截断，需与 `planet-live.csv` 交叉） |
| 4 | `variants.json.build = 25988413`，落后当前 build 26568081 | 变种 id 是否随 build 漂移未复核 | 每次 build 变更重跑并对照研究仓的 effect id 表；GUI 显示 build 不一致警告 |

> 这些缺口的共同原则：**宁可字段为 null 并显式记录，也不编造**；界面在缺数据时降级（只按 id 搜索 / 要求导入 live warinfo），不假装可用。
