# 服务端物品目录 3020 行：名字解析与 `progressionCategory` 语义证据（2026-11-18）

> 对应版本：[v0.4.0-alpha.1](RELEASE-v0.4.0-alpha.1.md)（v2 快照）；v3 增量（客户端 game.dll 静态表，命名 2164→2356）见 [CATALOG-NAMES-V3-2026-11-18.md](CATALOG-NAMES-V3-2026-11-18.md)。
> 产物：`data/sources/catalog_names_resolved.json`（v2 快照，**2164/3020 行有名字**）+ `coverage` +
> 每个类别的 `category_meaning`（含证据出处）；生成器 `tools/resolve_catalog_names.py`（只读、离线、确定性）。
> 数据落地：`tools/gen_catalogs.py` 读这份快照把目录 3020 行并入 `data/catalogs/items.json`。

## 1. 为什么需要这份快照

服务端 `GET /api/Progression/items`（build 26568081，3020 行）只有 id 与类别编号，没有名字：

```json
{"mixId": 4591677, "itemId": 1128110989, "parentId": 3388344762, "progressionCategory": 2}
```

目录本身**与账号无关**（主号 / 新号两次抓包响应 sha256 逐字节一致：
`d71655e6a47b70a6db1c1ab3ac57cd78aa038c6a79b2924b03af83f9114f4dff`），所以补名字只能靠
本机只读数据表逐行匹配 —— 匹配不到就留空，**绝不允许编译/音译/按顺序猜**。

## 2. 数字口径（避免把「覆盖行数」当成「已命名行数」）

| 数字 | 口径 | 说明 |
|---:|---|---|
| **3020** | 服务端目录行数 | 唯一权威行集：`data/sources/progression_item_catalog.json` |
| **1794** | 旧 `items.json` 里已命名的目录行 | v1 之前的基线（`mix_id`/`item_id` 精确；`option_id` 只对 cat2 使用） |
| **1908** | 旧 `items.json` 的**覆盖**行数 | 有 entry 即算，其中 114 行名字为空；**不是**命名数 |
| **1800** | ✗ 错误口径 | 把 cat0 行也拿 `itemId` 去撞 `option_id` 列，多出 6 行跨类别同 id 撞车 |
| **2164** | **本快照命名的目录行数** | = 1794 + v1 新增 138 + v2 新增 232（-18 替换不改计数） |
| **2191** | `items.json` 的 `named` | 2164 目录行 + 27 条目录外条目本来就有名字 |
| **856** | 仍未命名的目录行 | 见 §6 |

## 3. 每个 `progressionCategory` 的语义与证据

`label` 只取生成器认识的 7 个值；**语义有证据 ≠ 必须给 label**：枚举里没有对应值时宁可
`label=null` 并在 `zh`/`evidence` 写清语义（例：cat0 是战团相关条目，硬塞 cosmetic/currency 都会误导）。

