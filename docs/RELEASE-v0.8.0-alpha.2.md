# v0.8.0-alpha.2 — `mission_end.json` 按玩家校正 `platformAccountId`（shape 补齐）（2026-11-24）

> **bug 修复版**：只动 `alpha.N`（`0.8.0-alpha.1` → **`0.8.0-alpha.2`**）。

## 一、问题（研究线校验器 F07 抓到）

alpha.1 的 `mission_end.json` 样例里，`progressionPackageUpdates[]` 元素只有 `{id32, level, progress}`，
缺 `platformAccountId` —— 与真实抓包/模板的 `{platformAccountId, id32, level, progress}` 不一致。

## 二、根因排查结论：**不是引擎丢字段，是我方公开夹具被脱敏**

| 检查 | 结果 |
|---|---|
| 真实上游响应（a8b215e7，2026-11-23 实机） | `platformAccountId: "13887067702231565058"`（该玩家 HD2 20 位 id）✅ 上游确实有 |
| 客户端收到的响应（本次隔离运行 1791 B） | `platformAccountId: "00000000000000000000"` 原样在 → **无 live bug** |
| 引擎落盘 `earned.missions.last_response` | 与上游逐字段一致（含 platformAccountId）→ **引擎不重建、不丢字段** |
| 我方公开夹具 `data/fixtures/saves/mission_end/*.json` | 被脱敏脚本**故意剥掉**该字段（守门测试 `LEAK_MARKERS` 禁止 `platformAccountId` 字样） |
| 上一份样例怎么来的 | 本地 mock 直接服务该**脱敏夹具** → 上游本来就没有该字段 |

⇒ 引擎路径正确；问题在「样例用脱敏夹具 + 导出未按玩家校正」。

## 三、修复（`save-export` 侧）

新增 `correct_mission_end(doc, ledger)`：

- **值校正**：`progressionPackageUpdates[*].platformAccountId` 统一改成本玩家 identity
  （**HD2 20 位优先**——与官方真实抓包一致；无则退回 SteamID64）；
- **缺失补齐**：夹具脱敏丢掉的字段在此补上（真实上游总有，自建服回放需要）；
- **键序**：`platformAccountId` 排在元素最前（与官方响应一致）；
- **只改值不重建**：深拷贝后原地改，元素其它键/嵌套原样保留；不改入参。

> 公开夹具保持脱敏不变（安全边界），shape 的完整性由导出侧按玩家补齐/校正保证。

## 四、重出样例（同一路径）

`D:\mod\tmp\save-export-sample-mission\players\76561198968648344\`
- `mission_end.json` 17 键、`progressionPackageUpdates = [{platformAccountId: "11893343864225233967", id32: 277818845, level: 5, progress: 459}]`
  （= 玩家自己的 HD2 id，键序 platformAccountId 在最前）
- 生成链路：本地 mock 模拟真实上游（补 20 位零占位）→ 隔离引擎转发 → 账本原样落盘 → 导出校正
- 请研究线复跑校验器（F07 应转绿；F06/V05/F08/F09、M01–M07 应保持 PASS）

## 五、测试

- **727 → 728 passed**，`GATE=PASS`；
- 新增：导出补/校正 `platformAccountId`（含键序断言）、上游占位值被校正为本玩家 id；
- 既有：引擎原样保留原始响应（`last_response` 逐字段相等，含 platformAccountId）。

## 六、升级

换包即可；自建服无需改（覆盖层按文件名取用；值语义现在与官方一致）。
