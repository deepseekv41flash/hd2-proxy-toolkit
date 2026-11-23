# v0.5.3-alpha.1 — 存档层 G6：存档预演（2026-11-23）

> **功能版本**：`X.Y.Z` 变化（`0.5.2-alpha.1` → **`0.5.3-alpha.1`**）。

## 背景

到 `0.5.2-alpha.1`，本机账本已经会：识别玩家、首屏渲染、换号回滚、结算奖励累加、终身统计与成就合并。
但所有效果的**验收点都是"重启游戏之后"**（客户端结算后不重取 `/api/Progression`），实机验证一次成本不低。

这一版是 **G6**：把"这份档到底会让我看到什么 / 打完一局会加多少"变成一条命令 —— 不开游戏、不装证书、不改 hosts。

## 新命令：`hd2proxy save-preview`

```bat
hd2proxy.exe save-preview                     :: 读 _last.json 指向的档，套 samples 预演
hd2proxy.exe save-preview --json              :: 结构化输出（脚本用）
hd2proxy.exe save-preview --save steam_7656…  :: 指定档
hd2proxy.exe save-preview --save-file my.json :: 指定存档文件（手改档/别人传的档）
hd2proxy.exe save-preview --mission e899f6af.json   :: 指定结算样本
```

### 输出三块

| 块 | 内容 |
|---|---|
| **存档摘要** | saveId / 身份来源 / 经验 / 成就数 / 包进度数 / 库存行数 / 统计项数 / 结算局数 / `catalog_build` |
| **合并预演** | `main/`（老玩家）与 `fresh/`（空号）两套样本 × Progression 根 / Stats/profile / 库存：逐项「字段：旧值 → 新值」，库存按 mixId 给行级差异 |
| **结算投影** | 喂一份真实 `Mission/end` 样本：本局 +N 经验、+哪些物品（含入账来源 `rewards`/`badges`）、哪些包进度会推进、结算后账本值；并列出未消费字段（如 `campaignWon`、`repeatingPlayer`） |

### 纯计算边界

- **不联网**：只用 `data/fixtures/saves/` 里的真实抓包样本；
- **不写盘**：不碰 `runtime/saves`（除非用 `--save-file` 显式读取）；
- **不依赖引擎/证书/hosts**：开游戏前就能跑，也可以贴给朋友复现。

## 例子（空档，即新装用户）

```
存档预演 · saveId=local（_last.json（saveId=local））
  身份：未识别（local 档）
  经验 0 · 成就 0 · 包进度 0 · 库存 0 · 统计 0 项 · 结算 0 局

合并到 main/ 样本：
  · Progression 根：无改动
  · Stats/profile：无改动
  · 库存：无改动

模拟一局结算（12b9a872.json）：经验 +936（0 → 936）
      mixId 897894480：+7（0 → 7）
      mixId 3608481516：+4434（0 → 4434）
      包进度 1 项（按 max 合并）
      未消费字段：campaignWon、impact、multipliers、othersImpact*、repeatingPlayer
```

## `repeatingPlayer` 结案（研究线 2026-11-23）

12 份真实 `Mission/end` 响应里它**只有 `[]`（6 份）与 `null`（6 份）**，没有任何非空样本
⇒ 目前无证据支持"重复玩家奖励"这类语义，**不落账**；保留在 `unknown_keys` 输出里，
等任一方拿到非空样本再定。

## 测试与验收

- 单测 **631 → 644 passed**（+13）：载入优先级（`--save-file` → `--save` → `_last` → local）、
  坏文件回退空档、摘要字段、三类合并（含库存行级差异）、结算投影（含已有金额叠加）、
  空档不虚增、缺夹具目录告警、人读文本关键块。
- 门禁：`python tools/check_gate.py` → PASS。

## 兼容性

- 纯新增命令，不影响引擎/控制面/profile；
- `0.5.2-alpha.1` 的存档行为不变（本版只加了预演与文档）。

## 下一步

- `inventory/consume` 扣减：等研究线一次本地会话采到请求体形状（`{mixId, amount, …}`）；
- 实机验收（用户侧）：重启后统计/成就不回退、换号取大、G3 结算后经验/货币变多。
