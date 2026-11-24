# M4 实机逐项验收记录（2026-11-16）

> 结论：**v0.1 的 6 项核心能力在真实游戏里全部通过**（`PASS`），并额外验证了
> 安装/三连验证/还原全链路；期间暴露的 6 个真实问题已在同一轮修掉（见 §5）。
>
> 验收环境：Windows 11 + 游戏 build `26568081` + war `801`；本机非回环网卡 `100.67.169.17`；
> 代理引擎以 profile 模式监听 `443`，证书 ca 模式（有效期 48h，LocalMachine 信任）；
> 验收配置固化在 [`data/acceptance/m4-a.json`](../data/acceptance/m4-a.json) /
> [`m4-b.json`](../data/acceptance/m4-b.json)，今日战况快照用于挑靶星（见 §1）。

## 1. 前置链路（不需要游戏）

| 步骤 | 结果 | 证据 |
|---|---|---|
| 会话证书签发 | ✅ ca 模式，48h，`self_check=OK`，无多余私钥 | `certs renew` 输出；指纹 `EE61544F…CEDEF` |
| 真安装（一次 UAC） | ✅ hosts 写入 + LocalMachine 根信任 | `install` 输出第 5–7 步 + 回读：`hosts=OK 证书=OK` |
| 三连验证（无游戏） | ✅ 3/3 | `verify`：TLS 200 / CRL 8080 200 / **Status 200 · 56,973 B · 改写后响应已收到** |
| warinfo 改写（经代理实测） | ✅ 273→274 条 | planet 100 hash `3515299681→1398996417`（首轮）；300 号新增（详见 §2.3） |

## 2. 六项能力逐项结果

### 2.1 ✅ 变种词条（双 id 成对）—— PREDATOR STRAIN

- 首轮把变种挂到 TERREK(76)：**卡面不可点**（TERREK 本季无战役），看不到词条；
  日志证明改写本身已下发：`REWRITE +7 entries (planet 76 -> [1227, 1263])` +
  `REWRITE-EXTRA 星球 76 += effect 1243/1245（raw，绕阵营过滤）`。
- 换成**当前有战役的虫族星 PARTION(215)**（热更新，无需重启）后，用户截图确认
  卡面出现 `PREDATOR STRAIN` + `SELECT CAMPAIGN`：
  [`research/screenshots/m4-partion-predator-strain.png`](../research/screenshots/m4-partion-predator-strain.png)。
- 机制结论：`planet_effects` 原始通道不按 owner 过滤；**星球必须可点（有战役）** 才能看到卡面。
  靶星必须按**游戏索引**选（PARTION=215 来自 `index-names-801` 权威映射，不是目录行号）。

### 2.2 ✅ 全局效果（GWE type94）—— 轨道加特林变燃烧

- 配置：`globalEffects{"1501107": [1346]}`（1501113 本季不在 live globalEvents 里；
  1501107 是当前 live 事件，已有 effectIds）。
- 日志：`REWRITE-EXTRA 全局事件 1501107 += effect 1346`。
- 用户实机：**任务内呼叫轨道加特林弹幕 → 燃烧版**。
- 结论：事件 id 不必是旧的 1501113，只要在**当前 war 的 globalEvents** 里即可。

### 2.3 ✅ 战备试用（type32，≤3）—— MG-43 / M-105

- 配置：`status.trials=[1227,1263]`、`trials_planet=76`（试用按星球下发）。
- 日志：`REWRITE +7 entries (planet 76 -> [1227, 1263])`。
- 用户实机：准备任务时战备栏出现 **MG-43 机枪 / M-105 盟友**。

### 2.4 ✅ 物品解锁 —— 目录行 + 库存行成对

- 配置：4 组 `items.add`（克隆同族模板）+ 4 个库存 mixId。
- 日志：`ITEMS REWRITE +3 entries`、`INV REWRITE +4 -0 items`。
- 用户实机：军械库多出 **P-41 OMBUDSMAN、SG-8F PUNISHER FIRE OF LIBERTY、LAS-22、
  LAS-13 TRIDENT**。
