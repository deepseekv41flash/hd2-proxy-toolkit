# data/catalogs — 数据目录

由 `tools/gen_catalogs.py` 从三个**只读**研究仓 + 本仓库的变种覆盖层一次性生成并固化进本仓库；
运行时不再依赖旧仓。全部文件 UTF-8（无 BOM）、`ensure_ascii=False`、`indent=1`、主键排序，
同源重跑字节一致。条目数为 2026-11-18 生成快照（`build.json.game_build = 26568081`）。

同一次生成还会产出引擎读的 `data/legacy/variant_catalog.json`（与 `variants.json` 同源，
只是键名/顺序沿用引擎老格式）——两份目录不再手工同步，避免漂移。

**2026-11-18（v0.4.0-alpha.1）起 `items.json` 覆盖服务端目录全量 3020 行**（此前 1950 行）：
行集唯一权威是 `data/sources/progression_item_catalog.json`（与账号无关，主号/新号抓包逐字节一致）；
补进来的行带 `in_catalog` / `default_owned` 标记，没解析出名字的 `name=null`、类别无证据的
`category="unknown"`——**绝不编造名字或类别含义**（规则见下「口径与已知坑」）。
文件顶层另有 `catalog` 覆盖统计段（GUI「目录总览」直接读它）。

## 文件与来源

| 文件 | 条目 | 逻辑来源 | 说明 |
|---|---:|---|---|
| `build.json` | 5 字段 | 手工常量 + `variant_mod/variant_catalog.json` 的 build | `game_build=26568081`、`war_id=warseason=801`；`generated_from.variant_mod` 记录旧变种目录的 build（25988413） |
| `variants.json` | 26 变种 / 5 组 | `variant_mod/variant_catalog.json` + `data/sources/variant_overlay.json` | 分组保留 `exclusive`；`items` 覆盖目录全部变种（含未分组的实验项），保留 `tag`/`mechanic`/`help`；`aliases` 为简称→正式名，供界面搜索。虫族组 7 个（2026-11-17 从覆盖层补 **腐蚀变种** [1430,1431] / **毒瘴变种** [1434,1433]，见 `docs/VARIANT-INVENTORY-2026-11-17.md`）；覆盖层还可 `rename` 组名（原组名存 `source_name`）：Illuminate 组在源目录叫「卡牌 4」，按阵营改为「光能者 4」 |
| `stratagems.json` | 58 | `variant_mod/stratagem_catalog.json` | type32「临时配发战备」；每项保留 `id/name/key/native_hash/effect_hash/group` 全部原字段 |
| `effects.json` | 312 | `variant-net/out/effects-full.csv` + `variant-net/out/effect-menu.csv` | 两表 `effect_id` 完全对齐；数值/解码字段取 effects-full，`presence`/`race`/`display_name` 等展示字段取 effect-menu |
| `planets.json` | 438（273 有游戏索引） | `repo-datamined/out/planet/planet-index.json` + `index-names-801.json` | 主键 `index` = **planet_data 行号**；`game_index` = 游戏索引（Status/warinfo/写 profile 用），休眠星为 null；附 `x`/`y` 星图坐标；`settings_hash` 全为 null（见下） |
| `items.json` | 3062（**2405 有名字**，目录行 2378/3020；3020 = 服务端目录全量，42 = 目录外研究线/未上架） | `variant-net/refs/{armor_rows_parsed,store-cosmetics-20261106,unreleased_candidates}.json` + `variant-net/configs/` 与 `variant_mod/runtime/` 的 `inventory_*.json`、`items_inject.json`；名字补全用 `data/sources/progression_item_catalog.json` + `data/sources/item_names_derived.json`；附件行按 `progression_item_catalog.json` 的 cat2 全量补齐（旧注入子集只有 1176 行） | 物品解锁搜索用；`mix_id` 为库存键、`item_id` 为目录内容 id；`catalog_category` = 服务端目录类别（2 附件 / 3 外观 / 11 战备…），`name_source` = 名字出处（`catalog-option` 附件选项内部名 / `armor-table` 外观表 / `loadout-entity` dlbin 实体内部名）。**附件行额外带 `parent_id` / `parent_name` / `option_id`**：`parent_id` = 该附件所属武器的目录 mixId、`parent_name` = 武器内部名、`option_id` = 附件选项 id（多把枪共享，**故不写进 `item_id`**，否则合并阶段会「一对多 id」报错）；界面据此做「一级武器 → 二级配件」两级筛选。**`unlock_template`**（仅 3 把「服务端目录里没有」的未发布武器）：克隆哪条同族目录记录来上架（= 模板 itemId）——库存行不配目录行客户端不显示，界面加库存时自动配对；配对值来自 `data/sources/unreleased_items.json`，生成器会校验模板行确实在目录快照里。**目录补全三字段**（2026-11-18）：`in_catalog`=该行是否在服务端 `/api/Progression/items` 目录里（目录外 42 条为 false、其中 3 条带 `unlock_template`）、`default_owned`=空号（未解锁任何东西）也拥有（55 条，来自 `data/sources/fresh_account_inventory.json`；附件 optionId 被大量共享，**只在该 itemId 在目录里唯一时**才按 itemId 补标，否则会从 55 误标到 150）、`name_source` 除原有三源（`catalog-option`/`armor-table`/`loadout-entity`）外新增 `loadout-entry`、`boosters`、`stratagem-hash`、`stratagem-permit-child`、`armor-set-child`（v2，结构推断带 `name_confidence`）；v5 新增 `stratagem-client-settings`（cat11 战备许可行的客户端 `stratagem_settings` 表名字，`+4`==原生哈希直证，high；战备行有名 73 → **95/108**）；v3 再新增 **客户端 game.dll 静态表来源**：`dlbin-banner-table`、`dlbin-victory-pose-table`、`dlbin-voice-table`、`dlbin-resource-sample-table`、`dlbin-item-pack-table`、`dlbin-difficulty-table`、`dlbin-warbond-table` 与 `locid-id`（mixId 本身即 locid）。文件名解析快照见 `data/sources/catalog_names_resolved.json`（v3 基线 + v5 补丁，补丁记录在 `coverage.name_patches`），证据见 `docs/CATALOG-NAMES-2026-11-18.md`、`docs/CATALOG-NAMES-V3-2026-11-18.md` 与 `docs/CATALOG-NAMES-V5-2026-11-19.md` |

