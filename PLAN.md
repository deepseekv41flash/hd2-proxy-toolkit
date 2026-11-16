# HD2 战况代理工坊 —— 开发计划 v0.2

> 起草 2026-11-16 ｜ 状态：**已过技术选型，待你点头开工 M0**
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

| M | 内容 | 门禁（贴原始输出） | 估时 |
|---|---|---|---|
| **M0 骨架** | 建仓、目录、搬 engine 源码（先原样落地）、5 个 selftest 与证书工具适配、catalogs 生成 | 5 个 selftest 全 PASS；`py_compile` 干净；无旧路径硬编码 | 0.5 天 |
| **M1 引擎+控制面** | 模块化拆分、schema v2、热重载、控制 API、install/uninstall（UAC 自提升）、自动续证、CRL | 离线 pytest 全绿；`install → passthrough 起 → verify 三连 → stop → uninstall` 本机全通 | 1.5 天 |
| **M2 GUI 骨架** | Tk 壳 + 5 页 + 状态轮询 + schema 驱动表单 + 星球/效果搜索选择器（以原型为基线） | 5 页绑真实引擎状态；切换页无卡顿；截图 | 1.5 天 |
| **M3 6 项能力** | 6 张能力卡/模板 + 离线预演 + 扩展入口（延后项折叠标注） | 每项 ≥1 条离线用例 + 预演截图；模板填入后增量符合预期 | 1 天 |
| **M4 实机验收** | 进游戏逐项验证、修现场问题、记录日志证据 | 验收清单逐项 PASS（**需你开游戏配合**） | 0.5 天 |
| **M5 打包发布** | PyInstaller、README/使用说明/截图、v0.1.0 tag（远端按你意见再定） | 干净路径解压即用；安装→启动→验收→还原 全流程跑通 | 0.5 天 |

关键路径：M0 → M1 →（M2/M3 可部分并行）→ M4 → M5。M4 必须你在场。

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

## 附：本轮不做

- 星图可视化大画布、多人同步、服务端写入（幻影战局不落账，交接档 §6.1 已定证）
- L2 改装槽「真正生效」（已否证：只是 L0 回显）
- `Mission/Session` 边界攻关（交接档 backlog P1，独立课题）
