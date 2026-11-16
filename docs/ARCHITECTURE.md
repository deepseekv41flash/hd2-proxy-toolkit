# 架构（M1）

> 目标：把研究线的「1846 行单文件脚本」拆成**可测试、可热更新、可多入口**的产品骨架。
> 一句话：**引擎（写什么） / 配置面（改什么） / 控制面（谁指挥） / 系统面（装到哪）** 四层分离。

## 1. 模块地图

```
src/hd2proxy/
├─ __main__.py          CLI：engine / install / uninstall / verify / status / certs / profiles / migrate …
└─ engine/
   ├─ server.py         TLS MITM 服务 + 引擎入口（main）；EngineContext 持有运行期上下文
   ├─ paths.py          全部路径（仓库/数据/状态/证书/运行期），环境变量可覆盖
   ├─ logutil.py        日志（proxy.log / audit.log / 限流 / 轮转）
   ├─ httpio.py         HTTP/1.1 最小读写（head/headers/dechunk/gunzip）
   ├─ catalog.py        变种目录与阵营逻辑（只用于过滤）
   ├─ model.py          Mod 状态机 + resolve_plan + rewrite_status
   ├─ upstream.py       DoH 解析（绕 hosts）+ 上游地址
   ├─ certs.py          会话证书：签发 / 状态 / 自动续期 / preflight / CRL 服务
   ├─ config.py         schema v2：校验 / 归一化 / profile 存取 / 旧配置迁移 / → EngineSpec
   ├─ spec.py           EngineSpec（一次运行的全部输入；None = 研究线旧行为）
   ├─ control.py        本地控制面（127.0.0.1 + token）
   ├─ verify.py         三连验收（TLS 握手 / CRL / Status 回执）
   ├─ hosts.py          hosts 读写（marker 行、原子写、备份、编码/行尾保持）
   ├─ sysprobe.py       系统探针（网卡 IP/端口占用/游戏进程/证书存储/管理员）
   ├─ elevation.py      UAC 自提升（ShellExecuteEx "runas"）
   ├─ installer.py      安装/还原编排（先证书后 hosts；失败回读系统状态）
   ├─ legacy_proxy.py   兼容入口（脚本方式启动 → server.main）
   └─ hooks/            warinfo / status / inventory / items / customize / capture
```

## 2. 数据流（一次 Status 请求）

```
游戏 → TLS → server.Proxy.handle
   ├─ 读请求 → capture.capture_request()           （可选，白名单）
   ├─ 建上游连接（upstream.doh_resolve，绕 hosts）
   ├─ 读响应（必要时 dechunk / gunzip）
   ├─ 钩子按固定顺序执行（**顺序有语义**）：
   │    warinfo（星球身份）→ status（战况）→ inventory → items → customize → capture
   ├─ 若 body 有改动：重写 Content-Length / 去掉 Content-Encoding
   └─ 回给游戏
```

每个钩子都支持两种配置来源：

| 来源 | 何时用 | 行为 |
|---|---|---|
| `spec=<dict>` | 产品模式（profile v2）/ 单元测试 | 显式配置，确定性 |
| `spec=None` | 研究线兼容模式 | 读 `HD2_GWE_EXTRA` 环境变量 / `runtime/*.json` |

> 黄金回归：`tests/fixtures/golden/`（由 M0 实现生成）+ `tests/unit/test_hooks.py`
> 同时验证这两条路径，重构不允许改变输出。

## 3. 配置面（schema v2）

单一 profile JSON，见 `config.DEFAULT_PROFILE`。要点：

- `proxy`：host / listen_ip / port / crl_port / control_port / passthrough / verbose
- `cert`：days（≤2 硬上限）/ min_remaining_hours / auto_renew
- `warinfo`：`settings_hash` / `planet_infos`
- `status`：`variants[{name, planets}]` / `trials[]` / `planet_effects` / `globalEffects` /
  `campaigns` / `attacks` / `events` / `regions` / `planet_nodes` / `owner`
- `inventory`：`weapons` / `attachments` / `cosmetics` / `stratagems` / `probe` / `remove` /
  `customization`
- `items`：`template` / `add`
- `capture`：`enabled` / `dir` / `paths` / `req_paths` / `max_bytes` / `planet_settings`
- `experimental.customize`：L2 改装（实测送达不生效，默认关）

校验规则：**errors 阻止保存/启动**（schema、回环监听、证书天数、星球号范围…），
未知键与语义提醒进 `warnings`。`to_engine_spec()` 把 profile 归一化成引擎唯一消费的 `EngineSpec`。

> v0.1 的「变种」是**显式星球**（`variants[].planets`）：研究线的「自动跟随当前星球 +
> 粘性 3 颗」逻辑保留在 legacy 路径里，但产品面不做隐式行为（GUI 让用户选星球）。

## 4. 控制面（127.0.0.1 + token）

