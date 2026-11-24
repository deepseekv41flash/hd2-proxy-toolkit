# Changelog

本项目遵循「里程碑 + 语义化版本」：`0.x` 阶段接口/数据结构可能变动，发布 alpha/beta 时显式标注。

> **版本规则（2026-11-17 起）**：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动
> `alpha.N` / `rc.N`。alpha = 新功能阶段（可能有 bug），rc = 用户实机验证过（只修 bug），
> GA = 功能与 bug 收敛。完整规则见 [docs/VERSIONING.md](docs/VERSIONING.md)。

## v0.8.0-alpha.1（2026-11-24）— 每玩家结算响应体 `mission_end.json` + 身份头 uncertain 细化

- **`mission_end.json`（契约 §7 后续第 1 条）**：引擎在 `Mission/end` 入账时把**完整原始响应**整份落盘
  （`earned.missions.last_response` / `last_response_at`，只留最近一局、同 missionId 重试不覆盖）；
  `save-export` 发现该字段即写 `players/<steamId64>/mission_end.json`（shape 原样，不重建）。
  端到端验证：隔离引擎 + 本地 mock 模板 `12b9a872`（exp=936）→ 落盘 17 键、导出键集与模板逐项一致。
- **身份头 uncertain 细化**（研究线建议）：不可信时改为只发 `X-HD2-Account-Source: uncertain`（不带 Account），
  让自建服跳过 IP 映射/唯一玩家兜底、直接回落公共数据（v0.7.0-alpha.2 的"完全不盖头"会被 IP 兜底接管）。
- 测试 **720 → 727 passed**、GATE=PASS。
- 规则：能力变更 ⇒ 动 `X.Y.Z`：`0.7.0-alpha.2` → **`0.8.0-alpha.1`**。
- 后续：JSONL 结算事件流（形态 3）、`shared/` 拆分。

## v0.7.0-alpha.2（2026-11-24）— 身份头安全加固：GetMotd 校验失败时不再断言身份

- 问题（研究线自建服侧建议，按"宁可不盖"原则）：alpha.1 中若 GetMotd 已到但校验/切档失败，
  引擎会继续用预绑定（上一账号）身份盖 `X-HD2-Account` → 自建服可能错给别人的档。
- 修复：`ActiveSave` 增加 `_getmotd_seen` / `_identity_uncertain`；`_observe_identity` 异常兜底
  （WARN + `identity-uncertain` 事件）；`identity_header()` 在这两种状态下**不盖头**，
  自建服按"无身份头"回落公共数据；正常校验路径不变。
- 测试 **718 → 720 passed**、GATE=PASS。
- 规则：bug 修复只动 `alpha.N`：`0.7.0-alpha.1` → **`0.7.0-alpha.2`**。

## v0.7.0-alpha.1（2026-11-24）— 自建服导出 `save-export` + 身份头盖章 `X-HD2-Account`

- **新增 `hd2proxy save-export`**（契约：研究线 `SELFHOST-SAVE-CONTRACT-2026-11-24` 形态 2 主切片）：
  基线 ⊕ 本机账本 → `<data-root>/players/<steamId64>/{manifest,progression,inventory,stats_profile}.json` + `index.json`，
  自建服务器启动时直接加载回放。可选端点（`stats_profile_war` / `customize_v2`）默认导出（`--no-optional` 关闭）。
- **shape 保真**：输出 = 基线深拷贝只改值；合并语义沿用引擎（max / 库存只抬不降 / 集合并集）；
  原子写 + 可复现（除 `generatedAt` 逐字节一致）。
- **manifest 自描述**：`baselineId` / `baselineDirResolved` / `baselineFiles{name,sha256}` /
  `baselineSha256` / `ledgerSha256` / `counts{experience,achievements,inventoryRows,statsNonZero,missions}`。
- **身份头盖章**（多人自建服分档，v1 方案 a）：引擎给所有上游请求补
  `X-HD2-Account: <SteamID64|HD2 id>` + `X-HD2-Account-Source: prebind|getmotd|getmessages`；
  客户端自带该头时不重复；官方服忽略未知头无副作用。边界：头可伪造，仅限可信自建服。
- **测试 708 → 718 passed**（save-export 13 + 身份头 8 + e2e 头断言），`GATE=PASS`；
  研究线 `validate_save_export.py` 对样例实测 PASS 36/0 与 19/0。
- 规则：能力变更 ⇒ 动 `X.Y.Z`：`0.6.0-alpha.3` → **`0.7.0-alpha.1`**。
- 不做（后续）：`mission_end.json` 每玩家结算响应体、JSONL 结算事件流、`shared/` 拆分、HTTP 导出接口。

## v0.6.0-alpha.3（2026-11-23）— 换号不混档实机验收 + 修复 HD2 别名残留 / 首屏预合并回声污染

- **④ 换号不混档实机验收 PASS**（主号 ↔ 空号 `76561199881579811` 双向切换，官方服同一引擎进程）：
  双档分流、主号 earned 未被改动、空号段结算入账与 `Mission/end` 响应逐字段一致、切回主号整档回滚 + `_orphan` 审计；
  四条红线（experience / achievements / purchasedSeasonPassItems / inventory 行数）无跨账号混入。
  记录：`docs/ACCEPTANCE-M4.md` §M5「④ 换号 · 实机专项」。
- **修复 1 · HD2 20 位别名跨账号残留**：换号瞬间 `GetMotd` 先到（`GetMessages` 未到）时把上一账号的
  别名写进新档（`.bak` 实证），切回时又写进原档。改为只认**本局观测值**（`_hd2_session`）：Steam 号变化即清空旧别名，
  `GetMotd` 先到 → 新档 hd2 写 null、`GetMessages` 到后补；切回已有档不覆盖其正确别名；
  `GetMessages` 先到且属别的账号时不写进预绑定档。
- **修复 2 · 首屏预合并的「显示回声」污染**：预绑定 merge 在身份校验前把上一档账本合进响应，客户端把"看到的数"
  加增量后回显上报，被记成新账号成就（空号档实测出现主号值）。新增 `saves.preverify_merge`：
  **`safe`（默认）**只合并服务端自算字段（经验/包进度），成就/统计/库存不合并；
  `full` 全合并（`upstreamTest`/mock/自建服自动启用）；`off` 全关。换号告警补"首屏曾合并 N 处、显示偏高重启纠正"。
