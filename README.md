# hd2-proxy-toolkit —— HD2 本机代理工具箱

《HELLDIVERS 2》**本机 MITM 代理**的成品化实现：在本地改写客户端收到的战况接口响应
（`Status` / `warinfo` / `Progression/*`），**不碰游戏文件、不进进程内存**。

- 研究线与全部证据留档：[hd2-network-proxy](https://github.com/deepseekv41flash/hd2-network-proxy)
- 本仓库只放**产品代码**：代理引擎 + GUI + 配置面 + 打包，研究仓只读引用。
- 开发计划：[PLAN.md](PLAN.md) ｜ 代码来源与哈希：[docs/PROVENANCE.md](docs/PROVENANCE.md)
- GUI 选型实测（稳定性/资源占用）：[research/TECH-STACK-DECISION.md](research/TECH-STACK-DECISION.md)

> **当前状态：v0.10.0-alpha.1 已发布（2026-11-25，证书有效期策略：默认 2 天 / 显式 7 天上限）** —— 引擎模块化 + 配置面/控制面/安装还原/证书自动续期/三连验收
> + **Tk GUI 六页** + **6 项能力模板 + 离线预演** + **6 项能力实机逐项验收通过**
> （安装→游戏内验证→还原全链路，见 [docs/ACCEPTANCE-M4.md](docs/ACCEPTANCE-M4.md)），
> **738 个单元测试 + 5 个离线自检全绿**；已打包发布 `v0.7.0-alpha.1`（见下方「下载」）。
> 0.5.0 起加入**本机存档层**（`base ⊕ config ⊕ earned`）：启动按 `_last.json` 乐观预绑定上次的档渲染首屏、
> `Pes/GetMotd` 到达校验、同机换号**整档回滚**到会话基准快照 + 孤儿审计（研究线 2026-11-23 反馈的粒度修正）；
> 0.5.1 起**结算奖励入账**（`Mission/end` 响应 → 经验/货币/物品/包进度累加进本机账本，按 missionId 防双计）；
> 0.5.2 起**终身统计与成就**也进账本（`Stats/profile` 逐 key 取 max、成就上报 per-key max）；
> 0.5.3 起 `hd2proxy save-preview` 可**不开游戏预演**「这份档会改什么 / 一局会加多少」；
> 0.5.4 起局内**消耗扣减**也进账本（`inventory/consume` 请求体 → 数量减、下限 0、保留行）；
> 0.5.4-alpha.2 修复打包版在**中文 Windows 控制台**打印 `⚠` 警告时 GBK 编码崩进程（CLI 起引擎直接退出）；
> 0.5.4-alpha.3 修复**库存数量被本机账本改小**（改为只抬不降）与**续期换 CA 后游戏 Error 60**（续期后需重导信任）；
> 0.5.5 起**购买/解锁响应**也入账（`AcquireUnlockableItem.inventoryChanges` / `SeasonPass/item/buy.items`，负=扣钱正=授予，10s 去重），CA 变更留痕 `certs/ca-history.json`；
> 存档只在本机生效、不回传服务器。
> 0.3.0 起「启动引擎」会先做 **443/8080/17897 端口预检**（冲突列占用者、可换监听地址），总览页新增**系统自检**（端口 / hosts / 证书 / 游戏进程）；
> alpha.2 修掉现场检查弹控制台窗 + 切总览卡顿（子进程隐藏窗口 / 一条 `netstat -ano` / 诊断节流）；
> alpha.3 修掉「续期证书后游戏报 Error 60」：证书信任状态进自检/红字，GUI 新增「安装 / 修复（UAC）」，续期后自动引导导入信任；
> alpha.1(0.4.0) 把**服务端物品目录 3020 行全量**做进产品：`items.json` 1950 → **3062 条**、名字 1821 → **2191**、
> 标注**空号默认拥有 55 项**，物品页新增只读 **「目录总览」** tab（汇总 / 类别筛选 / 默认已有 · 目录缺标记）。
> alpha.1(0.4.1) 物品解锁加 **「清空全部已添加」**：一键撤回四类库存 + 目录追加（附件批量添加后的批量移除）；
> alpha.2(0.4.1) 从客户端 `game.dll` 静态表补完物品名字：命名 2191 → **2383**（横幅/称号/胜利姿势/战团包/礼包等），未解 871 → 679。
> alpha.3(0.4.1) 对照 wiki 已发布战备清单补齐最后 22 条战备名（目录命名 2383 → **2405**，战备 73 → **95** 有名）。
> alpha.4(0.4.1) 战备命名收尾（cat11 再补 7、cat10 子行反推 29 ⇒ 命名 **2441**、战备 **102/108**），全局效果按 target 链补 28 条英文名（效果名 **174 → 202** / 312）。
> alpha.5(0.4.1) 加速器共存修复：TUN/路由模式不再把监听地址选到虚拟网卡；hosts 被 `#uu_acc`/`#g_acc` 注释时自检与引擎日志直接报出；install 默认读 profile 的监听设置。
> alpha.6(0.4.1) 实机复验修复三处缺陷：星球选择器/模板不再允许选 0 号母星（无卡面，注入不可见）、控制面端口独占 + 状态文件覆盖前备份、GUI/CLI 遇 401 直接提示重启引擎；`certs status` 的 `trusted` 不再恒为 null。
> **alpha.1(0.4.2) 新能力「无需游戏拉战况」**：CLI `hd2proxy live` + GUI「拉取战况·推荐靶星」——免登录直拉官方 Status/GWE（与游戏内抓包逐字节相同），自动列出「有战役的可点靶星」（前线优先），杜绝母星 0 坑。
> **alpha.1(0.4.3) GUI 新增「实时战况」页**：免游戏拉取 + 排查视图（靶星表 / 星球效果聚合表 / 过滤 / 选中看 effect 名称 / 自动刷新 / 快照落盘），见 [截图](research/screenshots/live-page-20261120.png)。
> 界面实拍：[总览](research/screenshots/gui-overview.png) ｜ [战况改写](research/screenshots/gui-status.png) ｜
> [物品与战备](research/screenshots/gui-inventory.png) ｜ [目录总览（新）](research/screenshots/gui-inventory-catalog.png) ｜
> [抓包与日志](research/screenshots/gui-capture.png) ｜
> [设置](research/screenshots/gui-settings.png) ｜
> [M4 实机：PARTION 出 PREDATOR STRAIN](research/screenshots/m4-partion-predator-strain.png)


> **alpha 阶段提示**：工具目前处于 **alpha** 阶段，**可能有 bug**。欢迎到
> [Issues](https://github.com/deepseekv41flash/hd2-proxy-toolkit/issues) 报告工具问题或提改进建议
> （请附上 `hd2proxy info` 输出、`%LOCALAPPDATA%\HD2ProxyStudio\logs\proxy.log` 相关片段、
> 复现步骤与游戏 build/war 号；敏感信息请先脱敏）。

## 版本规则

本项目的版本号规则（详见 [docs/VERSIONING.md](docs/VERSIONING.md)）：

- **前三位 `X.Y.Z` 只在「功能/能力」变化时动**；只修 bug 就只动 `alpha.N` / `rc.N` 这一位。
- `X.Y.Z-alpha.N`：新功能刚落地、bug 可能较多（未做用户实机验收）。
- `X.Y.Z-rc.N`：**用户实机验证过**、已知 bug 不影响正常使用（之后只允许修 bug，再改功能回 alpha）。
- `X.Y.Z`：GA 正式版（功能与 bug 都收敛后再发；首个 GA 目标 `1.0.0`）。

```powershell
python tools/bump_version.py fix             # 只修 bug：alpha.N / rc.N +1
python tools/bump_version.py promote-rc      # alpha → rc.1（实机验收通过后）
python tools/bump_version.py ga              # rc → 正式版
python tools/bump_version.py feature --minor # 功能更新：X.Y.Z 变，回 alpha.1
```

门禁会校验版本一致性（`__version__` ↔ `pyproject` PEP 440 ↔ CHANGELOG ↔ 已打 tag 的 Release Notes）。

## 下载（v0.10.0-alpha.1）

> **预览版（alpha）**：M4 已逐项实机验证 6 项能力，但更多机型/网络环境/游戏更新后的
> 全流程稳定性还需要时间验证，先以 alpha 发布。完整说明见
> [Release Notes](docs/RELEASE-v0.10.0-alpha.1.md)。

- 下载：[GitHub Releases · v0.10.0-alpha.1](https://github.com/deepseekv41flash/hd2-proxy-toolkit/releases/tag/v0.10.0-alpha.1)
  （`hd2proxy-toolkit-v0.10.0-alpha.1-windows-x64.zip` + `SHA256SUMS.txt`）
- 要求：Windows 10/11 x64；**不需要装 Python**；日常运行不需要管理员，只有安装/还原各弹一次 UAC。
- 解压即用（onedir，约 15 MB 压缩包 / 解压后约 60 MB）。
  **普通用户双击 `hd2proxy-gui.exe` 打开图形界面**（无控制台）；`hd2proxy.exe` 是 CLI，
  双击它也会打开 GUI（带控制台，便于排障）。

```bat
:: 1. 图形界面（双击 hd2proxy-gui.exe 等价）
hd2proxy-gui.exe

:: 2. 先看环境与数据是否正常（不需要管理员、不需要游戏）
hd2proxy.exe info
hd2proxy.exe preview --profile data\acceptance\m4-b.json     :: 离线预演
hd2proxy.exe live                                             :: 无需游戏：拉当前战况 + 推荐可点靶星

:: 3. 安装（改 hosts + 信任本机 CA；需要一次 UAC）
hd2proxy.exe install --profile <你的 profile.json>
:: 4. 起代理（GUI 里也能起）
hd2proxy.exe engine --profile <你的 profile.json>
:: 5. 验完还原（hosts + 证书；需要一次 UAC）
hd2proxy.exe uninstall
```

> 安全边界：只改客户端收到的接口响应，不碰游戏文件、不进进程内存；单域名白名单 + 仅本机来源；
> 会话证书默认 2 天（显式可放宽到 7 天硬上限）、签完删 CA 私钥；详见下文「安全设计」。

## 现在能做什么

```bash
python -m pip install cryptography pytest   # 运行依赖 + 测试依赖
set PYTHONPATH=src                          # 源码树内使用（或 pip install -e .）
python tools/check_gate.py                  # 门禁：版本一致性 + 语法 + 路径 + 688 单测 + 5 个离线自检
```

自检全部离线（本机假上游 + 临时数据目录 + 临时证书），不需要游戏、不需要联网、不需要管理员。

M1 起也可以用 CLI 走完整流程（详细见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)）：

```bash
python -m hd2proxy gui                            # 打开图形界面（6 页）
python -m hd2proxy preview --profile <profile>    # 离线预演：不开游戏看 profile 会改什么（M3）
python -m hd2proxy save-preview                   # 存档预演：这份档会改什么 / 一局结算会加多少（G6）
python -m hd2proxy info                        # 版本 / 路径 / 引擎是否在跑
python -m hd2proxy certs renew --days 1        # 签发会话证书（ca 模式；默认 2 天，可 --days 7）
python -m hd2proxy install --dry-run --listen-ip <本机非回环IP>   # 只看计划，不改系统
python -m hd2proxy install --listen-ip <IP>    # 真安装（hosts + 证书信任；需要一次 UAC）
python -m hd2proxy engine --profile <profile>  # 起代理（前台；GUI 在 M2）
python -m hd2proxy status                      # 读运行中引擎状态
python -m hd2proxy verify                      # 三连验收（TLS / CRL / Status）
python -m hd2proxy uninstall --dry-run         # 还原计划（真还原需 UAC）
```

也可以直接跑引擎（研究模式，等价于研究线的 `war_proxy.py`）：

```bash
python src/hd2proxy/engine/legacy_proxy.py --help
python src/hd2proxy/engine/legacy_proxy.py --config data/legacy/config.example.json \
    --catalog data/legacy/variant_catalog.json --cert-dir certs --port 8443
```

## v0.1 能力范围（6 项核心）

| # | 能力 | 验证状态（研究线 + M4 实机） | 落点 |
|---|---|---|---|
| 1 | 变种词条（tag + mechanic 成对；虫族 7 个含腐蚀/毒瘴） | ✓✓ M4 实机 | 战况 · 变种卡 / 「变种词条试用」模板 |
| 2 | 全局效果（GWE type94） | ✓✓ M4 实机 | 战况 · 全局效果卡 / 「全局效果试用」模板 |
| 3 | 战备试用（type32，≤3） | ✓✓ M4 实机 | 「战备试用」模板（`status.trials` + `trials_planet`） |
| 4 | 物品解锁（武器/配件/外观 + 目录上架；附件按武器筛选 + 一键解锁整枪配件；**目录 3020 行全量只读总览**） | ✓✓ M4 实机 | **本地账号** · 各分类 +「目录总览」/「物品解锁」模板 /「存档」tab |
| 5 | 休眠星可玩化（planetInfo + 节点 + 战役 + 归属） | ✓✓ 研究实机结算 + M4 节点/连线 | 战况 · 休眠星卡 / 「休眠星可玩化」模板 |
| 6 | 生态借用（`settingsHash`） | ✓✓ M4 实机 | 战况 · 生态卡 / 「生态借用」模板 |

引擎侧保留研究线的全部钩子（防守战役、城市分区、L2 改装等）：它们收在战况页底部
**「扩展 / 实验」折叠区**，每项标注验证状态、默认收起，v0.2 做正式 UI。

### 离线预演（M3，不开游戏）

`preview` 把当前 profile 套到 `data/samples/` 里裁剪过的真实响应上，输出「会新增/修改哪些条目」
和「为什么预演看不到变化」（阵营过滤、条目已存在、样本里没有这颗星…）。纯计算：不联网、不写盘、不读 runtime。

```bash
python -m hd2proxy preview --profile <profile.json>          # 人读文本
python -m hd2proxy preview --profile <p> --fixture status --json
```

GUI 里是战况页顶部「能力模板」条右侧的**离线预演**按钮；结果进只读窗口。

### 存档（本机账本，仅本机视图 · v0.5.0-alpha.1）

服务端的进度响应只是「这一局能拿到的底子」，本工具在它之上叠一层**本机 earned 账本**：

```
响应 = base（服务端） ⊕ config（GUI 里勾的注入） ⊕ earned（本机已获得）
```

- 落盘：`<状态目录>/runtime/saves/<saveId>.json`（冻结版在 `%LOCALAPPDATA%\HD2ProxyStudio\`），
  `saveId = steam_<SteamID64>`（`Pes/GetMotd` 响应里的 `accountId`）。HD2 20 位账号 id 只作**别名**：
  它不保证每会话出现（主号整份抓包都没有），拿它当主键会让同一玩家分裂成两份档。
- **config 不落盘**：GUI 勾选每次响应现读、取消即撤销；`earned` 才是本机事实底账。
- 合并按字段分型：单调量（经验/成就/包等级）取大；可消耗量（货币/道具）以 `updated_at` 较新为准；
  覆盖量（飞船名/位置）以较新为准；集合类（解锁 id/已购）取并集。
- 换号保护：旧档是 `local`（未识别）→ 合并进正确档；旧档是**另一个已识别档**（同机换 Steam 号）→
  **绝不合并** —— 本局写入整档回滚到「会话基准快照」，脏档全文另存 `runtime/saves/_orphan/`
  （附回滚前后 hash 与被丢弃条目摘要），日志里打 WARN。身份校验一致时把基准重建为「最后一次已验证点」。
- **GUI 入口（v0.6.0 起）**：侧栏「本地账号（仅本机视图）」→「存档（本机账本）」tab：档摘要 /
  引擎校验态 / **存档预演**按钮 / 打开存档目录；页头固定三条边界（仅本机视图 / 不回传服务器 / 服务端仍是事实源）。
- 排障/调试：`saves.identity_strict`（默认 `false`）严格模式下身份未校验时**拒绝写盘**；
  `saves.wait_seconds`（默认 1.2）没有历史档时首屏最多等身份多久；
  **`saves.preverify_merge`（v0.6.0-alpha.3 新增，默认 `safe`）**身份未校验时的首屏合并策略：
  `safe` 只合并服务端自算字段（经验/包进度），**成就/统计/库存不合并**（防"上一档显示值 → 客户端回显 →
  记进新档"的污染回路）；`full` 全合并（`upstreamTest`/mock/自建服自动启用）；`off` 不合并。
  战况页顶部一行显示「存档 `<saveId>` · 预绑定待校验 / 已校验 · 本局有写入」。

- **结算奖励也会入账（v0.5.1 起）**：`POST /api/Operation/Mission/end` 的**响应**已含服务端算好的本局增量
  （`experience` / `rewards` / 各类奖励清单 / `progressionPackageUpdates`），不需要请求体；
  经验**累加**、物品按 mixId 累加、包进度按 max 合并，并按 `missionId` 防重试双计。
  客户端结算后**不会**重取 `/api/Progression` ⇒ **效果在重启游戏/回主界面后可见**。
- **终身统计与成就也进账本（v0.5.2 起）**：`Stats/profile` 的 27 项终身计数器逐 key 取 max
  （新号返回 0 也不会把本地战绩抹掉）；`PUT /api/Progression/Achievements` 上报的成就
  按 per-key max 合并（等价累计覆盖 + 幂等防双计）。局内**消耗扣减**（v0.5.4 起）：
  `inventory/consume` 请求体里的 `{mixId, amount}` 从账本数量里减，**下限 0、保留行 amount=0 不删行**
  （库存行同时承担"是否拥有"语义）；只扣账本已跟踪的行，形状不认识就不扣。
- **不开游戏也能预演（v0.5.3 起）**：`hd2proxy save-preview` 把本机账本套到真实样本上，
  列出「Progression/Stats/库存 哪些字段会被抬」以及「喂一份真实结算响应后 +多少经验/物品/包进度」
  —— 存档效果本来要重启游戏才可见，预演把这次实机成本省掉。
**验收口径（按模式分列，别被“没变化”误导）**：

| 模式 | 验收 = | 预期现象 |
|---|---|---|
| **官方服务器** | 不干扰服务端既有进度、不混档、不降级写入 | 打一局 → 重启：经验/货币**不变** ← **这是正确结果**（服务端本来就存着） |
| **mock / 自建（服务端给得少）** | 打一局 → 重启 → 经验/货币**变多** | 存档层把本机账本顶上去（`save-preview` 合并 `fresh/` 样本就是此效果） |

**自建服务器导出（v0.7.0 起，实验）**：`hd2proxy save-export --save-file <账本> --baseline <基线目录> --data-root <根>`
把「基线 ⊕ 本机账本」导出成服务端可直接回放的 `progression.json` / `inventory.json` / `stats_profile.json`
（+ `manifest.json` / `index.json`；可选端点默认导出；账本里有最近一局结算响应时会另出 `mission_end.json`；每玩家结算事件追加到 `settlements.jsonl`，manifest 带 `settlementsCursor`）。同时引擎会给上游所有请求补
`X-HD2-Account`（值优先 SteamID64）+ `X-HD2-Account-Source`（`prebind|getmotd|getmessages`），
供多人自建服按账号分档；客户端自带该头时不重复。边界：**头可伪造，仅适用于可信自建服**；
详见 [Release Notes](docs/RELEASE-v0.10.0-alpha.1.md)。

**已知限制（务必知道）**：客户端**一次会话只拉一次** `/api/Progression`，而引擎启动时先按
`runtime/saves/_last.json` 里「上次的档」渲染首屏，`Pes/GetMotd`（登录后 +24~42 s）才校验身份。
所以同机换号的那一刻，**那一整局客户端都可能沿用旧档的合并视图**（不止首屏，因为不会重取）——
重启游戏后才会换成新档。这不是 bug，是客户端请求时序决定的：我们选择「宁可首屏有内容，也不让老玩家
整局看空档」。v0.6.0-alpha.3 起默认 `safe` 策略**只合并服务端自算字段**，已阻断其中「客户端把看到的
成就数回显上报、被记进新账号账本」的污染路径（2026-11-23 换号实机验收发现并修复）。

离线验证样本：`data/fixtures/saves/{main,fresh}/`（两套真实抓包的 6 个存档端点，无身份/票据字段，
见该目录 README）；合并语义由 `tests/unit/test_saves*.py` 与 `test_active_save.py` 钉住。

## 目录结构

```
src/hd2proxy/engine/                    引擎（server / 钩子 / 配置 / 证书 / 安装 / 控制面 / 离线预演 preview.py）
src/hd2proxy/gui/                       Tk GUI：壳 + 6 页 + widgets + templates.py（能力模板）
src/hd2proxy/versioning.py               版本规则与 PEP 440 映射（docs/VERSIONING.md 的实现）
tests/unit/                             单元测试（688 条：钩子等价性 / 配置 / 证书 / 引擎整链路 / GUI / 预演 / 模板 / 变种目录 / 物品名 / 目录补全 / 存档 / 结算入账 / 统计成就 / 存档预演 / 消耗扣减 / CLI）
tests/selftest*.py                      5 个脚本式离线自检（迁自研究线，仅改路径）
tools/run_selftests.py                  自检总入口（独立证书/数据目录，GATE 判定）
tools/check_gate.py                     门禁：版本一致性 + 语法 + 绝对路径 + pytest + 5 自检
tools/bump_version.py                   按版本规则算下一版本号并更新 __version__/pyproject
tools/check_version.py                  版本一致性检查（__version__ ↔ PEP 440 ↔ CHANGELOG ↔ Release Notes）
tools/extract_catalog_index.py           /api/Progression/items 抓包 → 紧凑索引（含附件 parent，供按武器分组）
tools/extract_item_names.py             dlbin 只读路线：LoadoutEntry 物品内部名（武器/投掷物/背包）→ data/sources
tools/gen_session_certs.py              会话证书签发（ca 模式；默认 2 天、硬上限 7 天）
tools/gen_catalogs.py                   数据目录生成（GUI + 引擎目录；包含服务端目录 3020 行补全/命名/默认标记）
tools/resolve_catalog_names.py          目录名字/类别解析快照生成（只读研究仓数据表；产物 data/sources/catalog_names_resolved.json）
tools/gui_smoke.py                      GUI 冒烟：起真引擎 + 假上游 → 六页截图（`--tabs` 逐 tab 截图）
tools/extract_store_season_layout.py    store/season 抓包 → 结构映射 + 无名行锚点对账（补名字研究用）
tools/sign_local.ps1                    本机自签代码签名（装当前用户信任库 + 签 exe，见 docs/SIGNING-LOCAL.md）
tools/sync_release_area.py              把打包产物同步到「release 产物测试区」（解包最新版 + 归档旧 zip）
tools/win_integrity.py                  把目录树完整性标签标回 Medium（避免 Low IL 下写不了 AppData，见 docs/WIN-INTEGRITY-TRAP.md）
data/legacy/                            引擎读的变种目录（由 tools/gen_catalogs.py 生成，与 GUI 目录同源不漂移）
data/catalogs/                          规范化目录（变种/战备/效果/星球/物品/build 指纹）
data/samples/                           离线预演的样本响应（真实抓包裁剪、无账号字段）
data/fixtures/saves/                    存档系统离线样本（两账号 × 6 个存档端点，无身份/票据字段）
data/acceptance/                        M4 实机验收配置（m4-a 五项 / m4-b 六项，可复现）
research/                               技术选型实测脚本与结论（可复现）
docs/                                   来源与哈希、架构说明
```

## 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 游戏报 **Error 60**（"与服务器通讯时出错"） | 证书链变了但信任库还是旧的。引擎在证书剩余 < `cert.min_remaining_hours`（默认 12h）时**自动续期**，而"签完即删 CA 私钥"⇒ 续期会**重新生成 CA** | 重新导入信任：GUI 点「安装 / 修复」，或命令行 `hd2proxy.exe install --cert-dir %LOCALAPPDATA%\HD2ProxyStudio\certs`（一次 UAC）。引擎日志会有 `⚠ 证书未受信任：当前 CA 不在受信任根存储` |
| 游戏"与服务器通讯时出错"/ 引擎日志 `TLS REJECTED` | CA 没进受信任根存储（从未 install，或换了 CA） | 同上；`hd2proxy.exe certs status` 看 `trusted` 是否 `true` |
| 想确认 Error 60 是不是续期换 CA 导致 | 每次换发 CA 都会写 `certs/ca-history.json`（旧/新 thumbprint + 时间），引擎日志也会告警 | 看该文件最后一条时间是否与故障时间吻合 |
| 装了代理但游戏没走代理 | hosts 没指向本机监听 IP，或被加速器注释（`#uu_acc` / `#g_acc`） | 重跑 install（会重写 hosts）；总览页红条会直接报出来 |
| 引擎启动即退出、只有一行 pyinstaller traceback | 0.5.4-alpha.1 及更早：中文控制台 GBK 打印 `⚠` 崩进程 | 升级到 **0.5.4-alpha.2+** |
| 打了一局后货币显示变少 | 0.5.4-alpha.2 及更早：库存按本机账本"绝对覆盖" | 升级到 **0.5.4-alpha.3+**（只抬不降） |
| 443 被占用 / 起不来 | 旧的引擎/研究 mock/加速器占着 443 | 先停占用者（GUI 会列出 PID）；443 同时只能有一个主人 |

## 安全设计（沿用研究线结论，产品化不放松）

- **单域名白名单** + **仅本机来源**：不是开放代理，非白名单 SNI 直接拒绝（自检第 2 项）。
- **会话证书 ca 模式**：SAN 只有 API 域名，默认 1–2 天硬上限，签完立刻删 CA 私钥；
  本地 8080 提供 CRL（Windows Schannel 必需）；启动前 preflight 校验模式/期限/SAN/多余私钥。
- **默认不落请求/响应体**（抓包需显式开启，且会提示含账号 id）。
- **一键还原**：停进程 → 删信任证书 → 删证书文件 → 删 hosts 行。
- 不修改游戏文件、不注入进程 ⇒ 与 EAC 无关（EAC 只查游戏文件）。

## 加速器 / 代理共存（TUN / 路由模式）

Clash Verge、UU 等工具的系统代理模式对游戏无效（游戏是 Winsock 直连），本工具照常工作；
但**TUN / 路由模式**会改变系统网络外观，需要遵守一条操作纪律：

1. 切换代理/加速器模式后 → **重写 hosts**（GUI「安装 / 修复」或 `hd2proxy.exe install`）；
2. 然后 → **重启引擎**（切换前就在跑的引擎，其上游连接可能被过滤驱动拒绝）；
3. 最后 → 再启动游戏。

工具侧已做的保护（v0.4.1-alpha.5）：TUN/路由模式下「自动监听地址」不会再绑到虚拟网卡；
hosts 被加速器注释（`#uu_acc` / `#g_acc`）时，总览页红条、系统自检与引擎启动日志都会直接报出；
`install` 未显式给 profile 时会读默认 profile 的监听设置。实测对照见
[docs/ACCELERATOR-COMPAT-2026-11-20.md](docs/ACCELERATOR-COMPAT-2026-11-20.md)。

## 边界（研究线已定证，别把承诺说过头）

- 只改**客户端收到的**数据；服务端不落账（伪造星球/战役是"客户端侧真实、战局侧幻影"）。
- **存档只在本机生效、不回传服务器**：它改的是"已获得"在本机的显示与保留，不是退款/反作弊绕过，
  也不会让未购买的商店物品在服务端真正属于你；服务端进度仍是事实源。
- `Mission/Session` 类会话恢复端点有校验（`errorCode 8012016`），不要承诺重连可用。


## 许可

MIT（见 [LICENSE](LICENSE)）。代码与数据来自本人研究仓库，未包含任何游戏资产。