| cat | 行数 | 已命名 | label | 语义 | 置信 | 证据出处 |
|---:|---:|---:|---|---|---|---|
| 0 | 173 | 0 | null | 战团（Warbond）相关条目集合（含解锁/记账行） | high | UNLOCK-MAP §10.3 表；§R7 实机：注入 119 条 → 全部 Warbond 解锁 |
| 1 | 115 | 107 | `weapon` | 武器/可装备装备（LoadoutEntry 类） | high | UNLOCK-MAP §10.3；结构：cat2 附件行 1455/1455 的 parent 都是 cat1 |
| 2 | 1455 | 1404 | `attachment` | 武器附件/改装选项 | high | API-ENDPOINTS：`progressionCategory==2 且带 parentId` = 附件解锁行；UNLOCK-MAP §8/§10.3 |
| 3 | 427 | 367 | `cosmetic` | 外观（护甲/头盔/披风等） | high | UNLOCK-MAP §8 外观实机（真购买+注入）、§10.3、API-ENDPOINTS |
| 4 | 196 | 120 | `cosmetic` | 外观套装/涂装组（cat3 外观件的 parent 套装行） | medium | UNLOCK-MAP §10.3、R6 实机（注入 166 条 → 载具涂装选项）；结构 272 条 cat3 行 parent=cat4 |
| 5 | 30 | 20 | `booster` | Booster（配装增益） | high | UNLOCK-MAP §10.3、R2 实机 = Booster；`BOOSTER-COMPLETE` 表（cat5=30） |
| 6 | 23 | 0 | null | 记账/占位条目（注入无 UI 变化） | high | UNLOCK-MAP §10.3、R8 实机 23 条全注入无变化 |
| 7 | 32 | 0 | `cosmetic` | Emote（动作/表情） | high | UNLOCK-MAP §10.3、R5 实机 = Emote；label 归 cosmetic 是归类判断 |
| 8 | 27 | 0 | `cosmetic` | 胜利姿势（VICTORY POSE） | high | UNLOCK-MAP §10.3、R3 实机 = 胜利姿势、§9.2 更正 cat7→cat8 |
| 9 | 103 | 0 | `banner` | 横幅（Banner） | medium | UNLOCK-MAP §10.3 语义表（**未实测**）；按 avatarCustomization 推断同属 UI 类 |
| 10 | 111 | 73 | null | 战备许可（cat11）下的子项/记账行（UI 不可见） | medium | UNLOCK-MAP §10.3、R1 实机 108 条全注入 → 无 UI 变化；结构 108/111 行 parent=cat11 |
| 11 | 108 | 73 | `stratagem` | 战备许可（Stratagem Permit） | high | UNLOCK-MAP §9.2 实机：注入 30 条 → 约 30 个战备可用、§10.3；API-ENDPOINTS |
| 13 | 5 | 0 | null | 语音包（Voice Pack） | medium | UNLOCK-MAP §10.3（R11 合并注入无差异） |
| 14 | 1 | 0 | null | **无证据** | none | UNLOCK-MAP 只写「未知」；R11 无差异；输入表无该类别线索 |
| 15 | 10 | 0 | null | 资源类条目（用途未定） | medium | UNLOCK-MAP §10.3 |
| 16 | 9 | 0 | null | **无证据** | none | UNLOCK-MAP 类别台账（§10.1/§10.3）**没有 cat16**；API/表结构文档亦无 |
| 17 | 2 | 0 | null | 内衬（Under-suit） | low | UNLOCK-MAP §10.3（仅 2 行） |
| 18 | 15 | 0 | `currency` | 货币（Requisition / Super Credits / Medals） | high | API-ENDPOINTS：Requisition 行 `progressionCategory 18`、超商扣费两行均 cat18 |
| 19 | 49 | 0 | null | 记账条目（无 UI 可见变化） | high | UNLOCK-MAP §10.3、R9 实机 19 条全注入无差异 |
| 20 | 36 | 0 | null | 记账条目（曾假设等级奖励，无 UI 证据） | high | UNLOCK-MAP §10.3、R10 实机 6 条全注入无差异 |
| 21 | 32 | 0 | null | 记账条目（无 UI 可见变化） | high | UNLOCK-MAP §10.3、R4 实机 32 条全注入无变化 |
| 23 | 61 | 0 | null | 称号（Title） | medium | UNLOCK-MAP §10.3（**未实测**） |

> 证据文件：`variant-net/docs/UNLOCK-MAP-2026-11-06.md`、`variant-net/docs/API-ENDPOINTS-2026-11-01.md`
> （研究仓只读引用；实机台账行号见快照 `category_meaning[cat].evidence`）。
> 生成器只在「类别投票 ≥60%」没有结论时才使用这里的 label，两者都无 = `unknown`（本版 512 行）。

## 4. 名字来源与置信度

| 来源 | 行数 | 置信 | 说明 |
|---|---:|---|---|
| `catalog-option` | 1404 | high | cat2 附件行的 `itemId` = 改装选项 id → 选项内部名（`weapon-customization-options` 表） |
| `loadout-entity` | 24 | high | dlbin `LoadoutEntryComponentData` 行 → 实体内部名（`item_names_derived.json`，武器/投掷物/背包） |
| `armor-table` | 2 | high | 外观表行 id → 外观名（`armor_rows_parsed.json`） |
| `boosters` | 20 | high | `boosters-26088801.json` 的 itemId → 名字 |
| `loadout-entry` | 100 | 86 high + 14 medium | LoadoutEntry 内部名：cat1 同类别命中 = high；cat10 跨类别命中 = medium |
| `armor-set-child` | 118 | 117 medium + 1 low | cat4 套装行 = 全部同名 cat3 子行的名字（≥2 子行 medium、仅 1 子行 low） |
| `stratagem-hash` | 59 | medium | cat10 行 `mixId`=战备 `effect_hash` 且 `itemId`=`native_hash`，或 `mixId`=GWE `values_raw[0]` → 战备显示名 |
| `stratagem-permit-child` | 73 | medium | cat11 战备许可与 cat10 子行严格 1:1，用子行的战备名命名 |

- 显式映射优先、且**已有非空名字永不覆盖**；推断来源在 `items.json` 里带 `name_confidence`
  （medium 263 / low 1），不冒充显式映射。
