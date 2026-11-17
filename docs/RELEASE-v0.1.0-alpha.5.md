# v0.1.0-alpha.5 — 变种目录补齐（Caustic / Noxious）+ 版本规则与发版工具（2026-11-17）

> **alpha 预览版**：6 项能力已在 M4 逐项实机验证，alpha.3 在打包版 GUI 上跑完 15 项实测；
> 本版补的是「变种词条」数据层，并落实发版规则。更多环境/游戏更新的稳定性仍在观察。

## 本版修了什么

用户报：「『变种』里虫族少了 **Caustic Strain** 和 **Noxious Strain**」。排查后是两层原因：

| 现象 | 真实状态 | 为什么界面看不见 |
|---|---|---|
| Caustic Strain | 数据里**早就有** `caustic_strain: [1430, 1431]` | 它**没进 `groups`**；变种界面只渲染分组，未分组条目等于隐藏 |
| Noxious Strain | 完全没收录 | 源变种目录冻结在 2026-11-01（build 25988413），它是之后上线的内容 |

现在两条都进「虫族」组（5 → **7 个**）：

- **腐蚀变种 / Caustic Strain** → `[1430, 1431]`，presence `bugs_acid`；
- **毒瘴变种 / Noxious Strain** → `[1434, 1433]`，presence `bugs_defiler`。

旧内部名 `caustic_strain` 保留为**别名**，老 profile 里存的名字仍能解析，不用改配置。

## 怎么确认的（不是猜的）

1. 直连官方两个端点抓当前线上数据（不经过本机代理）：
   `GET /api/WarSeason/GalacticWarEffects`（**315 条**，研究仓 26088801 快照只有 312 条）、
   `GET /api/WarSeason/801/Status`（161 条 `planetActiveEffects`）。
2. 新出现的三条：`1432 = hiveworld_infested_planet`（HIVE WORLD，地图标记）、
   `1433 = bugs_defiler`、`1434 = type40 词条`。
3. 用当前 build 的本地 presence 明文表把 `effectType=71` 的 `values[0]` 反解成 presence 名：
   `murmur32("bugs_defiler") = 2982396937 = effect 1433`（与线上值一致）。
   presence 行 `+0x20` 的 locid 在 strings 表里解出 **NOXIOUS STRAIN**（描述与 wiki 逐字一致）。
4. tag↔mechanic 配对用**线上共现**判定：1433 与 1434 出现在**完全相同的 8 颗星球**
   （78/128/130/168/170/175/213/270），没有单边的星；作为对照，1432 只在其中 6 颗，
   所以 1434 不可能配 1432。Caustic 的 1430/1431 同样在 269/215 成对。

全量清单、配对证据、「哪些看起来像变种但注入不了」的清单都在
[`docs/VARIANT-INVENTORY-2026-11-17.md`](VARIANT-INVENTORY-2026-11-17.md)。

## 顺手排查：还有没有别的漏掉的变种

按 wiki 的 Combatant Forces 全量对照，**除这两条外没有其他漏项**：

| 阵营 | wiki 列出 | 目录覆盖 |
|---|---|---|
| 终结族 | 5 个 strain（Predator / Spore Burst / Rupture / Caustic / Noxious）+ Dragonroaches + Hive Lords | ✅ 7/7 |
| 机器人 | Jet Brigade / Incineration Corps / Cyborgs + Hulk / Heavy Armor / Devastator Surge | ✅ 6/6 |
| 光能者 | Appropriators / Vote Snatchers + Mindless Masses / Invasion Fleet | ✅ 4/4 |
| 超级地球 | Heavy SEAF Presence | ✅ 1/1 |

不在变种范畴（因此没加进选择器）：HIVE WORLD 与各类设施/风暴是**地图标记**；
THE GREAT HOST 是历史事件子阵营（当前线上 0 星）。
`TANK SURGE`（`bots_increased_tanks`）在线上目录里没有对应 effect，**本通道注入不了**，
不是漏项——细节见盘点文档 §4。

## 防复发

- `tools/gen_catalogs.py` 新增**覆盖层**输入 `data/sources/variant_overlay.json`：
  源目录冻结后的增量、改名、别名、分组规则都写进仓库，重跑可复现；
- **引擎目录 `data/legacy/variant_catalog.json` 也纳入生成**（以前是手工拷贝）。
  两份目录漂移正是这次「items 有、groups 没有」的直接土壤；
- 新增 `tests/unit/test_variant_catalog.py`（23 条）：wiki 全量清单、GUI/引擎目录逐条一致性、
  覆盖层的 6 种写错即报错情形。

## 本版还包含（alpha.4 之后累积的开发侧改动）

- `docs/VERSIONING.md` + `src/hd2proxy/versioning.py` + `tools/bump_version.py`：
  把「X.Y.Z 只给功能/能力更新，只修 bug 只动 alpha.N / rc.N」落成规则与工具；
  `tools/check_version.py` 作为门禁第 0 步。
- `tools/sync_release_area.py`：构建产物同步到专用测试区（与 GitHub Release 资产逐字节一致）。
- `tools/win_integrity.py`：修掉「测试区 exe 以 Low 完整性运行 → 写 AppData 报
  `PermissionError(13)`」的坑（构建/同步时自动把目录树标回 Medium）。
- 单测 **311 → 363**。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.0-alpha.5-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.0-alpha.5-windows-x64.zip -Algorithm SHA256
```

## 升级提示

- 覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）；
- 变种是按星球挂的：在「战况/变种词条」里选「虫族 · 腐蚀变种 / 毒瘴变种」→ 选星球 → 添加到方案 →
  「应用配置」，然后**重启游戏或让星图重新拉一次 Status** 才能看到星图词条。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看日志里 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 效果目录 `effects.json` 仍是 26088801 快照（312 条）；新 id 1432–1434 在效果表里没有名字
  （界面显示 `1434 · ?`，不影响注入）。