## 本仓库内输入（不是研究仓）

| 文件 | 用途 |
|---|---|
| `data/sources/variant_overlay.json` | 变种目录覆盖层（源变种目录冻结后新增/改名的变种，如 腐蚀变种 / 毒瘴变种） |
| `data/sources/progression_item_catalog.json` | 服务端 `/api/Progression/items` 抓包的紧凑索引（3020 行 `mix`→`item`/`cat`/`parent`，含原始抓包 sha256）。`parent` 是 cat2 附件行的**所属武器 mixId**（1455 行全有），附件按枪解锁的产品数据就靠它；生成器 `tools/extract_catalog_index.py` |
| `data/sources/unreleased_items.json` | 「服务端目录里没有、靠克隆模板上架」的物品配对（`mix` → `template` itemId，值来自研究线 M4 实机验证：LAS-22 / P-41 / SG-8F）。由 `tools/gen_catalogs.py` 校验模板行在目录快照里后写进 `items.json` 的 `unlock_template` |
| `data/sources/item_names_derived.json` | **LoadoutEntry 物品内部名（dlbin 只读路线产物）**：`generated_entities.dl_bin` 的 `LoadoutEntryComponentData` 行 `+0x00`(=目录 itemId) → 实体内部名（武器/投掷物/背包）。生成器 `tools/extract_item_names.py`，换 build 重跑即可 |
| `data/sources/catalog_names_resolved.json` | **目录名称解析快照 v2（3020 行）**：每行的 `name`/`name_source`/`confidence` + `category_meaning`（服务端 progressionCategory → 语义类别，附证据出处）+ `coverage` 统计。来源 = items.json 内部名 / dlbin LoadoutEntry 实体 / boosters 表 三条显式路线，+ 战备目录 hash 对表、战备许可 1:1 子行、外观套装同名子行 三条**结构推断**路线；**解析不到就留空**，推断名标 medium/low。生成器只读它、不会联网。研究侧生成脚本与报告见 `docs/CATALOG-NAMES-2026-11-18.md` |
| `data/sources/fresh_account_inventory.json` | **空号库存基线（55 行）**：新账号首次进游戏时 `Progression/inventory` 的 mixId 列表（`{note, source, capture_sha256, count, mix_ids}`）。生成器用它标 `default_owned`（空号已有 ⇒ 解锁工具不必再添加）；抓包证据 = 2026-11-17 新号抓包（研究侧目录，不进仓库） |

