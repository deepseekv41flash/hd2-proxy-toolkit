# v0.4.1-alpha.2 — 补完物品名字（客户端 game.dll 静态表路线，命名 2191 → 2383）（2026-11-18）

> **alpha 预览版 · 数据补全（非新功能）**：只动 `alpha.N`（`0.4.1-alpha.1` → **`0.4.1-alpha.2`**）。

## 背景

v0.4.0-alpha.1 把服务端目录 3020 行全量做进产品后，仍有 **871 行没有名字**
（cat 9 横幅 103 / cat 4 套装 76 / cat 23 称号 61 / cat 3 外观 60 / cat 2 附件 51 / cat 11 许可 35 …）。
按计划先抓了 store/season 响应（26 个战争债券详情 + 商店 6 货架/76 section/329 item 位置），
**验证了 API 响应只有 id/布局、没有名字**；但它给出了结构锚点（871 行里 386 行有 grid 定位），
并暴露了关键线索：`/api/Progression/inventory.avatarCustomization` 存的是已装备物品的**目录 mixId**
（banner/title/pose/voice/undergarment），说明「名字在客户端」。

## 本版做法：去客户端 `game.dll` 静态表取名字

对当前 build **26568081** 的 `<游戏安装>\data\game\game.dll`（49,075,800 B）逐表扫描，
找到「行 id 与目录 mixId 精确相等、且带名字 locid 字段」的静态表，用本机本地化语料
（`strings` 24,834 条，旧 build 26088801）解析 locid → 文本：

| 类别 | 表 / 结构 | 行 id 命中 | 新增命名 |
|---|---|---:|---:|
| cat 9 横幅 | `0x2C7FEF0` stride `0x18`（+0x10 大写名 locid、+0x14 标题式） | 75/103 | **+65**（high） |
| cat 23 称号 | `mixId` 本身就是名字 locid（`strings[mixId]`） | 38/61 | **+38**（high） |
| cat 8 胜利姿势 | `0x2CB4CF0` stride `0x80`（名字 +0x3C/+0x40） | 27/27 | **+27**（high） |
| cat 0 战团 | game.dll 战团表（26 个 warbond id→名）+ SeasonPass `premiumTokenMixId` 配对 | 26 | **+27**（medium） |
| cat 6 记账条目 | id=locid 约定 | 13 | **+13**（medium） |
| cat 21 礼包 | `0x2CAD240` stride `0x38`（短名 +0x0C/+0x10）+ id=locid | 12 | **+12**（medium） |
| cat 13 语音包 | `0x2CB02C8` 起 4 行 + `0x2C6A510` 1 行 | 5/5 | **+5**（high） |
| cat 15 资源 | `0x2C953B0` stride `0x40`（SAMPLE 名） | 3/3 | **+3**（high） |
| cat 16 难度 | 难度表 `+0x08` 名 locid | 2/9 | **+2**（medium） |

**交叉验证**（与抓包里的已装备项一一对应，全部命中）：
`banner 3460374366 → Patient Zero's Rememberance`、`titleId32 926009925 → ADMIRABLE ADMIRAL`、
`voice_pack_set 4010084743 → Default Helldiver Voice 2`。

## 数据变化（`data/catalogs/items.json`）

| 项 | 0.4.1-alpha.1 | **0.4.1-alpha.2** |
|---|---|---|
| `items.json` 条目 | 3062 | 3062（不变） |
| 有名字 | 2191 | **2383**（目录行 2356 / 3020） |
| 未解 | 871 | **679** |
| 名字置信度 | medium 263 / low 1 | **medium 317 / low 1**（high 2002） |
| `name_source` 种类 | 9 种 | **+7 种**（`dlbin-banner-table` / `dlbin-victory-pose-table` / `dlbin-voice-table` / `dlbin-resource-sample-table` / `dlbin-item-pack-table` / `dlbin-difficulty-table` / `dlbin-warbond-table` / `locid-id`） |

GUI 无需改动：`items.json` / `catalog_names_resolved.json` 同机制读取；未解行仍显示
`mixId · 类别（内部名未解）`，类别无证据的仍显示「未分类 catN」。

## 已穷举的失败路径（这些类别确实没有本地名字表）

- **cat 7（Emote 32）/ cat 17（内衬 2）/ cat 19（49）/ cat 20（36）/ cat 18（15）**：其 mixId 不在
  `game.dll` / `runtime.dll` / `helldivers2.exe` / 全部 `data/game/*.dl_bin` /
  `generated_entities.dl_bin` 中以「行 id + 名字字段」形式出现（cat19/20 只在奖励 id 数组里，无名字字段；
  cat17 仅在 116B 的 `body_settings` 里出现，无名）。
- cat 9 剩余 38 行：28 行根本不在客户端 banner 表（疑似未发布内容）、10 行缺旧语料文本；
- cat 23 剩余 23 行：旧 strings 语料没有这些 locid。
- **仍在进行**：当前 build 的 30 个 bundle `.strings` 解包（已解 5 个），解完可再补 cat9 约 10 行 +
  cat23 部分（对 cat7/17 无效——它们缺表不缺口文本）。

## 验证

- 单测 **472 passed**（更新 3 条：类别-来源同族约束扩展到 v3 的 dlbin 表来源；`name_confidence`
  规则覆盖新来源；unknown 类别命名行的标签断言兼容「默认已有」标记）。
- `python tools/check_gate.py` → **GATE=PASS**。
- 数据不变量：3020 行、目录内 2356 行已命名、55 空号默认、42 目录外、附件 1455/57 均不变。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.4.1-alpha.2-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.4.1-alpha.2-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置/证书/profile 都不受影响）。升级后打开「物品与战备 → 目录总览」可见
「已命名 2383」；战备、横幅、称号、胜利姿势、语音包、资源等类别里新增名字直接可见。

## 已知限制（alpha）

- 名字是**英文客户端内部名/显示名**（Banner 大写风格、Title 大写风格），本地化中文名仍不做；
- 未解 **679 行**分布见上「失败路径」；cat 2 附件剩余 51 行是未发布改装选项、cat 3 剩余 60 行是
  外观表本身无名，需等新数据/新 build；
- 引擎侧上游偶发超时（多 IP 重试）仍是待办。