- 抓包核对（`%LOCALAPPDATA%\HD2ProxyStudio\captures\m4\*_Progression_items.json`，原始 3020 条）：
  `2870692210` **目录里本来就有** → 目录只 +3、库存 +4，正好对应看到的 4 把
  （其中 LAS-13 TRIDENT 是纯库存行解锁）。

### 2.5 ✅ 休眠星四件套 —— BICEP 可点、有连线

- 首轮错误：300 号注了 TRANDOR 的 hash `1398996417` → 客户端按 hash 解析身份，
  星图显示成 **BALDRICK PRIME**（该 hash 对应 103 号星）、且 `waypoints=[]` 没有连线。
- 按研究线实机配方修正后（[`docs/../PROXY-CAPABILITY-TEST-20261111.md` 原文在 repo-datamined]）：
  `settingsHash=2995599666`（BICEP 行自己的）、`initialOwner=2`、`owner{"300":2}`、
  `waypoints=[180,7]`（180=HERTHON SECUNDUS，位置吻合）。
- 日志：`REWRITE-WARINFO 追加 planetInfo {... "waypoints":[180,7] ...}` +
  `追加星球节点 index=300 owner=2` + `追加战役 51999`。
- 用户实机：**BICEP 出现、有连线、可选中**（`SELECT CAMPAIGN`）。
- 结算：研究阶段已实机验证过完整 op 链（见 §3），本轮用户确认「之前测试过了」。

### 2.6 ✅ 生态借用（settingsHash）—— TRANDOR 变落叶林

- 配置：`settings_hash{"100": 721718208}`（落叶林，研究线实机值）。
- 日志：`REWRITE-WARINFO planet 100 settingsHash 3515299681 -> 721718208`。
- 用户实机：**TRANDOR 落地地形 = 落叶林**。
- 机制副作用（已记录）：settingsHash 同时决定星球身份，星图上 **TRANDOR 名字变成 UVP ALPHA**
  （落叶林那颗星的名字），属预期；不是 bug。

## 3. 休眠星结算的「前证」（研究阶段实机）

`repo-datamined/docs/cases/PROXY-CAPABILITY-TEST-20261111.md` §6.3（2026-11-11 22:2x）已完整验证：

| 时刻 | 端点 | 服务端回应 |
|---|---|---|
| 22:24:43 | `POST /api/Operation/Create`（planetIndex 300/campaign 51999/race 2/type 0） | `{"operations":[{"id":1281,...}]}` 接受 |
| 22:26:07 | `POST /api/Operation/Mission/Start`（planetIndex 300/operationId 1281） | `{"missionId":"32ba0833-…"}` 接受 |
| 22:37:11 | `POST /api/Operation/Mission/end`（planetIndex 300/missionSuccess true） | 结算 `campaignWon:true, impact:4`，奖励到账 |

同时记录边界：`GET /api/Mission/Session` 返回 `8012016 PlanetIndex is invalid in this context`
⇒ 重连/会话恢复路径不可用（v0.1 不承诺）。

本轮同一会话的抓包也证实 op 链路被接受：
`*_Operation_Create.json → {"operations":[{"id":1283,...}]}`、
`*_Operation_Mission_Start.json → {"missionId":"5a20f8da-feed-4f7b-96f2-179e00c4d3da"}`。

## 4. 离线预演 vs 实机一致性

用 `build/live/`（当日 DoH 直连拉取的真实 Status/warinfo）跑预演，M4-B 配置输出
「9 处增量 / 2 类响应」，与实机日志逐条对应：