- 测试 **689 → 696 passed**；README 修正"已知限制"表述（整局沿用旧档视图，不止首屏）。
- 规则：bug 修复只动 `alpha.N`：`0.6.0-alpha.2` → **`0.6.0-alpha.3`**。
- 验收补记（2026-11-24，docs-only）：**M6 mock/自建服验收 PASS** —— 研究线明文 mock（`127.0.0.1:9099`，
  "服务端给得很少"）+ 隔离状态目录（生产档副本）+ alpha.3 引擎，四条判据全过：
  ① exp 1→210、成就 0→4 条；② inventory 空→`897894480×1`+`3608481516×910`；
  ③ Stats 全 0→23 项抬回（`totalEnemyKills=356105`）；④ `Mission/end` 模板 936→账本 210→1146、库存/包进度累加。
  生产账本未被测试改动。记录：`docs/ACCEPTANCE-M4.md` §M6；证据：`D:\mod	mp\evidence-m6-mock\`。

## v0.6.0-alpha.2（2026-11-23）— 修复：`/api/Progression/inventory` 响应没套账本（服务端给得少时看不到本机库存）

- **问题**：`0.5.4-alpha.3` 只修了 `saves.apply_to_inventory` 的**语义**（只抬不降），
  但引擎响应链**从没接上**这一处 —— 只有 `save-preview` 在用。官方服给全量所以没暴露；
  离线/私服/回滚/mock 验收（上游 `items` 很少或为空）时，游戏里看不到本机账本已有的货币/物品行。
- **修复**：新增 `ActiveSave.apply_inventory()`，引擎存档层接 `INV_PATH` 分支：
  上游 ≥ 账本 → 听服务端；上游 < 账本 → 账本兜底；上游整份没给 `items` → 视为空库存补行；
  与「本地账号」四类库存注入叠加时在**注入后的视图**上合并。日志 `SAVE INV +N 行`、事件 `kind=inventory`。
- **测试**：688 → **689 passed**（active_save 单测 + engine_flow 端到端：上游 999999 保留 / 账本 1 补行 / `/status` 事件）。
- **发现方式**：离线 mock dry-run（`profile` + legacy `--config upstreamTest` 指明文上游）验证
  「服务端给得少 → 存档层兜底」时暴露；手法写进 Release Notes。
- 规则：bug 修复只动 `alpha.N`：`0.6.0-alpha.1` → **`0.6.0-alpha.2`**。

## v0.6.0-alpha.1（2026-11-23）— GUI「本地账号（仅本机视图）」：改名 + 存档 tab + 三条边界

- **页面改名**：「物品与战备」→ **「本地账号」（仅本机视图）**，侧栏同名；页头固定三条边界：
  **仅本机视图 / 不回传服务器 / 服务端仍是事实源**，并标注"改名自「物品与战备」"。
- **新增「存档（本机账本）」tab**（第 7 个）：
  - 摘要：档 saveId / 身份来源 / 经验 / 成就 / 包进度 / 库存行 / 统计项 / 结算局数 / `catalog_build`；
  - 引擎状态一行：`存档 <id> · 预绑定待校验 / 已校验 · 本局有写入`（与战况页顶部一致）；
  - **存档预演**按钮：后台跑 `save_preview.preview()`，弹只读窗口——不开游戏就能看
    "这份档会改什么 / 一局结算会加多少"；
  - 打开存档目录；边界三条在 tab 内再展开一次（写清"只在本机生效 / 不回传 / 服务端仍是事实源"）。
- **实机验收结论补档**：`docs/ACCEPTANCE-M4.md` 新增 M5 存档实机验收（① 首屏预绑定 ② 结算入账
  ③ 重启不回退 ④ 换号未测）。
- **测试**：687 → **688 passed**（新增：本地账号页 title/边界/存档 tab/引擎状态行）；
  GUI 冒烟新增 7 个 tab 截图（`gui-inventory-tab6-存档（本机账本）.png`）。
- 规则：功能变更 ⇒ 动 `X.Y.Z`：`0.5.5-alpha.1` → **`0.6.0-alpha.1`**。

## v0.5.5-alpha.1（2026-11-23）— 购买/解锁响应入账 + consume 真实外壳 + CA 变更留痕

- **G5+：真正的"解锁/购买"写路径入账**（`engine/hooks/purchase.py` + `ActiveSave.record_purchase()`）——
  旧仓 `variant-net` 逐字节实证：**负 amount = 扣钱、正 amount = 授予/记账**，直接对**响应**做增量：
  - `POST /api/Progression/ProgressionPackage/AcquireUnlockableItem`（武器/配件）：
    响应 `{"packageId32":…,"inventoryChanges":[{"mixId":货币,"amount":-5000},{"mixId":物品,"amount":1}]}`；
  - `POST /api/SeasonPass/item/buy`（战备）：响应 `{"items":[{"mixId":货币,"amount":-85},
    {"mixId":物品,"amount":1},{"mixId":medalsSpent,"amount":85}],"packageProgress":[]}`；
  - **去重**：按 `(packageId32,itemMixId)` / `(seasonPassItemId,warId)` + 10 s 窗口，防客户端重试双扣；
  - `+85` 是 `medalsSpentMixId`（已花奖章**累计计数器**），日志/文档不写"获得奖章"；
  - 响应无增量时用请求 `expectedCost` **兜底扣费**；`targetLevel` 只是 UI 门槛（不作校验）；
  - 审计进 `earned.purchases`（count / recent_keys / last）。
- **consume 真实外壳**：实机报文是 `{"consumedItems":[{mixId,amount}×5],"boosters":[]}`（发生在
  `Mission/end` 前 3 秒）⇒ 是**局内消耗品结算上报**，不是购买扣钱；解析补 `consumedItems`/`boosters`，
  语义仍不写死（日志中性 `UNLOCK-COST`）。
- **成就上报对照**：上报值 < 存档值时打 INFO（per-key max 不改动）；事件里记"报文长度（字符）"；
  **不再按字节数反推条数**（实测 141 B 对应 4 条，与研究线早先估算不一致）。
- **CA 变更留痕**（Error 60 根因治理）：续期换发 CA 时写 `certs/ca-history.json`（old/new thumbprint + 时间，
  保留 20 条），并在日志里显式告警"需重新 install/GUI 安装修复"。
- **README 验收口径按模式分列**：官方服务器模式 = 不干扰服务端既有进度（**重启后不变是预期**）、不混档、
  不降级写入；mock/自建模式 = 打一局→重启→经验/货币**变多**（存档层是权威）。
- **测试**：669 → **687 passed**（购买入账 15 / CA 历史 2 / consume 真实外壳 1 / 引擎端到端购买步骤）。
- 规则：功能变更 ⇒ 动 `X.Y.Z`：`0.5.4-alpha.3` → **`0.5.5-alpha.1`**。

## v0.5.4-alpha.3（2026-11-23）— 修复：库存数量被本机账本改小（只抬不降）+ 续期后信任失效 + consume 语义纠正

- **实机验收前复核发现的两个"会让用户少东西 / 连不上"级缺陷**：
  1. **库存数量会被改小**：`apply_to_inventory` 原先按账本**绝对数量覆盖**响应。本机账本只记
     "经过存档层的增量"，不知道玩家历史基线 —— 老玩家 5000 货币会被显示成"本局奖励那点"，
     **解锁时直接判余额不足**。改为**只抬不降**（服务端更大就保留服务端的；账本更大才抬），
     与 experience / 成就 / 统计的 max 语义一致；服务端仍是事实源，离线/私服场景由本机账本兜底。
     代价：纯本机消耗（服务端没扣）不会在界面上减数量 —— 可接受。
  2. **引擎自动续期后 CA 变化 → 游戏 Error 60**：证书剩余低于 `cert.min_remaining_hours` 时引擎启动
     自动续期，而架构上"签完即删 CA 私钥"⇒ 续期会**重新生成 CA**；旧 CA 仍在信任库但已不匹配
     ⇒ 游戏 TLS 握手被拒（Error 60「与服务器通讯时出错」）。**操作口径**：续期后必须重新导入信任
     （GUI 会引导；命令行 `hd2proxy.exe install`）。README 故障排查补了这条。
- **`consume` 语义：证据冲突，暂不改写语义** —— 用户认为它只在解锁物品时出现；研究线反证：
  11-17/11-18 两次**完整浏览会话**里 `consume` 出现 0 次，只在 E3 **打局会话**出现 2 次
  （均在 `Mission/end` 前约 10s、两客户端间隔 15ms）⇒ 与局内/结算强相关，不像军械库购买。
  结论：实现保留（防御式解析、不猜形状），**日志改为中性的 `UNLOCK-COST` 但不再宣称"购买扣钱"**；
  等真实请求体 + 触发时机再定语义。
- **真正的"购买/解锁扣钱"在响应里（G5 增强，下一版）**：旧研究仓 `D:\mod\workariant-net`
  `docs/UNLOCK-MAP-2026-11-06.md` §3.1 / `API-ENDPOINTS-2026-11-01.md` §8·§10 的逐字节样本：
  - 武器/配件 `POST /api/Progression/ProgressionPackage/AcquireUnlockableItem` 响应
    `{packageId32, inventoryChanges:[{mixId:货币, amount:-5000},{mixId:物品, amount:1}]}`；
  - 战备 `POST /api/SeasonPass/item/buy` 响应
    `{items:[{mixId:货币, amount:-85},{mixId:物品, amount:1},{mixId:货币, amount:85}], packageProgress:[]}`；
  ⇒ 负 amount = 扣钱、正 amount = 授予/记账，直接对**响应**做增量即可同时覆盖"扣钱 + 解锁物品"。
- **测试**：单测 666 → **669 passed**（库存：只抬不降 / 抬升 / 消费后显示语义）。
- 规则：只修 bug + 语义纠正 ⇒ 只动 `alpha.N`：`0.5.4-alpha.2` → **`0.5.4-alpha.3`**。

## v0.5.4-alpha.2（2026-11-23）— 修复：打包版引擎在中文 Windows 控制台启动即崩（GBK 编码）

- **现场**：`hd2proxy.exe engine` 在中文字符控制台（cp936/GBK）下，打印带 `⚠` 的警告行时
  `print` 抛 `UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'`，
  整个引擎进程被带走（现场只看到一行 pyinstaller traceback）。
  典型触发：证书信任自检 / hosts 与监听 IP 不一致的警告 —— 也就是**刚装完就要跑引擎**的那一步。
  影响：`0.5.0-alpha.1` ~ `0.5.4-alpha.1` 的**打包版 CLI 起引擎**（GUI 起引擎走另一条路径，未必暴露）。
- **修复**（两道防线）：
  1. `logutil.ensure_utf8_console()`：CLI/引擎入口启动时把 stdout/stderr 切到
     `utf-8 + errors="replace"`（`tools/pyinstaller_entry.py`、`__main__.main`、`server.main` 三处都调）；
  2. `log()` 的控制台输出改走 `_safe_print()`：任何原因导致 print 失败 → 降级用
     `errors="replace"` 写 bytes；控制台彻底不可用（windowed exe / 已关闭）也**绝不抛异常**
     （日志文件始终是完整 UTF-8 原文）。
- **回归测试**：`tests/unit/test_logutil_encoding.py`（10 条）用假 GBK 控制台复现现场：
  `log("⚠ …")` 不崩、文件里有原文、控制台降级写 bytes；`stdout=None` / `OSError` /
  无 `reconfigure` 的对象都不崩；并断言 CLI 与引擎入口**真的**调了 `ensure_utf8_console()`。
- 测试：单测 656 → **666 passed**；规则：**只修 bug** ⇒ 只动 `alpha.N`：`0.5.4-alpha.1` → **`0.5.4-alpha.2`**。

## v0.5.4-alpha.1（2026-11-23）— 存档层 G5 收尾：局内消耗扣减（`inventory/consume`）

- **新能力**：`POST /api/Progression/inventory/consume` 的**请求体** → 本机库存扣减
  （`engine/hooks/consume.py` + `ActiveSave.record_consume()`）。该端点响应恒 `{}`（2 B），
  扣减量只在请求体里。
- **扣减口径（与研究线 2026-11-23 逐条对齐）**：
  - `inventory_amounts[mixId] -= amount`，**下限 0**；
  - **保留行、`amount=0` 不删行** —— 库存行同时承担「是否拥有」语义（目录行 + 库存行成对才显示），
    删行可能让物品从军械库消失；服务端是否删行无样本，保留是安全默认；
  - 只扣**本机账本已跟踪**的 mixId：没基线就不凭空造数量（打 INFO 说明）；
  - 每次扣减打 INFO：`CONSUME mixId=… amount=…：存档 A → B（mission …）`，可与结算入账串起来对账。
- **请求体形状尚未采样**（研究线将在一次本地会话补采），解析按**两段式**：先防御式认
  `{"items":[…]}` / `[…]` / `{"consumables":[…]}` / 单条目 / `mixId32`；形状不认识就**不扣**
  （宁可不扣，也不扣错）；形状确认后只改解析器。
- **测试**：单测 644 → **656 passed**（+12：路径/形状/坏行/扣除/下限 0 保留行/未跟踪跳过/
  无变化不写盘/未识别不写盘/strict 拒写/INFO 日志带 missionId/扣到 0 后库存响应仍为 0）；
  引擎端到端新增「POST 消耗 → 存档数量扣减」。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.5.3-alpha.1` → **`0.5.4-alpha.1`**。

## v0.5.3-alpha.1（2026-11-23）— 存档层 G6：存档预演（不开游戏看「这份档会改什么 / 一局会加多少」）

- **新命令 `hd2proxy save-preview`**（`engine/save_preview.py`）：把本机账本**套到真实响应样本上**做纯计算预演：
  - **合并预演**：`main/` 与 `fresh/` 两套夹具 × Progression 根 / Stats/profile / 库存三类响应，
    逐项列出「哪个字段被抬、从多少到多少」（库存按 mixId 给行级差异）；
  - **结算投影**：喂一份真实 `Mission/end` 样本，算「这一局 +N 经验 / +哪些物品 / 哪些包进度」，
    以及结算后的账本值（不写盘）；
  - **存档摘要**：saveId / 身份来源 / 经验 / 成就 / 包进度 / 库存 / 统计项数 / 结算局数 / `catalog_build`。
  - 参数：`--save <saveId>`（默认 `_last.json` 指向的档）/ `--save-file <json>` / `--fixtures <dir>` /
    `--mission <样本名>` / `--json`；纯读：不联网、不写盘。
- **为什么需要**：存档效果要「重启游戏」才可见（客户端结算后不重取 `/api/Progression`），
  实机验证成本高；预演在开游戏前就能回答"这份档现在会让我看到多少"「打完一局会多多少」。
- **`repeatingPlayer` 结论（研究线 2026-11-23）**：12 份真实 `Mission/end` 响应里**恒为 `[]` 或 `null`**
  （无任何非空样本）⇒ **不落账**（保留在 `unknown_keys` 里，等出现非空样本再议）。
- **测试**：单测 631 → **644 passed**（+13：载入优先级/摘要/三类合并/结算投影/空档不虚增/缺夹具目录/文本渲染）。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.5.2-alpha.1` → **`0.5.3-alpha.1`**。

