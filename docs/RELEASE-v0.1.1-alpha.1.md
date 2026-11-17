# v0.1.1-alpha.1 — 「物品与战备」显示物品内部名（不再只有 id）（2026-11-17）

> **alpha 预览版**：本次是**小规模功能更新**（界面可读性），版本位从 `0.1.0` 升到 `0.1.1`，
> 阶段重置为 `alpha.1`。上一版 `v0.1.0-alpha.5` 的变种目录补齐仍然有效。

## 本版改了什么

「物品与战备」页的四个 tab（武器 / 附件 / 外观 / 战备）和「目录追加」，原来物品列表只显示
`4591677 · attachment` 这种「id + 英文类别」；1671 条物品里只有 391 条有名字，其余**无法辨认**。

现在给物品补**内部名**（本地化译名暂不做，工作量太大）：

| 类别 | 名字来源 | 例子 |
|---|---|---|
| 附件 | 服务端目录行 `itemId` = 武器改装选项 id → 改装选项内部名 | `TUBE REDDOT 1,5x`、`Vertical Grip Advanced`、`HOLOGRAPHIC SIGHT` |
| 外观 | 目录行 `itemId` = 外观表行 id → 外观表 names | `Arctic Decree` |
| 武器 / 战备 / 其它 | 目录行只有 id，本机**没有**可用名字来源 | 显示 `xxx · 战备（内部名未解）`，不编造 |

效果：

- 物品列表 / 已加入列表都显示 `mixId · 内部名`；
- 搜索框可按内部名搜索（搜 `reddot`、`vertical grip` 直接命中，原来只能按 id 搜）；
- 覆盖率：**1520 / 1671**（原 391 / 1671）；剩余 151 条是武器 21、战备 30、新版附件 49、
  目录外条目 51 —— 界面明确标「内部名未解」，不影响已有功能。

## 数据与可复现性

- 新增仓库内数据源 `data/sources/progression_item_catalog.json`：`GET /api/Progression/items`
  抓包的**紧凑索引**（3020 行：mixId → itemId / progressionCategory，带原始抓包 sha256），
  不参与运行时，只给生成器补名字用；
- 名字对照表：repo-datamined 的 `weapon-customization-options-26251122.json`（附件选项内部名）、
  variant-net 的 `armor_rows_parsed.json`（外观表）；
- `data/catalogs/items.json` 每条新增 `catalog_category`（目录类别：2=附件 / 3=外观 / 11=战备…），
  解析出名字的再带 `name_source`（`catalog-option` / `armor-table`）；
- 重跑：`python tools/gen_catalogs.py`（确定性输出；生成日志会打印名字覆盖数）。

## 已知限制

- 剩余 151 条无名字：武器/战备的目录 id 与本地表没有已知映射；49 条附件是武器改装选项表
  （build 26251122 解析产物）里没有的新选项。要补齐需要再做一次「目录 id ↔ 本地表」的定位工作。
- 内部名是**开发/内部命名**（如 `TUBE REDDOT 1,5x`、`Desert Solid`），不是玩家界面的中文名；
  同名附件会出现在多把武器下（`mixId` 不同），列表用 id 区分。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.1-alpha.1-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.1-alpha.1-windows-x64.zip -Algorithm SHA256
```

## 升级提示

- 覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）；
- 打开「物品与战备」即可看到名字；想找某个附件直接搜内部名关键词（如 `grip`、`reddot`）。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看日志里 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 效果目录 `effects.json` 仍是 26088801 快照（312 条）；新 id 1432–1434 在效果表里没有名字
  （界面显示 `1434 · ?`，不影响注入）。