| 预演输出 | 实机日志 |
|---|---|
| 星球 76 追加效果 1227/1263（trials） | `REWRITE +7 entries (planet 76 -> [1227,1263])` |
| 星球 76 追加效果 1243/1245（planet_effects） | `星球 76 += effect 1243/1245（raw）` |
| 全局事件 1501107 追加 1 个效果 | `全局事件 1501107 += effect 1346` |
| 星球 100 生态 hash 变更 | `planet 100 settingsHash 3515299681 -> 721718208` |
| 追加星球身份 index=300 | `追加 planetInfo index=300 waypoints=[180,7]` |

## 5. M4 暴露并修掉的问题（本轮代码修复）

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | 目录星球编号写进 profile 后目标星全错（找不到 CALYPSO） | `data/catalogs/planets.json` 的 `index` 是 planet_data **行号**，不是游戏索引；偏移不是常数（行 79=TERREK=游戏 76） | `tools/gen_catalogs.py` 合并权威映射 `index-names-801.json` → 每行新增 `game_index`/`x`/`y`（273 颗，休眠星 null）；`gui/catalogs.py` + `widgets.PlanetPicker` 一律用 `game_index`；`planet_label`/`planet_entries` 按游戏索引出标签 |
| 2 | 休眠星节点显示成别的星（BALDRICK PRIME）、无连线 | **settingsHash 决定星球身份**（名字/生态）；`waypoints` 为空 | 模板改为研究线实机原值：BICEP hash `2995599666`、`initialOwner/owner=2`、`waypoints=[180,7]` |
| 3 | 物品解锁不可见 | 只注库存行、没注目录行 | 模板改为「目录行 + 库存行成对」注入（研究线 4 组模板值） |
| 4 | `hd2proxy engine --profile X` 直接 usage error | `argparse.REMAINDER` 不吞以 `--` 开头的参数 | `__main__.main()` 对 engine/selftest/gate 走「整体转发」短路径（+回归测试） |
| 5 | 三连验证的 Status 检查一直 400（`Accept-Language HTTP header missing`） | 验证请求头是壳子级最小集，live API 现在强制要 `Accept-Language` | `verify._tls_get` 补 `Accept-Language: en-US` + `Accept: application/json` |
| 6 | 模板里的变种通道在人类星会被过滤（TERREK 白试一轮） | 模板用了 `status.variants`（引擎按 owner 过滤） | 模板改走 `planet_effects` 原始通道，并在说明里写清「靶星必须有战役可点」 |

> 另记一条**已知限制（未改代码）**：抓包钩子保存的是**改写前**的原始响应
> （`gwe-dump` 在钩子链末尾之外），所以抓包文件不能当「改写后」证据；
> 改写证据以 `logs/proxy.log` 的 `REWRITE*` 行 + 游戏内观察为准。v0.2 可考虑落盘 post-rewrite 副本。

## 6. 系统还原（验收后）

