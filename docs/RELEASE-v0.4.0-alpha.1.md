# v0.4.0-alpha.1 — 服务端物品目录全量做进产品（3020 行 · GUI「目录总览」· 空号默认 55）（2026-11-18）

> **alpha 预览版 · 新功能**：按版本规则动 minor 位（`0.3.0-alpha.3` → **`0.4.0-alpha.1`**）。

## 背景

「物品与战备」页的物品列表来自 `data/catalogs/items.json`，此前只覆盖 **1950 行 / 服务端目录 3020 行**：
缺口 1112 行在界面上不可见，已有行里也有大量「只有 mixId、没有名字」。用户要求把目录做完整。

关键前提（已证）：**服务端物品目录与账号无关** —— 主号与新号两次抓包
`GET /api/Progression/items` 响应 **sha256 逐字节一致**（`d71655e6a47b70a6db1c1ab3ac57cd78aa038c6a79b2924b03af83f9114f4dff`，
559,950 B，3020 行）。所以缺的不是「再抓一次」，而是**名字/类别加工与界面呈现**。

## 数据变化

| 项 | 之前（0.3.0-alpha.3） | 现在（0.4.0-alpha.1） |
|---|---|---|
| `items.json` 条目 | 1950 | **3062**（3020 目录行 + 42 目录外研究线条目） |
| 在服务端目录里 | 1908/3020 | **3020/3020** |
| 有名字 | 1821 | **2191**（目录行 2164；另 27 条目录外条目本来就有名） |
| 类别语义未解（`unknown`） | — | 512 行（保留服务端 cat 编号，界面显示「未分类 catN」） |
| 名字置信度 | — | high 1927 / **medium 263 / low 1**（推断名带 `name_confidence`，见下） |
| 空号默认拥有 | 未标 | **55 项**（`default_owned`） |
| 附件 | 1455 行 / 57 把武器 | 不变（1455 / 57，一键按武器解锁的粒度照旧） |
| GUI tab | 5 个 | **6 个**（新增只读「目录总览」） |

目录行类别的语义分布（3020 行口径）：附件 1455 · 外观 682 · 武器 115 · 战备 108 · 强化资源 30 ·
徽章 103 · 货币 15 · 未分类 512。

## 三条铁律（本版的核心，不是「尽量」）

1. **不编造名字**：只用**只读**路线逐行匹配 —— ① items.json 已有内部名 ② dlbin
   `LoadoutEntryComponentData` 实体内部名（`item_names_derived.json`）③ boosters 表；
   第二批再补两条**结构证据**路线：④ 战备目录 (effect_hash, native_hash) 与 effects.json GWE
   `values_raw[0]` 对表（cat10 记账行 → 战备名；cat11 许可按 1:1 子行取名）、⑤ 外观套装行取其
   全部同名子行的名字（cat4）。解析不到就 `name=null`，界面显示 `mixId · 类别（内部名未解）`。
   推断出来的名字在数据里带 `name_confidence`（medium/low），不冒充显式映射。
2. **不臆测类别含义**：`progressionCategory` → 语义类别先按「已有物品的多数类别投票（≥60%）」推断，
   再用名称解析快照里的 `category_meaning`（**每个 cat 都有证据出处**，见
   [CATALOG-NAMES-2026-11-18.md](CATALOG-NAMES-2026-11-18.md)）补空缺；仍无证据 = `unknown`。
   本版由证据新增三类：`booster` 强化资源（cat 5）、`banner` 徽章（cat 9）、`currency` 货币（cat 18）。
3. **`default_owned` 只按证据标**：来源是空号（新账号未解锁任何东西）的库存基线 55 个 mixId。
   按 `itemId` 补匹配**只允许该 itemId 在目录里唯一**时生效 —— 附件 optionId 被成百上千行共享，
   泛匹配会把 55 误标成 150（本版第一版实测踩到并收紧，单测锁定）。

## GUI：新增只读「目录总览」tab

「物品与战备」页第 6 个 tab：

- **汇总两行**：`服务端目录 3020 行（与账号无关）· 界面条目 3062（目录内 3020 + 目录外 42）` /
  `已命名 2191 · 未解 871 · 空号默认拥有 55 · 目录行类别：附件 1455 · 外观 682 · …`；