## v0.5.2-alpha.1（2026-11-23）— 存档层 G4 终身统计 + G5 成就上报合并

- **G4：Stats/profile 终身统计**（`engine/hooks/stats.py` + `ActiveSave.apply_stats()`/`record_stats()`）：
  - 只认 `/api/Stats/profile/summary` 与 `/api/Stats/profile/801/summary`（战局统计
    `/api/Stats/war/801/summary` 语义未证，**不碰**）；
  - 27 项 `totalXxx` 单调计数器：**逐 key 取 max**（只抬不降），换号/新号返回 0 时不会把本地
    已记录的战绩抹掉；不往响应里凭空加字段，bool/非数值一律跳过；
  - 全 0 响应（新号首局）**不写盘**（没信息量，不刷 `.bak`）；adopt 迁移时统计也按 key max 合并。
- **G5（上半）：`PUT /api/Progression/Achievements` 成就上报合并**（`engine/hooks/achievements.py`）：
  - 研究线实测：上报的是**完整小列表**（请求体 141 B ≈ 5–6 条，而主号 GET 只有 4 条），响应恒 `{}`；
  - 语义倾向累计覆盖 ⇒ 落成 **per-key max**（等价覆盖 + 幂等防双计 + 防旧快照把值改小）；
  - 请求体真实形状**未采样**，解析**防御式**：认 `{"achievements":[…]}` / `[…]` / `{"items":[…]}`，
    行内认 `{id,value}`；解析不出就**不写档**并记一次可操作日志（宁可不记，也不猜错写脏）；
  - 闭环：上报 → `earned.achievements` → 下次启动 `/api/Progression`（G2 钩子）合并回响应。
- **G5（下半）`inventory/consume` 扣减暂缓**：该端点响应恒 `{}`（2 B），扣减量只在**请求体**里，
  而现有抓包未采样请求体 ⇒ 没有形状就不猜着扣（钱扣错比不扣更糟）。已请研究线用 `body_shapes`
  补采 `consume` 与 `Achievements` 两个请求体，拿到后单独一版实现。
- **G4 另外两项的结论（证据）**：`SeasonPass` 元数据两账号**逐字节相同**（`039ff10e` / 14 589 B）⇒
  账号无关，不能当"买了什么"的证据；季票货币/已购在 `Progression.purchasedSeasonPassItems`（G2 已合并）
  与 inventory（G5 覆盖）里，**无需单独落账**。`Assignment` 两轮真实会话只有 GET、无写路径
  （进度由服务端推进）⇒ 按研究线建议降到最低优先级，暂只读不落账（rotation/expiry 语义未证）。
- **测试**：单测 613 → **631 passed**（+18：统计合并/记录/兼容形状/迁移 max、成就解析形状/per-key max/
  未识别不写档/闭环）；引擎端到端新增「Stats 合并 → PUT 成就入账」。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.5.1-alpha.1` → **`0.5.2-alpha.1`**。

## v0.5.1-alpha.1（2026-11-23）— 存档层 G3：结算奖励入账（只读响应，不碰请求体）

- **新能力（G3）**：`POST /api/Operation/Mission/end` 的**响应**里已经带服务端算好的本局增量，
  MITM 架构下**不需要请求体**（研究线 2026-11-23 结论）：`experience`（本局值，如 936）、
  `badges[].itemRewards`、`lootedItemRewards`、`lootedHeavyItemRewards`、`levelUpRewards`、
  `progressionPackageUpdates`。
- **入账规则**（`engine/hooks/mission_end.py` + `ActiveSave.record_mission_end()`）：
  - `experience` **累加**进存档（本局增量，不是覆盖）；
  - 物品/货币按 mixId 累加进 `inventory_amounts`；
  - `progressionPackageUpdates`（`{id32,level,progress}`，实测跨局递增 = 服务端当前值）按 **max** 合并；
  - 按 `missionId` 保留最近 20 局去重：客户端**重试同一份结算响应不会双计**；
  - `campaignWon / impact / othersImpact*` 是战果展示：**不碰**（研究线红线：不伪造社区战果）。
- **入账口径（有实据）**：`rewards` 是服务端**最终入账**清单，`badges[].itemRewards` 是明细 ——
  5 份真实响应恒有 `rewards[战备点] == 明细 × multipliers(3)`（1478→4434 / 346→1038 / 334→1002 /
  1534→4602），而征用单两者相同。默认取 `rewards`，缺失才退回明细；口径开关只有一处
  （`hooks/mission_end.ITEM_SOURCE`），日志会打两条来源的比例，实机对一次账即可确认。
- **生效时机（写进 README）**：客户端结算后**不会重取 `/api/Progression`**（研究线 E3 实测
  777/1227 条请求里 8 次 Progression 全部对应一次启动）⇒ 存档效果在**重启游戏/回主界面**后可见；
  结算画面数字由响应本身驱动，与存档无关。
- **G2 反馈小修（研究线验收建议）**：
  - 会话基准**只在会话首次身份校验一致时重建一次**（不再每次 GetMotd/HD2 别名到达都重建，
    回滚点稳定在"会话开始"而不是"最后一次校验"）；
  - `pending` 复用已带 `saveId` 校验（新增测试钉住"不会拿上一个号的基准"）；
  - orphan 的 `discarded` 对**数值字典（货币/道具数量）给具体数值**（added/removed/changed），
    换号回滚后能人工判断"哪笔钱该不该退"。
- **离线样本**：`data/fixtures/saves/mission_end/`（5 份真实结算响应；已剥 `platformAccountId`）。
- **测试**：单测 591 → **613 passed**（+22：结算解析 12、activeSave 入账/去重/strict/基准 8、
  夹具守门 2）；引擎端到端新增「POST 结算 → 存档累加 → 再拉 Progression 看到累加值」。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.5.0-alpha.1` → **`0.5.1-alpha.1`**。

## v0.5.0-alpha.1（2026-11-23）— 存档层 G2：本机 earned 账本接上 `/api/Progression` 首屏

- **新能力（G1+G2）**：把「配置驱动的解锁注入」扩成「每玩家可持久化的本机账本」：
  `响应 = base（服务端） ⊕ config（GUI 注入） ⊕ earned（本机已获得）`。存档落
  `runtime/saves/<saveId>.json`，`saveId = steam_<SteamID64>`（`Pes/GetMotd` 的 `accountId`）；
  HD2 20 位账号 id 只作**别名**（它不保证每会话出现，拿它当主键会让同玩家分裂成两份档）。
- **首屏时序（G2 核心）**：实测 items +13/+15 s → **Progression +16/+19 s** → inventory +18 s → … →
  GetMotd +24/+42 s，且客户端**一次会话只拉一次** Progression。引擎启动按 `_last.json`
  **乐观预绑定**上次的档渲染首屏；无历史档时首次 Progression 最多等 `saves.wait_seconds`
  （默认 1.2 s，等不到退回 local，不挂起）；GetMotd 到达后校验，不一致按口径分流。
- **`/api/Progression` 根钩子**（`engine/hooks/progression.py`）：**精确匹配根路径**（`/inventory`、
  `/items`、`/levelspec`、`/ProgressionPackages` 等不受影响），合并 experience / onboarding /
  shipName / location / purchasedSeasonPassItems / achievements / packageProgress；
  无改动时响应体原样返回（引用不变）。
- **⚠ 回滚粒度修正（研究线 2026-11-23 反馈）**：`.bak` 是单槽「上一版」，同局连续写 3 次只能退到第 2 次
  ⇒ 残留"部分写入"。现在回滚源改为**会话基准快照** `runtime/saves/_session-start/<saveId>.json`：
  首次写入前留基准 → 同机换号（旧档已识别）时**整档回滚**，脏档全文 + 回滚前后 hash + 被丢弃条目摘要
  另存 `runtime/saves/_orphan/`；身份校验一致 → 基准**重建**为「最后一次已验证点」；
  本局没写过 → **不动档**。`_last.json.pending` 让基准跨引擎重启存活（24 h 新鲜度上限）。
- **身份审计 + 排障**：档内 `identity` 增 `source`（getmotd / getmessages / adopted）与 `identified_at`；
  `/status` 新增 `save` 块；GUI 战况页顶部一行显示「存档 `<id>` · 预绑定待校验 / 已校验 · 本局有写入」。
- **响应路径记录**：`Pes/GetMotd`→SteamID64 主键；`Pes/GetMessages`→HD2 别名；`Progression/items`
  （**注入前**原始响应）→ `catalog_build = <items_sha8>/<rows>/<clientVersion>`；
  `Account/Login` 请求体 → `clientVersion`。
- **配置**：`saves.enabled`（默认开）、`saves.wait_seconds`、`saves.identity_strict`
  （严格模式：身份未校验时**拒绝写盘**，默认宽松）。
- **离线样本**：`data/fixtures/saves/{main,fresh}/` —— 两账号 × 6 个存档端点（真实抓包，**无**身份/票据字段；
  `items` 只记签名：main `93e7575a`/3021 行、fresh `d71655e6`/3020 行）。
- **已知限制（写进 README）**：同机换号那一刻，首屏可能已按旧档渲染，本局客户端不重取 Progression ——
  重启游戏后生效。这是客户端请求时序决定的，不是 bug（宁可首屏有内容，也不让老玩家整局看空档）。
- **测试**：单测 546 → **591 passed**（+45：会话快照/pending 15、activeSave 19、存档夹具 9、
  GUI 存档行 1、引擎端到端 1）；`test_engine_flow` 新增端到端：预置存档 → 引擎 →
  `/api/Progression` 返回 earned 合并后的值 + `/status.save` + 基准快照/pending 落盘。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.4.3-alpha.1` → **`0.5.0-alpha.1`**。

## v0.4.3-alpha.1（2026-11-20）— GUI 新增「实时战况」页（免游戏拉取 + 排查视图）

- **新页面**：侧栏新增 **实时战况**（第 3 项，`◉`），不启动游戏/引擎即可看到官方实时战况：
  - 顶部：拉取战况 / 保存快照 / 打开快照目录 / **自动刷新**（默认关，15–600 s 可调）；
  - 摘要卡：战局（warId · status time）、星球/战役、星球效果、GWE 目录条数 + 出口 IP；
  - 左表「靶星（有战役=卡面可点）」：阵营 / 星球 / 索引 / 战役 id，前线优先；
  - 右表「星球效果（planetActiveEffects）」：按星球聚合的 effect ids + 数量，支持
    **按星球名/索引/effect id 过滤**；选中一行在下方列出该星球每个 effect 的 `id · 名称`。
  - 每次拉取自动落盘 `%LOCALAPPDATA%\HD2ProxyStudio\live\last\`（status/gwe/meta.json），
    「保存快照」另存带时间戳目录。
- **排查价值**：卡面不显示时，先看左表确认目标星「有没有战役（是否可点）」，再看右表确认它
  「到底挂了哪些 effect」——把之前靠猜的两步变成一屏可见。
- 截图：[`research/screenshots/live-page-20261120.png`](research/screenshots/live-page-20261120.png)。
- **测试**：单测 511 → **514 passed**（+3：页面注册 / 快照渲染与过滤 / 无快照保存告警）；
  GUI 冒烟从 5 页扩到 **6 页**（新增 `gui-live.png`）。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.4.2-alpha.1` → **`0.4.3-alpha.1`**。

