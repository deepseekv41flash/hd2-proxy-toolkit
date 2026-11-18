# store / season 抓包准备与「补完物品名字」方案（2026-11-18）

> 目标：目录里还有 **871** 行没有名字（cat 0 战团相关 173 / cat 9 横幅 103 / cat 4 套装 76 /
> cat 23 称号 61 / cat 3 外观 60 / cat 2 附件 51 / cat 11 许可 35 …）。用户要求「抓 store/season
> 响应，补完没解出来的项」。本文记录抓包环境、已验证事实、要抓的界面、以及名字真正可能的来源。

## 1. 抓包环境（已就绪）

| 项 | 值 |
|---|---|
| 引擎 | 打包版 `hd2proxy.exe engine`，`passthrough=True`（**纯直通，零改写**，不污染数据） |
| 配置 | `D:\mod\tmp\capture-store-season-20261118\profile-passthrough-capture.json` |
| 抓包目录 | `D:\mod\tmp\capture-store-season-20261118\raw`（`<sha8>_<slug>.json` + `index.txt`） |
| 抓包范围 | 所有 `/api/` 响应体（`paths=["/api/"]`），单文件上限 16 MB；不落 header/token |
| 运行状态 | 监听 `100.67.169.17:443`、控制面 17897、CRL 8080；hosts 已把 API 域名指向本机 |
| 前置 | 证书受信（剩 ~22 h）；游戏启动后请求自动经过代理并落盘 |

抓包实现见 `src/hd2proxy/engine/hooks/capture.py`（白名单路径、gzip 解压、按内容 sha 去重、
只写 body 不写 header）。**只在本机**：不动游戏文件、不改响应。

## 2. 已验证事实：store/season 响应里没有名字

用 2026-11-17 的新号抓包（`D:\mod\tmp\capture-new-account-20261117\raw`，54 份响应，
含 `/api/StoreFront`、`/api/SeasonPass`、`/api/SeasonPass/1929468580`、
`/api/Progression/ProgressionPackages`、`/api/Progression/ItemPackages`、
`/api/Progression/Items/Customize/v2`）逐字段检查：

| 响应 | 内容 | 有名字/locid 吗 |
|---|---|---|
| `/api/StoreFront` | 4 个 storefront → 49 section → 211 个 `{mixId, salesId, position}` | ❌ |
| `/api/SeasonPass` | 26 个赛季：`id32` + `itemIds`(seasonPassItemId) + `premiumTokenMixIds` | ❌ |
| `/api/SeasonPass/{id}` | 10 页：每项 `{seasonPassItemId, itemMixId, gridPosition, medalCost, isPremium}` | ❌ |
| `/api/Progression/ItemPackages` | 57 个包：`itemMixId32` → `[{mixId, amount}]` | ❌ |
| `/api/Progression/ProgressionPackages` | 58 个包：等级奖励 `rewards[].id32` / `unlockableItems` | ❌ |
| `/api/Progression/Items/Customize/v2` | 已装备项（空号为空） | ❌ |

全抓包里带名字/locid 的字段只有战况相关（`GalacticWarEffects.nameHash`、`Status.title`、
`warinfo.planetNameId32`、`NewsTicker`），**与物品目录无关**。
结论：**抓 store/season 不会直接给出物品名字**，它给的是「mixId ↔ 商店货架/债券页 + grid 坐标」
的结构锚点；名字必须另外解（见 §5）。

## 3. 结构锚点对账（用 11-17 抓包跑工具得到）

工具：`python tools/extract_store_season_layout.py --capture-dir <raw> --out <dir>`。

目录无名行 **871**，被 store/season 结构覆盖 **211（24.2%）**：

| cat | 含义 | 无名行 | 有结构锚点 | 锚点来源示例 |
|---:|---|---:|---:|---|
| 0 | 战团（Warbond）相关 | 173 | 59 | `seasonpass:…/premium-token` |
| 9 | 横幅（Banner） | 103 | 24 | `storefront:2776696735/section:975650208/pos(2,1)` |
| 11 | 战备许可 | 35 | 22 | `storefront:124284010/section:…/pos(0,0)` |
| 19/20/21 | 记账条目 | 49/36/32 | 30/30/7 | `progression:<pkg>/reward` |
| 4 | 外观套装 | 76 | 0 | — |
| 23 | 称号 | 61 | 1 | `itempackage:…` |
| 7/8 | Emote / 胜利姿势 | 32/27 | 5/7 | `seasonpass:…/page:n` |
| 5/18 | Booster / 货币 | 10/15 | 9/6 | `itempackage:…` |
| 16 | 无证据类别 | 9 | 8 | `progression:…/reward` |

> 11-17 那次只打开了**当前一个**赛季详情页（`/api/SeasonPass/1929468580`），所以债券页锚点很少。
> 本次把 **26 个赛季全部打开**（游戏里可回看往期债券），锚点会大幅增加。

## 4. 本次要抓什么（游戏内操作清单）

