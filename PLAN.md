# HD2 战况代理工坊 —— 开发计划 v0.2

> 起草 2026-11-16 ｜ 状态：**M0–M5 全部完成；预览版 `v0.2.0-alpha.1` 已发布（2026-11-17，附件改成两级：按武器筛选 + 一键解锁整枪配件）**
> 依据：`variant-net/docs/HANDOFF-2026-11-15.md` + 现场侦察 + **技术栈实测**（[research/TECH-STACK-DECISION.md](research/TECH-STACK-DECISION.md)）
> 目标 build：**26568081**（warId 801，与交接档一致）
>
> **v0.2 变更**（按你的批复）：① 仓库名定为 `hd2-proxy-toolkit`；② v0.1 只做 **6 项核心能力**；
> ③ GUI 按「稳定 + 低资源」实测后定为 **Tkinter**；④ Git 先纯本地，M5 前再确认远端。

---

## 0. 一句话

把 `variant_mod/tools/war_proxy.py`（1846 行、11 项实机能力、环境变量 + 手改 JSON + PowerShell 启动）做成
**一个本机 GUI 应用**：双击开窗 → 勾选能力 / 选星球 → 一键安装并启动 → 游戏里立刻生效 → 一键还原。
代码进新仓库 `hd2-proxy-toolkit`，旧研究仓与旧工作副本**只读**。

---

## 1. 产品形态

| 项 | 决定 | 理由 |
|---|---|---|
| 交付物 | 单个可分发目录（PyInstaller onedir → zip），Windows 10/11 x64 | 接收者无需 Python；onedir 首启快、便于带数据文件 |
| 进程模型 | **engine（代理）+ GUI（窗口）双进程** | GUI 崩溃/关窗不打断游戏会话；engine 可 headless 被脚本/agent 调用 |
| 权限 | 日常运行**不需要管理员**；仅「安装 / 还原」弹一次 UAC | 443/8080 已实测非管理员可绑；hosts 与证书信任必须提权 |
| 数据目录 | `%LOCALAPPDATA%\HD2ProxyStudio\`（profiles / certs / logs / captures） | 程序目录只读、升级不丢配置；支持 `--data-dir` 便携模式 |
| CLI 保留 | `engine --headless`、`verify`、`selftest`、`config get/set` | 自动化复测、agent 直调、每里程碑门禁 |
| 界面 | 中文，5 页：总览 / 战况 / 物品与战备 / 抓包与日志 / 设置 | 原型已验证观感与中文渲染 |

---

## 2. v0.1 能力范围（6 项核心）

| # | 能力 | 现状验证 | v0.1 落点 | 配置键 |
|---|---|---|---|---|
| 1 | 变种词条（双 id 成对） | ✓ TERREK 出 PREDATOR | 战况·变种卡（阵营自动过滤） | `status.planet_effects` + `variants` |
| 2 | 全局效果（GWE type94） | ✓ 局内轨道加特林变燃烧 | 战况·全局效果卡 | `status.globalEffects` |
| 3 | 战备试用（type32，≤3） | ✓ MG-43/M-105 进栏 | 物品·战备 tab | `inventory.stratagems` |
| 4 | 物品解锁（武器/配件/外观 + 目录上架） | ✓ LAS-22 上架 | 物品·武器/配件/外观/目录 tab | `inventory.*` + `items.add` |
| 5 | **休眠星可玩化**（四件套） | ✓ BICEP 可点可结算 | 战况·休眠星模板 | `warinfo.planet_infos` + `status.planet_nodes/campaigns/owner` |
| 6 | 生态借用（settingsHash） | ✓ TRANDOR 变落叶林 | 战况·生态卡 | `warinfo.settings_hash` |

**引擎侧仍全量实现 11 项**（代码已有、几乎零额外成本），但 v0.1 界面只暴露上面 6 项；
其余进「扩展」入口（默认折叠，标注验证状态），留到 v0.2 做正式 UI：

| 延后项 | 现状 | 备注 |
|---|---|---|
| 防守战役伪造（五件套） | ✓ 实机出 DEFENSE 卡 | v0.2 做模板卡 |
| 城市分区（regions 补缺失） | ✓ 离线双验 + 实机 | v0.2 |
| 归属翻转（owner 独立卡） | ✓ 星图变色 | v0.1 里它是「休眠星四件套」的一件，已能用 |
| L2 改装槽 | ⚠ 送达不生效 | 只读展示，不做成功能 |

> 钩子顺序固定：**warinfo（星球身份）→ Status（战况）→ Progression（目录/库存）**，
> 不在 `main()` 另起路径（交接档 §4.1：三处历史 bug 都出在「另写一条路径」）。

---

## 3. 技术方案（已实测选定）

### 3.1 技术栈

| 层 | 选型 | 证据 |
|---|---|---|
| 语言/运行时 | Python 3.13.9 | 已装 |
| 证书 | `cryptography` 50.0.2，沿用 ca 模式 + CRL 8080 | 已装；leaf 模式游戏拒握手 |
| **GUI** | **Tkinter 8.6 + ttk（stdlib）** | 实测：**31.7 MB / 1 进程 / 0.0% 空闲 CPU / 188ms 启动**；pywebview 对照 408 MB / 7 进程 / 1.88%（详见选型报告） |
| 打包 | PyInstaller 6.16 onedir | Tk 最小包 **25 MB，开箱通过**；pywebview 同条件**打包后运行失败**（CLR 解析） |
| 测试 | pytest + 离线假上游（复用现有 5 个 selftest 思路） | 现有 selftest 已证明可离线跑 |

### 3.2 进程与 IPC

```
GUI (Tk 窗口)
 └─ HTTP 127.0.0.1:<随机端口>，token 存 engine.json
     └─ engine
         ├─ 443  MITM（单域名白名单 + 仅本机来源）
         ├─ 8080 CRL（Schannel 必须拿到这份 CRL 才握手）
         ├─ 控制面 API：/status /config /events /start /stop /verify
         └─ 钩子管线：warinfo → status → inventory → items → customize → capture