## v0.4.2-alpha.1（2026-11-20）— 无需游戏拉取当前战况（CLI `live` + GUI 推荐靶星）

- **新能力**：不启动游戏也能拉官方战况。`GET /api/WarSeason/current/WarId`、
  `/api/WarSeason/{war}/Status`、`/api/WarSeason/GalacticWarEffects` 都是**免登录公共只读**端点；
  实测直拉到的 GWE 与游戏内经过引擎抓包的那份 **sha256 完全一致**（2026-11-20）。
- **CLI `hd2proxy live`**：`--war / --faction / --limit / --out / --json / --timeout`。
  输出战况摘要（战局/星球/战役/效果/GWE 条数）+「可点靶星」推荐（有战役的星球，前线优先），
  `--out` 落盘 `status.json / gwe.json / meta.json` 快照。
- **引擎 `engine/live.py`**：DoH 解析真实 IP（绕 hosts 自环）→ SNI 直连 + **正常证书校验**；
  只读 GET、8 MiB 上限、默认 15 s 超时、失败抛 `LiveError`；摘要/靶星/落盘/文本均为纯函数（离线可测）。
- **GUI 战况改写页**：星球词条卡片新增「拉取战况·推荐靶星」按钮 —— 后台拉取后弹出候选靶星
  （阵营 + 名字 + 游戏索引，前线优先），选定后直接填入星球选择器；配合 alpha.6 的「母星 0 拒绝」，
  不会再踩 0 号 SUPER EARTH 的坑。
- **测试**：单测 500 → **511 passed**（+11：摘要 / 战役靶星 / 阵营过滤 / 名称标注 / 落盘 /
  DoH 失败 / WarId 解析 / CLI json·text·失败路径）。
- 规则：**功能变更** ⇒ 动 `X.Y.Z`：`0.4.1-alpha.6` → **`0.4.2-alpha.1`**。

## v0.4.1-alpha.6（2026-11-20）— 实机复验暴露的三处缺陷修复（靶星陷阱 / 状态文件被覆盖 / 401 无提示）

- **背景**：v0.4.1-alpha.5 在**真实 UU 路由模式**下做整链路实机复验。变种词条首轮看不到：
  profile 靶星写成了 `index 0`（SUPER EARTH 母星，没有卡面/战役），注入日志成功但游戏不渲染；
  排查期间又遇到「另一个引擎实例覆盖 `engine.json` → GUI/CLI 全部 401，GUI 误显示『引擎未运行』」。
- **修复 1（靶星 0 陷阱）**：GUI 星球选择器**排除 0 号**（SUPER EARTH 不进可选列表，默认值不再落在
  母星）；星球类模板 `_need_planet` 拒绝 0，并提示「母星没有卡面/战役，请选有战役可点的星球」；
  `config.validate` 对 `status.planet_effects` 指向 0 号给 warning（不阻止保存，但要看得见）。
  实机改用 269 BRILLIANCE（当天有战役的虫族星）后 **PREDATOR STRAIN 卡面显示 PASS**（截图存档）。
- **修复 2（控制面端口 / 状态文件被抢占）**：控制面 HTTP 服务改为**端口独占**
  （`allow_reuse_address=False` + `SO_EXCLUSIVEADDRUSE`）。Windows 上 `SO_REUSEADDR` 默认允许
  第二个引擎实例抢占 17897，覆盖 `engine.json` 后运行中引擎的随机 token 随之丢失；另外覆盖状态
  文件前若旧文件指向**仍活着**的引擎，先备份成 `engine.json.bak` 并在日志里告警。
- **修复 3（401 不再是裸状态码）**：CLI `status / verify / shutdown` 与 GUI 客户端遇到 401 时直接给出
  「状态文件与运行中引擎不匹配 → 重启引擎（停止 → 启动）」的可执行提示；GUI 顶部状态不再把这种情况
  显示成「引擎未运行」（否则用户会再点「启动引擎」起第二个实例），改为「状态文件不匹配（请重启）」。
- **修复 4（`certs status` 的 `trusted` 恒为 null）**：命令行 `certs status` 改为实际查询一次根存储
  （`check_trust=True`）；控制面 `/status` 是 GUI 轮询热路径，保持不查（省 certutil 子进程）。
- **实机验证（2026-11-20，build 26568081 / war 801 / UU 路由模式）**：变种词条 PREDATOR STRAIN
  卡面 PASS；库存注入 `INV REWRITE +103 -0` 用户确认解锁正常；三连 PASS；hosts 未被 UU 再次注释。
  证据：`docs/ACCEPTANCE-M4.md` §7 + `research/screenshots/real-brilliance-predator-strain-20261120.png`。
- **测试**：单测 494 → **500 passed**；`check_gate.py` GATE=PASS（5/5 离线自检）。
- 规则：只修 bug（无功能变更）⇒ 只动 alpha 位：`0.4.1-alpha.5` → **`0.4.1-alpha.6`**。

## v0.4.1-alpha.5（2026-11-20）— 加速器共存修复（TUN/路由模式监听 IP、hosts 注释识别、启动自检）

- **背景**：现场开启 Clash Verge TUN 与 UU 路由模式后，注入链路出现故障；实测定位到 3 个真实问题。
- **修复 1（TUN 下监听 IP 选错）**：`sysprobe.resolve_listen_ip` 以前直接采信默认路由 IP，TUN/路由模式
  会把默认路由转到虚拟网卡 → 引擎绑到 `198.18.0.1`（Clash）或 UU Wintun 地址，而 hosts 指向 LAN IP，
  游戏连不上。现在默认路由 IP **只有落在物理网卡上才采信**；`_VIRTUAL_MARKS` 增加
  `mihomo / meta tunnel / wintun / sing-box / v2ray / xray / uu wintun / 加速器` 等关键词。
- **修复 2（install 与引擎口径不一致）**：`install` 未传 `--profile` 时回退读取**默认 profile** 的
  `listen_ip`（以前直接 `auto`，与引擎不一致 → 把 hosts 写成虚拟网卡地址）。
- **修复 3（hosts 被加速器注释不可见）**：`diagnostics.hosts_diag` 新增 `comment_prefix`
  （识别 `#uu_acc` / `#g_acc`）；报错文案点明「加速器 hosts 保护 + 重写 hosts 后需重启引擎」；
  总览页/系统自检沿用同一结论，问题现在一眼可见。
- **修复 4（引擎启动自检）**：引擎启动时新增 hosts 自检（`diagnostics.hosts_startup_advice`），
  缺失 / 被注释 / 指向旧 IP 都会在 `proxy.log` 打 `⚠` 并给出修复动作，不再让用户只看到游戏的
  「与服务器通讯时出错」。
- **修复 5（文档）**：新增 `docs/ACCELERATOR-COMPAT-2026-11-20.md`（三种模式实测对照 + 操作纪律），
  README 增加「加速器 / 代理共存」说明：**切换模式 → 重写 hosts → 重启引擎 → 再开游戏**。
- **验证**：单测 486 → **493 passed**（+7：虚拟默认路由跳过 / 枚举为空回退 / install 默认 profile /
  hosts 前缀识别 / 启动建议 / 注释态报错文案 / 加速器网卡名识别）；`check_gate.py` **GATE=PASS**。
- 规则：只修 bug（不改功能）⇒ 只动 alpha 位：`0.4.1-alpha.4` → **`0.4.1-alpha.5`**。

## v0.4.1-alpha.4（2026-11-19）— 战备命名收尾 + 全局效果 target 链补名（命名 2405 → 2441，效果 174 → 202）

- **战备命名收尾（+36 行）**：
  - cat11 再补 **7** 条客户端表名（Eagle Rearm / Resupply / Medical Supplies / Eagle A2A Missiles /
    Walking Barrage Smoke / Orbital Confetti / Eagle Fly By），来源同 v5：`+4 == 原生哈希` → client 显示名
    （`name_source=stratagem-client-settings`，cat11 有名 95 → **102/108**）。
  - cat10 记账子行**反推 29 条**：cat11 许可行与 cat10 子行严格 1:1，用已命名的许可行名反补未命名子行
    （新 `name_source=stratagem-permit-parent`，medium；cat10 有名 73 → **102/111**）。
  - 新增工具 `tools/apply_cat10_parent_names.py`（只补空位 / 幂等 / 无 parent 跳过 / `--check` 只读）+ 5 条单测。
- **全局效果按 target 链补 28 条英文名**：剩余未名效果的 `nameHash` locid 在完整英文语料里不存在
  （v4 已证语料完整），改走「`values[0]` = 战备 effect_hash → cat10.mix → native_hash → client 显示名」，
  只对语义已验证的 type32（临时配发战备）/ type36（DSS 临时装备）派生，共 **28** 条
  （`name_source=target-chain`，带 `name_evidence`）；type50 虽技术上匹配但语义未验证，未纳入。
  **效果名 174 → 202 / 312**。
- **数据**：`items.json` 有名字 2405 → **2441**（目录行 2414/3020），未解 657 → **621**；
  `effects.json` 有名字 **202/312**；`gen_catalogs.py` 新增效果名覆盖层（只补空位、不覆盖上游名）。
- **口径**：效果/星球/战备新增名字**一律英文**（与游戏内本地化文本一致，避免中文译名不一致）；
  中文统一留待后续本地化批次。
- **验证**：单测 **486 passed**（478 + 5 + 3）；`check_gate.py` **GATE=PASS**。
- 规则：数据补全（非新功能）⇒ 只动 alpha 位：`0.4.1-alpha.3` → **`0.4.1-alpha.4`**。

## v0.4.1-alpha.3（2026-11-19）— 战备名字补齐（wiki 已发布清单对账，cat11 73 → 95 有名）