游戏启动后（引擎已在跑、hosts/证书就绪），依次：

1. **商店（Store/Acquisition）**：进入商店，把每个货架/页签/轮换页都点开、滚动一遍（每页停 2–3 秒）；
2. **战争债券（Warbonds / 战争债券页）**：进入债券菜单，**逐个打开全部 26 个赛季**（含往期），
   每个赛季把页面滚到底（每页停 2–3 秒）；顺带进高级版（Premium）页；
3. **自定义（角色外观）**：打开 Helldiver 自定义界面，切到 横幅 / 称号 / Emote / 胜利姿势 页签各停一下；
4. 正常退游戏（或退回主菜单）。**不要**在抓包时开 mod/注入（保持纯直通）。

抓包产物只在本机 `raw\` 目录；`index.txt` 每行 = 时间/路径/字节/sha。

## 5. 名字从哪来（两条路，抓包后按证据选）

1. **新端点 / 客户端本地化表**（直接解名）：
   - 本次抓包先用工具盘点端点，若出现未登记端点（工具会标「可能是新端点」）且带
     `nameHash`/`locid`/`title` 等字段 → 用研究仓的 locid→文本表（`locid-names.json`，
     24,834 条）直接解出名字；
   - 客户端 dlbin 里还有 `EmoteInfo`/`HelldiverCustomizationPieceInfo` 等表未扫 locid，
     若行 id 与目录 mixId 能对上，也能补名（并行研究项）。
2. **截图 + OCR + grid 坐标**（兜底，已验证可行路径）：
   - 抓包给出每个 mixId 在商店/债券页的 `gridPosition` 与页号；
   - 游戏内同一页截图（工具 `chatbot_ocr`，rich layout 可给文本框坐标）→ 按 grid 网格对齐
     「单元格 ↔ 文本框」→ 得到 `mixId → 名字`；
   - 只解析游戏 UI 上真实显示的名字，仍然遵守「不编造」原则。

## 6. 抓完后的分析命令

```bash
# 结构映射 + 端点盘点 + 名字字段扫描 + 无名行对账（输出 layout.json / report.md）
python tools/extract_store_season_layout.py \
  --capture-dir D:/mod/tmp/capture-store-season-20261118/raw \
  --out D:/mod/tmp/capture-store-season-20261118/analysis
