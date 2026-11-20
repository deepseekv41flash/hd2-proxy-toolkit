# 交接档：离线单机方案 + 自建联机服务器研究（2026-11-20）

> **这份档给未来会话重启这条研究线用，不属于 MITM 工具（hd2-proxy-toolkit）的待办。**
> 本会话（hd2-proxy-toolkit 开发会话）只记录结论与线索；实际攻关请在**新会话**里按 §9 的 runbook 开工。

## ⛔ 工作区与文件边界（硬性限制 —— 先读再动手）

这条研究线与 **MITM 工具（hd2-proxy-toolkit）的开发会话是分开的**。产品开发正在另一个会话/工作区里推进，
**不要动那个工作区的任何文件**，否则会直接污染产品线（版本号、门禁、发布流程、产物测试区全会被带偏）。

### 禁止写入（除非先得到用户明确批准）

| 路径 | 说明 |
|---|---|
| `D:\mod\work\hd2-proxy-toolkit\**` | **MITM 产品仓库（本档所在仓库）**：只读参考；禁止写入、禁止 `git add/commit/push`、禁止改配置 |
| `D:\mod\release-test\**` | 产品发布产物测试区（GUI/引擎从这里跑）：禁止替换 / 删除 / 重写 |
| `%LOCALAPPDATA%\HD2ProxyStudio\**` | 用户正在用的运行态（profile / 证书 / 抓包 / 日志 / `engine.json`）：禁止改；研究实验请用独立 `HD2PROXY_STATE` 隔离 |
| `%LOCALAPPDATA%\HD2ProxyStudio\profiles\default.json` | 用户默认 profile：**尤其不要改**（会直接影响实机注入行为） |

### 允许的用法