- **数据补全（用户要求「补这 22 条，先只补英文名」）**：对照 wiki `Stratagems` 页的 7 个 Permit 表
  （Orbital / Eagle / Support Weapon / Backpack / Vehicle / Sentry / Emplacement，排除 Other /
  Unavailable 与 Orbital Confetti、Eagle Fly By，去重后 **95 条已发布战备**）逐条核对目录：
  **95 条全部有 id（cat11 行都在）**，其中 73 条已有名字 —— 剩 **22 条只缺名字**，本轮补齐。
- **名字来源（客户端静态表，非 wiki）**：`cat11.mix_id --parent--> cat10 子行 item(原生哈希)
  --(+4 列)--> stratagem_settings.csv 的 client 行 --> 内部名 --> display_name`。
  列语义已验证：`+4 == 旧 stratagem_catalog.json 的 native_hash`（58/153 逐一对上）；
  该链反查 108 条 cat11 行命中 100 行。
- **补的 22 条**：Orbital 3（120mm HE Barrage / Airburst Strike / Precision Strike）、
  Eagle 3（Airstrike / Cluster Bomb / Strafing Run）、支援武器 3（B/FLAM-80 Cremator /
  MS-11 Solo Silo / PLAS-45 Epoch）、背包 3（AX/AR-23 Guard Dog / AX/FLAM-75 Hot Dog /
  SH-20 Ballistic Shield）、载具 3（EXO-51 Lumberer / EXO-55 Breakthrough / TD-220 Bastion）、
  哨戒炮 6（A/AC-8、A/FLAM-40、A/LAS-98、A/M-12、A/MG-43、A/MLS-4X）、阵地 1（E/AT-12）。
- **数据**：`items.json` 有名字 2383 → **2405**（目录行 2378/3020），未解 679 → **657**；
  cat11 战备行 108 行里有名 **73 → 95**；`name_source` 新增 `stratagem-client-settings`（high）。
- **工具**：新增 `tools/apply_stratagem_client_names.py`（只补空位 / 同名幂等 / 异名拒绝覆盖 /
  `--check` 只读 / 同步 coverage 并记 `coverage.name_patches`）+ 6 条单测。
- **验证**：单测 **478 passed**；`check_gate.py` **GATE=PASS**。
- 规则：数据补全（非新功能）⇒ 只动 alpha 位：`0.4.1-alpha.2` → **`0.4.1-alpha.3`**。

## v0.4.1-alpha.2（2026-11-18）— 补完物品名字（客户端 game.dll 静态表路线，命名 2191 → 2383）

- **数据补全（用户要求「补完没解出来的项」）**：先抓 store/season 响应验证「API 里没有名字」
  （26 个战争债券详情 + 商店 6 货架/76 section/329 item 位置；只给结构锚点，无 name/locid），
  再按 `/api/Progression/inventory.avatarCustomization` 的线索去**客户端 `game.dll`（build 26568081）
  静态表**取名字，行 id 与目录 mixId 精确相等、名字字段是 locid，用本机 strings 语料（24,834 条）解出：
  - cat9 横幅 **+65**（`0x2C7FEF0` stride `0x18`，high）｜cat23 称号 **+38**（mixId 本身即 locid，high）
  - cat8 胜利姿势 **+27**（`0x2CB4CF0`，high）｜cat13 语音 **+5**｜cat15 资源 **+3**
  - cat0 战团 **+27**（战团表 + SeasonPass premiumTokenMixId 配对，medium）｜cat6 **+13**｜
    cat21 礼包 **+12**（`0x2CAD240`，medium）｜cat16 难度 **+2**
- **数据**：`items.json` 有名字 2191 → **2383**（目录行 2356/3020），未解 871 → **679**；
  `name_source` 新增 7 种 dlbin/locid 来源；`name_confidence` medium 263 → 317。
  交叉验证：`banner 3460374366 → Patient Zero's Rememberance`、`title 926009925 → ADMIRABLE ADMIRAL`、
  `voice 4010084743 → Default Helldiver Voice 2`（与抓包 avatarCustomization 一一对应）。
- **已穷举失败路径**：cat7/17/18/19/20 的 mixId 不在本机任何二进制里以「行 id+名字字段」出现；
  cat9 剩 38（28 疑似未发布）、cat23 剩 23（旧语料缺 locid）。当前 build 的 30 个 `.strings` 仍在解包，
  解完可再补 cat9 约 10 + cat23 部分（对 cat7/17 无效）。
- **验证**：单测 **472 passed**（3 条断言扩展到 v3 来源）；`check_gate.py` **GATE=PASS**。
- 规则：数据补全（非新功能）⇒ 只动 alpha 位：`0.4.1-alpha.1` → **`0.4.1-alpha.2`**。

## v0.4.1-alpha.1（2026-11-18）— 物品解锁：一键清空全部已添加项（批量移除库存/目录追加）

- **新功能（用户报）**：附件这类成百上千条的物品能「批量添加」（一级选武器 → 一键解锁该武器全部配件），
  但**没有批量移除**，只能逐条点「删除选中」（一把枪几十条，撤回要点几十次）。
- 物品与战备页顶部汇总行右侧新增 **「清空全部已添加」**（danger 按钮）：一次撤回本页所有改动 ——
  武器/附件/外观/战备 **四类库存行** + **目录追加**列表全部清空；「目录缺失物品」自动配对的目录行
  随之消失；`profile["items"]["template"]` 这类标量设置保留。
- 交互：点击先弹确认框列出各类条数（如「武器 0 · 附件 117 · 外观 1 · 战备 0 · 目录追加 1」），
  **点「否」不做任何改动**；没有可清项时直接提示「本页没有已添加项（库存与目录追加都是空的）」。
  只改本机内存 profile，「应用配置」后才热更新到引擎（与其它编辑操作一致）。
- **验证**：单测 468 → **470**（批量添加后「否保留 / 是清空 + template 保留 + 汇总归零」端到端；
  空列表提示且不标脏）；`check_gate.py` **GATE=PASS**；打包版实机临时 state 隔离验证（批量添加 →
  清空 → 二次确认 → 已加入归零）。
- 规则：小幅功能扩展 ⇒ `0.4.0-alpha.1` → **`0.4.1-alpha.1`**（patch 位 + alpha.1 重置）。

## v0.4.0-alpha.1（2026-11-18）— 服务端物品目录全量做进产品（3020 行 · GUI「目录总览」· 空号默认 55）

- **新功能（用户要求）**：把 `/api/Progression/items` 的 **3020 行全量目录**做进产品 ——
  此前 `data/catalogs/items.json` 只覆盖 1950 行，缺口 1112 行的名字/类别在界面上完全是空的。
- **数据（items.json 1950 → 3062）**：
  1. **行集补齐**：3020 服务端目录行全部并入（`in_catalog=true`），另保留 42 条目录外研究线条目
     （`in_catalog=false`，其中 3 条仍有 `unlock_template`）；每行带 `catalog_category` 服务端类别编号。
     依据：目录与账号无关 —— 主号与新号两次抓包 sha256 逐字节一致（`d71655e6…`，3020 行）。
  2. **名字 1821 → 2191**（目录行 2164/3020）：新增 `data/sources/catalog_names_resolved.json`
     名称解析快照 v2，按 items.json 内部名 / dlbin LoadoutEntry 实体 / boosters 表 三条只读路线，
     再加两条**结构证据**路线（战备目录 `(effect_hash, native_hash)` 与 effects.json GWE
     `values_raw[0]` 对表 → cat10 记账行名字 + cat11 许可按 1:1 子行取名；外观套装行取全部同名
     子行的名字 → cat4）**逐行匹配**后补名；**解析不到就 `name=null`**（界面显示
     `mixId · 类别（内部名未解）`，不编译、不音译、不猜）。推断名在数据里带 `name_confidence`
     （medium 263 / low 1），不冒充显式映射。
  3. **类别语义（不臆测）**：`progressionCategory` → 语义类别先按「已有物品多数投票（≥60%）」推断，
     再用快照里的 `category_meaning`（每个 cat 附证据出处）补空缺；新增 `booster`（强化资源）/
     `banner`（徽章）/ `currency`（货币）三类；仍无证据的 **512 行记 `unknown`** 并保留 cat 编号。
  4. **空号默认拥有 55 项**：新增 `data/sources/fresh_account_inventory.json`（新号首进游戏的库存
     基线），标 `default_owned`；按 `itemId` 补匹配**只在该 itemId 目录里唯一时**生效（附件 optionId
     被大量共享，泛匹配会把 55 误标成 150 —— 实测踩到并收紧）。
  5. items.json 顶层新增 `catalog` 覆盖统计段（catalog_rows / in_catalog / named / unnamed /
     default_owned / by_category），GUI 与测试都直读它，不再各自数。
- **GUI（第 6 个只读 tab「目录总览」）**：汇总两行（目录 3020 · 界面条目 3062 = 目录内 3020 + 目录外 42 ·
  已命名 1959 · 未解 1103 · 空号默认 55 · 各类别行数）+ 类别筛选（全部/武器/附件/外观/战备/强化资源/
  徽章/货币/未分类/仅空号默认拥有/仅目录外）+ 全量列表（3062 条不截断，标签带类别与
  「默认已有」「目录缺」标记）；页面**不解锁任何东西**。物品页顶部汇总行同时并入「目录 3020 行 ·
  命名 1959 · 空号默认 55」。
- **生成器**（`tools/gen_catalogs.py`）：新增目录补全阶段（`_complete_catalog_items` + 类别投票 +
  名称快照 + 空号基线）与 `--resolved-names` / `--fresh-inventory` 参数；修两个 bug：`cat 0` 被
  `int(x or -1)` 变成 -1；itemId 兜底匹配曾用错索引。
- **验证**：单测 **445 → 468**（目录补全纯函数 12 条 / 真实数据验收 10 条 / GUI 目录总览 1 条 +
  旧测试口径更新）；`python tools/check_gate.py` **GATE=PASS**；`gui_smoke.py --tabs` 新增逐 tab
  截图能力，6 个 tab 渲染正常。
- 规则：功能变化 ⇒ `0.3.0-alpha.3` → **`0.4.0-alpha.1`**（minor bump + alpha.1 重置）。

## v0.3.0-alpha.3（2026-11-17）— 修复「续期证书后游戏报 Error 60 / Status -1」（CA 未受信 + GUI 无真安装入口）

- **修复（现场实测踩到）**：游戏弹 `ERROR / Request: … / Error: 60 / Status: -1`（"communicate with
  our server"）。取证：引擎 `/status` 显示 `req=0 deny=3 rewrite=0`，日志只有
  `TLS REJECTED … SSLZeroReturnError(TLS/SSL connection has been closed (EOF))` ——
  **不是网络问题**：16:06 在 GUI 点「签发 / 续期证书」换了一张新会话 CA，但**没有重新导入受信任根存储**；
  `install --dry-run` 里 `cert_trusted=false`。而当时 GUI 只有「安装计划（dry-run）」、**没有真安装入口**，
  界面/自检/日志都不提示「证书未受信」，用户只能看到通用网络错误。
