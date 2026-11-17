# 第三方 variant_mod 1.26 侦察报告：与本工具的共用方法 + 端口被占用解法

> 侦察对象：`D:\QQ\1427814410\FileRecv\自定义多变种与局内多战备编辑器-主机装完客机自动同步（仅支持UU加速器）.zip`
> （zip sha256 `84bb870314acfd47fa56c83a85a2183cc18d84bde4f532d69840a92c1fb86095`，
> 内含 `自定义变种与局内多战备编辑器-便携干净版/variant_mod`，版本 1.26，适配 build 19411 / 游戏 1.007.201）
>
> 方法：只读。解包到 `D:\mod\work\thirdparty-recon\zip\...`，先读作者自带文档，再读源码；
> **不运行**它的任何脚本、不安装、不改 hosts/证书。产物与结论见下（三态判定见 §7）。

## 1. 身份：它就是我们变种目录的上游同一套工具

与本地研究副本 `D:\Downloads\variant_mod`（我们 `data/sources` 变种目录的来源）逐字节比对：

| 文件 | zip 1.26 | 本地研究副本 | 结论 |
|---|---|---|---|
| `panel.py` | `926cdccc887e` 89066 B | 同 hash | **逐字节相同**（同一版本） |
| `README.md` / `使用说明.txt` | `e78f620418d1` / `ed54446fe2e6` | 同 | 逐字节相同 |
| `stratagem_catalog.json` | `c4a6de4ebc90` | 同 | 逐字节相同 |
| `variant_catalog.json` | `6182f63b8ec6` 4290 B | `b9683fb2f92d` 7289 B | 本地副本有我们研究期的实验改动 |
| `tools/war_proxy.py` | `01aff31b918c` 44714 B | `662af7d6fa8f` 81976 B | **本地副本 = 它 + 我们加的 7 个 `_gwe_*`/`_warinfo_*` 改写函数** |
| `config.json` | `9220cea9a4e2` | `b423ca8235c6` | 本地副本多了实验键 |

函数集合比对：zip 的 `war_proxy.py` 有 18 个函数，本地副本 25 个 —— **zip 里没有任何本地副本没有的函数**，
多出的 7 个全是我们的（`_gwe_inventory_rewrite` / `_gwe_items_rewrite` / `_gwe_customize_rewrite` /
`_gwe_capture_dump` / `_gwe_capture_req` / `_gwe_apply_extra` / `_warinfo_apply_extra`）。
⇒ 本产品引擎（`src/hd2proxy/engine/*`）与它**同源**：M0「引擎逐字节迁入」迁的就是这份 `war_proxy.py` 的血脉。

顺带：**「卡牌 4」的出处就是它的 `variant_catalog.json`**（`groups[].name = "卡牌 4"`，
4 条变种 `meta.faction` 全是 `illuminate`），α.4 已按覆盖层 `rename` 改为「光能者 4」并保留 `source_name`。

## 2. 「和代理工具共用的方法」清单（18 个共用函数 → 我们的落点）