```

GUI 只是控制 API 的一个客户端 ⇒ 未来换壳（Qt/Web）不动引擎，headless/agent 共用同一接口。

### 3.3 配置面（核心重做）

现状 = `HD2_GWE_EXTRA` 环境变量 + 8 个 `runtime/*.json` + `config.targets` 三套并存；
成品 = **单一 profile JSON（schema v2）**，热重载（mtime 变更即生效，不重启引擎）：

```jsonc
{
  "schema": 2,
  "proxy":  { "host": "api.live.prod.thehelldiversgame.com", "listenIp": "auto", "port": 443,
              "crlPort": 8080, "passthrough": true, "verbose": false },
  "warinfo":{ "settings_hash": {"100": 2995599666}, "planet_infos": [ /* 休眠星四件套之一 */ ] },
  "status": { "variants": ["掠食变种"], "trials": [1982351727],
              "planet_effects": [{"index": 76, "ids": [1243,1245]}],
              "globalEffects": {"1501113": [1346]},
              "campaigns": [], "attacks": [], "events": [], "regions": [],
              "planet_nodes": [], "owner": {} },
  "inventory": { "weapons": [], "attachments": [], "cosmetics": [], "stratagems": [] },
  "items":  { "add": [] },
  "capture":{ "enabled": false, "dir": "", "paths": [], "reqPaths": [] }
}
```

- 多套 profile（如「变种-虫族」「休眠星-300」「生态借用」），GUI 切换即热生效。
- 旧格式兼容层：可一键迁移旧 `config.json` / `runtime/*.json` / `HD2_GWE_EXTRA`（研究复现用）。

### 3.4 证书与信任（沿用 + 产品化）

- **ca 模式强制**（leaf 模式游戏直接拒握手）；SAN 单域名、默认 2 天（保留 ≤2 天硬上限）、签完删 CA 私钥、CRL 8080。
- 新增：**剩余 <12h 自动续期** + 主界面倒计时 + 过期时启动前拦截并提示重签。
- 还原 = 停进程 → 删 Root 里本项目所有证书（含历史残留）→ 删证书文件 → 删 hosts 行（原子写 + 备份）。

### 3.5 离线预演（做产品的关键）

改写函数都是纯函数：载入真实响应样本（Status / warinfo / inventory）→ 套用当前配置 →
表格显示「将新增/变更 N 条」。**不开游戏就能验证配置**，也是 M3 每项能力的自动化门禁。

### 3.6 复用旧面板的成熟件

`panel.py` 里已验证的系统探针直接迁移：`netstat/tasklist` 端口占用（含 0.0.0.0 通配检测）、
`ctypes` PID 存活、`certutil` 证书存储、hosts 行状态（含「被注释」识别）、非回环 IP 枚举、
游戏进程检测、DPI 缩放。

---

## 4. 仓库结构（新仓 `hd2-proxy-toolkit`）

```
hd2-proxy-toolkit/
├─ src/hd2proxy/
│  ├─ __main__.py            # CLI: gui / engine / install / uninstall / verify / selftest
│  ├─ engine/
│  │  ├─ server.py           # TLS MITM 服务（源自 war_proxy.py）
│  │  ├─ upstream.py         # DoH 解析 + 上游 TLS
│  │  ├─ pipeline.py         # 钩子注册与固定顺序
│  │  ├─ hooks/ (warinfo|status|inventory|items|customize|capture).py
│  │  ├─ certs.py  hosts.py  elevation.py  sysprobe.py
│  │  ├─ config.py           # schema v2 校验 / profile / 热重载
│  │  └─ control.py          # 本地控制 API + 事件环
│  └─ gui/  app.py + pages/(overview|status|inventory|capture|settings).py + widgets/
├─ data/catalogs/            # 变种 / 战备 / GWE 效果 312 / 星球 400 / 物品 / build 指纹
├─ tests/                    # 离线 pytest（每钩子 + 预演用例）
├─ tools/                    # gen_catalogs.py、打包脚本、样本脱敏
├─ research/                 # 本轮选型实测脚本与报告（保留可复现）
├─ docs/                     # README、使用说明、能力清单、安全设计、已知边界
└─ pyproject.toml  build.ps1  LICENSE(MIT)  .gitignore
```

**数据口径**：`data/catalogs/*.json` 由一次性生成脚本从研究仓产物产出后**固化进仓库**；运行时不依赖旧仓。

---

## 5. 里程碑（每步带门禁，估时按工作时段）

| M | 内容 | 门禁（贴原始输出） | 原估（人日） | 实测/校准（会话分钟） |
| **M0 骨架** | 建仓、目录、搬 engine 源码（先原样落地）、5 个 selftest 与证书工具适配、catalogs 生成 | 5 个 selftest 全 PASS；`py_compile` 干净；无旧路径硬编码 | 0.5 天 | ✅ **~19 分钟**（19:00→19:18） |
| **M1 引擎+控制面** | 模块化拆分（17 模块）、schema v2、热重载、控制 API、install/uninstall（UAC 自提升）、自动续证、CRL；数据管道：`settings_hash` 走 live warinfo 导入 | 见 §10（213 单测 + 5 自检 + 整链路实测全绿） | 1.5 天 | ✅ **26 分 38 秒**（19:19→19:45） |
| **M2 GUI 骨架** | Tk 壳 + 5 页 + 状态轮询 + schema 驱动表单 + 星球/效果搜索选择器（以原型为基线） | 见 §11（234 单测；5 页实拍；门禁 PASS） | 1.5 天 | ✅ **约 30 分钟**（19:56→20:26） |
| **M3 6 项能力** | 6 张能力卡/模板 + 离线预演 + 扩展入口（延后项折叠标注） | 见 §12（293 单测；每项能力 ≥1 条离线预演用例；预演截图） | 1 天 | ✅ **约 25 分钟**（交接档 21:31 → 收尾 21:44，含一次上下文折叠轮） |
| **M4 实机验收** | 进游戏逐项验证、修现场问题、记录日志证据 | 见 §13 与 [docs/ACCEPTANCE-M4.md](docs/ACCEPTANCE-M4.md)：**6/6 PASS** + 回读还原 | 0.5 天 | ✅ **约 80 分钟**（21:50→23:05；含 3 轮游戏内复核与 1 次 UAC 安装/还原） |
| **M5 打包发布** | PyInstaller onedir、README/使用说明/截图、`v0.1.0-alpha.1` tag + Release | 见 §14：zip 解压即用（干净路径验证）、打包 exe 冒烟、Release 附件 + SHA256 | 0.5 天 | ✅ **约 22 分钟**（23:06→23:28，含 3 次打包工具修复） |

关键路径：M0 → M1 →（M2/M3 可部分并行）→ M4 → M5。M4 必须你在场。

### 5.1 估算校准（2026-11-16，用实测反推）

| 里程碑 | 原估（人日） | 实测 | 偏差 |
|---|---|---|---|
| M0 | 0.5 天（≈4h） | **~19 分钟** | 约 12× |
| M1 | 1.5 天（≈12h） | **26 分 38 秒** | 约 27× |

结论：原表用的是「人类工作日」口径（含上下文切换、查资料、等待外部确认），
而实际是 agent 连续会话 + 子代理并行，**压缩了 12–27 倍**。因此：

- 后续按「会话分钟」估：**M2 ≈ 45–70 分钟、M3 ≈ 30–45、M5 ≈ 20–30**；
  剩余主动工作量合计约 **2–2.5 小时**；
- **M4 例外**：我的操作只要 15–20 分钟，但要你开游戏、逐项验证，wall-clock 取决于你；
- 缓冲仍留 30%：GUI 的观感迭代（截图后调布局）与打包（PyInstaller + Tk）是最可能超时的两步。

---

## 6. 风险与已知坑

| 坑 | 对策 |
|---|---|
| 证书硬期限；过期症状 = 静默停听（与「没启动」一样） | 自动续期 + 倒计时 + 启动前 preflight 拦截 |
| 客户端拒绝回环地址（build 19411+） | 只用非 127 本机网卡 IP（本机 `100.67.169.17`），GUI 自动枚举 |
| `Status` 条件请求头 → 304 无 body → 无法改写 | 沿用「对 Status 剥条件头」+ WARN 日志 |
| 改 body 必须重写 Content-Length / 去 chunked / 去 Content-Encoding | 沿用 `_fix_headers` + `maybe_gunzip`/`dechunk` |
| 中文进 spec 会双编码乱码 | 产品内部全结构化 JSON，禁止让用户拼 JSON 字符串 |
| 端口 443 被 VMware/VPN/其它代理占用 | 启动前冲突检测（含通配检测），GUI 给换 IP/端口引导 |
| 未签名 exe 可能被拦 | 发布说明写清；可选后续做代码签名 |
| Tk 观感短板 | 已用原型验证；深色主题 + 描边分区 + 懒加载页面 |

**合规红线**：证书名受限、有效期 ≤2 天、单域名白名单、仅本机来源、默认不落敏感 body
（抓包需显式开启并提示含账号 id）、一键还原。不碰游戏文件、不进进程内存 ⇒ 与 EAC 无关。

---

## 7. 与旧资产的关系（你的约束）

- **不改**旧研究仓 `variant-net`、`repo-datamined`；只**读取**其产物生成 catalogs。
- **不改**旧工作副本 `D:\Downloads\variant_mod`；新仓自带代码副本并注明出处。
- 发现旧文档/注释有错：先在新仓记录勘误点，**经你同意**才回调旧仓。
- `hd2-network-proxy` 保持研究资料仓定位；README 指一行到新仓（待你批准后做）。

---

## 8. 已定决策（2026-11-16 你的批复）

| # | 决策 | 结果 |
|---|---|---|
| 1 | GUI 技术栈 | 先调研 → 实测后定 **Tkinter**（31.7MB / 1 进程 / 0.0% 空闲 CPU / 打包 25MB 通过） |
| 2 | 仓库名 | **hd2-proxy-toolkit** |
| 3 | v0.1 范围 | **6 项核心**，其余引擎保留、界面延后 |
| 4 | GitHub | **先纯本地**，M5 前确认远端 |

---

## 9. M0 交付记录（2026-11-16）

**仓库**：https://github.com/deepseekv41flash/hd2-proxy-toolkit （public，`master`）

| 提交 | 内容 |
|---|---|
| `fc06376` | 仓库骨架：LICENSE / .gitignore / pyproject / README / 计划书 / 选型实测 / 来源档案 |
| `826ba04` | 引擎逐字节迁入（`src/hd2proxy/engine/legacy_proxy.py`，仅路径 shim）+ 5 个离线自检 + `run_selftests.py` / `check_gate.py` / `gen_session_certs.py` |
| `0071f53` | GitHub Actions 离线门禁（windows-latest） |
| `05fa6a1` | `python -m hd2proxy` 入口（engine/selftest/gate/info）；示例配置去机器相关值；PROVENANCE 补 CRLF/LF 双哈希 |
| `791681b` | catalogs 生成脚本 + 6 份规范化目录（双跑字节一致） |

**门禁证据（本机原始输出）**

```
$ python tools/check_gate.py
  py_compile: 11 个文件, 0 失败
  绝对路径: 0 处（说明：代码里只允许环境变量/相对仓库根的路径）
  basic        PASS    1.9s  RESULT=PASS
  rewrite      PASS    1.9s  RESULT=PASS
  hot_reload   PASS    4.7s  RESULT=PASS
  sticky       PASS    3.5s  RESULT=PASS
  faction      PASS    0.1s  RESULT=PASS
GATE=PASS
```

**CI 证据**：GitHub Actions `gate` 在 `windows-latest` 上连续两轮 `success`（31s / 37s）。

**catalogs 实测**：`variants 25 / stratagems 58 / effects 312 / planets 438 / items 1671 / build 5`，
连续两次运行 6 份 JSON 的 sha256 逐字节一致（`b50dc077…`、`6695ba81…`、`0aa32d33…`、`c8c179cf…`、`e8bc5eef…`、`54ab90ec…`），
无 BOM / 无 CRLF / 无绝对路径；缺源文件时报错退出、不落半套文件。

**与计划的偏离（均已在 PROVENANCE / catalogs README 记录）**

1. `data/legacy/config.example.json` 不再逐字节等于机器快照：`listenIp` 改占位符（原值为作者机器网卡 IP）、`passthrough` 默认 `true`；其余字段一致。
2. 新增 `src/hd2proxy/__main__.py`（pyproject 的 `hd2proxy` 入口需要，M0 只做 4 个子命令）。
3. catalogs 的 `planets.settings_hash` 全 null（源无该字段）→ 生态借用改用「运行时 live warinfo 导入」，M1 数据管道实现。

**遗留缺口（不阻塞 M0，进 M1/M3）**：见 [data/catalogs/README.md §已知缺口](data/catalogs/README.md) 四条。

---

## 10. M1 交付记录（2026-11-16）

**一句话**：引擎从「1846 行单文件」拆成 `engine/` 17 个模块，配置面 / 控制面 / 安装还原 /
证书自动续期 / 三连验收全部落地，且用 **M0 黄金基准**证明重构没有改变行为。

| 交付 | 内容 |
|---|---|
| 引擎模块化 | `server / model / catalog / certs / config / spec / control / verify / paths / logutil / httpio / upstream` + `hooks/` 6 个 + 系统面 `hosts / sysprobe / elevation / installer`；`legacy_proxy.py` 变兼容入口（脚本方式启动仍可用） |
| 配置面 | schema v2 单一 profile；校验（errors 阻止启动 / warnings 提示）、原子存取、`to_engine_spec()`、旧 `config.json`+`runtime/*.json`+`HD2_GWE_EXTRA` 一键迁移 |
| 控制面 | 127.0.0.1 + token；`/status /events /config(GET/PUT 热应用) /profiles /reload /verify /passthrough /capture /shutdown`；`engine.json` 供 GUI 发现；本机请求显式绕系统代理 |
| 证书 | ca 模式签发 / 状态快照 / 剩余 <12h 自动续期 / preflight（SAN、≤2 天、模式、多余私钥）/ CRL 服务 |
| 安装/还原 | `installer` 契约：dry-run 只给计划；先证书后 hosts；非管理员走 UAC 自提升子进程；成败以回读系统状态为准；还原不删证书文件 |
| 验收 | `verify.py` 三连（TLS 握手 / CRL 200 / Status 回执），CLI `verify` 走控制面 |
| 数据管道 | `capture.planet_settings=true` 时把 live warinfo 的 `settingsHash` 落盘到状态目录（能力 6 的数据来源，替代不存在的离线字段） |
| CLI | `info / engine / selftest / gate / profiles / migrate / certs / install / uninstall / status / verify / shutdown` |

**门禁证据（本机原始输出）**

```
$ python tools/check_gate.py
  py_compile: 60 个文件, 0 失败
  绝对路径: 0 处
  213 passed in 9.90s            # pytest tests/unit
  basic/rewrite/hot_reload/sticky/faction 全 PASS   # 5 个脚本式自检
GATE=PASS
```

**等价性证据**：`tests/fixtures/make_golden.py` 从 git 历史里的 M0 实现（commit `826ba04`）生成基准，
`tests/unit/test_hooks.py` 用「显式 spec」与「旧 env/runtime 文件」两条路径比对，输出逐字段一致。

**M1 期间修掉的真实产品级问题**

1. **本机请求被系统代理劫持**：Windows 注册表代理会让 urllib 把 `127.0.0.1` 也送进 Clash，
   控制面/CRL 直接失败 → 所有本机 HTTP 显式 `ProxyHandler({})`（研究线 curl 需 `--noproxy '*'` 的同类坑）。
2. 控制面 `send_header("Connection: close")` 少传 value → 所有控制请求 500。
3. `EngineContext` 缺 `set_passthrough_cb` 槽位 / 状态读取用了过期 spec → 直通切换后 `/status` 不更新。
4. profile 的 `crl_port` 没覆盖 legacy cfg → CRL 仍绑 8080（与实机代理抢端口）。
5. 回环监听：产品路径拒绝，但离线测试需要 → `--allow-loopback` / `cfg.allowLoopback` 显式开关（仅测试）。

**与计划的偏离**

- **真安装/还原未在本机执行**（要改 hosts + 写证书存储，需 UAC 且会与当前实机代理状态交叉）。
  M1 用「dry-run 计划 + 系统状态回读 + 临时 hosts/certutil 桩的 178 项系统面单测」覆盖；
  真安装留 M4 实机验收（你本人在场时跑一次 `install` 即可）。
- 物品名称表补齐（catalogs 缺口 2）未在 M1 做：现有源只解出约 391/1671 个名字，
  需要 dl_bin 名称表提取，随 M3 的「物品解锁」界面一起做。

---

## 11. M2 交付记录（2026-11-16）

**一句话**：Tk GUI 五页落地，作为「控制面客户端」跑通
`保存/应用 profile → 启动引擎 → 状态轮询 → 验证三连 → 安装计划 dry-run` 全链路。

| 交付 | 内容 |
|---|---|
| GUI 壳 | 顶栏（profile 保存/应用 + 引擎/证书/抓包/配置 pill）、左侧 5 页导航、底部状态行；后台 0.6s 轮询，Tk 主线程只渲染 |
| 总览页 | 四张状态卡（运行/证书/改写/抓包）+ 两行动作（启动/停止/切换直通/验证三连；续证/安装计划/还原计划/打开日志）+ 最近改写事件表 |
| 战况改写页 | 六项核心能力卡：变种词条、全局效果、星球词条、休眠星四件套、生态借用、归属翻转（2 列网格 + 纵向滚动） |
| 物品与战备页 | 武器/附件/外观/战备/目录追加 五个 tab：搜索 + 加入库存/目录 + 已加入表 |
| 抓包与日志页 | 抓包配置（开关/目录/白名单/planetInfos.settingsHash 记录）+ 引擎 stdout 实时日志 + 改写事件表 |
| 设置页 | proxy/cert 表单、profile 另存、路径与版本环境面板、打开状态/日志目录 |
| 工具 | `tools/gui_smoke.py`：起真引擎 + 假上游 → 五页截图 + `/status` 快照（M2 验收证据） |
| CLI | `python -m hd2proxy gui [--profile P]` |

**门禁证据（本机原始输出）**

```
$ python tools/check_gate.py
  py_compile: 59 个文件, 0 失败
  绝对路径: 0 处
  234 passed in 14.07s          # pytest tests/unit
  basic/rewrite/hot_reload/sticky/faction 全 PASS
GATE=PASS
```

**界面实拍**（`python tools/gui_smoke.py`，1180×780，绑真实引擎状态）：
`research/screenshots/gui-overview.png` / `gui-status.png` / `gui-inventory.png` /
`gui-capture.png` / `gui-settings.png`

**M2 期间修掉的真实问题**

1. `tk.Frame` 不支持 `style=`（Page 基类用错控件族）→ 页面全部创建失败。
2. 引擎 `listen_ip="auto"` 未被解析（只在空值时解析）→ 启动 bind 失败。
3. `/status` 没有抓包状态 → 总览/顶栏抓包显示永远"关"；补 `capture` 字段。
4. 总览动作按钮单行超宽被裁 → 改两行；设置页纵向溢出 → 紧凑化 + 环境面板换行。
5. 页面测试在「前面测试销毁过 Tk」后会跳过 → 补 TCL_LIBRARY/TK_LIBRARY 环境引导。
6. **休眠星坐标被截成 0**：`config.validate()` 用 int 归一化 `warinfo.planet_infos[].position`
   的 x/y（星图坐标是浮点，0.3 → 0）→ 改为数值归一化（int/float 都保留），并加回归测试。

**与计划的偏离**

- GUI 未做「星图可视化」：v0.1 用星球下拉 + 表格，符合「简洁」定位；星图画布留 v0.2。
- 物品名依赖 catalogs（约 391/1671 有名字）：其余显示类别，M3 与物品解锁界面一起补。
- 战况页 6 卡在 780 高度需纵向滚动（已实现），优先保证控件完整可见。

---

## 12. M3 交付记录（2026-11-16）

**一句话**：六项核心能力从「一页编辑器」升级为「能力模板 + 离线预演」——
不进游戏就能看到 profile 会改客户端什么、为什么没生效；延后项折叠在「扩展 / 实验」区并标注验证状态。

| 交付 | 内容 |
|---|---|
| 离线预演引擎 | `engine/preview.py`：`preview(profile) -> {passthrough, fixtures{counts,changes,warnings,applied}, warnings}`。对 5 类响应（status / warinfo / inventory / items / customize）套**同一批钩子**，输出「会新增/修改哪些条目」与「为什么预演看不到变化」。纯计算：不联网、不落盘、不读 runtime（`logutil.quiet()` 连日志都不写） |
| 样本 | `data/samples/{status,warinfo,inventory,items,customize}.json`（真实抓包裁剪、无账号字段）+ `README.md`（来源 / 边界 / 换成自己 live 样本的步骤） |
| CLI | `python -m hd2proxy preview --profile P [--fixture status\|warinfo\|inventory\|items\|customize\|all] [--json]`；无 profile 时列出本机 profile |
| 能力模板 | `gui/templates.py`：6 个核心模板（变种词条 / 全局效果 / 战备试用 / 物品解锁 / 休眠星四件套 / 生态借用）+ 3 个延后项（防守战役、城市分区、L2 改装，带 `evidence` 验证状态）；只改内存 profile，幂等 |
| GUI 集成 | 战况页顶部「能力模板」条（模板下拉 + 目标星球 + 应用 + **离线预演**按钮，预演结果进只读窗口）；底部「扩展 / 实验」折叠区（默认收起，逐项标验证状态并可应用） |
| 战备试用补洞 | 试用按星球下发，之前「只有 trials 没有变种」的 profile 会被 `build_status_plan` 静默丢成空计划 → 新增 `status.trials_planet`（null=跟随变种星球），模板自动写入 |
| 测试 | `test_preview.py` 21 条（六项能力各 ≥1 条 + 直通/空 profile/样本缺失/未知样本/不写日志等边界）、`test_templates.py` 31 条（6+3 模板 apply 后仍能通过 validate、幂等、延后项标注） |

**门禁证据（本机原始输出）**

```
$ python tools/check_gate.py
  py_compile: 63 个文件, 0 失败
  绝对路径: 0 处
  293 passed in 16.80s          # pytest tests/unit（M2 末 234 → +59）
  basic/rewrite/hot_reload/sticky/faction 全 PASS
GATE=PASS
```

**离线预演样例**（`python -m hd2proxy preview --profile <演示 profile>`，节选）

```
· 战况 Status：5 处增量（会改写）
  - 星球 100 追加效果 1243
  - 星球 100 追加效果 1245
  - 星球 76 追加效果 1244
  - 结构化改写：战役 +1 条
  - 星球 158 归属 2 → 1
  ! 变种 掠食变种（terminid）与星球 76 的 owner=unknown 不同阵营，实机会被过滤掉
· 星球 WarInfo：2 处增量（会改写）
  - 星球 76 生态 settingsHash 0x0000006F → 0x000003E7
  - 追加星球身份 index=350（休眠星补节点身份）
· 物品库存：3 处增量（会改写）  · 物品目录：1 处  · L2 改装（实验）：2 处
合计：13 处增量，5 类响应会被改写
```

**界面实拍**：`research/screenshots/gui-status.png`（模板条 + 预演按钮）、
预演/模板说明走 `_TextDialog` 只读窗口（复用安装计划窗口）。

**M3 期间修掉的真实问题**

1. **`_warnings` 被当成拼错的用户键**：`load_profile_file` 挂的内部元数据会被下一次
   `validate()` 报「未知顶层键」，预演/GUI 都显示这条噪声 → `validate()` 跳过 `_` 前缀键（加回归测试）。
2. **只有战备试用没有变种的 profile 不生效**：`build_status_plan` 只从变种星球建计划，trials 被静默吞掉 →
   新增 `status.trials_planet`，无变种也能单独挂星球生效（预演可见「追加效果 1227」）。
3. **预演会把钩子日志写进 `logs/proxy.log`**：钩子内部直接调 `log()`，参数传不进去 →
   `logutil.quiet()` 进程级静音，预演真正零副作用。
4. 模板说明文字在 1180 宽下被裁 → 按容器宽度动态 `wraplength`。

**与计划的偏离（有意）**

- **直通模式下预演仍然算增量**：默认 profile 是 `passthrough=true`，若照「直通=0 改动」实现，
  新建 profile 的预演永远空白。改为「预演算关闭直通后的增量 + 顶部警告 + 每类响应标 applied」，
  GUI 明确提示「需先关直通」。
- **延后项不止折叠展示**：3 个延后模板也能直接应用（引擎能力已在），只是界面归入「扩展 / 实验」并标注验证状态。
- **休眠星模板带默认星 300（BICEP）**：坐标/hash 用研究线模板值，说明里明确「换 build 需抓 live warinfo 核对」。

**剩余**：M4 实机逐项验收（需你开游戏，含真 install/uninstall）；M5 PyInstaller 打包 + 发布。

---

## 13. M4 实机交付记录（2026-11-16）

**一句话**：v0.1 的 6 项核心能力在真实游戏里**逐项 PASS**；安装（UAC）→ 三连验证 → 游戏内验证 →
uninstall + 清理旧 hosts 残留的**完整闭环**跑通；期间暴露的 6 个真实问题当场修掉。
完整证据见 [docs/ACCEPTANCE-M4.md](docs/ACCEPTANCE-M4.md)。

| 能力 | 实机观察 | 结论 |
|---|---|---|
| 变种词条 | PARTION 卡面 `PREDATOR STRAIN`（截图 `research/screenshots/m4-partion-predator-strain.png`） | ✅ |
| 全局效果 | 轨道加特林弹幕 → 燃烧版（事件 1501107 + effect 1346） | ✅ |
| 战备试用 | 战备栏出现 MG-43 / M-105 | ✅ |
| 物品解锁 | 军械库出现 P-41 / SG-8F / LAS-22 / LAS-13 TRIDENT（目录 +3、库存 +4） | ✅ |
| 休眠星四件套 | BICEP 节点出现、有连线、可选中（结算见研究阶段 §6.3 前证） | ✅ |
| 生态借用 | TRANDOR 落地落叶林（名字随 hash 变 UVP ALPHA，预期副作用） | ✅ |

**前置链路**：证书签发（48h ca）→ 真安装 UAC（hosts + LocalMachine 根信任，回读 OK）→
引擎 `rewrite` 模式 → 三连验证 3/3（Status 200 · 56,973 B 改写后响应）→ 当日 live Status/warinfo
经 DoH 直连拉取用于挑靶星/预演对照。

**M4 暴露并修掉的问题**

| # | 问题 | 修复位置 |
|---|---|---|
| 1 | `planets.json` 的 `index` 是 planet_data 行号，写进 profile 后目标星全错 | `tools/gen_catalogs.py` 合并 `index-names-801.json` → 新增 `game_index`/`x`/`y`；GUI `catalogs.py`/`PlanetPicker` 一律用游戏索引 |
| 2 | 休眠星显示成别的星（BALDRICK PRIME）、无连线 | settingsHash 决定星球身份 → 模板改 BICEP 自己的 `2995599666` + `waypoints=[180,7]` + owner 统一 2 |
| 3 | 物品解锁不可见 | 模板改为「目录行 + 库存行成对」注入 |
| 4 | `hd2proxy engine --profile X` 直接 usage error | `__main__.main()` 对 engine/selftest/gate 整体转发（argparse REMAINDER 不吞 `--` 参数） |
| 5 | 三连验证 Status 检查 400（`Accept-Language` 缺失） | `verify._tls_get` 补真实客户端语言/内容头 |
| 6 | 变种模板在人类星被阵营过滤 | 模板改走 `planet_effects` 原始通道；靶星必须「有战役可点」 |

**还原**：停引擎 → `uninstall`（hosts −1 行、`certutil -delstore` rc=0、回读干净）→
清理研究线遗留 `# variant-mod` 行（本工具只认 `# hd2proxy`）→ 最终 hosts 域名行 0、证书存储匹配 0、
无残留监听；hosts 备份留 2 份。

**已知限制（记入 docs/ACCEPTANCE-M4.md §5）**：抓包钩子保存的是**改写前**原始响应，
改写证据以 `logs/proxy.log` 的 `REWRITE*` 行 + 游戏内观察为准（v0.2 可加 post-rewrite 副本）；
`Mission/Session` 重连仍返回 8012016（研究线定证，v0.1 不承诺）。

**耗时校准**：M4 实际约 **75 分钟**（21:50→23:05），其中我这边操作/排查约 20 分钟、
游戏内验证与等待约 55 分钟（3 轮复核 + 1 次 UAC 安装/还原），与 §5.1「需你开游戏、wall-clock 取决于你」一致。

---

## 14. M5 打包发布记录（2026-11-16）

**一句话**：PyInstaller onedir 打包 + 干净路径验证 + GitHub Release `v0.1.0-alpha.1`
（alpha：6 项能力已实机验证，但更多环境/游戏更新后的稳定性待观察）。

| 项 | 结果 |
|---|---|
| 版本 | 显示 `0.1.0-alpha.1`（`__version__`）；PEP 440 元数据 `0.1.0a1`（pyproject） |
| 打包 | PyInstaller 6.16 onedir；`dist/hd2proxy/hd2proxy.exe` + `_internal/` + 可编辑 `data/` |
| 冻结适配 | `engine/paths.py` 识别 `sys.frozen`：优先 exe 旁 `data/`，否则 `_MEIPASS/data`；`cmd_engine` 冻结时在进程内调 `server.main`；`selftest/gate` 明确提示「源码树工具，打包版不含」 |
| 产物 | `hd2proxy-toolkit-v0.1.0-alpha.1-windows-x64.zip`（约 14.8 MB）+ `SHA256SUMS.txt` |
| 构建工具 | `tools/build_dist.py`：构建 → 打包后 exe 冒烟（`--version`/`info`/`preview`）→ zip/SHA256 → 解压到临时目录跑 `preview`（干净路径验证）→ 可选 `--test-area` 同步测试区 |
| 测试区 | `tools/sync_release_area.py`：把 release 资产同步到专门的产物测试区（`current/` 解包最新版、`artifacts/` 放 zip+sums+notes、`archive/` 留历史版本）；**默认取 GitHub Release 资产**，保证与用户下载物逐字节一致（重打包 zip 会因时间戳改变哈希） |
| 冒烟 | 打包 exe `--version` / `info` / `preview` 全 OK；GUI 进程可启动；`engine --help` 正常 |
| Release | tag `v0.1.0-alpha.1`（prerelease）+ zip + SHA256SUMS + Release Notes（`docs/RELEASE-v0.1.0-alpha.1.md`） |
| 文档 | README 增加「下载 / 快速开始（alpha）」；CHANGELOG.md；ARCHITECTURE §12 打包与分发 |

**构建期间修掉的工具问题**（都不影响产品代码）：
1. 冒烟断言用中文串在管道里被 cp936 编码破坏 → 改 ASCII 稳定串 + 子进程 UTF-8 env；
2. `make_archive` 的 base 名带版本点号，`Path.with_suffix` 误裁 → 用返回值；
3. zip 里数据在 `_internal/data`，用户看不到 → 构建时把 `data/` 再铺一份到 exe 旁（便携可改），
   干净路径验证改用 exe 旁 `data/`。

### 14.1 alpha.2 修复（2026-11-17，用户报「release exe 双击自动退出、没有 GUI」）

- 根因：`hd2proxy.exe` 是控制台 CLI，双击（无参数）→ 打印帮助后 `exit 2`，控制台立即关闭；
  GUI 本身正常（`hd2proxy.exe gui` 实测窗口存活），属发布 UX 设计问题。
- 修复：① 无参数默认打开 GUI；② 新增 windowed 的 `hd2proxy-gui.exe`（无控制台，双击即用）；
  ③ 打包改为单 bundle 双 exe（共用 `_internal`），冒烟新增「两个 GUI 入口存活 + 窗口标题」与
  「无参数打开 GUI」回归断言。
- 实测（打包后 exe，DSH computer use 实际打开+操作）：`hd2proxy-gui.exe` 窗口正常、无控制台；
  切「战况改写」页渲染正常；点「离线预演」弹只读结果窗口；`hd2proxy.exe` 无参数也打开 GUI。
  截图：`research/screenshots/alpha2-gui-status.png` / `alpha2-gui-preview.png` / `alpha2-cli-noargs-gui.png`。
- 发布：`v0.1.0-alpha.2`（prerelease），alpha.1 在 Release Notes 顶部标注被取代。

### 14.2 alpha.3 修复（2026-11-17，用户报「点启动引擎出现第二个 GUI 窗口」）

- 根因：`gui/client.py` 按源码模式拼 CLI 命令：`engine_argv` 用
  `[sys.executable, legacy_proxy.py, --profile …]`，`run_cli` 用
  `[sys.executable, "-m", "hd2proxy", …]`；冻结后 `sys.executable` 是 `hd2proxy-gui.exe`，
  子进程变成「GUI exe + 非法参数」→ windowed exe 弹 PyInstaller 错误对话框（第二个窗口），
  且证书/安装/验证/启动引擎等按钮在打包版全部失效（本会话最小冻结探针验证）。
- 修复：`client._bundle_cli_exe()` + `cli_argv()`：冻结时改用同目录 `hd2proxy.exe` 跑
  `engine` / `certs renew` / `install` / `verify` 等子命令；源码模式保持 `python -m hd2proxy`。
- 回归测试：冻结/源码两种模式的 `cli_argv`、`engine_argv` 断言。
- 打包 GUI 逐页实测补充修复：①冻结子进程 GBK 输出解码回退（GUI 里 CLI 结果不再乱码）；②冻结版 logs/runtime 落状态目录 + 「打开日志」友好提示（308 passed）。

### 14.3 alpha.4 修复（2026-11-17，alpha.3 打包 GUI 实测的 3 个小问题）

- 「切换直通」只改引擎运行时状态、不写回 profile → 随后「应用配置」按旧 profile 把直通恢复
  （看起来像开关失灵）。修复：切换成功即写回内存 profile + `mark_dirty`。
- 打包版证书签发提示写 `python -m hd2proxy install …`（打包版照抄必失败）→ 冻结模式改 `hd2proxy.exe …`。
- 安装/还原计划、离线预演、证书弹窗长行不换行、左右被裁 → `wrap="word"` + 从开头显示。
- 附：`tools/sign_local.ps1` 本机自签代码签名（CurrentUser 受信任根/发布者 + 签 exe），
  `build_dist.py` 支持 `HD2PROXY_SIGN=1` 自动签名；详见 `docs/SIGNING-LOCAL.md`。
- 回归测试 +3 → **311 passed**（当时）。

### 14.4 版本规则落实（2026-11-17，用户定的发版规则）

**规则**（完整版见 `docs/VERSIONING.md`）：

| 变更 | 版本位 | 例 |
|---|---|---|
| 功能/能力更新（新能力/新页面/新模板/新子命令/行为语义变） | `X.Y.Z` 变，阶段重置 `alpha.1` | `0.1.0-alpha.4` → `0.2.0-alpha.1` |
| 只修 bug（不改功能/行为） | 同 `X.Y.Z`，`alpha.N` 或 `rc.N` +1 | `0.1.0-alpha.4` → `0.1.0-alpha.5` |
| 用户实机验收通过 → 发布候选 | `alpha` → `rc.1` | `0.1.0-alpha.5` → `0.1.0-rc.1` |
| 功能完成、bug 收敛 | 去后缀发 GA | `0.1.0-rc.2` → `0.1.0` |

阶段语义：**alpha** = 新功能刚落地、可能 bug 多；**rc** = 用户实机验证过、已知 bug 不影响正常使用
（此后只修 bug）；**GA** = 功能与 bug 都收敛（首个 GA 目标 `1.0.0`）。

**已合规模拟核**：alpha.1–alpha.4 的核心版本都是 `0.1.0`，alpha.2/3/4 均为只修 bug → 符合规则。

**工具化**：

- `src/hd2proxy/versioning.py`：解析/校验/PEP 440 映射/阶段迁移（纯逻辑，27 条单测）。
- `tools/bump_version.py`：按规则算下一版并同时改 `__version__` 与 `pyproject`，打印后续待办
  （`fix` / `promote-rc` / `ga` / `feature --major|minor|patch`；`--dry-run` 只看结果）。
- `tools/check_version.py` + 门禁第 0 步：校验 `__version__` 格式 ↔ `pyproject` PEP 440 ↔
  CHANGELOG 条目 ↔ 已打 tag 的 `docs/RELEASE-v*.md`（4 条任一不符 → GATE=FAIL）。

**发版流程（此后固定）**：

1. `python tools/bump_version.py <fix|promote-rc|ga|feature …>`
2. 补 CHANGELOG 条目 + `docs/RELEASE-v<ver>.md`
3. `python tools/check_gate.py`（含版本一致性）→ 提交/推送 → CI 绿
4. `HD2PROXY_SIGN=1 python tools/build_dist.py`（本地签名 + 冒烟 + zip/SHA256）
5. `gh release create v<ver> --prerelease …`（GA 才去掉 `--prerelease`）→ 核对资产 digest
6. `python tools/sync_release_area.py --area <测试区>` 更新 release 产物测试区

### 14.5 alpha.5 修复（2026-11-17，「变种」里虫族少了 Caustic / Noxious）

- 用户报：变种界面虫族只有 5 个，缺 **Caustic Strain** / **Noxious Strain**；要求顺手排查其他漏项。
- 根因两层：① `caustic_strain`（1430/1431）在 `items` 里但**没进 `groups`**，界面只渲染分组 → 等于隐藏；
  ② Noxious 完全没收录（源变种目录冻结在 2026-11-01，它 10-29 才加入游戏）。
- 取证：**两个官方端点都接受未鉴权直连** —— `GET /api/WarSeason/GalacticWarEffects`（315 条）与
  `GET /api/WarSeason/801/Status`（161 条 `planetActiveEffects`，需 `Accept-Language`）。
  tag↔mechanic 用**线上星球共现**判定：1433/1434 星球集合完全相同（8 颗），1432 只占其中 6 颗 → 排除。
  presence 名用当前 build 明文表 `murmur32` 反解，locid → strings 得 `NOXIOUS STRAIN` / `CAUSTIC STRAIN`。
- 修复：虫族组 5 → **7**（腐蚀变种 [1430,1431] / 毒瘴变种 [1434,1433]）；`caustic_strain` 保留为别名
  （老 profile 不用改）；`tools/gen_catalogs.py` 增加覆盖层 `data/sources/variant_overlay.json`，
  并**把引擎目录 `data/legacy/variant_catalog.json` 纳入生成**（此前手工拷贝，正是漂移来源）。
- 排查结论：按 wiki Combatant Forces 全量对照，**除这两条外无其他漏项**（机器人 6/6、光能者 4/4、
  超级地球 1/1）；`TANK SURGE` 等线上无对应 effect ⇒ 本通道注入不了，非漏项。
  完整清单见 `docs/VARIANT-INVENTORY-2026-11-17.md`。
- 回归测试 +24 → **364 passed**。

---


### 14.6 v0.1.1-alpha.1（2026-11-17，「物品与战备」只有 id 没有名字）

- 用户报：物品与战备页所有物品只显示 `mixId · attachment`，无法辨认；要求先显示**内部名**
  （本地化译名暂不做，工作量太大）。这是**小规模功能更新** ⇒ `0.1.0` → `0.1.1`，阶段重置 `alpha.1`。
- 名字来源（2026-11-17 定位）：
  - **附件**：服务端 `/api/Progression/items` 行的 `itemId` = 武器改装选项 id；选项内部名在
    `generated_weapon_customization_settings` 的解析产物
    `repo-datamined/refs/weapon-customization-options-26251122.json`（342 条）。1404/1455 附件行命中。
  - **外观**：目录行 `itemId` = 外观表行 id（已有 `armor_rows_parsed.json` 的 names）。
  - **武器 / 战备**：目录 id 与本地表（weapon keys、entity index、stratagem settings）均无已知映射
    （试过 murmur32/djb2/crc32/fnv 与各类内部名变体，0 命中）⇒ 留空并在界面标「内部名未解」。
- 落地：新增仓库内数据源 `data/sources/progression_item_catalog.json`（3020 行紧凑索引，含抓包 sha256）；
  `tools/gen_catalogs.py` 增 `enrich_item_names()`（附件/外观补名，只填空缺不覆盖）；
  `gui/catalogs.py` 统一 `item_display_label()`（有名字显示名字，无名字显示类别 +「内部名未解」）；
  `data/catalogs/items.json` 每条加 `catalog_category`（有名字的再加 `name_source`）。
- 覆盖：**1520 / 1671** 有名字（原 391），搜索框可按内部名搜（`reddot` / `vertical grip`）。
- 回归测试 +9 → **373 passed**（`tests/unit/test_item_names.py`）。

---

### 14.7 v0.1.1-alpha.2（2026-11-17，武器内部名走 dlbin 只读路线）

- 用户提示：武器/战备名称可以走**之前的 dlbin 路线**（更新后被 EAC 拦的是**写**，**读**仍然可用；
  本机有 hd2-datamined 仓库与解包密钥）。
- 定位（✓ 定证）：`generated_entities.dl_bin` 的 `LoadoutEntryComponentData`（块 `0x4F2CF417`，
  199 行 × 32 B）行 `+0x00` = 服务端目录行的 `itemId`；该行所属实体在 `EncyclopediaEntryComponentData`
  里有内部名。用 `refs/entity-locid-names.json`（build 26088801）对实体哈希取名字：
  **191/199 行有名字、177 个唯一 itemId**（`Veto` / `Gallant` / `Shear` / `Smokescreen` / `Pineapple`…）。
- 落地：新增 `tools/extract_item_names.py`（只读；几何自证失败即报错）→ `data/sources/item_names_derived.json`；
  `tools/gen_catalogs.py` 增加第 4 条名字规则 `loadout-entity`（只填空缺、不覆盖）。
  覆盖 **1520 → 1544 / 1671**。
- **战备仍无解**：cat 11 的解锁 itemId 在 55 张表 + 实体库里 u32/u64 全扫 0 命中（仅 9 处偶然），
  客户端靠服务端/商店响应关联；当前抓包没有 store/season 响应 ⇒ 30 条战备保持「内部名未解」。
  下一步：用本产品的抓包功能抓一次战备/商店页面，再做 itemId→locid→名字的映射。
- 单测 373 → **375 passed**。

---

### 14.8 v0.1.1-alpha.3（2026-11-17，四个 tab 不筛选类别）

- 用户报：「外观」里出现 `TUBE REDDOT 1,5x`、`Vertical Grip` 等明显属于附件的东西。
- 根因：`InventoryPage._build_edit_tab` 四个 tab 都用 `catalogs.search_items("")` 填全量列表，
  只改标题 —— 列表内容完全相同（不是数据分类错，是界面没用 `category` 字段）。
- 修复：`Catalogs.search_items(text, limit, category=...)` + `item_category()`；
  四个 tab 按 `weapon/attachment/cosmetic/stratagem` 过滤（武器 24 / 附件 1176 / 外观 426 / 战备 30）；
  搜索带类别过滤；`_add_item` 加兜底：异类条目拒绝并提示正确类别。
- 15 条 `category=None` 的混类探测条目（`inventory_probe_inject.json`）不进四个 tab，
  只在「目录追加」里出现。
- 回归测试 +4 → **379 passed**（tab 只显示本类 / 搜索不越界 / 跨类拒绝 / 数据层分类保证）。

---

### 14.9 v0.1.1-alpha.4（2026-11-17，附件列表只显示 80 条）

- 用户报：附件 tab 只有 80 项，而 `items.json` 里有 1176 条附件。
- 根因：`Catalogs.search_items()` 默认 `limit=80`、关键词搜索 `limit=200` —— 数据没丢，
  是列表截断；计数标签显示 `80/80` 进一步让人误以为只有 80 条；列表上方搜索框也只在前 80/200 条里过滤。
- 修复：`search_items(limit=None)` = 不截断；四个 tab + 目录追加都装全量
  （附件 1176 / 外观 426 / 武器 24 / 战备 30 / 目录追加 1671）；计数显示真实总数；
  列表下方提示改为「本类共 N 条；上方搜索框在全部条目里过滤」。
- 回归测试 +1 → **380 passed**（列表条目数 == 目录总数；提示行含总数）。

---

### 14.10 v0.2.0-alpha.1（2026-11-17，附件按武器筛选 + 一键解锁整枪配件）

- 用户要求：附件 tab 改为两级 —— 一级只列「配件所属武器」，选中武器展开二级列出该武器配件；
  直接选中一级武器点「添加到库存」= 解锁该武器全部配件。
- 依据：附件解锁是「武器 × 附件」粒度（`docs/UNLOCK-MAP-2026-11-06.md`；目录行 `parentId` = 武器 mixId）。
- 数据补全：附件目录行从研究注入子集 1176 → 全量 **1455 / 57 把武器**（`items.json` 1671 → 1950），
  每条加 `parent_id` / `parent_name`（1411 已解）/ `option_id`；新增工具
  `tools/extract_catalog_index.py` 生成带 parent 的目录索引（3020 行）。
- GUI：`_build_attachment_tab` 两级 SearchList；一级点「添加到库存」= 批量加该武器全部 mixId（去重 +
  报告新增/已存在）；二级选中则只加一条；关键词跨武器搜配件名（标签带武器名）。
- 回归测试 380 → **386 passed**。

---

### 14.11 v0.2.0-alpha.2（2026-11-17，Shear 等目录缺失武器解锁不生效）

- 用户报：Shear（`2112173638`）加进库存后游戏里不出现，对照 Bolt Pistol / Melta Mine 正常。
- 根因：**库存行必须与目录行成对注入**。前两者在服务端 `/api/Progression/items` 目录里本来就有；
  Shear / P-41 Ombudsman / SG-8F Punisher Fire of Liberty 目录里没有，只注库存行客户端不显示，
  还需要 `items.add [{id, template}]` 克隆同族模板补一条目录行。而四个 tab 的「添加到库存」
  只写库存行（`目录追加` tab 才写目录行）→ 按普通物品方式添加时目录行漏掉；日志里一条
  `ITEMS REWRITE` 都没有可证。
- 修复：加库存时按 `items.json` 的 `unlock_template` 自动配对目录行；移除时对称撤回；
  `目录追加` tab 选中这类物品自动带模板；打开页面时自愈老 profile（幂等）。
- 数据：新增 `data/sources/unreleased_items.json`（3 把武器的模板配对，M4 实机验证值），
  `tools/gen_catalogs.py` 校验「模板行在目录快照里」后写入 `unlock_template`。
- 引擎级离线预演验证（真实抓包 3020 行）：写 `{"id":2112173638,"template":3866352840}` →
  「物品目录补 itemId 2112173638（克隆模板 3866352840），1 处新增」。
- 回归测试 386 → **394 passed**。

---

### 14.12 v0.2.0-alpha.3（2026-11-17，战况改写页：小列表改下拉 + 选中表自适应）

- 用户反馈：变种词条/全局效果/星球词条只有 3 行高；下方「选中…」表固定 2 行，5 个变种生效只显示 2 个。
- 改动：新增通用控件 `PickDropdown`（一行高、可搜索、点开原生下拉）；三处列表替换；
  `RowEditor` 加 `autosize`（2–8 行按数据自适应）。
- GUI 实拍：变种下拉完整列出 18 条（含阵营前缀），效果 312 条可展开；表格按行数增高。
- 回归测试 394 → **399 passed**（只动显示与交互，版本位不变）。

---

### 14.13 v0.2.0-alpha.4（2026-11-17，光能者分组改名「卡牌」→「光能者」）

- 用户追问：变种选择器里 Illuminate 组为什么叫「卡牌」。追查：名字来自外部 mod
  「全变种 Quanbianzhong 10.00」目录（note 明写沿用其命名），研究仓与本仓库原样透传，
  GUI 直接显示 `groups[].name`；这 4 条变种 `meta.faction` 全是 illuminate，组名与阵营不符。
- 修复：覆盖层 `groups` 规则新增 `rename`（原组名存 `source_name`、数量后缀按成员数重算），
  显示改为「光能者 4」；文档阵营列同步修正。
- 回归测试 399 → **402 passed**。

---

### 15.1 v0.3.0-alpha.1（2026-11-17，端口诊断 P0：预检 / 换监听地址 / 系统自检 / 游戏守卫）

- 依据：第三方 `variant_mod 1.26` 侦察报告（`docs/THIRDPARTY-VARIANTOM-1.26-2026-11-17.md`）——
  引擎侧独占绑定/5s 重试/BIND FAIL 占用者已继承，本版补面板层。
- 新增：启动前 443/8080/17897 端口预检（三态 + 占用者名/PID/路径 + 通配提示）；
  「换监听地址」对话框（真实网卡候选 + 占用状态 + 推荐）；`engine/diagnostics.py`
  系统自检（端口/hosts 四态/证书/游戏）；总览页红字摘要 + 自检弹窗；游戏运行守卫。
- 端口探测升级：netstat 查 IPv4+IPv6、占用者带路径、SO_EXCLUSIVEADDRUSE 试绑、PID 排除自家引擎。
- 回归测试 402 → **423 passed**。

---

## 附：本轮不做

- 星图可视化大画布、多人同步、服务端写入（幻影战局不落账，交接档 §6.1 已定证）
- L2 改装槽「真正生效」（已否证：只是 L0 回显）
- `Mission/Session` 边界攻关（交接档 backlog P1，独立课题）