- **修复内容（四项）**：
  1. **证书信任状态可见**：`certs.cert_status(check_trust=True)` 新增 `trusted` / `trust_scope`
     字段，未受信时 warnings 给出可操作文案；`sysprobe.cert_trusted()` 带 3 秒缓存（一次检查要
     spawn `certutil`，不能反复跑）；控制面 `/status` 保持默认不查（GUI 0.6s 轮询的热路径）。
  2. **诊断升级为 error**：`diagnostics.evaluate()` 把「证书未受信」列为 **error**（不是 warn），
     总览红字与「系统自检」都会直读；文案点明「游戏 TLS 握手会被拒（引擎日志 TLS REJECTED）」。
  3. **GUI 补真安装入口**：总览页新增「**安装 / 修复（UAC）**」按钮（改 hosts + 导入信任，一次 UAC）；
     「签发 / 续期证书」成功后**自动检测信任**，未受信就弹一次确认并一键导入（只问一次，不重复弹）。
  4. **引擎侧提示**：启动时检测到 CA 未受信打印 `⚠ 证书未受信任…修复：hd2proxy.exe install 或 GUI
     「安装 / 修复」`；TLS 拒绝日志追加「多为客户端不信任本机 CA → 点 GUI 安装 / 修复或运行
     hd2proxy install」提示。
- **验证**：单测 434 → **445**（证书信任状态三态、`sysprobe.cert_trusted` 缓存与 `clear_caches`、
  诊断 error 判定、GUI 安装/续期引导 5 条）；源码实测：未受信证书目录 → `trusted=False` +
  自检 error + 引擎启动 ⚠ + `curl` 触发握手失败日志含提示；真实证书目录 → `trusted=True` 无误报。
- 规则：只修 bug ⇒ 版本位不变（`0.3.0-alpha.2` → `0.3.0-alpha.3`）。

## v0.3.0-alpha.2（2026-11-17）— 修复切「总览」页卡顿 + 弹几个 PowerShell 窗口（子进程隐藏窗口 / 一次 netstat / 诊断节流）

- **修复（用户报）**：「工具 GUI 切总览页会卡住一会，并且弹出几个 powershell 窗口」。
  根因不是渲染，是**控制台子进程**：冻结版 GUI 是 windowed 程序（自己没有控制台），它 spawn 的每个
  控制台子进程都会新开一个窗口（Windows Terminal 是默认宿主，看起来像 PowerShell）；
  而总览的现场检查每次刷新要 spawn **7 个**子进程、耗时 **755 ms**（冷启动实测）：
  443/8080/17897 每端口两条 `netstat -p TCP` / `-p TCPv6`（共 6 条）+ 一条 `tasklist`（573 ms）。
  更糟的是总览每次刷新都 `sysprobe.clear_caches()`，缓存形同虚设 → 每次切页都重跑一遍。
- **修复内容（四项）**：
  1. `engine/sysprobe._run` 给**所有**外部命令加隐藏窗口参数（`CREATE_NO_WINDOW` +
     `STARTF_USESHOWWINDOW`/`SW_HIDE`）—— 窗口必须从根上消掉，只靠节流仍会闪；
  2. 端口占用改成**一次 `netstat -ano`**（不带 `-p`，天然覆盖 TCP+TCPv6）产出全量监听表、
     缓存 3 s，三个端口共用；进程名改用 **ctypes Toolhelp 快照**（0 子进程、<5 ms），
     `tasklist` 只在快照失败时兜底；
  3. 总览页现场检查 **2.5 s 节流**，去掉每次刷新的 `clear_caches`；「系统自检」保留强制重算；
     引擎启动/停止后由 App 主动清缓存并**绕过节流**重算（端口现场已变，不能显示旧值）；
  4. `engine/server.py::port_owner_report` 改走 `sysprobe`（不再自带 netstat/tasklist），
     `gui/client.py::run_cli` 补隐藏窗口参数 —— 「安装 / 证书」等按钮也不再弹 CLI 控制台窗。
- **实测**：`diagnostics.collect()` **755 ms / 7 次 spawn → 55 ms / 1 次 spawn**（冷启动）、
  **1 ms / 0 次**（缓存命中）；切总览页不再闪窗、不再卡顿。
- 单测 427 → **434**（新增：三端口共用一条 netstat 的回归断言、`_parse_all_listeners` 多端口/
  IPv6/排除 ESTABLISHED、隐藏窗口参数与 `_run` 接线、`clear_caches` 三张缓存全清、
  Toolhelp 失败退回 tasklist、总览诊断节流；受影响 6 个用例改为注入进程名表，不再依赖本机进程）。
- 规则：只修 bug ⇒ 版本位不变（`0.3.0-alpha.1` → `0.3.0-alpha.2`）。

## v0.3.0-alpha.1（2026-11-17）— 端口诊断 P0：启动前端口预检 / 换监听地址 / 系统自检 / 游戏运行守卫

- **新增（能力）**：把第三方 `variant_mod 1.26` 面板层的端口诊断交互移植进本工具（引擎侧的
  独占绑定 + 5s 重试 + BIND FAIL 占用者日志此前已继承）。分析见
  `docs/THIRDPARTY-VARIANTOM-1.26-2026-11-17.md`。
  1. **启动前端口预检**：点「启动引擎」先查 **443（代理）/ 8080（CRL）/ 17897（控制面）** 三态
     （free / 本工具占用 / 别人占用）；冲突弹窗列出占用者进程名+PID+完整路径，
     可「换监听地址…」「仍然启动」「取消」。0.0.0.0/:: 通配绑定单独提示（换 IP 无效，必须关掉）。
  2. **「换监听地址」对话框**（总览冲突弹窗 + 设置页按钮）：候选只列真实网卡 IPv4，
     逐个标 443 占用状态、网卡名、虚拟网卡与推荐项（主网卡优先）；应用写回 profile。
  3. **系统自检 + 总览红字**：`engine/diagnostics.py` 一次性检查端口 / hosts（含被注释、
     IP 与监听不一致）/ 证书 / 游戏进程；总览页有问题时红字直读，点「系统自检」看全文。
     新增关键告警：**hosts 已指向本机但引擎没在跑 → 进游戏必报「与服务器通讯时出错」**。
  4. **游戏运行守卫**：检测到 `helldivers2.exe` 在跑时，启动/停止引擎会先弹确认（会掐断会话）。
- 端口探测升级：`netstat` 同时查 IPv4/IPv6（双栈 `[::]:443` 也能查到）、占用者带进程完整路径、
  显式 `SO_EXCLUSIVEADDRUSE` 试绑判定「能否独占绑定」、按 PID 区分自家引擎（正常）。
- 单测 402 → **423**（端口监听者解析/通配识别/独占试绑/三态、hosts 四态判定、
  快照结论全分支、候选 IP 排序与推荐、预检冲突、GUI 红字与自检弹窗、换监听地址写回）。
- 规则：新增能力 ⇒ `X.Y.Z` 变动、阶段重置（`0.2.0-alpha.4` → `0.3.0-alpha.1`）。

## v0.2.0-alpha.4（2026-11-17）— 光能者分组改名（「卡牌 4」→「光能者 4」）+ 打包 GUI 实测

- **修复（用户报）**：变种选择器里 Illuminate 阵营的分组显示成「卡牌 4」。追查确认**不是翻译错误**：
  名字来自外部 mod「全变种 Quanbianzhong 10.00」的目录（该目录 note 写明「选项名称沿用
  Quanbianzhong 10.00」），研究仓快照与本仓库 `variants.json` 都原样透传，GUI 直接显示
  `groups[].name`。而这 4 条变种的 `meta.faction` 全是 `illuminate`（光能者）——官方中文叫
  「光能者」，组名与阵营不符。
- **修复内容**：覆盖层 `groups` 规则新增 `rename`：把「卡牌」组显示名改为「**光能者 4**」，
  原组名保留在 `groups[].source_name` 可追溯；数量后缀仍按实际成员数重算。
  `docs/VARIANT-INVENTORY-2026-11-17.md` 与 `data/catalogs/README.md` 的阵营口径同步修正。
- **验证**：单测 399 → **402**（覆盖层 rename 生效/留档、空 rename 拒绝、Illuminate 组显示名与
  faction 一致；另加 GUI 选择器标签断言）；打包 GUI 用计算机操作实测：五页切换、变种下拉展开、
  选中表自适应（见 docs/RELEASE-v0.2.0-alpha.4.md）。
- 规则：只修显示措辞、不新增能力 ⇒ 版本位不变（`0.2.0-alpha.3` → `0.2.0-alpha.4`）。

## v0.2.0-alpha.3（2026-11-17）— 「战况改写」页：三处小列表改成下拉 + 选中表按行数自适应

- **改进（用户要求）**：变种词条 / 全局效果 / 星球词条原来用 3 行高的列表，只能看到 3 条、还占版面；
  改成和「星球选择」一样的**一行下拉**（`PickDropdown`：收起占一行，点开是原生下拉弹窗，
  可输入关键词实时过滤；右侧显示「共 N 条」）。变种 18 条、效果 312 条都能完整展开。
- **修复（设计问题）**：下方「选中变种 / 全局效果 / 星球词条」表固定 2 行高，5 个变种生效时只显示 2 条
  （用户报「只能显示两个、实际 5 个」）。`RowEditor` 新增 `autosize`：按实际行数自适应（2–8 行），
  5 条就显示 5 条，清空后缩回 2 行。
- 单测 394 → **399**（下拉全量条目 / 输入过滤与恢复 / 选中回显 dual ids / 三张表按行数增高 / 缩回）。
- 规则：只动显示与交互、不新增能力 ⇒ 版本位不变（`0.2.0-alpha.2` → `0.2.0-alpha.3`）。

## v0.2.0-alpha.2（2026-11-17）— 修复「目录里没有的武器解锁不生效」（Shear 等三把未发布武器）

- **修复（用户报）**：Shear（`2112173638`）加进库存后游戏里不出现，而对照组 Bolt Pistol /
  Melta Mine 正常。根因：**库存行必须与目录行成对注入**。
  - Bolt Pistol / Melta Mine 在服务端 `/api/Progression/items` 目录里本来就有 → 只注库存行即可；
  - Shear / P-41 Ombudsman / SG-8F Punisher Fire of Liberty **目录里没有** → 只注库存行客户端不显示，
    还要克隆同族模板 itemId 补一条目录行（`items.add [{id, template}]`）；
  - 而「物品与战备」四个 tab 的「添加到库存」**只写了库存行**，`目录追加` tab 才写目录行 ——
    用户按普通物品方式添加时，目录行就漏了（日志里一条 `ITEMS REWRITE` 都没有）。
