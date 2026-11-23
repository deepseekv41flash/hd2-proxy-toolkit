# v0.5.5-alpha.1 — 购买/解锁响应入账 + consume 真实外壳 + CA 变更留痕（2026-11-23）

> **功能版本**：`X.Y.Z` 变化（`0.5.4-alpha.3` → **`0.5.5-alpha.1`**）。

## 背景

实机会话（2026-11-23 18:15–18:25）跑通了 G1–G5：身份识别、`local→steam` 迁移、结算 +210 exp、
成就 4 条、统计 27 项全部入账。但也暴露三件事，这一版收口：

1. `consume` 的真实报文外壳不是我们猜的 —— 实机抓到了；
2. 真正的"解锁扣钱"发生在**购买响应**里（旧仓逐字节实证），不在 consume；
3. Error 60 的根因是"续期换 CA 后信任库没更新"，需要留痕 + 显式告警。

## 一、G5+：购买/解锁响应入账

旧仓 `variant-net`（`docs/UNLOCK-MAP-2026-11-06.md` §3.1、`docs/API-ENDPOINTS-2026-11-01.md` §8·§10）：

| 路径 | 响应（带增量） |
|---|---|
| `POST /api/Progression/ProgressionPackage/AcquireUnlockableItem` | `{"packageId32":2221505542,"inventoryChanges":[{"mixId":3608481516,"amount":-5000},{"mixId":718265621,"amount":1}]}` |
| `POST /api/SeasonPass/item/buy` | `{"items":[{"mixId":1276729503,"amount":-85},{"mixId":3859732805,"amount":1},{"mixId":905852432,"amount":85}],"packageProgress":[]}` |

**负 amount = 扣钱、正 amount = 授予/记账** → 直接对响应做增量，同时覆盖"扣钱 + 解锁物品"。

| 实现约束 | 做法 |
|---|---|
| 客户端重试会重复响应 | 按 `(packageId32,itemMixId)` / `(seasonPassItemId,warId)` + **10 s 窗口**去重，绝不双扣 |
| `+85` 是 `medalsSpentMixId`（已花奖章**累计计数器**） | 按普通 mixId 增量处理，但日志/文档**不写"获得奖章"** |
| 响应可能缺增量（被中间层剥掉） | 用请求 `expectedCost` **兜底扣费** |
| `targetLevel` 只是 UI 门槛 | 不作校验（旧仓实证） |
| 数量下限 | 扣到 0 为止，**保留行**（库存行 = 拥有语义） |
| 审计 | `earned.purchases = {count, recent_keys, last}` |

## 二、`consume` 真实外壳（实机 2026-11-23）

```json
{ "consumedItems": [ {"mixId": 548295611, "amount": 1}, {"mixId": 2446402932, "amount": 1},
                     {"mixId": 1228689284, "amount": 1}, {"mixId": 2616066963, "amount": 1},
                     {"mixId": 3467463065, "amount": 1} ], "boosters": [] }
```

- 发生在 `Mission/end` **前 3 秒**、5 个不同 mixId ×1 ⇒ **局内消耗品结算上报**（撤离时上报用掉的东西），
  不是购买扣钱；
- 解析器补 `consumedItems` / `boosters` 外壳；语义**不写死**（日志中性 `UNLOCK-COST`）。

## 三、成就上报：不再按字节数反推

实机报文 141 B 对应 **4 条**（与研究线早先"≈5–6 条"的估算不一致）⇒ 解析一律走 JSON parser；
事件里改为记"报文长度（字符）"；新增 INFO：上报值 < 存档值时打印对照（per-key max 不改动）。

## 四、CA 变更留痕（Error 60 根因治理）

- 续期换发 CA 时写 `certs/ca-history.json`（`{at, old, new}`，保留 20 条）；
- 日志显式告警：**旧 CA 仍在信任库但已不匹配 → 需重新 `install` / GUI「安装 / 修复」，否则游戏报 Error 60**；
- `certs.ca_history(cert_dir)` 供排障读取。

## 五、README 验收口径按模式分列（避免被"没变化"误导）

| 模式 | 验收 = | 预期 |
|---|---|---|
| **官方服务器** | 不干扰服务端既有进度、不混档、不降级写入 | 打一局→重启：经验/货币**不变** ← **正确结果**（服务端本来就存） |
| **mock / 自建（服务端给得少）** | 打一局→重启→经验/货币**变多** | 存档层把本机账本顶上去（`save-preview` 合并 `fresh/` 样本即此效果） |

## 六、测试与门禁

- 单测 669 → **687 passed**（购买入账 15 / CA 历史 2 / consume 真实外壳 1 / 引擎端到端购买步骤）；
- `GATE=PASS`。

## 七、下一步

- `_last.json` **预绑定路径**实机验证（需重启一次引擎；日志应出现 `activeSave=steam_…（last）`）；
- GUI「本地账号（仅本机视图）」页（已拍板：改名 + 存档 tab + 三条边界提示条）。