## 口径与已知坑

- **items.json 的两套 id**：外观表（`armor_rows_parsed.json`）行 id 是目录 **itemId**；商店表/库存配置的 id 是 **mixId**。同一数值同时出现在两套 id 时按同一物品合并（依据 `variant-net/docs/UNLOCK-MAP-2026-11-06.md` §8.2：外观表简单件 `itemId == mixId`；本次 2 例：`1808786641`、`1513263450`）。
  - 排序：先按 `mix_id` 升序；只有 `item_id` 的记录排在最后、按 `item_id` 升序。
  - `source`：单来源写字符串，多来源合并为去重数组（逻辑名，不含绝对路径）。
  - `name`：只取源里已解出的名字（外观表/商店表），没有就是 null（不编造）；优先 Title-Case 写法。
  - `category`：按来源文件的粗分类（`weapon` / `attachment` / `cosmetic` / `stratagem`），**不是**游戏内 `progressionCategory` 原字段；`inventory_probe` 混多个 cat，记 null。
- **服务端目录全量并入（2026-11-18，v0.4.0-alpha.1）✗ 不要手改数据文件**：`items.json` 现在 =
  服务端目录 **3020 行** + **42 条目录外条目**（研究线未上架的老条目，`in_catalog=false`）。补行规则
  （全在 `tools/gen_catalogs.py`，改规则要改脚本再重跑）：
  - **名字**：为「目录里有行但 items 里没名字」的行补（含已有条目缺名的情况）；只认
    `data/sources/catalog_names_resolved.json` 快照（三条显式路线 + 三条结构推断路线逐行匹配），
    解析不到就 `name=null` —— **不编译、不音译、不按顺序猜**；推断来源在条目上带 `name_confidence`。
  - **类别**：`progressionCategory` → 语义类别先按「已有物品的多数类别投票（≥60%）」推断，再用快照里的
    `category_meaning` 补空缺（每个 cat 的证据出处见 `docs/CATALOG-NAMES-2026-11-18.md`）；仍无证据 =
    `category="unknown"` 且保留 `catalog_category` 编号（界面显示「未分类 catN」，不臆测含义）。
  - **`default_owned`**：来自空号基线 55 个 mixId；按 `itemId` 补匹配**只允许该 itemId 在目录里唯一**时
    （附件 optionId 被成百上千行共享，泛匹配会把 55 误标成 150，实测踩过）。
  - **GUI**：「物品与战备」页第 6 个只读 tab「目录总览」直接读本文件的 `catalog` 覆盖段与每行
    `in_catalog` / `default_owned`；汇总行/类别筛选/「默认已有」「目录缺」标记都来自这里。

- **附件解锁粒度是「武器 × 附件」，不是「附件」✗**：同一附件挂在多把武器下时各有独立 `mix_id`（`TUBE REDDOT 1,5x` 覆盖 38 把枪 = 38 个 mixId），库存按 mixId 逐行拥有 ⇒「A 枪已解锁」不等于「B 枪的同名配件已解锁」。
  - 实证：某账号 `Progression/inventory` 969 条里拥有 cat2 **280/1455**、只覆盖 **47/57** 把枪。
  - 界面「一级选武器 → 添加到库存」= 按该武器全部附件行的 mixId 批量解锁（去重、报告新增/已存在），**不做**全局同名 option 解锁。