- **只读**：可以把产品仓库当资料读（`data/catalogs/*`、`src/hd2proxy/engine/*`、`docs/*`、抓包样本等）；
- **产物另放**：研究线自己的代码 / 数据 / 结论写到独立目录（建议 `D:\mod\work\hd2-offline-research\`，或研究仓
  `D:\mod\work\variant-net\` 下的新子目录），并**单独 git 管理**；不要写进产品仓库；
- **需要产品侧改动时**：不要直接改。先把需求 / 补丁写成研究线文档，回到 MITM 会话由用户决定是否集成；
  确需改产品代码时走「新建分支 + 用户批准 + 门禁 + 版本规则（功能改 `X.Y.Z`、只修 bug 动 `alpha.N`）」，不得直推 `master`。

### 环境隔离建议（强烈推荐）

- 用**独立 workspace / 独立会话**推进这条线，不要和产品自检、门禁、`selftest`、发布流程混跑；
- 实验用独立状态目录：`set HD2PROXY_STATE=D:\mod\work\hd2-offline-research\state`
  （证书 / hosts 备份 / 日志 / `engine.json` 都会被隔离到那里）；
- hosts / 证书 / 端口这类系统级改动仍遵循 §8 的环境坑与「改完还原」纪律（UAC、备份、`uninstall` 回读）；
  **端口冲突见 §8.1**（443 只能有一个主人：产品引擎或研究 mock）。

### 动手前 30 秒自检

```powershell
# 1) 先确认自己在哪个目录、哪个仓库（应在研究线目录，不在产品仓库）
Get-Location
git rev-parse --show-toplevel 2>$null
# 2) 研究实验的状态目录必须是独立目录（不是默认 HD2ProxyStudio）
$env:HD2PROXY_STATE
# 3) 产品仓库必须是干净的、且你没有任何待提交改动（期望：无输出）
git -C D:\mod\work\hd2-proxy-toolkit status --short
```

> 一句话：**产品仓库只读、产物另行落盘、改产品先过用户。**
> 产品当前版本以 `D:\mod\release-test\current\hd2proxy\hd2proxy.exe --version` 为准（本档 §2 的快照只代表 2026-11-20 11:17 那一刻）。

## 0. 一句话结论

- **离线单机**：技术前提基本成立（游戏任务本体在客户端、任务链参数由客户端提交、登录响应只有一个 `sessionId`），
  缺的是「把整条启动链 mock 掉」的工程实现与 3 个未知点的实测（客户端校验 / 其它主机依赖 / 任务中服务端校验）。
- **自建联机**：可行度比一般网游高。信令层（大厅/匹配/任务登记）是官方后端职责，可自建；
  **传输层与世界状态不需要我们造**——HD2 是主机权威 P2P，引擎会把房主的银河战况板整张同步给客机
  （已有第三方 mod 的零安装客机实测证据）。真正缺的是「会话建立是否需要官方凭证」等未知点。

## 1. 范围（用户已确认的边界）

- **只接管游戏自己的流量**（`api.live.prod.thehelldiversgame.com` 这个 API 主机）；
- **Steam 与 EAC 不接管、照常运行**（即 Steam 正常在线、EAC 正常保护启动）；
- 不修改游戏文件（EAC 会判「未知的文件版本」，连 1 bit 差分都拦）；
- 目标场景：官方服务器不可达（网络故障/维护）时，仍能**离线进主界面 → 单人任务**；以及**小圈子自建联机**。
- **工作区边界（硬性）**：本线在**独立工作区/会话**推进；**不得写入** `D:\mod\work\hd2-proxy-toolkit`（产品仓库）、
  `D:\mod\release-test`（产物测试区）与 `%LOCALAPPDATA%\HD2ProxyStudio`（用户运行态）——详见开头「⛔ 工作区与文件边界」。

## 2. 现状快照（2026-11-20 11:17，供新会话对照）

| 项 | 值 |
|---|---|
| 产品版本 | `D:\mod\release-test\current\hd2proxy` = **v0.4.1-alpha.5**（GitHub prerelease 已发） |
| 进程 | 当前 **无** hd2proxy / hd2proxy-gui 在跑（引擎未启动） |
| hosts | `100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy`（⚠️ 引擎没跑时开游戏会 `Error 56`） |
| 代理/加速器 | 当前未开（无 TUN/UU 网卡；默认路由走以太网 `100.67.0.1`） |
| 本机 IP | `100.67.169.17`（以太网） |
| 证书 | 会话 CA 48h 自动轮换，轮换后需 `install` 重装信任（详见 §8） |

**新会话开工前先自检环境**（PowerShell）：

```powershell
# 版本
& 'D:\mod\release-test\current\hd2proxy\hd2proxy.exe' --version
# hosts 是否指向本机 + 引擎是否在跑
Select-String -Path C:\Windows\System32\drivers\etc\hosts -Pattern 'thehelldiversgame'
Get-NetTCPConnection -State Listen -LocalPort 443,17897 -ErrorAction SilentlyContinue
# 当前网络模式（是否 TUN / UU 路由 / 系统代理）
Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription
Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object InterfaceAlias,NextHop,RouteMetric
```

## 3. 已证实的关键事实（带证据路径）

### 3.1 官方 API 全貌（信令层）

- **59 种端点 / 5,638 次请求 / 20 组**：`D:\mod\work\variant-net\docs\API-ENDPOINTS-2026-11-01.md`
- 登录：`POST /api/Account/Login`（请求体 ~437 B 含 Steam 票据类数据）；**响应只有一个 `sessionId`**：
  `{"sessionId":"a9cbb374-…"}`（52 B）——
  证据：`D:\mod\tmp\capture-store-season-20261118\raw\a5335597_api_Account_Login.json`
- 身份：`accountId` 就是 **SteamID64**（`/api/Pes/GetMotd` 响应里见 `"accountId":"76561198968648344"`）
- 大厅（5 个端点）：`PUT /api/lobby`（1,350 B，**body 里含 `connectionString` 房主连接串** +
  `players[4]`（`isHost`/`memberAccountId`/`playerName`/`playerRank`…）+ `lobbyId`/`planetId`/`warId`/
  `difficulty`/`state`/`privacyMode`/`crossplayMode`/`hostability`/`sosBeacons`）、
  `GET /api/lobby/{id}`、`POST /api/lobby/{id}/member`、`POST /api/lobby/accounts`、
  `DELETE /api/lobby/clear`；body 形状见 API-ENDPOINTS §8.3
- 任务链（9 个端点，**服务端只是登记/结算，参数由客户端提交**）：
  `Operation/Create`（`operationSettingsId`/`jointOperationId`/`type`/`id`/**`seed`**/`race`/`warId`/
  `placementNodeIndex`/`campaignId`/`planetIndex`/`difficulty`/`missions[]`）→
  `Mission/Start`（`{missionId}`）→ `Mission/end`（提交战果/奖励）+
  `Mission/Session`、`Mission/RewardEntries`；时间线与真实抓包：
  `D:\mod\work\variant-net\docs\MISSION-CAPTURES-2026-11-01.md`
- **59 个端点里没有任何「分配游戏服务器」的端点** ⇒ 任务本体在房主客户端跑（支持 §4 的可行性判断）
- 反作弊：`/api/Account/ReportPosition`（位置上报）；EAC 只校验游戏文件、不校验服务器真伪
  （否则本地 MITM 不可能成功）——见 `D:\mod\work\hd2-proxy-toolkit\docs\ACCELERATOR-COMPAT-2026-11-20.md`

### 3.2 会话内世界状态是「主机权威 + 引擎原生同步」（自建联机的关键证据）

第三方 mod（variant_mod 1.26）的**零安装客机实测**：
`D:\Downloads\variant_mod\FINDING-零安装客机-2026-10-23.md`（以及 `README.md` 的「多人」一节）

- 主机装 hosts+证书+代理，客机**什么都不装**，客机能完整看到主机注入的变种（**星图词条 + 局内刷怪**），
  飞船加入与**任务中途加入**都正常；
- 主机 `proxy.log` 证明：**客机从未连过主机代理**（没有来自客机 IP 的请求，也没有 DENY）；
- 机制：引擎把房主的银河战况板**整张同步**给加入的客机
  （`game.dll+0x12D5AC0` 段 A，每条记录 `0x9C0`=2496 B，效果数组在 `+0xC8`）；
  这是游戏自己的会话同步，不是 mod 手动推的；
- 反面教训：另一位作者（quanbianzhong）手动推 495 KB「影子板」导致客机崩在
  `helldivers2.exe+0x5970F6`（客机资源清单里没有对应资源包）⇒ **主机权威同步只对客机本地已定义的 id 安全**。

⇒ 对自建联机的意义：**世界状态/局内内容不用后端提供，由房主同步**；后端只需要做「信令 + 任务登记」。

### 3.3 服务器领先客户端的内容解不出来（边界的证据）

- 当前 build（26568081）30 个 bundle 的 `.strings` 全解包后 = 24,834 条 locid，与旧 build **逐 id 相同**；
  `cat9/cat23` 剩余未命名行的 locid 两端都不存在 ⇒ 服务器领先客户端（未发布内容），
  详见 `D:\mod\work\hd2-proxy-toolkit\docs\CATALOG-NAMES-V3-2026-11-18.md` 的 v4 复核附录。
- 对本线的含义：**不要指望"把客户端没下发的世界/物品数据补出来"**；离线/私服里世界内容只能来自
  ① 客户端本地已定义内容 ② 房主上一次正常联网时同步到的 board。

### 3.4 加速器 / 代理共存（已由工具侧修复，但会影响实验环境）

`D:\mod\work\hd2-proxy-toolkit\docs\ACCELERATOR-COMPAT-2026-11-20.md`：

- Clash 系统代理模式：游戏不读系统代理，MITM 照常工作；
- Clash TUN / UU 路由模式：默认路由转到虚拟网卡，**旧版** `listen_ip="auto"` 会绑到 `198.18.0.1` / UU Wintun；
  v0.4.1-alpha.5 已修（默认路由 IP 仅当落在物理网卡才采信）；
- UU 路由模式启用时会把 hosts 行注释成 `#uu_acc…`；**切换模式后必须「重写 hosts → 重启引擎」**；
- 实测结论：TUN / UU 路由下注入链路都能工作（三连 PASS），只是要多这两步。

