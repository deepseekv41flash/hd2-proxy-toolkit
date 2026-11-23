# v0.5.2-alpha.1 — 存档层 G4 终身统计 + G5 成就上报合并（2026-11-23）

> **功能版本**：`X.Y.Z` 变化（`0.5.1-alpha.1` → **`0.5.2-alpha.1`**）。

## 背景

G1–G3 之后，存档已经能：识别玩家（SteamID64 主键）、首屏按上次档渲染、换号整档回滚、
结算奖励累加。这一版补 G4/G5 的两块「长期数据」：**终身统计**与**成就计数**。

## G4：Stats/profile 终身统计

`GET /api/Stats/profile/summary` 与 `/api/Stats/profile/801/summary` 返回同一份 27 项
`totalXxx` 终身计数器（真实样本：主号 `totalEnemyKills=356065`，空号全 0）。

| 规则 | 说明 |
|---|---|
| **逐 key 取 max** | 单调计数器只增；客户端/服务端都只会变大 |
| 只改响应已有键 | 不往客户端凭空加统计项 |
| 非数值/bool 跳过 | 防止把 `flag` 之类误当计数 |
| 全 0 不写盘 | 新号首局没有信息量，不刷 `.bak`、不置 `session_dirty` |
| 迁移按 max | `adopt_identity` 合并时统计不因为"较新的档"被改小 |
| 不碰战局统计 | `/api/Stats/war/801/summary`（92 KB）语义未证，明确排除 |

**为什么用 max 而不是覆盖**：Stats 是纯展示的终身战绩；换号/新号返回 0 时用覆盖会把本地已有战绩
抹成 0。研究线 2026-11-23 建议同类「单调计数器」一律 per-key max。

## G5（上半）：成就上报合并

`PUT /api/Progression/Achievements` 的响应恒为空 `{}`（2 B），**值在请求体里**。

研究线实测（2026-11-23）：

- 上报的是**完整小列表**：请求体 141 B ≈ 5–6 条，而主号 `GET /api/Progression` 里只有 4 条 ⇒ 不是增量；
- 同一次结算后 **44 ms** 内两个客户端（`x-real-ip` 12/14）各发一次 ⇒ 多客户端各自上报；
- 语义倾向**累计覆盖**，但建议落成 **per-key max**：等价覆盖、天然幂等（防双计）、
  还能防"客户端用旧快照把值改小"。

实现按此口径：`earned.achievements` 逐 key 取 max；随后下次启动的 `/api/Progression`
（G2 钩子）会把它合并回响应 —— 闭环。

**请求体形状尚未采样**（现有抓包只落响应 `{}`），所以解析是**防御式**的：认
`{"achievements":[…]}` / `[…]` / `{"items":[…]}` 三种外壳、行内认 `{id, value}`；
解析不出来就**不写档**并记一次可操作日志 —— 宁可不记，也不猜错把成就写脏。

## G5（下半）：`inventory/consume` 扣减 —— 暂缓（不是忘了）

`POST /api/Progression/inventory/consume` 响应恒 `{}`，**扣减量只在请求体里**，
而现有抓包没有该请求体样本。**没有形状就不猜着扣**（钱扣错比不扣更糟）。
已请研究线用 `body_shapes` 补采 `consume` 与 `Achievements` 的请求体，拿到后单独一版实现。

## G4 另外两项：证据结论

| 端点 | 结论 |
|---|---|
| `SeasonPass` | 两账号元数据**逐字节相同**（`039ff10e` / 14 589 B）⇒ **账号无关的静态数据**，不能当"买了什么"的证据；季票货币在 inventory、已购项在 `Progression.purchasedSeasonPassItems`（G2 已合并）⇒ **无需单独落账** |
| `Assignment` | 两轮真实会话只有 GET（`/api/v2/Assignment/War/{n}` ×17、`/Player` ×9），**无写路径** ⇒ 进度由服务端推进；rotation/expiry 语义未证 ⇒ 按研究线建议**降到最低优先级**，暂只读不落账 |

## 测试与验收

- 单测 **613 → 631 passed**（+18）：
  - Stats：路径判定 / 只抬不降 / 未知键与非数值 / 兼容两种存档形状 / 迁移 max / 记录与 dirty /
    全 0 跳过 / 不降级不写盘 / 坏 body / 记录→重启→合并闭环；
  - 成就：三种外壳 / 坏行与负值 / 同 id 取大 / per-key max / 未识别不写档 / strict 拒写 / 上报→Progression 闭环。
- 引擎端到端新增：`GET /api/Stats/profile/summary`（上游空号全 0 + 存档 40 万击杀）→ 返回 40 万；
  `PUT /api/Progression/Achievements` → 存档 `achievements` 落账。
- 门禁：`python tools/check_gate.py` → PASS。

## 兼容性

- 存档 `schema v2` 不变（`earned.stats` 由扁平/嵌套两种形状都兼容，写入统一为 `stats.profile`）；
- 无 profile / 控制面协议变化；`0.5.1-alpha.1` 行为不变（只多了 stats/成就两条记录与合并）；
- 实机待验：① 打一局 → 重启 → 统计页/成就数不回退；② 换号后新号看到的本地统计是"取大"而不是清零。
