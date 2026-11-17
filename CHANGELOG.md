# Changelog

本项目遵循「里程碑 + 语义化版本」：`0.x` 阶段接口/数据结构可能变动，发布 alpha/beta 时显式标注。

> **版本规则（2026-11-17 起）**：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动
> `alpha.N` / `rc.N`。alpha = 新功能阶段（可能有 bug），rc = 用户实机验证过（只修 bug），
> GA = 功能与 bug 收敛。完整规则见 [docs/VERSIONING.md](docs/VERSIONING.md)。

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
