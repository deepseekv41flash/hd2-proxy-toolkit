# v0.5.4-alpha.3 — 修复：库存数量被改小 / 续期后信任失效；consume 语义纠正（2026-11-23）

> **bug 修复版**：只动 `alpha.N`（`0.5.4-alpha.2` → **`0.5.4-alpha.3`**）。

## 一、库存数量会被本机账本改小（严重）

`apply_to_inventory` 原先按账本**绝对数量覆盖**响应：

```
响应 items[].amount = 账本里的数量        ← 错
```

本机账本只记"经过存档层"的增量（结算奖励 / 解锁扣减），**不知道玩家历史基线**。
后果：老玩家 5000 货币，打过一局后界面可能显示成"只有本局奖励那点"；解锁/购买时客户端判余额不足。

修复：**只抬不降** —— 响应里的数量与服务端取 `max`：

```
响应 items[].amount = max(服务端 amount, 账本 amount)
```

- 服务端给得更多 → 听服务端的（服务端仍是事实源）；
- 账本给得更多（离线 / 私服 / 回滚场景）→ 用本机账本兜底；
- 与 experience / 成就 / 统计的 max 语义统一；
- 代价：纯本机扣减（服务端没扣）不会在界面上减数量 —— 可接受，服务端真实扣减时会跟着降。

## 二、引擎自动续期后 CA 变化 → 游戏 Error 60（严重）

**机制**：证书剩余 < `cert.min_remaining_hours`（默认 12h）时，引擎启动会自动续期；
架构上"签完即删 CA 私钥"，所以续期会**重新生成 CA**。旧 CA 仍在受信任根存储里，
但服务器已经用新 CA 签发了叶子证书 ⇒ 游戏 TLS 握手被拒：

```
Error: 60
Something unexpected went wrong while trying to communicate with our server.
```

**修复/口径**：
- 现象与原因写进 README 故障排查（引擎日志本来就会打 `⚠ 证书未受信任：当前 CA 不在受信任根存储`）；
- **续期后必须重新导入信任**：GUI 会引导「安装 / 修复」；命令行执行
  `hd2proxy.exe install --cert-dir %LOCALAPPDATA%\HD2ProxyStudio\certs`；
- 建议：一次装好后把 `cert.days` 设 2（上限）并把 `cert.min_remaining_hours` 保持在 12，
  避免频繁续期；每次续期后跑一次 install 即可。

## 三、`consume` 语义：证据冲突，本版只改日志措辞、不宣称语义

用户观察：`POST /api/Progression/inventory/consume` 只在**解锁物品**时出现。
研究线反证（2026-11-23）：11-17 / 11-18 两次**完整浏览会话**（军械库/商店/季票/邮件）里 `consume` 出现 **0 次**；
只在 E3 **打局会话**出现 2 次（均在 `Mission/end` 前约 10 秒、两客户端间隔 15 ms）⇒ 与局内/结算强相关。

**处理**：实现与防御式解析保留；日志从 `CONSUME …` 改为中性的 `UNLOCK-COST …`；
**不把语义写死成"购买扣钱"**；等真实请求体 + 触发时机（是否在撤离/结算瞬间）再定。

## 四、真正的"购买/解锁扣钱"在**响应**里（旧仓逐字节样本，G5 增强下一版）

旧研究仓 `D:\mod\workariant-net`（`docs/UNLOCK-MAP-2026-11-06.md` §3.1、
`docs/API-ENDPOINTS-2026-11-01.md` §8·§10）：

| 路径 | 响应（带增量） |
|---|---|
| `POST /api/Progression/ProgressionPackage/AcquireUnlockableItem`（武器/配件） | `{"packageId32":…,"inventoryChanges":[{"mixId":3608481516,"amount":-5000},{"mixId":718265621,"amount":1}]}` |
| `POST /api/SeasonPass/item/buy`（战备） | `{"items":[{"mixId":1276729503,"amount":-85},{"mixId":3859732805,"amount":1},{"mixId":905852432,"amount":85}],"packageProgress":[]}` |

⇒ **负 amount = 扣钱、正 amount = 授予/记账**。直接对响应做 `amount ±` 应用，就能同时覆盖
"解锁扣钱 + 解锁物品"，比只读 consume 请求体更贴近用户说的"解锁消耗"。列为下一版实现。

## 四、测试与门禁

- 单测 666 → **669 passed**（库存：只抬不降 / 抬升 / 消费后显示语义）；
- `GATE=PASS`。

## 五、现场处置记录（2026-11-23）

实机验收时用户遇到 Error 60，定位为"续期换 CA + 信任未重导"；执行
`hd2proxy.exe install --cert-dir <state>\certs` 重新导入当前 CA 后恢复
（回读校验：`thumbprint=B00398DB… trust_scope=LocalMachine trusted=true`）。