| 它的函数 / 机制 | 干什么 | 我们的对应实现 | 状态 |
|---|---|---|---|
| `parse_headers` / `dechunk` / `maybe_gunzip` / `read_head` | HTTP 头解析、chunked 去分块、gzip、按行读 | `engine/httpio.py`、`engine/server.py` | 已继承 |
| `rewrite_status` / `resolve_plan` | Status 响应按 tag+mechanic 成对注入 | `engine/hooks/status.py`、`engine/server.py` 的 REWRITE 段 | 已继承 + 扩展（profile/planet 过滤） |
| `doh_resolve` / `upstream_addr` | DoH 绕 hosts 解析上游、拒绝回环 | `engine/upstream.py`（继承后我们把「回环丢弃」写进断言） | 已继承 |
| `serve_crl` | 本机 8080 提供 `ca.crl`（Schannel 需要吊销检查） | `engine/certs.py::serve_crl` | 已继承 |
| `_session_mode` | 证书 ca/leaf 模式判定 | `engine/certs.py` | 已继承 |
| `preflight` | 启动前安全自检（白名单域名/证书/回环） | `server.py::preflight` + `certs.preflight` | 已继承 + 扩展 |
| `rotate_logs` / `log` / `log_throttled` | 日志轮转 + 限流 | `engine/logutil.py` | 已继承 |
| `port_owner_report` | BIND FAIL 时用 netstat+tasklist 查占用者 | `server.py` 的 BIND FAIL 分支 | 已继承（仅引擎侧） |
| `main` 的绑定段 | 独占绑定 `SO_EXCLUSIVEADDRUSE` + 5 秒重试 10 次 | `server.py:655-687` | 已继承 |
| 面板层 `port_owner` / `listener_status` / `listener_summary` / `conflict_report` / `--ports` / 换监听地址对话框 | 端口占用诊断与换 IP 交互 | **无**（`sysprobe.port_owner` 存在但没被 GUI/CLI 使用） | **缺失（见 §6）** |
| 面板层 `game_running` 守卫 | 1.23 起检测到游戏在跑时，启停代理会弹窗阻止 | **无**（`sysprobe.game_running` 存在，仅单测调用） | **缺失** |
| `setup.ps1` 原子写 hosts + 回读校验 | 先写临时文件再替换、重试 12×；写完回读并识别「被加速器注释」 | `engine/hosts.py::_write_atomic`（同思路，12×300ms）+ `find_marker(commented)` | 已继承且更完整 |
| `tools/selftest_*.py` 四件套 | rewrite/sticky/hot_reload/faction 离线自检 | `tools/run_selftests.py`（5 个：basic/rewrite/hot_reload/sticky/faction） | 已继承 + 扩展 |

## 3. 19411 三个坑（它踩过、我们已继承）——只作确认

1. **新版客户端拒绝回环地址**：hosts→127.x 时客户端 TCP 连上立刻断（ClientHello 都不发）。
   解法：hosts + 代理监听都改成**本机局域网网卡 IP**，并按默认路由挑主网卡（避开 VMware/Hyper-V）。
   我们：`sysprobe.resolve_listen_ip` + `validate_listen_ip` 拦截回环/0.0.0.0。
2. **客户端要求吊销检查**：证书要有 CDP `http://127.0.0.1:8080/ca.crl`，代理启动时内建 CRL 服务。
   我们：`certs.py` 同款。
3. **chunked 头没重写**：解了分块却把原头发给客户端 → 200 但 0 字节。我们：`_fix_headers` 同款。

## 4. 端口被占用：它的一整套解法（本报告重点）

核心前提（它 README 写明）：**游戏硬连 `api.live.prod.thehelldiversgame.com:443`，hosts 只能改域名指向的 IP、
不能改端口** —— 所以「换端口」实际是**换本机网卡 IP，端口仍是 443**。