- **类别筛选**：全部 / 武器 / 附件 / 外观 / 战备 / 强化资源 / 徽章 / 货币 / 未分类 /
  仅空号默认拥有 / 仅目录外（可追加）；
- **全量列表 3062 条不截断**，标签比编辑列表多两处信息：有名字的行补类别（`… · TUBE REDDOT 1,5x（附件）`）、
  `默认已有`（空号就有，解锁工具不必再加）、`目录缺`（服务端目录里没有，需要走「目录追加」）；
- **只读**：本页不解锁/不追加任何东西，切 tab 不写 profile（单测断言 `app.dirty` 不变）。
- 物品页顶部汇总行同时并入 `｜ 目录 3020 行 · 命名 2191 · 空号默认 55`。

前 5 个 tab 行为不变（四个编辑 tab 只显示各自类别；「目录追加」仍是写 profile 的老通道）。

## 数据源与生成器

| 文件 | 变化 |
|---|---|
| `data/catalogs/items.json` | 3062 条；每行新增 `in_catalog` / `default_owned`；顶层新增 `catalog` 覆盖统计段 |
| `data/sources/catalog_names_resolved.json` | **新增**：3020 行名称解析快照 v2（`name`/`name_source`/`confidence` + `category_meaning` 证据 + `coverage`）；名字来源除显式映射外含战备 hash 对表 / 许可子行 / 套装子行三类推断（medium 263 / low 1） |
| `data/sources/fresh_account_inventory.json` | **新增**：空号库存基线 55 个 mixId（附抓包 sha256） |
| `tools/gen_catalogs.py` | 新增目录补全阶段（`_complete_catalog_items` / 类别投票 / 名称快照 / 空号基线）与 `--resolved-names` / `--fresh-inventory`；修 `cat 0` 被 `int(x or -1)` 变成 -1、itemId 兜底匹配索引错误两个 bug |
| `tools/resolve_catalog_names.py` | **新增**：目录名字/类别解析快照生成器（只读研究仓数据表、离线、确定性；产物 `data/sources/catalog_names_resolved.json`） |
| `tools/gui_smoke.py` | 新增 `--tabs`：逐 tab 截图（含新的「目录总览」），供发布证据 |
| `docs/CATALOG-NAMES-2026-11-18.md` | **新增**：3020 行的名字来源/置信度与每个 `progressionCategory` 语义证据台账 |

`data/catalogs/*` 仍是**生成产物**：要改数据请改 `tools/gen_catalogs.py` + `data/sources/*` 后重跑
（同源重跑字节一致），不要手改 JSON。

## 验证

- 单测 **445 → 468 passed**：
  - 目录补全纯函数 12 条（补行不编名字 / 快照只填空缺 / 默认标记收紧 / itemId 唯一才补 / 类别投票 ≥60% /
    快照缺失降级）；
  - 真实数据验收 9 条（3020/3020、3062、55、42、附件 1455/57、`catalog` 段与 GUI 汇总一致、
    未命名行显式标注、默认项与空号基线一一对应、类别标签注册）；
  - GUI 目录总览测试 1 条（tab 顺序、3062 条不截断、类别筛选、默认/目录缺标记、只读不变脏）；
  - 旧测试口径更新：战备条数从写死 30 改为按数据算；cat1 名字来源接受 `loadout-entry` 同族。
- `python tools/check_gate.py` → **GATE=PASS**（5/5 离线自检 + 版本/语法/路径/单测）。
- `python tools/gui_smoke.py --pages inventory --tabs` → 6 个 tab 截图正常（目录总览汇总/筛选/标记可见）。
- 数据不变量：3020/3020、3062、55、42、附件 1455/57、目录行已命名 2164、名字来源三类推断全部带
  `name_confidence`（测试 `test_inferred_names_carry_confidence` 锁定）。

## 打包版实机验证（计算机操作，非源码版）