## 4. 研究线 A：官方服务器不可达时的「离线单机」

### 4.1 可行性判断（分三段）

| 段 | 判断 | 依据 |
|---|---|---|
| 登录/主界面 | **很可能可行** | 登录响应只有 `sessionId`（无签名/票据回执），后续请求也由我们接管，本地服务端无需校验 |
| 单人任务开局 | **较可能可行** | 无「分配游戏服务器」端点；`Operation/Create` 的 seed/planet/campaign 全是客户端提交；世界内容在客户端/房主 |
| 任务结算/进度 | 可伪造（但只对本地有意义） | `Mission/end` 提交战果、响应带奖励；离线伪造 = 自己给自己发 |

### 4.2 需要 mock 的端点（最小集）

`Account/Login`（返回 `{"sessionId":"<uuid>"}`）→ `Configuration/GameClient` → `WarSeason/current/WarId` /
`WarSeason/{war}/Status` / `warinfo` / `timeSinceStart` / `NewsTicker` / `GalacticWarEffects` →
`Progression/*`、`StoreFront/*`、`SeasonPass/*`（可回放或空）→ `FriendsV2/*`、`NewsFeed`、`lobby*`（静态/空）→
任务链 `Operation/Create` → `Mission/Start` → `Mission/end` → `Mission/Session`、`ReportPosition`（回 200/204）。

### 4.3 建议实现形态（capture → replay 的「本地云端」profile）

产品里已有 **passthrough capture**：把每个 `/api/` 响应落盘为 `<sha8>_<slug>.json` + `index.txt`。
新增一个 `mock=true` 的 profile 模式即可：

1. **录制**：正常联网启动并玩一局（覆盖登录 + 主界面轮询 + 一局任务链），产物放在独立抓包目录；
2. **回放**：按「方法 + 端点模式（查询参数归一）」匹配录制响应；未匹配 → 同类缓存响应或空 200/204；
3. **时间平移**：`timeSinceStart`、`NewsTicker` 时间戳、`Status` 中的时间字段按当前时间线性平移
   （防止客户端判定数据过期）；
4. **任务链 mock 表**：`Create` 返回 operationId/seed、`Start` 返回 missionId、`end` 返回录制奖励包；
5. **安全阀**：默认只在「官方不可达」时启用；联网时保持 passthrough，避免污染真实账号进度。

### 4.4 已知未知点（新会话逐项验证）

| # | 未知 | 怎么验 | 风险 |
|---|---|---|---|
| A1 | 客户端是否校验登录响应的其它字段 | 回放 `{"sessionId":uuid}` 看是否进主界面 | 低（响应本身就只有 sessionId） |
| A2 | 游戏进程除 API 主机外还连哪些主机 | 游戏运行时按 PID 抓 DNS 缓存 + TCP/UDP 连接（`Get-DnsClientCache` / `Get-NetTCPConnection -OwningProcess`） | 若有第二条游戏自有通道，需要一并接管 |
| A3 | 任务中是否有服务端实时校验 | mock 后端下进图；观察 `ReportPosition`/`Mission/Session` 失败是否踢出 | 已知 `Mission/Session` 有校验（`errorCode 8012016`），别承诺"重连可用" |
| A4 | 断网时 Steam 是否仍给票据 | Steam 在线（非离线模式）即可规避；离线模式未测 | 中（但用户已把 Steam 排除在接管范围外，正常在线即可） |
| A5 | mock 响应会不会触发 EAC | EAC 只查文件（已证），mock 不改文件 → 低风险 | 低 |