| 动作 | 结果 |
|---|---|
| 停引擎 | 无残留监听 443/8080/17897 |
| `uninstall`（一次 UAC） | ✅ hosts 移除 1 行；`certutil -delstore` 删信任（rc=0）；回读 `hosts=干净 证书=已移除` |
| 清理研究线遗留 hosts 行（`# variant-mod`） | ✅ 移除 1 行（本产品只认自己的 `# hd2proxy` marker，旧行不归它管） |
| 最终回读 | hosts 里 `thehelldiversgame` 行数 **0**、证书存储匹配 **0**、无监听；主机名解析恢复正常 |
| 备份 | `%LOCALAPPDATA%\HD2ProxyStudio\hosts-backups\` 保留安装/还原前各一份 |

## 7. 2026-11-20 变种词条复验（v0.4.1-alpha.5 · 真实 UU 路由模式 · 实机 PASS）

> 这轮是「加速器共存修复」后的实机复验，同时暴露并修掉一个产品坑：**靶星选 0 号（母星）**。

**首轮失败（现象）**：profile 的 `status.planet_effects` 是 `[{"index": 0, "ids": [1243, 1245]}]`。
引擎日志显示注入成功（`REWRITE-EXTRA 星球 0 += effect 1243/1245（raw，绕阵营过滤）`、
`REWRITE +2 entries`），但游戏里什么都看不到。

**根因**：`index 0 = SUPER EARTH`（星图 hub），**没有卡面、没有战役** —— 挂上去的效果客户端
不会渲染。不是阵营过滤问题：`planet_effects` 是原始通道，本来就不按 owner 过滤；限制在于
「星球必须有战役、卡面可点」（同 §2.1 的 M4 结论：TERREK(76) 无战役看不到，PARTION(215) 有战役
就出现了）。

**修正与实机结果**：把靶星改成当天**有战役的虫族星 269 BRILLIANCE**（campaign 51778，
天然还挂着 `CAUSTIC STRAIN` 作对照），重启引擎后：

- 引擎日志（12:38:38）：`REWRITE-EXTRA 星球 269 += effect 1243（raw，绕阵营过滤）` +
  `… += effect 1245` + `REWRITE +2 entries`；
- 用户实机截图确认卡面出现 **PREDATOR STRAIN** + 官方 fluff（"A mutated strain of Terminids
  has been reported on this planet…"）+ `SELECT CAMPAIGN`：
  [`research/screenshots/real-brilliance-predator-strain-20261120.png`](../research/screenshots/real-brilliance-predator-strain-20261120.png)

**同轮实机确认的其它项**：
- 库存注入：`INV REWRITE +103 -0 items`（121 个 profile mixId 中 103 个上游缺失，全部补齐）→
  用户确认「解锁正常」；
- 真实 UU 路由模式下：hosts 未被 UU 再次注释、引擎监听 `100.67.169.17:443`、三连 PASS、
  主界面全链路（登录/战况/军械库/抓包）均正常。

**产品侧修复（进 v0.4.1-alpha.6）**：
1. GUI 星球选择器**排除 0 号**（SUPER EARTH 不进可选列表）——否则选择器默认选中它，
   模板一应用就把效果注到母星（本轮就是这么踩的）；
2. 星球系模板 `_need_planet` 拒绝 0，并提示「母星没有卡面/战役，请选有战役可点的星球」；
3. `config.validate` 对 `planet_effects` 指向 0 号给 **warning**（不阻止保存，但要看得见）。
| 证书文件 | 按契约 `uninstall` **不删**证书文件（`certs/` 仍在），过期 ≤2 天，可手工清理 |

## 7. 复现方式

```bash
# 1) 用当日 live 数据挑靶星（DoH 绕 hosts，只读）
# 2) 生成验收配置（脚本为一次性，参数见 data/acceptance/*.json）
python -m hd2proxy install --profile data/acceptance/m4-b.json --cert-dir <certs>   # 一次 UAC
python -m hd2proxy engine  --profile data/acceptance/m4-b.json --cert-dir <certs>
python -m hd2proxy verify                                                            # 三连
# 游戏内逐项对照 §2；测完：
python -m hd2proxy uninstall --cert-dir <certs>                                      # 一次 UAC
```

验收配置说明：`m4-a.json` = 前 5 项（无休眠星，出问题易降级）；`m4-b.json` = 全 6 项。
两份都不含账号/本机路径（抓包开关已关）。

---

## M5 · 存档系统实机验收（2026-11-23）

> 构建：`v0.5.4-alpha.3`（会话）+ `v0.5.5-alpha.1`（预绑定重启验证）；官方服务器；单机单人一局短任务。
> 证据：`%LOCALAPPDATA%\HD2ProxyStudio\logs\proxy.log`、`runtime/saves/`、`captures/`。

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| ① | 首屏身份识别 + 不混档 | **PASS** | 首会话 `local → steam_76561198968648344` 走 **merged** 分支（`local.merged-20261123-181618.json` 归档）；`identity.source=getmotd`；重启后 `activeSave=steam_…（last）`、日志 `首屏按 steam_… 渲染（来源 last，earned 改动 0 字段）`、`getmotd 身份校验一致` |
| ② | 结算奖励入账（G3） | **PASS** | `MISSION +210 exp · 3608481516×910 · 897894480×1`（mission `e9f0440b…`）与抓到的 `Mission/end` 响应逐字段一致；成就真实报文 4 条（`{6:1680,8:386242,17:4290,24:2925}`）入账；统计 27 项入账（`totalEnemyKills=356105`） |
| ③ | 重启后不回退 / 不破坏 | **PASS** | 重启后无降级写入、无 `TLS REJECTED`；`inventory` 合并**只抬不降**（老玩家货币不被改小）；`session_dirty` / 会话基准状态正确 |
| ④ | 换号不混档（第二账号） | **PASS（含 2 个新发现，已修 → v0.6.0-alpha.3）** | 2026-11-23 20:04–20:22 实机：主号 ↔ 空号 `76561199881579811` 双向切换；两份档分流、主号 earned 未被改动、空号档回滚+`_orphan` 审计；暴露「HD2 别名跨账号残留」与「首屏预合并回显污染」两个缺陷，均已修复（见下 §④ 专项） |

**已知限制（已在 README 写清）**：客户端一次会话只拉一次 `/api/Progression`；同机换号那一刻首屏可能已按旧档渲染，重启后生效。

### ④ 换号不混档 · 实机专项（2026-11-23 20:04–20:22）

> 引擎：`v0.6.0-alpha.2`；官方服务器；同一引擎进程内 Steam 切号（不重启引擎）。
> 证据目录：`D:\mod	mp\evidence-m5-switch\`（快照）+ `runtime/saves/` + `logs/proxy.log`。

**空号段（20:04–20:19）**

| 检查 | 结果 |
|---|---|
| 身份切换 | `⚠ 身份切换：steam_76561198968648344（已识别）→ steam_76561199881579811；不合并。本局写入=无，回滚=none` ✅ |
| 新档内容 | `steam_76561199881579811.json`：exp 0 / 成就 0 / 购买 0 / 库存 0（未混入主号）✅ |
| 主号档 | sha 全程 `b8564771…` **未变**、`_orphan` 空 ✅ |
| 结算入账 | `MISSION +207 exp · +2 物品 · 3608481516×898 897894480×1 · 1 包进度`，与抓到的 `Mission/end` 响应逐字段一致 ✅ |
| 四条红线 | experience / achievements / purchasedSeasonPassItems / inventory 行数 均未混入主号值 ✅ |

**主号切回（20:21:41）**

| 检查 | 结果 |
|---|---|
| 切换保护 | `身份切换：空号 → 主号；不合并；本局写入=有，回滚=restored；脏档另存 _orphan/20261123-202141-…-identity-switch.json`（空号本局增量整档回滚 + 全文留 orphan，符合"绝不静默丢"）✅ |
| 主号 earned | exp 210 / 成就 4 条 / 库存 `910+1` **原样**（未被空号段改动）✅ |
| `_last.json` | 指回主号 ✅ |

**本专项发现并修复的 2 个缺陷（→ v0.6.0-alpha.3）**

1. **HD2 别名跨账号残留**：换号瞬间 `GetMotd` 先到（`GetMessages` 未到）时，上一账号的 20 位 HD2 id 被写进新档
   `.bak` 实证：`{hd2:11893343864225233967, steam:76561199881579811}`（主号别名 + 空号 steam），约 1 分钟后才被
   `GetMessages` 纠正；切回主号时同样会把空号别名短暂写进主号档。
   修复：别名只认**本局观测值**（`_hd2_session`）；Steam 号变化时清空旧别名；`GetMotd` 先到 → 新档 hd2 写 null，
   `GetMessages` 到后再补；切换回已有档不覆盖其正确别名；`GetMessages` 先到且属别的账号时不写进预绑定档。
2. **首屏预合并的"显示回声"污染**：预绑定 merge 在身份校验前把上一档账本合进响应 → 客户端把"看到的数"
   加增量后 `PUT /Achievements` 上报 → 被记进新账号账本（实测空号档出现 `{6:1681, 8:386301, 17:4290, 24:2926}`，
   明显来自主号 1680/386242/4290/2925）。
   修复：新增 `saves.preverify_merge` 三档（**默认 safe**）：
   - `safe`：身份未校验时只合并**服务端自算、不会回显**的字段（经验/包进度/…），**成就/统计/库存不合并**；
   - `full`：全合并（`upstreamTest`/mock/自建服自动启用，保证「服务端给得少 ⇒ 存档层兜底」可验证）；
   - `off`：不合并。
   换号告警同时补一句"本局首屏曾按旧档合并 N 处 —— 显示可能偏高，重启纠正"，把显示窗口说清。

**已知限制（修正表述）**：客户端一次会话只拉一次 `/api/Progression`；同机换号时该会话**可能整段**沿用上一档的
合并视图（不止首屏），重启游戏后按新档纠正。v0.6.0-alpha.3 起 `safe` 默认已阻断其中的成就回声污染路径。


### ④ 的 B 方案离线预检（2026-11-23 晚，无实机）

> 目的：在拿不到第二账号实机前，先用**研究线给的期望值 + 我们已有夹具**做"渲染对照"，
> 把 ④ 的判据从"感觉没混"变成具体数字。工具：`hd2proxy save-preview --json`（离线，不开游戏）。

- 期望值来源（研究线 19:0x）：主号 experience `2759938`、achievements `[1679,386201,4290,2924]`、
  assignments `24`、packageProgress `52`、purchasedSeasonPassItems `426`、inventory items `970` 行、
  catalog_build `93e7575a/3021/1007203`；空号 experience `1`、achievements `0`、inventory `55` 行、
  catalog_build `d71655e6/3020/-`。
- **与我们夹具逐项一致**：`data/fixtures/saves/main/progression.json` 的 experience=`2759938`、
  achievements 4 条、assignments 24、packageProgress 52、purchasedSeasonPassItems 426；
  `main/items.json` sha8=`93e7575a`、`fresh` = `d71655e6/3020` ⇒ 双方基线同源，可直接对照。

**预检结果（本机主号账本 vs 主号基线）** —— 期望「只抬不降、不丢项」：

| 字段 | 服务端（主号基线） | 合并后 | 判定 |
|---|---|---|---|
| experience | 2759938 | **2759938**（不变） | 账本只有增量 210 < 基线 ⇒ 听服务端 ✅ |
| achievements | `[1679,386201,4290,2924]` | `[1680,386242,4290,2925]` | 抬到本机实机最新值（+1/+41/0/+1）✅ |
| totalEnemyKills 等 13 项统计 | 356065 等 | 356105 等 | 逐项只抬 ✅ |
| inventory（`main/inventory.json`，970 行） | 如 `3608481516=1000` | `3608481516=1000` 保持；`897894480` 补行 amount=1 | 只抬不降 + 缺行补行 ✅ |
| catalog_build | `93e7575a/3021/1007203` | 同 | 不漂移 ✅ |

**预检结果（若把主号账本误套到空号基线）** —— 即"两边混"最坏形态，量化后便于实机识别：

| 字段 | 空号基线 | 误套主号账本后 | 说明 |
|---|---|---|---|
| experience | 1 | **210** | 主号账本的增量被抬上去 ⇒ 空号首屏会"像主号" |
| achievements | `[]` | 4 条（主号） | 同上 |
| inventory | 55 行（含 `3608481516=1000`） | 补 `897894480×1` | 主号独有行出现 |

⇒ **④ 实机判据（据此细化）**：切到空号后，若首屏出现 `experience=210 / 成就 4 条 / 897894480 行`，
说明 `_last.json` 预绑定还没被 `GetMotd` 纠正（**已知窗口，非写盘混档**）；等 `getmotd 身份校验一致`
或重启后必须回到空号基线（`1 / 0 / 55 行`），且 `_orphan` 里出现主号本局脏档、`runtime/saves/` 两份文件互不影响。
四条红线：**experience / inventory items 行数 / achievements 条数 / purchasedSeasonPassItems**。


**现场处置记录**：首次实机报 **Error 60** → 根因是引擎 auto-renew 换发 CA 后信任库未更新；
`hd2proxy.exe install --cert-dir <state>\certs` 重导当前 CA 后恢复（`trusted=true`，`LocalMachine`）。
后续版本已加 `certs/ca-history.json` 留痕 + 日志告警。

## M6 · mock / 自建服验收（2026-11-24）

> 目的：验证存档层**核心价值**——当"服务端给得很少"（私服 / 自建 / mock）时，本机账本必须把
> 经验 / 成就 / 库存 / 统计 / 结算兜底顶上；同时证明对官方服的正式账本**零影响**。
> 构建：`v0.6.0-alpha.3`；引擎与 mock 同机；**隔离状态目录**（生产账本副本），不碰真账本。

### 环境

| 组件 | 配置 |
|---|---|
| mock（研究线提供） | `127.0.0.1:9099` 明文 HTTP/1.1（不压缩）；数据集=空号基线 + 身份改为**主号**（`GetMotd=76561198968648344` / `GetMessages=11893343864225233967`）+ `inventory={"items":[]}` |
| 引擎 | `hd2proxy engine --config legacy-cfg-9099.json(upstreamTest:"127.0.0.1:9099") --profile profile-mock-443.json`，`HD2PROXY_STATE=D:\mod\tmp\mock-accept-20261124\state`（内含生产档副本），监听 `100.67.88.219:443`，`preverify_merge=full`，抓包开 |
| 客户端 | 游戏主号 `76561198968648344` 正常登录（进主菜单） |

### 判据与结果（全 PASS）

| # | mock 给的值（服务端很少） | 引擎响应 / 账本结果 | 判定 |
|---|---|---|---|
| ① Progression | exp `1`、成就 `0`、packageProgress `9`、spi `0` | **exp 210**、成就 **4 条** `{6:1680,8:386242,17:4290,24:2925}`、packageProgress **9**（账本无记录→保持服务端值）、spi `0` | ✅ |
| ② inventory | `items=[]` | **`897894480×1` + `3608481516×910`**（恰 2 行，空→全量回填） | ✅ |
| ③ Stats | 27 key **全 0** | **23 项**抬回（`totalEnemyKills=356105`；账本 27 项里 4 项本身为 0，故 23 非零） | ✅ |
| ④ Mission/end | 固定模板 `experience=936` | 账本 exp **210→1146**；库存 `897894480 1→8`、`3608481516 910→5344`；missions 1→2；包进度 `{277818845:{level:5,progress:459}}` | ✅ |

引擎日志（`state/logs/proxy.log`）：
`SAVE REWRITE +5 field(s)` / `SAVE INV +2 行（只抬不降）` / `SAVE STATS +23 field(s)` ×2（summary 与 /801/summary）/
`MISSION +936 exp · +2 种物品 · 3608481516×4434 897894480×7 · 1 个包进度`；`getmotd 身份校验一致`，无换号/无 orphan/warnings 空。

### 证据

- `D:\mod\tmp\evidence-m6-mock\`：`raw_Progression.json` / `raw_inventory.json` / `raw_stats.json`（**注入前**上游原始响应）、
  `ledger-before.json`（生产真档副本）、`ledger-after-test.json`、`proxy.log`、`verification.json`（四条 pass 布尔）
- 隔离测试目录 `D:\mod\tmp\mock-accept-20261124\state\`（引擎日志 / captures / 被测试改写的账本副本）
- 研究线 `tools/mock_request_summary.py --json` 导出（待对账）

### 隐私/安全边界

- 隔离状态目录：测试产生的合成结算只写副本，**生产账本 sha/content 未变**（exp 210 / 成就 4 / 库存 910+1 / 统计 27 / missions 1，`_last` 未变）。
- mock 只在回环 `127.0.0.1:9099`；443/hosts 仍指向本机引擎；测试后生产引擎与证书原状恢复。

### 复现要点

```bash
# 1) 隔离状态 + 生产档副本
mkdir -p /d/mod/tmp/mock-accept-20261124/state/runtime/saves
cp "$LOCALAPPDATA/HD2ProxyStudio/runtime/saves/"*.json /d/mod/tmp/mock-accept-20261124/state/runtime/saves/
# 2) 起引擎（mock 已在 127.0.0.1:9099）
HD2PROXY_STATE="D:/mod/tmp/mock-accept-20261124/state" hd2proxy.exe engine \
  --config <legacy-cfg-9099.json: {"host":"api.live.prod.thehelldiversgame.com","upstreamTest":"127.0.0.1:9099"}> \
  --profile <profile-mock-443.json: 443 + saves.enabled + preverify_merge=full + capture> \
  --cert-dir "$LOCALAPPDATA/HD2ProxyStudio/certs" --verbose
