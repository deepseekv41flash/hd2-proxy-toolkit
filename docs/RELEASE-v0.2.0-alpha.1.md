# v0.2.0-alpha.1 — 「附件」改成两级：按武器筛选 + 一键解锁该武器全部配件（2026-11-17）

> **alpha 预览版**：新增功能 ⇒ 版本位 `0.1.1` → `0.2.0`，阶段重置为 `alpha.1`。

## 本版新增

「物品与战备 · 附件」tab 改成**两级菜单**（依据：附件解锁是「武器 × 附件」粒度，
同一附件在不同枪上是不同 mixId —— 见 `work/variant-net/docs/UNLOCK-MAP-2026-11-06.md`）：

| 层级 | 内容 | 操作 |
|---|---|---|
| **一级** | 只列**武器**（57 把，带配件数：`Adjudicator · 28 件`、`Breaker · 46 件` …） | 选中武器 → 二级展开该武器配件 |
| **二级** | 该武器的**具体配件**（内部名：`Vertical Grip Flashlight`、`Urban Camo` …） | 选中某条 → 「添加到库存」只加这一条 |
| 一级直选 | 不选二级、只选一级武器 | 直接点「添加到库存」= **一次解锁该武器全部配件** |

细节：

- **批量解锁去重**：已在列表里的 mixId 会跳过，toast 报告「新增 N，已存在 M」；
- **关键词搜索跨武器**：输入配件名（如 `TUBE REDDOT`）→ 二级列出全部命中（标签带武器名）；
  清空关键词再点「搜索」= 回到按武器浏览；
- 数量输入对批量解锁同样生效（每条配件加同样的数量）；
- 一级列表每行显示配件数，方便判断哪把枪的配件多。

## 数据补全

附件目录原先只收了研究注入用到的 1176 条，本版补到**全量 1455 条 / 57 把武器**
（`items.json` 1671 → **1950** 条），每条附件新增：

| 字段 | 含义 |
|---|---|
| `parent_id` | 所属武器的 mixId（目录 `parentId`） |
| `parent_name` | 武器内部名（1411/1455 已解；其余显示 `武器 #0x…`） |
| `option_id` | 附件选项 id（元数据，不参与合并） |

新工具 `tools/extract_catalog_index.py`：把 `/api/Progression/items` 抓包压成
`data/sources/progression_item_catalog.json`（3020 行 `mix→item/cat/parent`，含抓包 sha256），
换 build 重跑即可；`tools/gen_catalogs.py` 据此补全附件行。

## 验证

- 单测 **380 → 386**：两级导航、一键解锁全部 + 去重、二级单条添加、跨武器搜索、
  附件分组数据层（1455/57）、目录索引带 parent；
- GUI 实拍：一级 57 把武器、选中 `Adjudicator` 后二级 28 个配件，提示行写明「直接点添加到库存 =
  解锁全部；选中某条则只加那一条」。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.2.0-alpha.1-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.2.0-alpha.1-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。
注意：更新 `D:\mod\release-test` 前先关掉正在运行的 GUI（它会锁住 `current/` 里的文件）。

## 已知限制（alpha）

- 武器名来自实体内部名（LoadoutEntry），3 把武器没有内部名 → 一级列表显示 `武器 #0x…`；
- 51 条附件本身没有内部名（改装选项表未覆盖）→ 二级列表显示「附件（内部名未解）」；
- 战备（30 条）仍显示「内部名未解」（解锁 itemId 与本地数据无已知映射，需抓 store/season 响应）；
- 抓包保存的是**改写前**原始响应；`Mission/Session`（重连）`8012016` 不承诺。