- **修复内容**：
  - 添加库存行时，若该物品在 `items.json` 里带 `unlock_template`（= 服务端目录缺失），
    自动在 `profile["items"]["add"]` 里配对一条 `{"id": mixId, "template": 模板 itemId}`；
  - 移除库存行时对称撤掉配对的目录行；
  - 「目录追加」tab 选中这类物品时也自动带上模板（不必手填全局模板 itemId）；
  - 打开「物品与战备」页时**自愈老 profile**：库存里已有这类物品但缺目录行的自动补齐（不必删了重加）；
  - `data/sources/unreleased_items.json`：三把武器的模板配对（研究线 M4 实机验证值），
    `tools/gen_catalogs.py` 校验模板行在目录快照里后写进 `items.json` 的 `unlock_template` 字段。
- 单测 386 → **394**（模板数据一致性 / 模板行在目录里 / 与 GUI 模板不漂移 / 加库存自动配对 /
  已发布武器不写多余目录行 / 移除对称撤掉 / 目录追加 tab 带模板 / 老 profile 自愈幂等）。
- 规则：只修 bug ⇒ 只动 `alpha.N`（`0.2.0-alpha.1` → `0.2.0-alpha.2`），版本位不变。

## v0.2.0-alpha.1（2026-11-17）— 「附件」改成两级：按武器筛选 + 一键解锁该武器全部配件

- **新增（功能更新）**：「物品与战备 · 附件」改成**两级菜单**：
  - 一级只列**武器**（57 把，带配件数：`Adjudicator · 28 件`、`Breaker · 46 件`…）；
  - 选中武器后，二级列出**该武器的具体配件**（附件解锁是「武器 × 附件」粒度，见
    `docs/UNLOCK-MAP-2026-11-06.md`：同一附件在不同枪上是不同 mixId）；
  - **直接选中一级武器点「添加到库存」= 一次解锁该武器全部配件**（去重：已在列表里的跳过，
    toast 报告新增/已存在条数）；在二级列表选中某条则只加那一条；
  - 关键词搜索跨全部武器搜配件名（结果标签带武器名）；清空关键词再搜索 = 回到按武器浏览。
- **数据补全**：附件目录行从「研究注入用到的 1176 条」补到**全量 1455 条 / 57 把武器**
  （`items.json` 1671 → **1950** 条）；每条附件新增 `parent_id`（所属武器 mixId）、
  `parent_name`（武器内部名，1411/1455 已解）、`option_id`（附件选项 id，元数据）。