### 4.5 验证 runbook（按顺序，每步有判据）

1. **录完整会话**：正常联网启动游戏 → 进主界面 → 打一局 → 退出。判据：抓包目录里有
   `Account/Login`、`WarSeason/*/Status`、`Operation/Create`、`Mission/Start`、`Mission/end`。
2. **断网启动定位最小登录集**：启引擎 + mock（先只 mock 登录与主界面必需端点）→ 断网 → 启动游戏。
   判据：能进主界面；记录卡住时的第一个请求。
3. **逐项补齐**：按日志/控制面 `/status` 补 mock 端点，直到主界面无报错。
4. **单人开局**：mock `Operation/Create` + `Mission/Start`，观察能否进图；
   同时按 A2 的方法抓进程连接，确认是否还需要连别的域名。
5. **结算**：mock `Mission/end`，确认结算画面与本地进度变化（只本地）。
6. **固化**：把这套 mock 数据与开关做成 profile 特性，写进 release notes。

## 5. 研究线 B：自建联机服务器（官方不可达时的小圈子联机）

### 5.1 架构结论

```
玩家A(房主) ──API──▶ 自建信令服务（替代官方后端：登录/大厅/任务登记/结算）
     │                    ▲
     │  Steam P2P（不需要我们实现）      │API
     ▼                    │
玩家B(客机) ──────────────┘   ← 世界状态由房主引擎同步给客机
```

- **信令层**：需要自建（登录、`lobby*`、`Operation/*`、`Mission/*`，其余回放/空）；
- **传输层**：Steam 网络层负责打洞/中继——**已由二进制证据确认 HD2 用 `ISteamNetworkingSockets` + SDR**
  （见 §12），**不要试图替换**，也不需要替换：传输本来就由 Steam 负责，我们只当「signaling service」；
- **世界状态**：房主权威 + 引擎原生同步（§3.2 证据），后端不需要下发一致世界数据；
- **身份**：`accountId` = SteamID64（§3.1）；登录请求体里应有 Steam 票据但**未抓过 body**，
  小规模私服可按「客户端 IP / 预配置表」映射到 SteamID64 规避解析票据。

### 5.2 最小信令服务实现要点

1. `Account/Login`：为每个客户端返回一个 sessionId（内存表 `sessionId → accountId`）；
2. `lobby` 有状态：
   - `PUT /api/lobby`：把 body 原样存进内存表（`lobbyId → body`）+ 维护 `accountId → lobbyId`；
   - `POST /api/lobby/accounts` / `GET /api/lobby/{id}`：按表返回（`connectionString` **原样转发**，
     不需要理解内容——这是自建信令可行的核心原因）；
   - `POST /api/lobby/{id}/member` / `DELETE /api/lobby/clear`：维护成员；
3. 任务链：`Operation/Create` 分配递增 `operationId`（回显客户端给的 seed/planet/missions 即可），
   `Mission/Start` 分配 `missionId`，`Mission/end` 返回录制/自算的奖励包；
4. 其余端点：回放或空 200/204（主界面轮询不要报错）。

### 5.3 已知未知点

| # | 未知 | 怎么验 | 风险 |
|---|---|---|---|
| B1 | 会话建立（Steam 层）是否需要官方签发的 session/lobby 凭证 | 同局域网双机 + 自建信令，能否互见大厅/加入 | 关键未知；决定成败 |
| B2 | `connectionString` 的格式/语义 | 双机联机时本地脱敏记录格式与长度（**原值不要入库**，属敏感数据） | 中 |
| B3 | 登录请求体里的 Steam 票据如何处理 | 抓一次登录 body（本地脱敏分析）；或按 IP 映射绕过 | 中 |
| B4 | 跨平台（`crossplayMode`） | 同 Steam 平台可先忽略 | 低 |
| B5 | 客机世界状态在「主机 mock 世界」下是否稳定 | 主机用 mock Status + 客机加入，看星图/局内 | 按 §3.2 证据预期稳定（必须用客机本地已有的 id） |
| B6 | ToS 风险 | —— | 高（联机绕过官方匹配/结算，多人可见，封号风险高于单机离线） |

### 5.4 验证 runbook

1. **阶段 A（不需要自建）**：两台机器同局域网，官方服务器正常，联机一局；记录
   - 客机任务中进程的 TCP/UDP 远端（Steam 中继 IP？对端公网 IP？）
   - `PUT /api/lobby` body 里 `connectionString` 的**格式与长度**（脱敏，不落原值）
   判据：确认传输层归属（P2P/中继），阶段 B 才有意义。
2. **阶段 B**：两台机器 hosts 指向同一台自建信令服务（先只实现登录 + lobby 转发），Steam 正常；
   判据：互相能看到大厅 / 能点加入（B1 的答案）。