| # | 方法 | 代码位置 | 要点 / 原话 |
|---|---|---|---|
| 1 | **独占绑定探测** | `panel.py: ip_free()` | 「Windows 上检测端口占用必须用 `SO_EXCLUSIVEADDRUSE`；带 `SO_REUSEADDR` 时即使别人正在监听也能『绑定成功』，检测会误报空闲」 |
| 2 | **三态判定 free / ours / conflict** | `panel.py: listener_status()` | 先 `ip_free` 试绑；失败再区分「本工具自己的代理（正常）」与「别人占用」。自己的 pid 来源：`panel_proxy.pid` / `proxy.pid` / `status.json` |
| 3 | **占用者实名（PID+进程名+完整路径）** | `panel.py: port_owner()` / `_proc_path()` | `netstat -ano -p TCP` 找 LISTENING → `tasklist` 取进程名 → `QueryFullProcessImageNameW` 取路径；**结果缓存 3 秒**（面板每秒轮询，不能每秒 spawn 两个进程） |
| 4 | **通配绑定识别（0.0.0.0）** | `port_owner()` 的 `wildcard` | 有进程绑 `0.0.0.0:443` 时**换任何 IP 都无效**，必须关掉它；提示语会写「全地址绑定，换 IP 无效」 |
| 5 | **启动时 5 秒重试** | `war_proxy.py: main()` 绑定段 | 面板每秒探测占用的那一瞬间、旧代理退出未释放，都属于瞬时冲突，不该直接判死：10 次 × 0.5s |
| 6 | **BIND FAIL 写占用者** | `war_proxy.py` 的 `port_owner_report()` | 失败日志：`BIND FAIL ip:port -> err` + `占用者: python.exe (PID 14972)`；按路径区分「旧代理在别的 VariantMod 目录」vs「加速器/代理软件」 |
| 7 | **面板状态栏 + 红字阻塞提示** | `panel.py: listener_summary()` / `_render_status()` | 状态栏写 `监听 ip:443（空闲 / 本 mod 占用（正常）/ 冲突）`；红字区按优先级阻塞：回环监听、**本机 IP 已变但配置是旧 IP（hosts 需重写）**、端口冲突（含占用者路径）、证书未装、hosts 备注 |
| 8 | **「换监听地址（IP）」对话框** | `panel.py: choose_listen_ip()` | 只列真实网卡 IP（19411 后回环不可用）；每行标注「空闲 / 本 mod 占用（正常）/ 被占用」、「局域网（推荐）」；有 wildcard 时直接红字禁止；应用后写入 config 并**问是否提权更新 hosts** |
| 9 | **`--ports` 命令行** | `panel.py: --ports` | 打印：当前端口所有占用者（标注 own/other + 路径）、当前配置监听者状态、候选回环地址占用表 |
| 10 | **`compat-probe.ps1` 一键取证** | `tools/compat-probe.ps1` | 九项：加速器进程、运行中的网络过滤驱动、TAP/TUN 网卡、hosts 生效行/被注释行、443 占用者、域名解析与期望比对、到目标 IP 的路由、默认路由、proxy.log 尾部 |
| 11 | **游戏运行守卫** | `panel.py: game_running()` + 启停前 `askyesno` | 1.23 起：检测到 `helldivers2.exe` 在跑时点击启动/停止代理会先弹窗阻止（避免掐断会话） |
| 12 | **hosts 写入安全** | `setup.ps1: Write-HostsFile` | 先前「Set-Content 先截断后失败」把 hosts 写成 0 字节；改为临时文件 + 12 次重试替换；写完**立刻回读校验**，识别加速器给行首加 `#g_acc` 的注释行为并报 `hosts-rewritten` |

## 5. 我们产品现状对照

| 能力 | 我们 | 差距 |
|---|---|---|
| 引擎独占绑定 + 5s 重试 + BIND FAIL 占用者日志 | ✅ `server.py` | 与它一致 |
| 端口占用探针（netstat+tasklist、缓存、通配识别） | ⚠️ `sysprobe.port_owner/port_in_use` **已实现但未接线** | 只差 GUI/CLI 调用 |
| 启动前端口预检 + 占用者显示 | ❌ | 现在只能等引擎 BIND FAIL 看日志 |
| 「换监听 IP」交互（候选 IP + 占用状态 + 应用后重写 hosts） | ❌ | 设置页只能手填 IP |
| 本机 IP 变更检测（hosts 里是旧 IP 的警告） | ❌ | `installer.verify_system_state` 只在安装时回读一次 |
| hosts 被加速器注释的界面告警 | ⚠️ `hosts.find_marker` 能识别 `commented`，安装/还原计划里会显示 action，但**自检/总览页不显式告警** | 缺一处 UI |
| 游戏运行中启停代理的保护 | ❌（`sysprobe.game_running` 存在但仅单测用） | 缺 |
| `--ports` / 诊断脚本等价物 | ❌（CLI 无 ports 子命令；无 compat-probe 等价） | 缺 |
| 控制面热重载 / profile / 打包 exe / 证书自动续期 | ✅ 我们独有 | 不必移植 |

补充：我们的端口冲突面比它宽 —— 引擎要占 **443（代理）+ 8080（CRL）+ 17897（控制面）** 三个端口，
预检与诊断应三个都查（它只有 443/8080）。

## 6. 建议的移植清单（按优先级）

> **落地状态（2026-11-17，v0.3.0-alpha.1）**：P0 四项已全部实现 —— 启动前端口预检、
> 「换监听地址」对话框、总览/系统自检（端口+hosts+证书+游戏）、游戏运行守卫；
> 实现为 `engine/diagnostics.py` + `gui/listen_ip.py`，单测 402 → 423。