- 新增工具 `tools/extract_catalog_index.py`：把 `/api/Progression/items` 抓包压成
  `data/sources/progression_item_catalog.json`（3020 行 mix→item/cat/**parent**，含抓包 sha256），
  换 build 重跑即可；`tools/gen_catalogs.py` 据此补全附件行并生成 `parent_*` 字段。
- 单测 380 → **386**（两级导航 / 一键解锁全部 + 去重 / 二级单条添加 / 跨武器搜索 /
  附件分组数据层 / 目录索引带 parent）。
- 规则：新增功能 ⇒ `X.Y.Z` 变动、阶段重置（`0.1.1-alpha.4` → `0.2.0-alpha.1`）。

## v0.1.1-alpha.4（2026-11-17）— 附件列表只显示 80 条：去掉列表截断（1176 条全量进列表）

- **修复（用户报）**：「附件」tab 只显示 80 条，而 `items.json` 里有 1176 条附件。根因是
  `Catalogs.search_items()` 的默认 `limit=80`（关键词搜索 200）——数据没丢，是**列表截断**：
  - tab 初始填充只取前 80 条，计数标签还显示 `80/80`，看起来像「只有 80 条」；
  - 列表上方搜索框只在这 80/200 条里过滤，宽泛关键词命中超过 200 条时仍会被截断。
- 现在：`search_items(limit=None)` = 不截断；四个 tab 与「目录追加」都装全量
  （附件 **1176**、外观 426、武器 24、战备 30、目录追加 1671）；计数标签显示 `1176/1176`；
  列表下方提示改为「本类共 N 条；上方搜索框在全部条目里过滤」。
- 性能：Tk Listbox 装 1.7k 条无压力（实测启动/切换无可感延迟）。
- 单测 379 → **380**（新增：列表不截断——附件列表条目数 == 目录附件总数；提示行写着总数；
  既有 tab 测试从「min(80, 总数)」改为「等于总数」）。
- 规则：只修 bug/行为 ⇒ 只动 `alpha.N`（`0.1.1-alpha.3` → `0.1.1-alpha.4`）。

## v0.1.1-alpha.3（2026-11-17）— 修复「物品与战备」四个 tab 不筛选类别（外观里混进附件）

- **修复（用户报）**：「武器 / 附件 / 外观 / 战备」四个 tab 原来**共用同一份全量列表**
  （只差标题不同），所以「外观」里会冒出 `TUBE REDDOT 1,5x`、`Vertical Grip` 这类附件；
  而且能把附件加到「外观」的库存列表里。现在四个 tab 各自只显示对应类别：
  - 武器 24、附件 1176、外观 426、战备 30（合计 1656；另有 15 条探测文件里的混类条目
    不属于任何一类，只在「目录追加」tab 出现）；
  - 搜索框也带类别过滤（附件 tab 搜 `grip` 有 112 条，外观 tab 搜 `grip` 为 0）；
  - 加了一层兜底：万一列表被塞进异类条目，「添加到库存」也会拒绝并提示正确类别。
- 数据侧无需改动：`items.json` 的 `category` 字段本来就是准的（来自库存配置文件的分类），
  这次只是界面没用它；新增 `Catalogs.item_category()` 与 `search_items(..., category=...)`。
- 单测 375 → **379**（`tests/unit/test_gui_pages.py` +3：tab 只显示本类 / 搜索不越界 / 跨类拒绝；
  `tests/unit/test_item_names.py` +1：分类筛选的数据层保证）。
- 规则：只修 bug/行为 ⇒ 只动 `alpha.N`（`0.1.1-alpha.2` → `0.1.1-alpha.3`）。

## v0.1.1-alpha.2（2026-11-17）— 武器内部名补齐：走 dlbin 只读路线（LoadoutEntry → 实体名）

- **修复/补全（alpha.1 的数据缺口）**：alpha.1 只解出「附件 + 外观」的内部名（1520/1671），
  武器类（含主武器/副武器/投掷物/背包）仍是 `xxx · 武器（内部名未解）`。本版用**dlbin 只读路线**补上：
  - `generated_entities.dl_bin` 的 `LoadoutEntryComponentData`（块 `0x4F2CF417`，199 行 × 32 B）行 `+0x00`
    就是服务端目录行的 **itemId**；该行所属实体在 `EncyclopediaEntryComponentData` 里有内部名
    （`Veto` / `Gallant` / `Shear` / `Smokescreen` / `Pineapple` …）；
  - 新增 `tools/extract_item_names.py`：只读解包缓存 + typelib + 研究仓实体名，产出
    `data/sources/item_names_derived.json`（build 26568081，**191/199 行有名字、177 个唯一 itemId**）；
  - 生成器新增第 4 条名字规则（`loadout-entity`），只填空缺、不覆盖已有名字。
  - 覆盖：**1520 → 1544 / 1671**；武器 tab 里能直接看到 `Veto` / `Gallant` / `Shear` 等名字，
    搜索框可搜 `veto` / `gallant`。
- **为什么写工具而不是一次性脚本**：2026-11-13 起**写** `data/game/*.dl_bin` 会被 EAC 判「未知的文件版本」，
  但**读**一直可用（解包密钥在 `refs/dlbin/keys/`、明文缓存在 `refs/dlbin/plaintext-<build>/`）。
  换 build 后重跑 `python tools/extract_item_names.py` 即可刷新武器内部名。
- **已知限制**：战备（目录 cat 11）的解锁 itemId 在本地 **55 张数据表 + 实体库**里都搜不到映射
  （全表 u32/u64 扫描 0 命中；只有 9 处偶然命中），说明客户端靠服务端/商店响应关联，
  当前抓包里没有 store/season 响应 ⇒ 30 条战备仍显示「内部名未解」，不编造。
- 单测 373 → **375**（`tests/unit/test_item_names.py`：加武器名断言、dlbin 产物结构校验、优先级规则）。
- 规则：本版是**数据补全/修复** ⇒ 只动 `alpha.N`（`0.1.1-alpha.1` → `0.1.1-alpha.2`）。

## v0.1.1-alpha.1（2026-11-17）— 「物品与战备」显示物品内部名（不再只有 id）

- **新增（小规模功能更新）**：「物品与战备」页的物品列表/编辑器原来只显示 `mixId · attachment`
  这种「id + 英文类别」，1671 条里只有 391 条有名字，其余无法辨认。现在补**内部名**（本地化译名暂不做）：
  - 附件：服务端目录行 `itemId` = 武器改装选项 id → 选项内部名（如 `TUBE REDDOT 1,5x`、`Vertical Grip`）；
  - 外观：目录行 `itemId` = 外观表行 id → 外观表名字（已有的显示名逻辑，本次合并进同一解析）；
  - 武器 / 战备等类别：目录行只有 id、本机没有可用的名字来源 → **留空并明确标注**
    「内部名未解」，不编造。
  - 结果：**1520 / 1671** 条有名字（原 391）；列表与编辑器显示 `mixId · 名字`，搜索框可按名字搜
    （如搜 `reddot` / `vertical grip` 直接命中）。
- 数据侧：`data/catalogs/items.json` 每条新增 `catalog_category`（目录类别：2=附件、3=外观、11=战备…），
  已解析出名字的再带 `name_source`（`catalog-option` / `armor-table`），便于回溯。
- 新增仓库内数据源 `data/sources/progression_item_catalog.json`：服务端 `/api/Progression/items`
  抓包的紧凑索引（3020 行 mixId→itemId/类别，含原始抓包 sha256）；其余名字来源来自
  repo-datamined 的武器改装选项表与 variant-net 的外观表。
- 单测 364 → **373**（新增 `tests/unit/test_item_names.py` 9 条：名字覆盖、抽样映射、GUI 标签/搜索、
  生成器解析规则与类别冲突报错）。
- 规则：本版是**功能更新** ⇒ 版本位 `0.1.0` → `0.1.1`，阶段重置 `alpha.1`。

## v0.1.0-alpha.5（2026-11-17）— 变种目录补齐（Caustic / Noxious）+ 版本规则与发版工具

- **修复（用户报）**：「变种」里虫族少了 **Caustic Strain** 和 **Noxious Strain**。根因是两层：
  1. `caustic_strain`（1430/1431）早就在数据里，但**没进 `groups`**——变种界面只渲染分组，等于隐藏；
  2. Noxious（1434/1433）完全没收录——源变种目录冻结在 2026-11-01，它是之后上线的内容。
  现在两条都进「虫族」组（5 → **7**）：**腐蚀变种** `[1430, 1431]`（`bugs_acid`）、
  **毒瘴变种** `[1434, 1433]`（`bugs_defiler`）；旧内部名 `caustic_strain` 保留为别名，
  老 profile 里的名字仍能解析。证据：直连官方 `GalacticWarEffects`（315 条）+ `801/Status`
  （161 条）现网快照，tag↔mechanic 由**线上星球共现**判定（1433/1434 的星球集合完全相同）；
  全量盘点与「为什么别的没漏」见 [docs/VARIANT-INVENTORY-2026-11-17.md](docs/VARIANT-INVENTORY-2026-11-17.md)。
- **改进（防复发）**：`tools/gen_catalogs.py` 增加**覆盖层**输入 `data/sources/variant_overlay.json`
  （源目录冻结后的增量/改名/别名/分组规则写进仓库，可复现），并**把引擎目录
  `data/legacy/variant_catalog.json` 也纳入生成**——以前它是手工拷贝，两份目录漂移正是
  「items 里有、groups 里没有」的土壤。新增单测 `tests/unit/test_variant_catalog.py`（23 条）：
  wiki 全量清单、GUI/引擎目录一致性、覆盖层规则（含 6 种写错即报错的情形）。
- 新增版本规则落地：`docs/VERSIONING.md`、`src/hd2proxy/versioning.py`、
  `tools/bump_version.py`（按规则算下一版并改 `__version__`/pyproject）、
  `tools/check_version.py`（版本一致性；门禁新增第 0 步）。
- 新增 `tools/sync_release_area.py`：把 release 产物同步到专用测试区（`current/` 解包最新版、
  `artifacts/` 放当前版本资产、`archive/` 留历史）；默认取 GitHub Release 资产，保证与用户
  下载物逐字节一致；`build_dist.py` 支持 `--test-area` / `HD2PROXY_TEST_AREA` 构建后自动同步。
- 单测 311 → **364**（新增变种目录 24 条 + 版本规则 27 条 + 完整性标签工具 2 条；其余为既有）。
- **修复（环境坑）**：release 测试区里的 GUI 双击后仍以 **Low 完整性**运行（文件被 Low 令牌工具解压→
  继承 Low 标签），导致「保存配置/证书签发/启动引擎」`PermissionError(13)`。新增 `tools/win_integrity.py`，
  在 `sync_release_area.py`（解包测试区后）与 `build_dist.py`（构建后）自动把目录树标回 Medium；
  记录见 [docs/WIN-INTEGRITY-TRAP.md](docs/WIN-INTEGRITY-TRAP.md)。

## v0.1.0-alpha.4（2026-11-17）— alpha.3 打包版实测发现的 3 个小问题 + 本机自签签名

- **修复**：「切换直通」只改引擎运行时状态（控制面 `/passthrough`），不写回 profile ——
  切到「改写」后再点「应用配置」会按旧 profile 把直通恢复，看起来像开关失灵。
  现在切换成功即写回内存 profile 并标记「未保存」（点「保存配置」可持久化）。
- **修复**：打包版证书签发的「下一步」提示写成 `python -m hd2proxy install …`，打包版里照抄
  必然失败；现在冻结模式提示 `hd2proxy.exe …`，源码模式仍是 `python -m hd2proxy …`。
- **修复**：安装计划 / 还原计划 / 离线预演 / 证书签发等只读弹窗长行不换行、左右被裁看不全；
  现在按词换行，并默认从开头显示（原来滚到末尾）。
- **新增**：`tools/sign_local.ps1` —— 本机自签代码签名：创建自签代码签名证书、装到当前用户
  受信任根 + 受信任发布者（免管理员）、给 dist 里的 exe 签名；`build_dist.py` 支持
  `HD2PROXY_SIGN=1` 在构建后自动签名。用途仅为**本机测试不被 SmartScreen 拦**，
  对外分发无增益（别人仍看到未知发布者）。详见 `docs/SIGNING-LOCAL.md`。
- 新增回归测试：`_cli_hint` 冻结/源码、`apply_passthrough` 写回、保存后 passthrough 往返（**311 passed**）。
- 新增开发侧工具 `tools/sync_release_area.py`：把打包产物同步到「release 产物测试区」
  （解包最新版到 `current/`、归档旧 zip、写 `VERSION.txt`）；`build_dist.py` 支持
  `--test-area` / `HD2PROXY_TEST_AREA` 构建完自动同步，发版后测试直接双击测试区里的 exe。

## v0.1.0-alpha.3（2026-11-17）— 修复 GUI「启动引擎」弹出第二个窗口/按钮失效

- **修复**：打包版 GUI 按源码模式拼 CLI 命令（`[sys.executable, legacy_proxy.py, …]` /
  `[sys.executable, "-m", "hd2proxy", …]`），冻结后 sys.executable 是 gui exe，子进程变成
  「GUI exe + 非法参数」→ windowed 版弹 PyInstaller 错误对话框（用户看到的第二个窗口），
  「签发/续期证书、安装计划、还原计划、验证三连、启动引擎」等按钮在打包版全部失效。
  改为冻结时用同目录 `hd2proxy.exe` 跑子命令（源码模式不变）。
- 新增回归测试：冻结/源码两种模式下的 `cli_argv` 与 `engine_argv` 断言。
- **修复（打包 GUI 实测发现）**：子进程中文输出乱码。冻结版 PyInstaller 引导器的 stdout 编码
  由控制台代码页决定（中文 Windows = cp936），`PYTHONUTF8` / `PYTHONIOENCODING` 对冻结进程
  **无效**（四种组合实测输出字节完全相同）→ GUI 里「安装计划（dry-run）」等结果整段变成 `?`。
  现在 GUI 收原始字节再解码：UTF-8 优先、失败回退 GBK；引擎日志流式读取同样处理。
- **修复（打包 GUI 实测发现）**：冻结版把 `logs/`、`runtime/` 写在 exe 旁边；若用户把目录放到
  Program Files 等只读位置会静默写失败（日志丢失、`打开日志` 报 FileNotFoundError 原文）。
  现在冻结版这两类运行期目录统一落在可写状态目录（`%LOCALAPPDATA%\HD2ProxyStudio`），
  源码模式仍在仓库内；「打开日志 / 打开状态目录」在文件不存在时给一句人话提示而不是抛原始异常。
- 新增回归测试：`decode_output` UTF-8/GBK、`run_cli` GBK 解码、`open_path` 友好提示、
  冻结版 logs/runtime 落状态目录（共 **308 passed**）。
- 其余同 alpha.2。

## v0.1.0-alpha.2（2026-11-17）— 修复双击 exe 直接退出

- **修复**：`hd2proxy.exe` 双击（无参数）时打印 CLI 帮助后 `exit 2`、看起来「自动退出且没有 GUI」。
  现在无参数会直接打开 GUI；新增 **`hd2proxy-gui.exe`**（windowed，无控制台）给普通用户双击使用。
- 打包改为「单 bundle 双 exe」（共用 `_internal`，体积基本不变）；打包冒烟增加两个 GUI 入口的
  存活/窗口检查 + 无参数打开 GUI 的回归断言。
- 其余功能同 alpha.1。

## v0.1.0-alpha.1（2026-11-16）— 首个可分发预览版

首个打包含 GUI 与引擎的 Windows x64 预览版。M4 已逐项实机验证 6 项核心能力，
但更多机型/网络环境/游戏更新后的全流程稳定性仍需观察，故以 **alpha** 发布。

### 新增（M0–M4 累计）

- **引擎**：本机 MITM（443）+ 本地 CRL（8080），单域名白名单 + 仅本机来源；
  钩子管线 `warinfo → status → inventory → items → customize → capture`；命中改写自动修正
  Content-Length/编码；控制面 `127.0.0.1 + token`（/status /config /events /verify /shutdown）。
- **配置面**：schema v2 单一 profile JSON（校验/归一化/热重载/旧配置迁移）；`status.trials_planet`。
- **证书**：ca 模式会话证书（SAN 单域名、≤2 天、签完删 CA 私钥）、剩余 <12h 自动续期、preflight。
- **系统面**：hosts 原子写 + 备份 + 编码/行尾保持；UAC 自提升安装/还原；回读系统状态判定成败。
- **GUI（Tk，5 页）**：总览 / 战况改写 / 物品与战备 / 抓包与日志 / 设置；后台轮询，关窗不停引擎。
- **6 项能力模板**：变种词条 / 全局效果 / 战备试用 / 物品解锁 / 休眠星四件套 / 生态借用；
  延后项（防守战役 / 城市分区 / L2 改装）折叠在「扩展 / 实验」区并标验证状态。
- **离线预演**：`preview` 把 profile 套到真实抓包裁剪样本上，不开游戏看「会改什么 / 为什么没生效」；
  CLI 与 GUI 共用。
- **数据目录**：variants/stratagems/effects/planets（含**游戏索引**映射）/items/build 指纹 + 预演样本 + M4 验收配置。
- **打包**：PyInstaller onedir（`hd2proxy.exe` + 可编辑 `data/`），zip ~15 MB；解压即用，不需要 Python。

### M4 实机验收（6/6 PASS，详见 `docs/ACCEPTANCE-M4.md`）

- 变种词条（PARTION 出 PREDATOR STRAIN）、全局效果（轨道加特林变燃烧）、战备试用（MG-43/M-105）、
  物品解锁（P-41 / SG-8F / LAS-22 / LAS-13 TRIDENT）、休眠星（BICEP 出现+连线+可点，结算前证）、
  生态借用（TRANDOR 落叶林）。
- 安装（UAC）→ 三连验证 → 游戏内验证 → uninstall + hosts 清理的完整闭环；最终 hosts 域名行 0、证书 0。

### 修复（M4 现场发现）

- 星球目录 `index` 是 planet_data 行号 ≠ 游戏索引 → 新增 `game_index` 权威映射，GUI/CLI 一律用游戏索引。
- 休眠星 `settingsHash` 决定星球身份、`waypoints` 决定连线 → 模板改研究线实机配方。
- 物品解锁需「目录行 + 库存行」成对注入 → 模板修正。
- `hd2proxy engine --profile X` 参数转发报错；三连验证 Status 因缺 `Accept-Language` 报 400 → 修复。
- 变种模板改走 `planet_effects` 原始通道（靶星必须有战役可点）。