3. **阶段 C**：B 成功后，房主侧用 mock `Status` 提供世界数据；客机加入后看星图与局内是否跟随房主
   （按 §3.2 预期会跟随）。
4. **阶段 D**：任务链 mock（Create/Start/end）跑通一局，检查结算。

## 6. 已排除的死路（别重复）

| 死路 | 为什么 |
|---|---|
| 虚拟局域网（ZeroTier / Radmin / 蒲公英）实现 LAN 联机 | 游戏没有 LAN/直连入口，传输走 Steam P2P 不经虚拟网卡；大厅发现还依赖官方后端 |
| 自建 relay 替换 Steam 传输 | SDR 是 Valve 私有中继网络：服务端不开源，开源版 GameNetworkingSockets **也不含 SDR**；要换得改客户端 network config → EAC 拦。而且**不需要换**：传输沿用 Steam 即可（§12） |
| 改 `game.dll` / `data/game/*.dl_bin` 实现离线 | EAC 判「未知的文件版本」，1 bit 差分也拦（见 `docs/RELEASE-v0.1.1-alpha.2.md`） |
| 指望补出服务器领先客户端的内容（未发布世界/物品） | v4 已证：30 bundle `.strings` 全解、24,834 locid 与旧 build 相同，剩余 locid 两端都没有 |
| 用 `hd2proxy.exe status` 看 hosts 状态 | 它读的是引擎运行状态，不含 hosts；hosts 看 GUI 总览/系统自检或 `install --dry-run` |

## 7. 可复用的工具与资料（全部本机路径）

**产品/工具（已具备）**