用 `HD2PROXY_SIGN=1 python tools/build_dist.py` 构建的 `dist\hd2proxy\` 实测（本机自签，签名
status=Valid），覆盖本次新增的 GUI 与数据：

| 场景 | 结果 |
|---|---|
| 启动打包版 `hd2proxy-gui.exe`（无控制台窗口） | 主窗口「HD2 战况代理工坊」正常；总览页渲染正常，引擎未运行时有现场检查红字提示 ✓ |
| 切「物品与战备」页 | **6 个 tab** 全部渲染：武器 / 附件 / 外观 / 战备 / 目录追加 / **目录总览**；顶部汇总行含「目录 3020 行 · 命名 2191 · 空号默认 55」✓ |
| 点「目录总览」tab | 汇总两行正确：`服务端目录 3020 行（与账号无关）· 界面条目 3062（目录内 3020 + 目录外 42）` / `已命名 2191 · 未解 871 · 空号默认拥有 55 · 目录行类别：附件 1455 · 外观 682 · 武器 115 · 战备 108 · 强化资源 30 · 徽章 103 · 货币 15 · 未分类 512`；列表 **3062/3062 条**，条目带类别与「默认已有」标记 ✓ |
| 列表关键词过滤（输入 `reddot`） | **71/3062** 条，全部是 `TUBE REDDOT 1,5x / 2x` 变体且标签带类别（附件）✓ |
| 类别筛选切「武器」 | 「当前「武器」118 条」，列表只剩武器条目（有名字的直接显示名字，无语义的显示「武器（内部名未解）」）✓ |
| 打包数据完整性 | 打包内 `data/catalogs/items.json` 与仓库生成物 **3062 条、sha256 一致**；`hd2proxy.exe --version` = `0.4.0-alpha.1`，`--version/info/preview` 构建自检均 OK ✓ |
| 控制台窗口回归（alpha.2 修复） | GUI 全程 **180 s / 3496 次采样（50 ms 间隔）**，新出现的可见控制台类窗口（ConsoleWindowClass / CASCADIA_HOSTING_WINDOW_CLASS / PseudoConsoleWindow）**0 个** ✓ |

截图（打包版实机）：`research/screenshots/alpha4-packaged-catalog.png`（目录总览全量）、
`alpha4-packaged-catalog-search.png`（reddot 过滤 71 条）、`alpha4-packaged-catalog-weapons.png`
（类别筛选「武器」118 条）、`alpha4-packaged-inventory.png`（物品页 6 个 tab）。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.4.0-alpha.1-windows-x64.zip` | onedir 分发包（解压即用，17.6 MB） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```text
7dd4fcbbb34b25b41cddb80df8b06e75e80767b9da95f92764656629a6a7a4bf  hd2proxy-toolkit-v0.4.0-alpha.1-windows-x64.zip
300aabb0a90b017a0d65cabe65d26eed63f0e0e88ec6df186aafd3cf72855ffb  hd2proxy/hd2proxy.exe
0bfe86588f945d4e1791dd4b8d38b80c5d3d07cb6023e1d27e04458b61843a09  hd2proxy/hd2proxy-gui.exe
```

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.4.0-alpha.1-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置与证书在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响；profile 格式未变）。
升级后打开「物品与战备 → 目录总览」即可核对完整目录。

## 已知限制（alpha）

- 名字仍是 **2191/3062**（目录行 2164/3020）：cat 0（战团相关）173 行、cat 9（徽章）103 行、cat 4 剩余 76 行、
  cat 11 剩余 35 行、cat 23（称号）61 行、cat 19/20/21/7/8 等记账/Emote/姿势行在本地只读数据里
  **没有 id→名字映射**，需要抓 store/season 响应才能补；本地化中文名只有战备/部分套装名有（目录里其余内部名是英文）。
- 类别未解 **512 行**（cat 0/6/10/13/14/15/16/17/19/20/21/23）：研究数据里没有语义证据，按规则记
  `unknown` 并保留 cat 编号，不臆测；其中 cat 10 的 73 行已有名字（战备 hash 对表，medium），
  名字照给、类别仍 unknown。
- 42 条**目录外**研究线条目（`in_catalog=false`，含 3 条带 `unlock_template` 的未上架武器）行为不变：
  仍走「目录追加」的克隆模板通道。
- 引擎侧上游偶发超时（多 IP 重试）仍是待办，未包含在本版。
