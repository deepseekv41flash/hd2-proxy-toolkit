# v0.10.1-alpha.3 — 修复「所有武器缺改装按钮」

> 2026-11-25 · 预发布（alpha）· 纯 bug 修复（`0.10.1-alpha.2` → `0.10.1-alpha.3`）
>
> 实机反馈（空白号）：军械库里**所有可改装武器都没有「改装」按钮**。

## 根因

**1) `isDiscovered` 被改成 true，与游戏真实数据相悖（alpha.2 引入）**

实证：真实库存两份抓包 **1030 行全部 `isDiscovered:false`**（主号 970 行、空白号 60 行，各类目一致）。
alpha.2 为让护甲/披风出现而把授予行统一改成 `true`；护甲/披风的真正缺口是"离线目录只有 46 个 pc3 id"
（alpha.2 已改运行时目录解决），`isDiscovered` 的改动属过度修正，副作用即"缺改装按钮"。
⇒ 回退为 **false（默认）**，并加 profile 开关 `inventory.unlock_discovered`（默认 false）供需要时显式打开。

**2) 武器改装入口与 ship module 同属"进度包"机制（缺失）**

每把武器有 **type=2 武器精通包**（`/api/Progression/ProgressionPackages` 里 50 条 × 25 级；
2026-11-20 真机抓包）。空白号 `packageProgress` 只有 6 条（ship module 等），**没有任何武器包条目**
⇒ 改装入口缺失（与 ship module 页需要包等级的机制一致）。
⇒ 解锁补丁现在把 **50 条武器包补到 level=1**（最小侵入：只让条目存在，不伪造升级/奖励进度）。

## 保留 alpha.2 的修复

- 运行时客户端目录展开（pc3 440+ 个 id，护甲/披风/头盔全覆盖）；
- 6 条 ship module 包 `packageProgress.level=5` + 6 个 `requiredItems` 补进库存。

## 新增安全阀

- 库存注入尊重客户端 **4096 条 InventoryCap**（HellForge `RegisteredItems.cs:119` 实测注释；
  超限后游戏忽略其余行，武器会"没有附件"）。注入留 64 条余量，超限时日志报告跳过数；
  当前空白号总量 ~3.1k 行，**不触发**，属预防性保护。

## 验证

- 单测 **14 条**：武器包/舰船包补丁（新增 50 条、level=1；幂等；不相关包不动）、`isDiscovered=false`、
  4096 上限保护、运行时目录/回退、hook 端到端、配置校验。
- 全量 **758 passed、GATE=PASS**；出货 exe 端到端（mock + 回环）：`packageProgress` 含 50 条武器包、
  6 条舰船包 level=5；inventory 授予行 `isDiscovered=false`。
- **仍需实机确认**：改装按钮是否恢复（本次按你提示的"进度包前提"补齐了武器包条目）。

## 如果仍缺改装按钮

请回报两点，我按数据继续定位（不必反复试）：
1. 关掉「一键解锁全部物品」+ 应用配置 + 重启游戏后，按钮是否回来（判定是否注入导致）；
2. 是否**所有武器**都缺（已确认）还是只有部分；以及是否有其它界面异常（武器升级页/军械库列表）。