- `D:\mod\work\hd2-proxy-toolkit\` —— MITM 工具源码（capture/replay 的改造入口）：
  - `src/hd2proxy/engine/server.py` 引擎启动与请求改写
  - `src/hd2proxy/engine/hooks/` 各类改写钩子（status/warinfo/inventory/items/capture）
  - `src/hd2proxy/gui/` Tk GUI
  - `tools/gen_catalogs.py`、`tools/build_dist.py`、`tools/sync_release_area.py`
- `D:\mod\release-test\current\hd2proxy\` —— 已安装的发布版（v0.4.1-alpha.5）
- `docs/ACCELERATOR-COMPAT-2026-11-20.md` —— TUN/UU 共存与操作纪律（实验环境必读）
- `docs/THIRDPARTY-VARIANTOM-1.26-2026-11-17.md` —— 第三方 mod 侦察报告（端口/共存/函数映射）

**研究资料**

- `D:\mod\work\variant-net\docs\API-ENDPOINTS-2026-11-01.md` —— 59 端点全量清单 + lobby body 形状
- `D:\mod\work\variant-net\docs\MISSION-CAPTURES-2026-11-01.md` —— 任务链真实抓包时间线（Create/Start/end）
- `D:\mod\work\variant-net\docs\GWE-EFFECTS-FULL-26088801.md` —— GWE 效果与目标链（离线下世界数据的语义参考）
- `D:\Downloads\variant_mod\FINDING-零安装客机-2026-10-23.md` —— **主机权威 board 同步的实测证据**
- `D:\Downloads\variant_mod\README.md` —— 多人说明 + UU 兼容性 + 19411 后必须绑 LAN IP
- `D:\QQ\1427814410\FileRecv\自定义多变种与局内多战备编辑器-主机装完客机自动同步（仅支持UU加速器）.zip`
  —— 上述 mod 的原始分发包（作者口径：仅支持 UU 加速器）

**Steam 侧官方/开源资料**：见 §12（Steamworks 文档、GameNetworkingSockets 仓库、HD2 二进制证据与复验命令）。

**抓包样本（可直接用于 replay 试验）**

- `D:\mod\tmp\capture-store-season-20261118\raw\` —— 73 个响应，含
  `a5335597_api_Account_Login.json`（登录 sessionId）、`WarSeason/801/Status`、`Configuration/GameClient`、
  `lobby/accounts`、`StoreFront`、`SeasonPass/*` 等
- `D:\mod\tmp\capture-new-account-20261117\raw\` —— 空号启动样本（默认库存/解锁状态对照）
- `D:\mod\out\gwe\` —— GalacticWarEffects 等在线快照（含 `planetActiveEffects` 历史）

## 8. 环境坑（实验前必读）

1. **hosts 持久、引擎可停**：hosts 指向 `100.67.169.17` 而引擎没跑 → 游戏报 `Error 56 / Status: -1`；
   要么启动引擎，要么 `hd2proxy.exe uninstall` 还原。
2. **证书 48h 轮换**：到期后引擎会生成新 CA，必须 `hd2proxy.exe install`（一次 UAC）重装信任，
   否则游戏 TLS 被拒（`Error 60`）。
3. **TUN / 路由模式加速器**：切换后必须「重写 hosts → 重启引擎」；v0.4.1-alpha.5 已修自动选卡，
   但旧版会绑到虚拟网卡。
4. **绑定地址**：新版客户端拒绝回环，必须绑 LAN IP（第三方 mod 的 19411 结论与此一致）。
5. **启动引擎的推荐方式**（release-test）：

```powershell
$exe='D:\mod\release-test\current\hd2proxy\hd2proxy.exe'
$cfg="$env:LOCALAPPDATA\HD2ProxyStudio\profiles\default.json"
$cert="$env:LOCALAPPDATA\HD2ProxyStudio\certs"
Start-Process -FilePath $exe -ArgumentList @('engine','--profile',$cfg,'--cert-dir',$cert,'--control-port','17897') -WindowStyle Hidden
# 等 6-8 秒后验收：
& $exe verify
# 控制面用 127.0.0.1:17897，token 在 %LOCALAPPDATA%\HD2ProxyStudio\engine.json
```

### 8.1 ⚠️ 端口占用与共存纪律（研究线必读）

**研究线会和产品抢同一批端口**，尤其是 443：mock/自建服务端要接住游戏的 TLS，必须绑在**非回环地址的 443**
（新版客户端拒绝回环，见上一条），而产品 MITM 引擎绑的正是同一个 `100.67.169.17:443` —— **两者不能同时跑**。

#### 产品会话占用的端口（研究实验前先确认它们是否该被占）

| 端口 | 绑定地址 | 归属 | 说明 |
|---|---|---|---|
| **443** | `100.67.169.17`（LAN IP，非 0.0.0.0） | MITM 引擎 | 游戏 API 的 TLS 入口；hosts 指向这里 |
| **8080** | `127.0.0.1` | MITM 引擎 | CRL 服务（游戏 Schannel 需要） |
| **17897** | `127.0.0.1` | MITM 引擎 | 控制面（GUI/CLI 用，0.4.1-alpha.6 起**端口独占**，第二个实例抢不到） |

> 产品引擎启动时会预检这 3 个端口；被占会重试 5 s 后 `BIND FAIL` 并在日志里打印占用者。
> 反过来，研究 mock 先占住 443，产品引擎就起不来（报 `bind ... 失败` / `WinError 10048`）。

#### 共存纪律（按顺序，缺一步就会互相坑）

1. **同一时间只允许一个「443 服务端」**：要么产品引擎，要么研究线 mock —— 不要试图用 `SO_REUSEADDR`
   抢端口（产品 443/控制面都是独占绑定），也不要 `taskkill` 对方的进程（用户的实机测试可能正在进行）。
2. **切换前先查占用**（见下方命令）；要停对方时**先告知用户**（那是用户的运行态）。
3. **切到研究 mock**：停产品引擎 → 改 hosts 指向 mock 的 IP（备份 hosts，产品侧 `hd2proxy.exe uninstall`
   可还原它自己那行）→ 起 mock → 再开游戏。
4. **切回产品**：停 mock → 重写 hosts 指回 `100.67.169.17`（`hd2proxy.exe install`）→ 启动产品引擎 → `verify` 三连。
5. **实验结束必须收尾**：停掉自己起的监听 → 还原 hosts → 确认 443/8080/17897 空闲后再把机器交回产品会话。
6. 研究线**不要**去改产品 profile 的 `proxy.port / crl_port / control_port` 来"绕开"冲突（那是用户的运行配置）；
   自己的服务端端口自己定，但**游戏入口只能是 443**。

#### 查占用（可复制）

```powershell
# 1) 谁在听 443 / 8080 / 17897（占用的 PID）
Get-NetTCPConnection -State Listen -LocalPort 443,8080,17897 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
# 2) 用 PID 看是什么进程（研究线/产品/加速器）
Get-Process -Id <上一步的 OwningProcess> -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path
# 3) 产品侧：引擎是否在跑（会读控制面；未运行也算正常，说明 443 可能空着）
& 'D:\mod\release-test\current\hd2proxy\hd2proxy.exe' status
# 4) 研究实验前期望：如果产品引擎不该跑，上面 1) 应该没有 443 的监听
```

> 判断口诀：**443 只能有一个主人**；8080/17897 是产品专属（mock 不需要它们，别去占）。
> 研究线的 mock 端口、证书、状态目录都用独立位置（`HD2PROXY_STATE` 隔离），别复用产品证书。

## 9. 新会话开工 runbook（按顺序）

0. **先读开头「⛔ 工作区与文件边界」并做 30 秒自检**：确认自己**不在** `hd2-proxy-toolkit` 产品仓库里写东西、
   用的是独立 `HD2PROXY_STATE`、产品仓库 `git status` 为空；研究产物写到独立目录（单独 git）。
   再用 §8.1 的命令确认 **443 当前归谁**（产品引擎在跑就先停/先协调，否则你的 mock 起不来）。
1. **读这份档 + §7 三份研究资料**（API-ENDPOINTS §8.3 / MISSION-CAPTURES / FINDING-零安装客机）；
2. **环境自检**（§2 命令）：版本、hosts、引擎、网络模式；
3. **先做「不需要用户操作」的部分**：
   - 用现有抓包样本（§7）做一次「mock 登录 + 主界面」的离线验证（不启动游戏也能先验回放逻辑）；
   - 写好 capture→replay 的骨架（新 profile 开关），用样本回放做单测；
4. **需要用户配合的部分**（提前说明）：
   - 启动游戏录一局完整会话（含任务链）；
   - 断网启动实验；
   - 自建联机实验需要**两台机器**（或一台物理机 + 一台虚拟机）在同一局域网；
5. **产出**：结论写回本文档同目录（建议命名 `docs/OFFLINE-PRIVATE-SERVER-RESEARCH-*.md`），
   成品能力才进 `hd2-proxy-toolkit` 主线，研究结论不要混入发布版本。

## 10. 开放问题清单（供新会话逐项攻）

- [ ] A1 登录响应 mock 能否被接受（回放 `{"sessionId":uuid}`）
- [ ] A2 游戏进程的完整主机依赖清单（DNS/SNI/TCP/UDP）
- [ ] A3 任务中服务端校验点（`ReportPosition` / `Mission/Session` 失败的影响）
- [ ] A4 断网/离线 Steam 下的票据可用性
- [ ] A5 capture→replay 的时间字段平移策略（避免客户端判定过期）
- [ ] B1 同局域网双机能否仅靠自建信令 + Steam 建连（**最关键**）
- [ ] B2 `connectionString` 的语义与格式（脱敏记录）
- [ ] B3 登录请求体里 Steam 票据的处理方式
- [ ] B4 自建信令下大厅列表/加入流程的完整性
- [ ] B5 主机 mock 世界数据下客机同步稳定性（只使用客户端已定义 id）
- [ ] B6 风险与边界确认（ToS；只在私域/离线使用）
- [ ] B7 HD2 运行时是否真的走 `ISteamNetworkingSockets` + SDR 中继（静态证据已很强，见 §12.4）；
      Steam 托管的大厅/组队（`ISteamMatchMaking*`/`SteamParties`）与游戏自有 `/api/lobby` 谁是主值——
      这决定「官方 API 挂掉时 Steam 侧大厅还能不能用」，以及自建信令会不会与 Steam 大厅状态打架

## 11. 与 MITM 工具（本会话主线）的关系

- **工作区隔离（硬性）**：本线是**只读**产品仓库的外部研究线——不得写入/提交 `hd2-proxy-toolkit`，
  不得动 `release-test` 与用户 `HD2ProxyStudio` 运行态；详见开头「⛔ 工作区与文件边界」。
- 本会话已交付的相关底座：MITM 引擎（capture/rewrite/hosts/证书/控制面）、
  加速器共存修复、诊断与自检、发布与 release-test 同步流程（含 0.4.2 起的 `live` 免游戏拉战况）。
- **本线不属于工具待办**：除非用户明确要在产品里做「离线/私服」能力，否则不要把它塞进
  `hd2-proxy-toolkit` 的 PLAN/CHANGELOG；也不要为了研究实验去改产品代码或运行中的 profile。
- 若将来把 capture→replay 做成产品特性：属于**功能变更**（版本规则：动 `X.Y.Z` + alpha.1 重置），
  并需要单独评估 ToS 与用户风险提示；由 MITM 会话在主线上实现，本线只提供需求与补丁文档。

## 12. Steam 侧官方/开源资源 + 对 B 线的净影响（2026-11-20 补）

> 一句话：**官方文档齐全、传输层有开源等价实现、但 Steam 匹配/大厅后端与 SDR 中继服务端都不开源。**
> 对 B 线是**利好**——我们要自建的「信令/任务登记」正好是 Valve 文档里说的「P2P 需要的那一层」；
> 我们不碰的「传输」直接沿用 Steam。缺的仍然只有**游戏自己的 app 层会话协议**。

### 12.1 官方文档（公开可读，无需合作伙伴账号）

| 文档 | 地址 | 与 B 线的关系 |
|---|---|---|
| Steam Datagram Relay（SDR） | https://partner.steamgames.com/doc/features/multiplayer/steamdatagramrelay | Valve 运营的中继网络：打洞、中继、隐藏 IP；**私有服务** |
| Steam Networking | https://partner.steamgames.com/doc/features/multiplayer/networking | `ISteamNetworkingSockets` / `ISteamNetworkingMessages` |
| Steam Matchmaking & Lobbies | https://partner.steamgames.com/doc/features/multiplayer/matchmaking | Steam 托管的大厅/匹配（对应我们自建的 `/api/lobby`） |
| Game Servers | https://partner.steamgames.com/doc/features/multiplayer/game_servers | 专用服务器注册/托管 |
| `ILobbyMatchmakingService`（Web API） | https://partner.steamgames.com/doc/webapi/ILobbyMatchmakingService | 服务端侧大厅 API |

调用这些服务要 Steamworks 合作伙伴身份（免费注册），但**文档本身公开**，可据此判断 HD2 用了哪一层。

### 12.2 开源的：GameNetworkingSockets（宽松许可）

`https://github.com/ValveSoftware/GameNetworkingSockets` —— 与 Steamworks 版同源的精简传输层：

- 面向连接 + 面向消息；可靠/不可靠；分片重组；基于 ack-vector 的可靠性层（比 TCP 滑动窗口强）；
- **AES-GCM-256 每包加密 + Curve25519 密钥交换**；
- P2P：NAT 穿透走 WebRTC ICE，**「Plug in your own signaling service」**（`README_P2P.md` 有信令插件范例，
  `tests/test_p2p.cpp` 是完整例子）；
- 明确**不做**：上层实体序列化/增量状态编码、压缩 ⇒ **游戏自己的会话协议仍要自己做**（= B 线工作量）；
- 第三方绑定：C#（Facepunch.Steamworks / ValveSockets-CSharp）、Go、Rust。

**开源版不含 SDR**（README 原文）：*"some features are only available on Steam, such as Steam's
authentication service, signaling service, and the SDR relay service"*；SDR 是活服务，Valve 要控制安全与
向后兼容负担，**不向所有平台/非 Steam 合作伙伴开放**。

### 12.3 不开源的部分

- **SDR 中继网络本身**（Valve 私有运营；OSS 不含；不可自建）；
- **Steam 托管的大厅/匹配后端**（可用，不可自建）；
- Game Coordinator / 服务器托管 / EAC 服务。

### 12.4 HD2 的二进制证据（本轮补充，强静态证据）

对 `D:\SteamLibrary\steamapps\common\Helldivers 2\bin\helldivers2.exe`（28,743,256 B）扫描：

- Steamworks 接口版本串：`SteamNetworkingSockets012`(0x1739504)、`SteamNetworkingMessages002`(0x17394e9)、
  `SteamNetworking006`、`SteamMatchMaking009`、`SteamMatchMakingServers002`、`SteamParties002`、
  `SteamNetworkingUtils004`、`SteamUtils010`、`STEAMUSERSTATS_INTERFACE_VERSION013`；
- **引擎自己的 Steam C API 包装源码路径**：`D:\Work\c0b269749c96c578\stingray\runtime\steam\c_api\c_api_steam.cpp`
  ⇒ 不是「碰巧链接了 steam_api64.dll」，而是**引擎网络层就建在 Steam 网络上**；
- **SDR 连接状态串**：`POP remote`、`POP relay`、`FindingRoute`、`Connecting`、
  `Accepted session request from %llx`、`Session connect failed %llx, error: %i`、
  `Steam connection status changed [%u, %s (%i)->%s (%i)] … Remote Identity: %s / Listen socket: %u /
  Address remote: %s / POP remote: %u / POP relay: %u / End reason / End debug / Connection Description`，
  以及连接状态枚举 `Dead`/`Linger`/`FinWait`/`ProblemDetectedLocally`/`ClosedByPeer`/`Connected`、
  `VoIP-Room`、`Steam not setup (yet)`。
  这些是 `ISteamNetworkingSockets` 连接信息/调试输出字段（POP = SDR point of presence）
  ⇒ 引擎走的是 Steam 网络 API，并会读取 SDR 中继的 POP 信息；
- `bin\steam_api64.dll` 在位（317,080 B）。

⚠️ 以上是**静态证据**：能证明「链接并入调用了这套 API」，**运行时是否强制走 relay**（vs 纯直连打洞）
仍要实测（= B7）。复验：

```powershell
cd 'D:\SteamLibrary\steamapps\common\Helldivers 2\bin'
python -c "import mmap;f=open('helldivers2.exe','rb');m=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ);print([hex(m.find(s)) for s in [b'SteamNetworkingSockets012',b'SteamNetworkingMessages002',b'POP relay',b'c_api_steam.cpp',b'SteamParties002']])"
```

### 12.5 对 B 线的净影响（结论）

1. **传输层不用做、也不要换**：Steam 网络 API 已在二进制里确认被引擎调用（运行时是否强制经 relay 待 B7）；
   替换它才需要改客户端（EAC 拦），沿用它是零成本。
2. **信令层正是我们要做的那一层**：Valve 官方架构 = P2P 传输 + 可插拔 signaling；我们在自建信令里
   **原样转发 `connectionString`**（§5.2），本质就是给玩家当 signaling service，传输仍交给 Steam。
   这份文档反过来给 §5.1 的方案**加了权威支撑**（不是野路子）。
3. **SDR / Steam 匹配后端不可自建、也无需自建**：只要 Steam 在线，打洞/中继照常工作；
   我们的自建后端只替代 `api.live.prod.thehelldiversgame.com` 那套游戏自有 API。
   推论：**单机离线（线 A）也不受 SDR 影响**，因为它只影响联机传输，而 Steam 本就在用户边界外照常运行。
4. **真正要攻的还是 app 层**：大厅 body 语义、`connectionString` 格式、任务链 —— 即 §5.2 与 B1–B3。
   GNS README 也明说它「不做上层序列化/状态增量」⇒ 这部分没有任何开源件可抄。
5. **连带新问题（B7）**：HD2 同时链接了 `SteamMatchMaking*`/`SteamParties`。若它的大厅/组队也走 Steam
   托管服务，那么「官方 API 挂了」时 Steam 侧大厅仍可用（利好）；但反过来**自建信令可能与 Steam 大厅
   状态打架**（谁是真值、进游戏时以谁为准），需要实验区分主从。
