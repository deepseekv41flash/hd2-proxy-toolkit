# v0.10.1-alpha.2 — 修复「一键解锁全部物品」在空白号上的三个缺口

> 2026-11-25 · 预发布（alpha）· 纯 bug 修复（`0.10.1-alpha.1` → `0.10.1-alpha.2`）
>
> 实机反馈（空白号）：**头盔/护甲只解锁 1 套（SS-500 PALE PROSECUTOR）、披风只有 2 件
> （THUNDERING HOOVES OF LOYALTY / ARCTIC DECREE）、舰船模块 0 件**。

## 根因（三条，均已在数据/参考实现里核实）

1. **目录来源错了**：alpha.1 用离线 `data/catalogs/items.json`（商店/护甲表归档，是**子集**）在
   规格构建期展开。该文件里 `progressionCategory=3`（头盔/披风）只有 **46** 个 id，
   而客户端实际目录 `/api/Progression/items` 里 pc3 有 **441** 个 —— 少注入了近 400 件，
   这正是"只出 2 件披风"的直接原因。
2. **授予行 `isDiscovered=false`**：护甲/披风这类外观需要 `isDiscovered=true` 才出现在军械库
   （参考 HellForge 对"授予物品"一律写真值；空白号此前全是 false）。
3. **舰船模块不是库存行**：它们是 6 条 `progression package`（type=1，每条 5 级）的**等级进度**，
   客户端按 `/api/Progression.packageProgress[].level` 显示；此外 6 条包的 `requiredItems`（6 个 pc0 物品）
   必须在库存里，否则 Ship Module 页显示"under construction"。
   （来源：HellForge `ProfileStore.cs:530` 注释 + 2026-11-20 真机 `ProgressionPackages` 抓包。）

## 修复

| 项 | alpha.1 | alpha.2 |
|---|---|---|
| 展开时机/来源 | 规格期 × 离线目录（子集） | **请求期 × 运行时客户端目录**（`/api/Progression/items` 响应缓存）；未收到目录前退回离线 |
| 授予行 | `isDiscovered: false` | **`isDiscovered: true`** |
| 舰船模块 | 只注入奖励物品行（等级仍 0 → 不显示） | **6 条包 `packageProgress.level` 置 5** + 6 个 `requiredItems` 补进库存 |
| 货币 | 按离线 `category=currency` 排除 | 按 `progressionCategory=18` 排除 |

实现：
- 新增 `engine/unlock_all.py`：运行时目录缓存（`set_catalog`/`ownable_ids`）、库存注入
  （`inject_inventory`，isDiscovered=true）、舰船模块包等级（`patch_progression`，6 条包 × 5 级、幂等）。
- `hooks/inventory.py`：`unlockAll` 标志 → 请求期补行（幂等，客户端轮询不重复）。
- `hooks/progression.py`：`apply(..., unlock_all_enabled=)` → 合并存档后再把包等级置满。
- `engine/server.py`：收到 `/api/Progression/items` 时缓存运行时目录（日志 `UNLOCK 运行期目录已缓存 N 行`）；
  `/api/Progression` 根响应按开关打补丁；启动/热重载日志改为描述新机制。
- `engine/config.py`：规格里只放 `unlockAll` **标志**（`{enabled, scope}`），不再规格期展开；
  `inventory.enabled` 计入解锁开关（只有解锁时存档钩子也要生效）。
- GUI：确认框/摘要改为"运行期按客户端目录展开（离线估算 N 行）+ 舰船模块 6 条包等级置满"。

## 验证

- 单测 **13 条**（`tests/unit/test_unlock_all.py`）：运行时目录缓存/货币排除/6 个前置物品必在/
  回退离线目录/授予行 isDiscovered=true 且幂等/包等级置满且不相关包不动/无数组与坏 JSON 兜底/
  hook 端到端（inventory 注入 + progression 补丁）/规格只放标志/config 校验。
- 出货 exe 端到端（mock 上游 + 回环探针）：先取 `/api/Progression/items` 让引擎缓存目录，
  再请求 inventory → 行数 = 基线 + 目录全部物品（含 pc3 全部、isDiscovered=true）；
  请求 `/api/Progression` → 6 条舰船模块包 level=5。
- 全量测试与门禁见 CHANGELOG。

## 仍需实机确认

- 护甲/头盔/披风是否**全部**出现在军械库（本次已按客户端完整目录注入，理论上应显著多于 3 件）；
- 舰船模块页是否出现并显示 30 条已发布模块（等级置 5 + 前置物品已给）；
- 若个别类别仍不显示：用 profile `inventory.unlock_scope` 收窄排查，或反馈具体类目/条目。