```

- `report.md` 会列出：所有端点（已知/新）、任何名字/locid 字段、871 行无名行的锚点覆盖与样例；
- 若确认名字只能靠客户端表/截图，则下一步走 §5.1 或 §5.2，把结果写成
  `data/sources/store_season_names.json`（每条带 `name_source` + `confidence` + 截图/表名证据），
  再由 `tools/gen_catalogs.py` 并入 `items.json`（与现有 6 条名字来源同一机制）。

## 7. 红线

- 抓包必须**纯直通零改写**（本 profile 已设 `passthrough=true`），避免污染数据；
- 抓包产物只在本机分析，不提交账号相关响应（`raw/` 不进仓库）；
- 名字必须有证据来源（客户端表字段 / 游戏 UI 截图 OCR / 本地化 locid）；解析不到就保持 `null`。

## 8. 抓包结果（2026-11-18 实测）

抓包会话完成：73 份响应（`raw/index.txt` 73 行），引擎 pid 8844（抓完后已停止；重启命令见 §1）。
**26 个赛季详情全部抓到**（`/api/SeasonPass/{id}` ×26，页数 10/3/3/3/…），商店侧抓到
`/api/StoreFront`（4 货架）、**新端点** `/api/StoreFront/rotation`、**新端点**
`/api/StoreFront/2776696735`（货架详情，含 section 与 item grid）。合并后：**6 个 storefront /
76 个 section / 329 个 item 位置**；ItemPackages 57、ProgressionPackages 58。

### 8.1 与目录无名行对账（工具：`tools/extract_store_season_layout.py`）

无名行 **871**，有结构锚点 **386（44.3%）**（上次仅 211 / 24.2%）：

| cat | 含义 | 无名行 | 有锚点（本次 / 上次） | 锚点来源 |
|---:|---|---:|---:|---|
| 9 | 横幅 | 103 | **79** / 24 | 债券页 item（grid 坐标） |
| 4 | 外观套装 | 76 | **59** / 0 | 债券页 item（含 premium 标记） |
| 23 | 称号 | 61 | **22** / 1 | 债券页 / itempackage |
| 0 | 战团相关 | 173 | 59 / 59 | 赛季 premiumTokenMixIds |
| 8 | 胜利姿势 | 27 | **26** / 7 | 债券页 item |
| 7 | Emote | 32 | **24** / 5 | 债券页 item |
| 11 | 战备许可 | 35 | 22 / 22 | 商店货架 |
| 19/20/21 | 记账条目 | 49/36/32 | 30/30/7 | 养成包奖励 |
| 5/15/16/18 | 混合 | 10/10/9/15 | 9/3/8/6 | itempackage / progression reward |
| 3/2/6/10/13/14/17 | — | 60/51/23/38/5/1/2 | 0（13/17 各 1：见 §8.2） | — |

> 商店货架里也出现 cat11 战备许可（商店卖许可）；债券页 item 覆盖 cat9/4/7/8/23 最多。

### 8.2 仍然没有名字，但找到「mixId 在客户端有名字表」的直接证据

再次逐字段确认：**store/season 响应不含任何物品名字/locid**。但 `/api/Progression/inventory` 的
`avatarCustomization` **存的是已装备物品的目录 mixId**，且正好落在此前无名的类别上（实测交叉核对）：

| avatarCustomization 槽位 | 值 | 目录对应 |
|---|---:|---|
| `banner` | 3460374366 | **cat9 横幅**（无名） |
| `titleId32` | 926009925 | **cat23 称号**（无名，注意：是 mixId 不是 locid） |
| `victory_pose_index` | 3269065783 | **cat7**（无名） |
| `voice_pack_set` | 4010084743 | **cat13 语音包**（无名） |
| `undergarment_type` | 826373086 | **cat17 内衬**（无名） |

⇒ 游戏客户端**必然存在「mixId → 显示名(locid)」的本地表**（否则 UI 显示不出名字）。
下一步（已派研究子代理并行做）：在 `generated_entities.dl_bin` 等明文 dlbin 里定位
`titleId32`/`banner`/`victory_pose_index` 等槽位所在表，解出 locid → 文本并回填。

### 8.3 工具修复

`extract_store_season_layout.py` 首版把 StoreFront 的三个响应（列表 / rotation / 详情）当成
同一个 base 互相覆盖（少算 4 个货架 + rotation）；已改为**合并**，并新增
`avatarCustomization` 槽位提取（`titleId32` 单独记为 locid 候选）。单测覆盖合并逻辑与 name 字段检测。

### 8.4 兜底路线（若 dlbin 表找不到）

用本次抓包的 **grid 坐标** + 游戏内截图 OCR 对齐（§5.2）：每个 `seasonpass:<id>/page:<n>/pos(x,y)`
对应 UI 一格；截图（rich layout OCR 给文本框坐标）→ 网格对齐 → `mixId → 名字`。需要再跑一次
「开债券页 + 截图」的短会话。

## 9. v3 命名路线：名字在客户端 `game.dll`（进行中，2026-11-18 晚）

研究子代理在**当前 build 26568081 的 `game.dll`**（`<游戏安装>\data\game\game.dll`，约 49 MB）里
定位到按 mixId 排列的客户端表，并用目录 mixId 对齐验证（本人独立复核了偏移/命中数）：

| 类别 | 表位置 / stride | 行 id 命中 catalog | 名字字段 |
|---|---|---|---|
| cat9 横幅 | `0x2C7FEF0` / `0x18` | **75/103** ✓ | +0x10 大写名 locid、+0x14 标题式名 locid |
| cat8 胜利姿势 | `0x2CB4CF0` / `0x80` | 25~27/27 ✓ | +0x3C / +0x40 |
| cat21 礼包 | `0x2CAD240` / `0x38` | **8/8** ✓ | 行内名字 locid |
| cat15 资源（SAMPLE） | `0x2C953B0` / `0x40` | **3/3** ✓ | 行内名字 locid |
| cat13 语音包 | `0x2CB02C8` 附近 4 行 + `0x2C6A510` 1 行 | 5/5（子代理） | 行内 locid |
| cat16 难度 | 子代理报「难度表」 | 9 行（子代理） | 行 +0x08 |
| cat0 战团 | game.dll 战团表 | 26 个战团 | 战团名 locid（结合 SeasonPass premiumTokenMixIds → medium） |
| cat23 称号 | **mixId 本身即 locid**（如 926009925） | 38/61 | 直接查 strings |

已排除：cat7（Emote）/ cat17（内衬）/ cat19 / cat20 的 mixId 不出现在 game.dll / 其它 exe·dll /
`generated_entities.dl_bin` 任何本机二进制的 u32 里（逐个扫过）；cat19/20 只出现在奖励 id 数组（无名字字段）。

正在做：解析**当前 build 的 30 个 bundle `.strings`**（旧语料是 26088809 build 的 24,834 条），
补新 locid（称号/横幅标题式名等），预计 v3 在 v2 已命名 2164 基础上 **+150~180**，
产出 `resolved_v3.json` + `report-v3.md`（含每类证据与失败路径）。

### 集成流程（v3 到货后）

```bash
cp D:/mod/tmp/catalog-names/v3/resolved_v3.json data/sources/catalog_names_resolved.json
python tools/gen_catalogs.py          # 名字进 items.json（name/name_source/name_confidence）
python -m pytest tests/unit -q && python tools/check_gate.py
```

版本按数据补全（非新功能）走 `fix` 位：`0.4.1-alpha.1` → **`0.4.1-alpha.2`**。
