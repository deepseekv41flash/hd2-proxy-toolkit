# Changelog

本项目遵循「里程碑 + 语义化版本」：`0.x` 阶段接口/数据结构可能变动，发布 alpha/beta 时显式标注。

> **版本规则（2026-11-17 起）**：前三位 `X.Y.Z` 只在功能/能力变化时动；只修 bug 只动
> `alpha.N` / `rc.N`。alpha = 新功能阶段（可能有 bug），rc = 用户实机验证过（只修 bug），
> GA = 功能与 bug 收敛。完整规则见 [docs/VERSIONING.md](docs/VERSIONING.md)。

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