- **不使用** `unreleased_items.json` 的 `template` 当名字：那是「克隆哪条已有目录行」的模板 id，
  用它命名会把已有武器错标成未发布武器（研究线 M4 已验证）。
- 战备名取战备目录的**显示名**（部分未翻译保持英文大写），因此目录里战备/部分套装名可能是中文，
  其余仍是内部英文名；本地化不追求统一（避免再引一层翻译表）。

### v2 相对 v1 的增量（+232）

| cat | 行数 | v1 已命名 | v2 已命名 | 新增来源 |
|---:|---:|---:|---:|---|
| 4 | 196 | 2 | **120** | `armor-set-child` 118 |
| 10 | 111 | 32 | **73** | `stratagem-hash` 59（41 填补 + 18 替换原 loadout 名）+ `loadout-entry` 14 保留 |
| 11 | 108 | 0 | **73** | `stratagem-permit-child` 73（59 战备显示名 + 14 子行 LoadoutEntry 内部名） |

## 5. 试过但零增益的来源（别再重复挖）

| 来源 | 结论 |
|---|---|
| `armor_rows_parsed.json`（389 个有名 id） | 命中 cat3 367 行，全部已被 `items.json` 覆盖 → 边际 0 |
| `store-cosmetics-20261106.json`（4 个有名 id） | 全部已被覆盖 → 边际 0（但验证了「套装名=子行名」规则 2/2） |
| `weapon-customization-options`（252 个 optionId） | cat2 已满；剩余 51 行 cat2 的 optionId 不在该表 → 边际 0 |
| `locid-names.json`（6 张表）/ `entity-locid-names.json` / `loadout-entry.json` / `table-row-names.json` / `pod-rack-aliases.json` / `stratagem-display-names.json` / `stratagem-alias.json` / `wiki/*` | 键都是 locid 哈希 / 实体 u64 哈希 / 行序 / 人工别名，**没有目录 `mixId/itemId` 键**；与 3020 行 id 交集 = 0 |
| `unreleased_candidates.json` | 15 个 id、无名字；与目录行交集 0 |

## 6. 仍无名字的 856 行（分布）

| cat | 无名行数 | 缺口原因 |
|---:|---:|---|
| 4 | 76 | 套装行无名字表；有 2 个外部证据样本（DP-8/SS-500）但剩余行没有同名子行 |
| 0 | 173 | 战团相关条目无名字表 |
| 9 | 103 | 横幅无本地名字表 |
| 11 | 35 | 许可 id ↔ 战备名未解的部分（战备目录只有 58 条 + effects 命中 83 条） |
| 23 | 61 | 称号无本地名字表 |
| 3 | 60 | 外观表本身无名（披风等）+ 33 行外观表无名行 |
| 2 | 51 | 新改装选项不在本地 option 表 |
| 19 / 20 / 21 / 7 / 8 / 6 | 49 / 36 / 32 / 32 / 27 / 23 | 记账类 / Emote / 胜利姿势，无名字表 |
| 10 | 38 | 战备 hash 未覆盖的子项 |
| 18 / 15 / 5 / 16 / 1 / 13 / 17 / 14 | 15 / 10 / 10 / 9 / 8 / 5 / 2 / 1 | 货币/资源/无定义 Booster/无证据类别等 |

> 这些都需要**新的本地化/商店/战备表或抓包**才能补，不靠猜。cat14 / cat16 连类别语义都无证据。

## 7. 复跑方式

```bash
# 默认按脚本位置探测 <mod>/work（研究仓与产品仓并列），输出 resolved.json
python tools/resolve_catalog_names.py

# 显式指定工作根与输出（推荐；v2 语义即当前快照）
python tools/resolve_catalog_names.py --work-root <mod>/work --out data/sources/catalog_names_resolved.json
```

- **只读**：只以读模式打开输入；除 `--out` 外不写任何文件，绝不写产品仓/游戏目录。
- **不联网**：无网络调用、无第三方依赖（纯标准库）。
- **确定性**：无随机/时间戳，`indent=1` 固定；输入内容 sha256 写进快照 `sources`，换输入才变。
- **自检断言**（任一失败非零退出）：行数 3020、`by_cat` 合计 = total、`by_source` 合计 = named、
  `named + unresolved = total`、有名必有来源、`confidence ∈ {high,medium,low}`、`label` 只出现 7 值枚举或 null。
- 注意：当前 `items.json` 已并入快照，直接复跑时「来源归因」会几乎全部变成 `items.json`（名字集合不变）；
  复现本次归因需把 `--items` 指向集成前的 1950 条版本（v1 交付时实测 `rows` 逐字节一致）。
