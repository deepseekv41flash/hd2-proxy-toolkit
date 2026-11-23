# v0.5.1-alpha.1 — 存档层 G3：结算奖励入账（只读响应，不碰请求体）（2026-11-23）

> **功能版本**：`X.Y.Z` 变化（`0.5.0-alpha.1` → **`0.5.1-alpha.1`**）。

## 背景

`0.5.0-alpha.1` 把「本机 earned 账本」接上了首屏 `/api/Progression`，但账本还不会**长大**：
玩家打完一局，经验/货币/物品奖励只存在于那一次的结算响应里，重启后照旧。

这一版是 **G3**：把「结算奖励」写进本机账本。研究线 2026-11-23 给了关键结论 ——
**不需要请求体**：`Mission/end` 的**响应**里已经是服务端算好的本局增量。

## 入账来源（对着 5 份真实响应核过）

| 字段 | 语义 | 我们怎么用 |
|---|---|---|
| `experience` | **本局获得值**（如 936），不是账号总值 | **累加**进存档 `earned.experience` |
| `rewards[]` | 服务端**最终入账**清单（含 `multipliers` 倍率） | 默认按 mixId **累加**进 `inventory_amounts` |
| `badges[].itemRewards[]` | 明细（每个勋章给什么） | 缺 `rewards` 时退回明细；有 `rewards` 时当交叉校验 |
| `lootedItemRewards` / `lootedHeavyItemRewards` / `levelUpRewards` | 战场拾取 / 升级奖励 | 明细来源之一（`rewards` 缺失时并入） |
| `progressionPackageUpdates[]` | `{id32, level, progress}`，实测跨局递增 = **服务端当前值** | 按 **max** 合并（不累加、不降级） |
| `campaignWon` / `impact` / `othersImpact*` | 战果展示 | **不碰**（研究线红线：不伪造社区战果） |

### 为什么默认取 `rewards` 而不是 badges 明细

5 份真实响应里恒成立：

```
rewards[3608481516] == sum(badges[].itemRewards[3608481516]) × 3
1478 → 4434 ｜ 346 → 1038 ｜ 334 → 1002 ｜ 1534 → 4602
rewards[897894480] == badges 明细（征用单不受倍率影响）
```

倍数来自响应自身的 `multipliers[].factor`（实测 3）。所以 `rewards` 是「最终发到你账上的数」，
badges 是「构成明细」。口径开关只有一处（`hooks/mission_end.ITEM_SOURCE`）；
日志会打两条来源的比例，**实机对一次账**就能确认 —— 若不符，一处切回 `badges` 即可。

## 防双计

客户端网络重试会重复同一份结算响应。所以按 `missionId` 去重（最近 20 局），重复响应直接跳过并
记一行日志；若响应里既无 `missionId` 也无 `operationId`，**拒绝入账**（宁可少记一局，也不双计）。

## 生效时机（务必知道）

客户端结算后**不会重取 `/api/Progression`**（研究线 E3 实测：777/1227 条请求里 8 次 Progression
全部对应一次启动；结算 15:23 之后没有新的 Progression 请求）。结算后客户端只做
`GET /api/Stats/profile/summary ×2`、`PUT /api/Progression/Achievements ×2`、`POST /api/Mission/Session`。

⇒ **存档的效果在「重启游戏 / 回主界面」后可见**；结算画面上的数字由那次的响应驱动，与存档无关
（也就是说：不写档，结算画面也是正常的 —— 这符合预期，不要拿结算画面验收存档）。

## G2 反馈小修（研究线验收建议，本版一并做）

| 建议 | 处理 |
|---|---|
| `pending` 复用要校验 `saveId` | 已有校验（`pending.save_id == 预绑定 saveId`），本版补测试钉住「不会拿上一个号的基准」 |
| 基准只在**首次**身份校验时重建 | 已改：`_rebase_done` 会话内只重建一次（重复 GetMotd / 后到的 HD2 别名不再移动回滚点） |
| orphan 的 `discarded` 对货币单独标注 | 已改：数值字典给出 `added/removed/changed` 的**具体数值**（如 `{"3608481516": {"before": 500, "after": 0}}`） |
| fixtures 不含身份/票据 | 保持；新增结算样本时已剥 `platformAccountId` 并有字节级守门测试 |

## 测试与验收

- 单测 **591 → 613 passed**（+22）：
  - `test_mission_end.py`（12）：5 份真实样本解析 / 本局增量语义 / `rewards` 口径与 `badges` 切换 /
    `rewards` 缺失回退 / 其它奖励清单 / 包进度形态 / 坏 body / 摘要；
  - `test_active_save.py`（+8）：累加入账 / 同 missionId 去重 / 不同 mission 各自计数 /
    包进度 max 不降级 / 缺 missionId 拒绝 / 坏 body / strict 未校验拒写 / pending 跨号不复用；
  - `test_save_fixtures.py`（+2）：结算样本完整性与无身份痕迹；
  - `test_engine_flow.py`：引擎端到端新增「POST 结算 → 存档累加 → 再拉 Progression 见累加值 +
    `/status.save.session_dirty`」。
- 门禁：`python tools/check_gate.py` → PASS。

## 兼容性

- 存档 `schema v2` 不变（`earned` 新增 `missions` 审计块属加法，老档照读）；
- 无 profile / 控制面协议变化；`0.5.0-alpha.1` 的 G2 行为不变（只多了结算入账）；
- 实机仍需验证一次：打完一局 → **重启游戏** → 看经验/货币是否比战前多（这才是 G3 的验收点）。
