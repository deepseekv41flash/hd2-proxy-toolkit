# v0.2.0-alpha.4 — 光能者分组改名（「卡牌 4」→「光能者 4」）+ 打包 GUI 实测（2026-11-17）

> **alpha 预览版 · 只修显示措辞**：版本位不变，`0.2.0-alpha.3` → `0.2.0-alpha.4`。

## 问题（用户提问）

变种选择器里 Illuminate 阵营的分组显示成「**卡牌 4**」，问「为什么会翻译成卡牌」。

追查结论：**这名字不是翻译出来的**，是逐层原样继承的下游数据：

| 环节 | 名字 | 依据 |
|---|---|---|
| 外部 mod「全变种 Quanbianzhong 10.00」目录 | `groups[].name = "卡牌 4"` | 该目录 `note` 明写「选项名称沿用 Quanbianzhong 10.00（玩家熟悉的那一套）」 |
| 研究仓冻结快照（本仓库数据上游） | `卡牌 4` | `variant-net/rollback/variant_catalog.json.orig` |
| 本仓库生成目录 | `groups[].name` 原样透传 | `tools/gen_catalogs.py` 对分组只拷贝、不翻译 |
| GUI 显示 | 「卡牌 4 · 入侵舰队」= 组名 + 变种名 | `gui/catalogs.py` 的 `variant_entries()` |

而这 4 条变种的 `meta.faction` **全是 `illuminate`**（光能者：入侵舰队 / 无票者大军 / 入侵者 / 窃票者），
官方中文叫「光能者」——组名与阵营不符，属外部目录遗留口径。研究仓与游戏效果数据里都没有
「卡牌」这一命名的出处（`card` 字样 0 命中），因此不能为它背书。

## 本版修复

1. **覆盖层支持分组改名**：`data/sources/variant_overlay.json` 的 `groups` 规则新增 `rename`：
   ```json
   {"match": "卡牌", "rename": "光能者"}
   ```
   - 界面显示改为「**光能者 4**」；原组名保留在 `groups[].source_name = "卡牌 4"`（可追溯）；
   - 组名里的数量后缀仍按实际成员数自动重算（加/减变种都不会写错数字）。
2. **文档口径同步**：`docs/VARIANT-INVENTORY-2026-11-17.md` 阵营列改为「光能者」并加一条口径说明；
   `data/catalogs/README.md` 记录 `rename` 规则与 `source_name`。
3. 生成器对 `rename` 做校验：空字符串会直接报错，不会静默产出半个组名。

## 验证

### 单测

- **399 → 402 passed**：覆盖层 rename 生效 + 原组名留档 + 源数据不被就地修改、空 rename 拒绝、
  Illuminate 组显示名与 `faction` 一致；GUI 选择器标签断言（含「光能者 4 · 入侵舰队」、不再出现「卡牌」）。

### 打包 GUI 实测（计算机操作，非源码版）

用 `cua-driver` 实际操作**打包后的 `hd2proxy-gui.exe`**（alpha.4 构建产物）：

- 五页导航正常；「战况改写」页三处均为一行下拉（变种「共 18 条」、全局效果/星球词条「共 312 条」）；
- 下拉框输入「光能者」→ 计数变 **4/18**，展开列出 **光能者 4 · 入侵舰队 / 无票者大军 / 入侵者 / 窃票者**
  四条（改名生效，不再出现「卡牌」）；
- 选中「光能者 4 · 入侵舰队」→ 提示行显示 `入侵舰队 → ids 1413,1414（illuminate）`，计数恢复 18 条；
- 「选中变种」表 **5 个变种显示 5 行**（自适应生效，不再只露 2 行）；
- 「物品与战备」页：打开即自愈——`目录追加` 从 0 变 **1 条**（`2112173638 · Shear` 的目录行自动配对），
  说明上一版修复在打包产物里同样生效。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.2.0-alpha.4-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.2.0-alpha.4-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。
注意：更新 `D:\mod\release-test` 前先关掉正在运行的 GUI（它会锁住 `current/` 里的文件）。

## 已知限制（alpha）

- 本版只改分组显示名与文档口径；变种 id、注入逻辑、效果数据均未变；
- 分组名数量后缀依赖覆盖层的 `append`/成员数；将来若直接在源目录改成员，仍需重跑 `tools/gen_catalogs.py`；
- 抓包保存的是**改写前**原始响应；`Mission/Session`（重连）`8012016` 不承诺。