# 3) 游戏主号登录 → 看 state/logs/proxy.log 的 SAVE REWRITE / SAVE INV / SAVE STATS
# 4) 受控验结算（不必真打任务）：
curl -s --ssl-no-revoke --cacert "$LOCALAPPDATA/HD2ProxyStudio/certs/anchor.pem" \
  --resolve api.live.prod.thehelldiversgame.com:443:100.67.88.219 \
  -X POST -H "Content-Type: application/json" -d '{}' \
  https://api.live.prod.thehelldiversgame.com/api/Operation/Mission/end
```

**注意**：源码模式跑引擎时 `paths.SAVES_DIR` 指向**仓库内** `runtime/saves`；隔离运行期数据用 `VMOD_DATA`，
隔离状态/证书用 `HD2PROXY_STATE`（仅 frozen 版生效）。

### M6 三方对账（研究线 mock 日志 × 引擎日志 × 抓包，2026-11-24 11:42–11:47）

| 端点 | mock 侧（研究线 `mock_request_summary.py --since/--until`） | 引擎侧 | 结论 |
|---|---|---|---|
| `GET /api/Progression` | 1 次 11:42:19.563 · `[exact]` 1500 B | `gwe-dump` 1500 B + `SAVE REWRITE +5` | ✅ |
| `GET /api/Progression/inventory` | 1 次 11:42:19.596 · `[exact]` **45 B** | `gwe-dump` 45 B + `SAVE INV +2 行` | ✅ 逐字节吻合 |
| `GET /api/Stats/profile/summary` | 1 次 11:42:19.709 · `[exact]` 644 B（另有 `/801/summary` 同秒） | `SAVE STATS +23` ×2 | ✅ |
| `POST /api/Operation/Mission/end` | **仅 1 次** 11:46:23.078 · 1614 B `[state:mission_end]` | `MISSION +936 …`（同一秒） | ✅ 无重复触发 |
| `POST /api/Pes/GetMotd` | 1 次 11:42:22 · 136 B `[exact]` · `accountId=76561198968648344` | `getmotd 身份校验一致` | ✅ |

窗口 65 行请求 / 37 个端点模板；四条判据相关端点全部 `[exact]`，**无 fallback、无 4xx/5xx**。
另有 3 次客户端**设置写**（`PUT OnboardingState` ×2、`PUT ShipName` ×1）落 `[fallback] 200 {}` ——
存档层不消费这类响应，对判据无影响；若将来验"设置类写回显"，需 mock 侧加这两个端点回显。

研究线记录：`docs/ACCEPTANCE-MOCK-ALPHA3-2026-11-24.md`；数据集/日志留存 `state/tmp/accept-main-identity/`、
`state/logs/acceptance-20261124/`（含 `dataset-diff.txt`）。
