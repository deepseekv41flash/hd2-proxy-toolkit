# Changelog

本项目遵循「里程碑 + 语义化版本」：`0.x` 阶段接口/数据结构可能变动，发布 alpha/beta 时显式标注。

> **版本规则（2026-11-17 起）**：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动
> `alpha.N` / `rc.N`。alpha = 新功能阶段（可能有 bug），rc = 用户实机验证过（只修 bug），
> GA = 功能与 bug 收敛。完整规则见 [docs/VERSIONING.md](docs/VERSIONING.md)。

## 未发布（开发中）

- 新增版本规则落地：`docs/VERSIONING.md`、`src/hd2proxy/versioning.py`、
  `tools/bump_version.py`（按规则算下一版并改 `__version__`/pyproject）、
  `tools/check_version.py`（版本一致性；门禁新增第 0 步）。
- 新增 `tools/sync_release_area.py`：把 release 产物同步到专用测试区（`current/` 解包最新版、
  `artifacts/` 放当前版本资产、`archive/` 留历史）；默认取 GitHub Release 资产，保证与用户
  下载物逐字节一致；`build_dist.py` 支持 `--test-area` / `HD2PROXY_TEST_AREA` 构建后自动同步。
- 单测 311 → **338**（新增版本规则 27 条）。

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