引擎启动后写 `%LOCALAPPDATA%/HD2ProxyStudio/engine.json`（pid/port/url/token），
GUI / CLI / 脚本通过它发现引擎。所有请求要求 `X-HD2-Token`（或 `?token=`），常量时间比较。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/healthz` | 存活 |
| GET | `/status` | 运行期快照（模式/profile/监听/证书/统计/最近改写） |
| GET | `/events` | 最近改写事件（环形缓冲，最多 200） |
| GET | `/config` | 当前 profile（legacy 模式下返回 `mode: legacy`） |
| PUT | `/config` | 校验 + 落盘 + **热应用**（不重启、不断开游戏连接） |
| GET | `/profiles` | 本机 profile 列表 |
| POST | `/profiles/activate` | 切换 profile（热应用） |
| POST | `/reload` | 从文件重载 |
| POST | `/verify` | 三连验收 |
| POST | `/passthrough` | 直通/改写切换 |
| POST | `/capture` | 抓包开关 |
| POST | `/shutdown` | 优雅退出 |

> 本机 HTTP 请求**必须绕过系统代理**（Windows 注册表代理会劫持 127.0.0.1）：
> `verify.local_opener()` 与 CLI `_api` 都显式禁用代理。

## 5. 系统面：安装 / 还原

契约（`installer.py`）：

1. 父进程组装 `InstallPlan`（host / listen_ip / cert_dir / 指纹 / scope）；
2. `--dry-run` 只打印 `plan_steps` + `verify_system_state`，**不改任何系统状态**；
3. 真安装：先导证书、后改 hosts（避免「hosts 已指向代理但证书未信任」的窗口期）；
4. 非管理员：写临时 plan JSON → UAC 提权重跑 `install --plan <json> --elevated`；
5. 成败**以回读系统状态为准**（hosts marker 行 + certutil -store），不只看子进程退出码；
6. 还原只撤 hosts 行 + 删证书信任，**不删证书文件**（由调用方按数据目录策略清理）。

安全边界（沿用研究线）：单域名白名单、仅本机来源、SAN 单域名、有效期 ≤2 天、
签完删 CA 私钥、本地 CRL、默认不落请求/响应体。

## 6. 测试与门禁

| 层 | 位置 | 说明 |
|---|---|---|
| 钩子等价性 | `tests/unit/test_hooks.py` | 与 M0 golden 逐字段比对（spec 与 legacy 两条路径） |
| 配置面 | `tests/unit/test_config.py` | 校验/归一化/迁移/→spec 映射 |
| 证书 | `tests/unit/test_certs.py` | ca 签发/状态/自动续期/preflight/多余私钥拒绝 |
| 系统面 | `tests/unit/test_hosts.py` / `test_installer.py` / `test_sysprobe.py` | 临时 hosts + certutil 桩 + 提权注入点，不碰系统 |
| 整链路 | `tests/unit/test_engine_flow.py` | 起引擎→控制面→verify→热重载→直通→退出；install dry-run |
| 线上语义 | `tests/selftest*.py` | 5 个脚本式集成自检（与 M0 相同断言） |

门禁：`python tools/check_gate.py` = 语法 + 绝对路径 + pytest + 5 个脚本自检。


## 7. GUI 层（M2）

```
src/hd2proxy/gui/
├─ app.py        App 壳：顶栏（profile 保存/应用 + 状态 pill）/ 左侧 5 页导航 / 底部状态行；
│                profile 在内存中编辑，改完点「应用配置」→ PUT /config 热更新（引擎未运行则保存文件）
├─ theme.py      调色板/字体/ttk 样式 + 小部件工厂（card/section/table/pill/button/ScrollText）
├─ widgets.py    SearchList（搜索+列表）/ PlanetPicker（星球下拉）/ RowEditor（可删行表）
├─ catalogs.py   只读数据目录封装（变种/战备/效果/星球/物品/build），缺文件降级不崩
├─ client.py     EngineClient：engine.json 发现 + token API（显式绕系统代理）+ 引擎子进程管理与日志环
└─ pages/        overview / status_page / inventory / capture / settings
```

要点：

- **GUI 只是控制面客户端**：不碰 hosts/证书/游戏；安装/还原通过 CLI 子进程（dry-run 展示计划），
  引擎是独立进程 —— 关窗不会打断游戏会话。
- **profile 是唯一数据面**：页面只改内存里的 schema v2 dict + `mark_dirty()`，统一「保存/应用」；
  热更新走 PUT /config，无需重启代理。
- **轮询在后台线程**（0.6s），Tk 主线程只渲染；窗口销毁时停轮询（避免 Tk 状态异常）。
- 截图工具 `tools/gui_smoke.py`：起真引擎 + 假上游 → 逐页截图，是 M2 的验收证据。

M2 遗留打磨项（不影响使用）：战况页 6 张卡在 780 高度下需要纵向滚动（已可滚）；
物品名称依赖 catalogs（约 391/1671 有名字，其余显示类别）；`settingsHash` 生态借用需先导入 live warinfo。
