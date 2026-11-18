# hd2-proxy-toolkit —— HD2 本机代理工具箱

《HELLDIVERS 2》**本机 MITM 代理**的成品化实现：在本地改写客户端收到的战况接口响应
（`Status` / `warinfo` / `Progression/*`），**不碰游戏文件、不进进程内存**。

- 研究线与全部证据留档：[hd2-network-proxy](https://github.com/deepseekv41flash/hd2-network-proxy)
- 本仓库只放**产品代码**：代理引擎 + GUI + 配置面 + 打包，研究仓只读引用。
- 开发计划：[PLAN.md](PLAN.md) ｜ 代码来源与哈希：[docs/PROVENANCE.md](docs/PROVENANCE.md)
- GUI 选型实测（稳定性/资源占用）：[research/TECH-STACK-DECISION.md](research/TECH-STACK-DECISION.md)

> **当前状态：v0.4.1-alpha.1 已发布（2026-11-18，M0–M5 完成）** —— 引擎模块化 + 配置面/控制面/安装还原/证书自动续期/三连验收
> + **Tk GUI 五页** + **6 项能力模板 + 离线预演** + **6 项能力实机逐项验收通过**
> （安装→游戏内验证→还原全链路，见 [docs/ACCEPTANCE-M4.md](docs/ACCEPTANCE-M4.md)），
> **472 个单元测试 + 5 个离线自检全绿**；已打包发布 `v0.4.1-alpha.1`（见下方「下载」）。
> 0.3.0 起「启动引擎」会先做 **443/8080/17897 端口预检**（冲突列占用者、可换监听地址），总览页新增**系统自检**（端口 / hosts / 证书 / 游戏进程）；
> alpha.2 修掉现场检查弹控制台窗 + 切总览卡顿（子进程隐藏窗口 / 一条 `netstat -ano` / 诊断节流）；
> alpha.3 修掉「续期证书后游戏报 Error 60」：证书信任状态进自检/红字，GUI 新增「安装 / 修复（UAC）」，续期后自动引导导入信任；
> alpha.1(0.4.0) 把**服务端物品目录 3020 行全量**做进产品：`items.json` 1950 → **3062 条**、名字 1821 → **2191**、
> 标注**空号默认拥有 55 项**，物品页新增只读 **「目录总览」** tab（汇总 / 类别筛选 / 默认已有 · 目录缺标记）。
> alpha.1(0.4.1) 物品解锁加 **「清空全部已添加」**：一键撤回四类库存 + 目录追加（附件批量添加后的批量移除）。
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

## 下载（v0.4.1-alpha.1）

> **预览版（alpha）**：M4 已逐项实机验证 6 项能力，但更多机型/网络环境/游戏更新后的
> 全流程稳定性还需要时间验证，先以 alpha 发布。完整说明见
> [Release Notes](docs/RELEASE-v0.4.1-alpha.1.md)。

- 下载：[GitHub Releases · v0.4.1-alpha.1](https://github.com/deepseekv41flash/hd2-proxy-toolkit/releases/tag/v0.4.1-alpha.1)
  （`hd2proxy-toolkit-v0.4.1-alpha.1-windows-x64.zip` + `SHA256SUMS.txt`）
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

:: 3. 安装（改 hosts + 信任本机 CA；需要一次 UAC）
hd2proxy.exe install --profile <你的 profile.json>
:: 4. 起代理（GUI 里也能起）
hd2proxy.exe engine --profile <你的 profile.json>
:: 5. 验完还原（hosts + 证书；需要一次 UAC）
hd2proxy.exe uninstall
```

> 安全边界：只改客户端收到的接口响应，不碰游戏文件、不进进程内存；单域名白名单 + 仅本机来源；
> 会话证书 ≤2 天、签完删 CA 私钥；详见下文「安全设计」。

## 现在能做什么

```bash
python -m pip install cryptography pytest   # 运行依赖 + 测试依赖
set PYTHONPATH=src                          # 源码树内使用（或 pip install -e .）
python tools/check_gate.py                  # 门禁：版本一致性 + 语法 + 路径 + 472 单测 + 5 个离线自检
```

自检全部离线（本机假上游 + 临时数据目录 + 临时证书），不需要游戏、不需要联网、不需要管理员。

M1 起也可以用 CLI 走完整流程（详细见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)）：

```bash
python -m hd2proxy gui                            # 打开图形界面（5 页）
python -m hd2proxy preview --profile <profile>    # 离线预演：不开游戏看会改什么（M3）
python -m hd2proxy info                        # 版本 / 路径 / 引擎是否在跑
python -m hd2proxy certs renew --days 1        # 签发会话证书（ca 模式，≤2 天）
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
| 4 | 物品解锁（武器/配件/外观 + 目录上架；附件按武器筛选 + 一键解锁整枪配件；**目录 3020 行全量只读总览**） | ✓✓ M4 实机 | 物品 · 各分类 +「目录总览」/「物品解锁」模板 |
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

## 目录结构

```
src/hd2proxy/engine/                    引擎（server / 钩子 / 配置 / 证书 / 安装 / 控制面 / 离线预演 preview.py）
src/hd2proxy/gui/                       Tk GUI：壳 + 5 页 + widgets + templates.py（能力模板）
src/hd2proxy/versioning.py               版本规则与 PEP 440 映射（docs/VERSIONING.md 的实现）
tests/unit/                             单元测试（472 条：钩子等价性 / 配置 / 证书 / 引擎整链路 / GUI / 预演 / 模板 / 变种目录 / 物品名 / 目录补全 / CLI）
tests/selftest*.py                      5 个脚本式离线自检（迁自研究线，仅改路径）
tools/run_selftests.py                  自检总入口（独立证书/数据目录，GATE 判定）
tools/check_gate.py                     门禁：版本一致性 + 语法 + 绝对路径 + pytest + 5 自检
tools/bump_version.py                   按版本规则算下一版本号并更新 __version__/pyproject
tools/check_version.py                  版本一致性检查（__version__ ↔ PEP 440 ↔ CHANGELOG ↔ Release Notes）
tools/extract_catalog_index.py           /api/Progression/items 抓包 → 紧凑索引（含附件 parent，供按武器分组）
tools/extract_item_names.py             dlbin 只读路线：LoadoutEntry 物品内部名（武器/投掷物/背包）→ data/sources
tools/gen_session_certs.py              会话证书签发（ca 模式，≤2 天硬上限）
tools/gen_catalogs.py                   数据目录生成（GUI + 引擎目录；包含服务端目录 3020 行补全/命名/默认标记）
tools/resolve_catalog_names.py          目录名字/类别解析快照生成（只读研究仓数据表；产物 data/sources/catalog_names_resolved.json）
tools/gui_smoke.py                      GUI 冒烟：起真引擎 + 假上游 → 五页截图（`--tabs` 逐 tab 截图）
tools/extract_store_season_layout.py    store/season 抓包 → 结构映射 + 无名行锚点对账（补名字研究用）
tools/sign_local.ps1                    本机自签代码签名（装当前用户信任库 + 签 exe，见 docs/SIGNING-LOCAL.md）
tools/sync_release_area.py              把打包产物同步到「release 产物测试区」（解包最新版 + 归档旧 zip）
tools/win_integrity.py                  把目录树完整性标签标回 Medium（避免 Low IL 下写不了 AppData，见 docs/WIN-INTEGRITY-TRAP.md）
data/legacy/                            引擎读的变种目录（由 tools/gen_catalogs.py 生成，与 GUI 目录同源不漂移）
data/catalogs/                          规范化目录（变种/战备/效果/星球/物品/build 指纹）
data/samples/                           离线预演的样本响应（真实抓包裁剪、无账号字段）
data/acceptance/                        M4 实机验收配置（m4-a 五项 / m4-b 六项，可复现）
research/                               技术选型实测脚本与结论（可复现）
docs/                                   来源与哈希、架构说明
```

## 安全设计（沿用研究线结论，产品化不放松）

- **单域名白名单** + **仅本机来源**：不是开放代理，非白名单 SNI 直接拒绝（自检第 2 项）。
- **会话证书 ca 模式**：SAN 只有 API 域名，默认 1–2 天硬上限，签完立刻删 CA 私钥；
  本地 8080 提供 CRL（Windows Schannel 必需）；启动前 preflight 校验模式/期限/SAN/多余私钥。
- **默认不落请求/响应体**（抓包需显式开启，且会提示含账号 id）。
- **一键还原**：停进程 → 删信任证书 → 删证书文件 → 删 hosts 行。
- 不修改游戏文件、不注入进程 ⇒ 与 EAC 无关（EAC 只查游戏文件）。

## 边界（研究线已定证，别把承诺说过头）

- 只改**客户端收到的**数据；服务端不落账（伪造星球/战役是"客户端侧真实、战局侧幻影"）。
- `Mission/Session` 类会话恢复端点有校验（`errorCode 8012016`），不要承诺重连可用。


## 许可

MIT（见 [LICENSE](LICENSE)）。代码与数据来自本人研究仓库，未包含任何游戏资产。
