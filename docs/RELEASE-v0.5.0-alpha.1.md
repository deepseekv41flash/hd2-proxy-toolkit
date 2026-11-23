# v0.5.0-alpha.1 — 存档层 G2：本机 earned 账本接上 `/api/Progression` 首屏（2026-11-23）

> **功能版本**：`X.Y.Z` 变化（`0.4.3-alpha.1` → **`0.5.0-alpha.1`**）。

## 背景

`0.4.3-alpha.1` 之前，所有内容都是「配置驱动」的：GUI 勾了什么，这一局响应就多什么，
关掉即恢复。存档线（移交给本线的 G1–G6）要的是**每玩家可持久化、可成长**的账本：

```
响应 = base（服务端这一局给的） ⊕ config（GUI 注入） ⊕ earned（本机已获得）
```

G1 已把底座做好（`engine/saves.py`：原子写 / 合并语义 / 身份选档 / `_last.json` 预绑定）。
这一版是 **G2**：把账本真正接上首屏进度响应，并把「换号时怎么不混档」的粒度定死。

## 这版做了什么

### 1. 首屏时序（为什么必须"预绑定"）

研究线实测两次真实会话 + mock 8 次启动，时序固定：

| 时间 | 端点 |
|---|---|
| +13 / +15 s | `/api/Progression/items` |
| **+16 / +19 s** | **`/api/Progression`（首屏进度，整局只拉一次）** |
| +18 s | `/api/Progression/inventory` |
| +24 / +42 s | `/api/Pes/GetMotd`（**身份 SteamID64 在这里才出现**） |

⇒ 等身份到达再选档，老玩家整局看空档。所以：**启动按 `_last.json` 预绑定上次的档 → 首屏先渲染 →
GetMotd 到达校验**。没有历史档时，首次 Progression 最多等 `saves.wait_seconds`（默认 1.2 s），
等不到就按 `local` 渲染 —— 绝不挂住客户端。

### 2. `/api/Progression` 根钩子

新 `engine/hooks/progression.py`：**精确匹配根路径**（`/inventory`、`/items`、`/levelspec`、
`/ProgressionPackages`、`/ItemPackages` 一律不碰），把 earned 合并进
experience / onboarding / shipName / location / purchasedSeasonPassItems / achievements / packageProgress。
合并后无变化时响应体原样返回（引用不变，便于上层判等）。

### 3. ⚠ 回滚粒度修正（研究线反馈后定）

研究线指出的隐患：`.bak` 是**单槽「上一版」**。同机换号时若本局先后写了 3 次，
回滚到 `.bak` 只会退到「第 2 次写入后」，第 3 次与第 2 次之前的写入仍留在错误身份的档里 ——
**部分写入比整档污染更难排查**。

本版改成**会话基准快照**：

| 环节 | 行为 |
|---|---|
| 会话开始 | `_bind()` 把当前档原样快照到 `runtime/saves/_session-start/<saveId>.json` |
| 本局写入 | `update_earned()` 写盘并置 `session_dirty`（只有 earned 写入算脏；目录/身份等元数据不算） |
| 身份一致 | 基准**重建**为「最后一次已验证点」，清 `_last.json.pending`，校验后收摊删快照 |
| 身份不一致（旧档已识别） | **整档回滚**到基准；脏档全文 + 回滚前后 hash + 被丢弃条目摘要 → `runtime/saves/_orphan/`；日志 WARN |
| 身份不一致（旧档 local/未识别） | **合并**进正确档并归档（不混档、不丢空号进度） |
| 本局没写过 | **不动档**（没有需要撤回的东西） |
| 崩溃/关窗跨重启 | `_last.json.pending`（24 h 新鲜度上限）让基准**沿用最早那份**，跨重启也能回滚到整个未校验窗口之前 |

### 4. 身份审计与排障

- 档内 `identity` 增 `source`（`getmotd` / `getmessages` / `adopted`）与 `identified_at`
  —— 排查「这份档怎么认到身份的」最省时间；
- `/status` 新增 `save` 块（save_id / origin / verified / session_dirty / catalog_build / 最近事件 / 警告）；
- GUI **战况页顶部**一行：`存档 <saveId> · 预绑定待校验 / 已校验 · 本局有写入`（截图：
  [`research/screenshots/gui-status.png`](../research/screenshots/gui-status.png)，
  演示 profile 下显示 `存档 local · 待校验`）；
- 配置：`saves.enabled`（默认开）、`saves.wait_seconds`（默认 1.2）、
  `saves.identity_strict`（严格模式：身份未校验拒绝写盘，默认关）。

### 5. 离线样本

`data/fixtures/saves/{main,fresh}/`：两账号 × 6 个存档端点（Progression / inventory /
Customize v2 / Stats profile ×2 / SeasonPass），来自 2026-11-17（空号）与 11-18（主号）真实抓包，
**只留 body、无 header/token/sessionId/accountId**（守门测试逐字节扫描）。
`Progression/items` 目录不入仓（560 KB/份），只记签名：main `93e7575a`/3021 行、fresh `d71655e6`/3020 行。

## 已知限制（务必知道）

客户端**一次会话只拉一次** `/api/Progression`。同机换号那一刻，首屏可能已按旧档渲染过，
本局客户端不会重取 —— **重启游戏后**才会换成新档。这是客户端请求时序决定的，
我们的取舍是「宁可首屏有内容，也不让老玩家整局看空档」。

## 测试与验收

- 单测 **546 → 591 passed**（+45）：
  - `test_saves_session.py`（15）：会话基准快照 / 三次写入整档回滚 / 会话前无档则删除 /
    无快照不动档 / 跨重启沿用最早基准 / 基准重建 / pending 生命周期与新鲜度 / identity 审计 / 差异摘要；
  - `test_active_save.py`（19）：预绑定 / 首屏渲染 / 等身份超时 / local 合并 / 身份校验 /
    换号整档回滚 + orphan 审计 / 重复 GetMotd 不写盘 / strict 拒写 / 收摊清理 / 过期 pending 重取基准；
  - `test_save_fixtures.py`（9）：真实夹具行数/大小/无身份痕迹/空档不虚增/只抬不降；
  - `test_gui_pages.py`（+1）：战况页存档状态行；`test_engine_flow.py`（+1）：引擎端到端存档合并。
- 门禁：`python tools/check_gate.py` → PASS（591 单测 + 5 个离线自检）。

## 兼容性

- 无数据/profile/控制面协议破坏性变化；新增 profile 段 `saves`（旧 profile 缺省即启用默认值）；
- 存档文件为 `schema v2`（新增 `identity.source/identified_at` 是**加法**，老档照常读）；
- `legacy` 模式（无 profile）**不启用**存档层，行为与 `0.4.3-alpha.1` 一致；
- 存档只在本机生效、**不回传服务器**；服务端进度仍是事实源。