**P0（下一版 alpha 就做，直接把 `sysprobe` 已有的轮子接上）**
1. **引擎启动前端口预检**：GUI 点「启动引擎」时查 443/8080/17897；冲突则弹窗列占用者（名/PID/路径），
   并给两个按钮：`换监听地址` / `仍然尝试（看日志）`。拒绝回环与通配绑定单独提示。
2. **「换监听地址」对话框**：候选 = 真实网卡 IP（`sysprobe` 已有枚举），逐个标占用状态，
   推荐按默认路由的主网卡；应用后写 profile 并提示重写 hosts（复用现有 install 流程）。
3. **总览页/自检加系统状态**：hosts 是否生效（含被注释）、hosts IP 与本机当前 IP 是否一致、
   端口占用、证书剩余时间 —— 现在「验证三连」只测 TLS/CRL/Status，测不出这四类现场问题。
4. **游戏运行守卫**：`sysprobe.game_running()` 接进启停代理按钮（弹确认）。

**P1**
5. `hd2proxy diagnose`（或 `ports`）子命令：打印上面这些状态 + 占用者，等价 `--ports`/`compat-probe` 的只读版。
6. hosts 被注释/被改写时在总览页红字告警（hosts.py 已能识别）。
7. hosts 写入后回读校验接入安装流程（我们已有原子写；补一条「写完回读不通过 → 明确提示」的界面文案）。

**P2**
8. UU 共存取证：把它的 compat-probe 九项按我们打包形态重做（PowerShell 脚本或 CLI 子命令）。
9. 「加速器 hosts 保护」识别：安装失败时把 `#g_acc`/`#` 注释特征写成人话提示。

## 7. 三态判定（可用性结论）

| 结论 | 内容 | 依据 |
|---|---|---|
| ✅ 已在真机/单测验证可用 | 共用代理核心（hosts+CA+443 MITM+CRL+Status 改写+chunked 修复+粘性星球+热重载）；我们 402 单测 + 5 自检 + M4 实机；本报告 §2/§3 | 我们仓库现状 + 历史验收文档 |
| ✅ 作者有实测记录、可相信 | 端口 443 被占 → 5s 重试 + BIND FAIL 占用者（1.16 现场日志实测）；UU **进程模式**共存（2026-10-23 实测）；多人「房主装、客机零安装」星图+刷怪同步（2026-10-23 实测，机制为引擎原生战况板同步，非我们推送） | 作者 README/COMPAT/FINDING 文档 |
| ⚠️ 作者声称但未实测 | UU **路由模式 / TAP 网卡**下能否共存；**无 mod 客机**能否完整显示/呼叫 `kind=32` 战备试用（作者自己标注「需单独实测」） | README 明确标注 |
| ⚠️ 它自身的小缺陷（我们实现时避开） | `port_owner()` 用 `netstat -ano -p TCP` **只列 IPv4**：双栈监听 `[::]:443` 的进程可能查不到（`wildcard` 也判不出），表现为「被占用！但没占用者」；`--ports` 仍列 127.x 候选（与 19411 后回环不可用的结论自相矛盾，作者标为兜底显示） | `panel.py` 源码核对 |
| ❌ 不可直接用于产品 | 它的 `setup.ps1/teardown.ps1/run.ps1` 依赖它自己的目录结构、`python` 启动方式与日志路径；我们的产品是打包 exe + profile/控制面，不能整包搬；只能搬 §4 的方法与交互设计 | 目录结构/入口不同 |
| ❌ 风险提示（转述作者） | 本地改写响应可能违反游戏服务条款；会话证书/私钥别外传；作者建议只与熟人联机使用 | 使用说明 §十一 |

## 8. 证据位置

- 解包副本（只读）：`D:\mod\work\thirdparty-recon\zip\自定义变种与局内多战备编辑器-便携干净版\variant_mod\`
- 原始 zip：`D:\QQ\1427814410\FileRecv\自定义多变种与局内多战备编辑器-主机装完客机自动同步（仅支持UU加速器）.zip`
- 本地研究副本（同源、含我们扩展）：`D:\Downloads\variant_mod\`
- 本产品对应实现：`src/hd2proxy/engine/{server,upstream,certs,hosts,installer,sysprobe}.py`、
  `src/hd2proxy/gui/{app.py,pages/{overview,settings}.py}`