- **effects.json**：`live_planets` 保留 effects-full 的原始文本（可能被截断，如「…共9」），未解析成 index 列表。
- **planets.json**：`repo-datamined/out/planet/planet-data.json` 中**没有** `settingsHash` / `settings_hash` 字段（438 条已递归确认键名），因此 `settings_hash` 全部为 null；每次生成日志都会打印该结论。
- **`index` 是行号，不是游戏索引（M4 实机踩坑）✗**：`planet_data` 行按名字字母序排列、共 438 行，只有 273 颗在战场上；游戏里的 `planetStatus.index` / `planetActiveEffects.index` 是**压缩后的游戏索引**，行号与它偏移不是常数（如行 79 = TERREK = 游戏 76；行 180 = GACRUX = 游戏 171）。权威映射来自 `repo-datamined/out/planet/index-names-801.json`（`warinfo planetInfos + planet_data tail hashmap` 对齐产物），生成时按 `row` 合并进 `game_index`，文件头写 `game_index_source`。
  - **写 profile / 调引擎一律用 `game_index`**；`index` 只用于回查离线资料（名称/生态/坐标）。
  - 休眠星（165 行）没有游戏索引：`game_index` 为 null，休眠星模板用自选节点号（如 BICEP=300）+ 目标行自己的 `settingsHash` 补身份。
  - 星球身份（星图名字/生态）由 **`settingsHash`** 决定，不是 `index`：拿错行的 hash 会把节点显示成另一颗星（M4 实机：300 号注 TRANDOR 的 hash → 显示 BALDRICK PRIME）。
- **variants.json**：`faction` 原样保留（含跨阵营实验项，如 `gloom_cross`）；仅当源里缺 `faction` 时才按 `presence` 前缀推断。

## 生成命令

```bash
# 0) 先重生成 data/sources/ 的两个快照（换 build / 新抓包时）
python tools/extract_catalog_index.py --gwe-dir <抓包目录>   # → data/sources/progression_item_catalog.json（mix/item/cat/parent）
python tools/extract_item_names.py --build 26568081          # → data/sources/item_names_derived.json（LoadoutEntry 内部名）
#    手工维护的 data/sources/unreleased_items.json（目录缺失物品的模板配对）随目录一起被 gen_catalogs 读取

# 0.5) 目录名字/类别快照（只读研究仓数据表；输出 data/sources/catalog_names_resolved.json）
python tools/resolve_catalog_names.py --work-root <mod>/work --out data/sources/catalog_names_resolved.json

# 1) 目录本体（默认读 data/sources/ 的三份快照：目录索引 / 名称解析 / 空号库存基线）
python tools/gen_catalogs.py            # 同时写 data/catalogs/*.json 与 data/legacy/variant_catalog.json
python tools/gen_catalogs.py --no-legacy  # 只写 GUI 目录
# 覆盖输入路径（默认值见脚本常量 DEFAULT_*）：
python tools/gen_catalogs.py --catalog-index <catalog.json> --resolved-names <resolved.json> --fresh-inventory <fresh.json>
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
| 2 | 物品名字/类别覆盖：名字 **2383/3062**（目录行 2356/3020），未解 **679 行**；类别语义未解 **512 行** | 未解行显示 mixId +「未分类 catN（内部名未解）」；无证据类别不做臆测归类 | 剩余名字缺口：cat0 144 / cat9 38（28 疑似未发布）/ cat3 60（外观表本身无名）/ cat4 76 / cat2 51（未发布改装选项）/ cat23 23（旧 strings 语料缺 locid）/ cat7 32 / cat19 49 / cat20 36 / cat11 35；cat7/17/18/19/20 已穷举确认本机无名字表（需截图 OCR 或新 build/新语料）；当前 build 的 30 个 `.strings` 已全部解包复核，英文本地化 24,834 条与旧 build 逐 id 相同（新增 0），cat9 剩的 10 行 / cat23 剩的 23 行是「服务器目录领先客户端内容」（未发布），**语料路线已到尽头**，只能等新 build 或截图 OCR |
| 3 | `effects.live_planets` 保留原始文本 | 不能按「当前在线星球」过滤效果 | 解析成 index 列表（effects-full 文本可能被截断，需与 `planet-live.csv` 交叉） |
| 4 | `variants.json.build = 25988413`，落后当前 build 26568081 | 变种 id 是否随 build 漂移未复核 | 每次 build 变更重跑并对照研究仓的 effect id 表；GUI 显示 build 不一致警告 |

> 这些缺口的共同原则：**宁可字段为 null 并显式记录，也不编造**；界面在缺数据时降级（只按 id 搜索 / 要求导入 live warinfo），不假装可用。
