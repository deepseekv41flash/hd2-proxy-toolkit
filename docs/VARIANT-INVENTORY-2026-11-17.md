# 变种目录全量盘点 + 2026-11-17 补齐记录（build 26568081 / war 801）

> 起因：用户报「『变种』里虫族少了 Noxious Strain 和 Caustic Strain」，并要求顺手排查还有没有别的漏项。
> 结论先行：**虫族确实少了这两个；其他阵营（机器人/光能者/超级地球）一个不缺**；
> 另外列出「线上没有对应 effect、因此无法用本通道注入」的项目，避免下次再被当成漏项查一遍。
> 落地代码：`tools/gen_catalogs.py`（覆盖层）+ `data/sources/variant_overlay.json`；
> 守门测试：`tests/unit/test_variant_catalog.py`。

## 1. 根因：两层，缺的不是同一件事

| 现象 | 真实状态 | 为什么界面看不见 |
|---|---|---|
| Caustic Strain | `data/catalogs/variants.json` 里**早就有** `caustic_strain: [1430, 1431]` | 它**没进 `groups`**；变种界面（`status_page._build_variants` → `Catalogs.variant_entries()`）只渲染 groups，未分组条目等于隐藏 |
| Noxious Strain | 完全没收录 | 源目录 `variant_mod/variant_catalog.json` 冻结在 2026-11-01（build 25988413），Noxious 是之后才上线的内容 |

⇒ 修复不能只「往 items 里塞一条」，必须同时：进分组、给玩家看得懂的名字、引擎目录同步（引擎按名字查 ids）。

## 2. 证据来源（全部可复现）

### 2.1 官方 API 直连（本次新发现：两个端点都接受未鉴权请求）

`hosts` 已把 `api.live.prod.thehelldiversgame.com` 指向本机代理，抓当前线上数据要**绕过 hosts**：
用公共 DNS 取真实 IP（`Resolve-DnsName -Server 223.5.5.5` → `172.200.240.16`），
再以 `server_hostname=该域名` 建 TLS 连接直连。

| 端点 | 请求要点 | 本次结果 |
|---|---|---|
| `GET /api/WarSeason/GalacticWarEffects` | 无需鉴权 | **315** 条效果（研究仓 26088801 快照是 312 条） |
| `GET /api/WarSeason/801/Status` | 必须带 `Accept-Language: en-US`（否则 400 `Accept-Language HTTP header missing`） | **161** 条 `planetActiveEffects`，68 个不同 effect |

快照（本地留档，不入库）：

| 文件 | 字节 | sha256 |
|---|---:|---|
| `D:/mod/out/gwe-live/20261117T021554Z_GalacticWarEffects.json` | 73,005 | `b87f679b4303232fb4db80bd6f69992a935b1da14ca15d444e033f0a302ee5c8` |
| `D:/mod/out/gwe-live/20261117T021829Z_801_Status.json` | 56,956 | `c5ad4ac3d5a5bcff7b75e01dd03989b3eceda61adf409dbec482b3df0998593a` |

### 2.2 本地 presence 表（当前 build 明文）

`refs/dlbin/plaintext-26568081/generated_galactic_presence_settings.dl_bin`
（sha256 `8666e05a…78c3b5`，137 行）—— `effectType=71` 的 `values[0]` 就是
`murmur32(presence 名)`（口径见 repo-datamined `docs/tables/PLANET-TABLES-26088801.md §3.6`）。
用行内 `+0x20/+0x24` 的 locid 去 `refs/strings-en-26088801.json` 解显示名/描述。

### 2.3 名称核对：wiki（中英）

| 词条 | 英文 | 中文（wiki zh） | presence | 证据 |
|---|---|---|---|---|
| Caustic Strain | `CAUSTIC STRAIN` | 腐蚀变种 | `bugs_acid` | 英文描述 "highly alkaline bile sacs … corrosive fluids" 与 strings locid 461034013 逐字一致 |
| Noxious Strain | `NOXIOUS STRAIN` | 毒瘴变种 | `bugs_defiler` | 英文描述 "toxin-secreting glands … incapacitating venom" 与 strings locid 1937755919 逐字一致 |

- <https://helldivers.wiki.gg/wiki/Caustic_Strain>、<https://helldivers.wiki.gg/wiki/Noxious_Strain>
- <https://helldivers.wiki.gg/zh/wiki/腐蚀变种>、<https://helldivers.wiki.gg/zh/wiki/毒瘴变种>
- 「毒瘴变种」页面写明更新日志 `1.007.202 2026-10-29 加入游戏` ⇒ 比源目录冻结晚，属新增内容。

### 2.4 tag ↔ mechanic 配对：线上共现（直接证据，非邻接推断）

方法：`Status.planetActiveEffects` 里同一对 tag/mechanic 若在**完全相同的星球集合**上出现，
且不存在只出现单边的星球，即判为一对。

| 配对 | tag | mechanic | 线上星球集合（2026-11-17） | 判据 |
|---|---|---:|---|---|
| Caustic | **1430** | 1431 | 269, 215 | 两边集合相同，无单边 |
| Noxious | **1434** | 1433 | 78, 128, 130, 168, 170, 175, 213, 270 | 两边集合相同，无单边 |

对照：新条目 `1432 = hiveworld_infested_planet`（显示名 `HIVE WORLD`，`kind=1` 地图标记）
只出现在 6 颗星，是上面 8 颗的子集 —— 若把 1434 配给 1432，则 168/213 两颗星（有 1434 无 1432）
会自相矛盾 ⇒ 1434 只能配 1433。

## 3. 全量清单（本产品能注入的「变种」）

「线上星球」= 2026-11-17 22:18Z 实际在 `planetActiveEffects` 里出现的星球索引；
`—` 表示当前没排期，不代表不能注入（这些在旧版本实机/历史上都出现过）。

| 分组 | 变种 | ids（tag, mechanic） | presence | 线上星球 | 目录状态 |
|---|---|---|---|---|---|
| 虫族 | 掠食变种 Predator Strain | 1243, 1245 | `bugs_super_predator` | — | 原有 |
| 虫族 | 孢裂变种 Spore Burst Strain | 1244, 1386 | `bugs_gloom` | — | 原有 |
| 虫族 | 爆裂变种 Rupture Strain | 1303, 1310 | `bugs_burrower` | 126, 212, 214 | 原有 |
| 虫族 | 蟑龙 Dragonroaches | 1306, 1309 | `bugs_dragon` | 100, 173, 212, 259 | 原有 |
| 虫族 | 霸王虫 Hive Lords | 1307, 1308 | `bugs_hive_lord` | 170, 212, 259 | 原有 |
| 虫族 | **腐蚀变种 Caustic Strain** | **1430, 1431** | `bugs_acid` | 215, 269 | **本次补齐（改名+进组）** |
| 虫族 | **毒瘴变种 Noxious Strain** | **1434, 1433** | `bugs_defiler` | 78, 128, 130, 168, 170, 175, 213, 270 | **本次新增** |
| 机器人 | 生化人 Cyborgs | 1360, 1361 | `bots_cyborgs` | 158, 207, 260 | 原有 |
| 机器人 | 灼热部队 The Incineration Corps | 1248, 1249 | `bots_ivory_legion` | 246, 261 | 原有 |
| 机器人 | 喷气部队 The Jet Brigade | 1202, 1203 | `elite_bot_jumpattack` | 158 | 原有 |
| 机器人 | 重甲激增 Heavy Armor Surge | 1355 | `bots_increased_warstriders` | — | 原有 |
| 机器人 | 巨型者激增 Hulk Surge | 1357 | `bots_increased_hulks` | — | 原有 |
| 机器人 | 蹂躏者激增 Devastator Surge | 1359 | `bots_increased_devastators` | — | 原有 |
| 卡牌 | 入侵舰队 Invasion Fleet | 1413, 1414 | `illuminate_invading` | 7 | 原有 |
| 卡牌 | 无票者大军 Mindless Masses | 1377, 1378 | `illuminate_harvester` | 231 | 原有 |
| 卡牌 | 入侵者 Appropriators | 1380, 1379 | `illuminate_engineer` | — | 原有 |
| 卡牌 | 窃票者 Vote Snatchers | 1402, 1403 | `illuminate_bodyhorror` | 7 | 原有 |
| 通用 | 重兵部署 Heavy SEAF Presence | 1401, 1400 | `seaf` | 270 | 原有 |

### 3.1 wiki 口径对照（是否有其他漏项）

| wiki 分类 | wiki 列出 | 目录覆盖 |
|---|---|---|
| 终结族 子阵营 | Predator / Spore Burst / Rupture / Caustic / Noxious Strain | ✅ 5/5（本次补齐后） |
| 终结族 特殊变种 | Dragonroaches、Hive Lords | ✅ 2/2 |
| 机器人 子阵营 | Jet Brigade、Incineration Corps、Cyborgs | ✅ 3/3 |
| 机器人 敌情激增 | Hulk Surge、Heavy Armor Surge、Devastator Surge | ✅ 3/3 |
| 光能者 子阵营 | Appropriators、Vote Snatchers | ✅ 2/2 |
| 光能者 敌情激增 | Mindless Masses、Invasion Fleet | ✅ 2/2 |
| 超级地球 部队 | Heavy SEAF Presence | ✅ 1/1 |

⇒ **除本次补的两条，没有其他漏项。**

## 4. 「看起来像变种、但本通道注入不了」的清单（避免下次重复排查）

`planetActiveEffects` 只能引用**线上 GalacticWarEffects 目录里存在的 effect id**；
本地 presence 表里有、但线上目录里没有 type71 条目的，注入了客户端也解析不到。逐条列出：

| 名称 | presence | 判定 | 依据 |
|---|---|---|---|
| TANK SURGE | `bots_increased_tanks` | ⛔ 无 GWE 条目 ⇒ 不可注入 | 线上 315 条里没有指向它的 type71；wiki 的 "Heavy Armor Surge"（= 坦克+纵步者）已由 1355 覆盖 |
| E-710 RICH STRAIN | `bug_facility_strain_rich` | ⛔ 无 GWE 条目 | 同上（id 已不在线上目录） |
| E-710 提取类设施 | `e710_farms` / `e711_processing_facility` 等 | ⛔ 设施/地图标记，非战斗变种 | kind 语义（`+0x14`）+ 无 GWE 条目 |
| HIVE WORLD（虫窝世界） | `hiveworld_infested_planet` | ⚠ 是**星球环境条件**，不是战斗变种 ⇒ 不进「变种」分组 | 对应线上 effect **1432**（type71, `kind=1` 地图标记），2026-11-17 在 78/128/130/170/175/270 六星生效 |
| CLASS 1/2/3 EXOSTORM | `illuminate_ritual_storm_lvl1/2/3` | ⚠ 地图标记（1373/1374/1375），非战斗变种 | `kind=1` |
| 各类设施（DATA CENTER / XENOENTOMOLOGY CENTER / DSS 建造点…） | `bot_facility_*` / `research_*` / `democracy_station_*` | ⚠ 地图标记 | `kind=1` |
| THE GREAT HOST | `illuminate_fleet`（effect 1269） | ⚠ **历史事件子阵营**（超级地球保卫战那一波），当前线上 0 星；目录里保留未分组条目 | wiki "The Great Host"：非周期性星球变种，靠银河图标显示存在 |

> 说明：上表「⛔」项不是缺漏，而是内容侧就没有下发菜单；本仓库的工具无法凭空造 effect id。

## 5. 复现

```powershell
# 1) 取真实 IP（hosts 指向代理，必须用公共 DNS）
Resolve-DnsName -Name api.live.prod.thehelldiversgame.com -Server 223.5.5.5 -Type A
# 2) 直连抓两个端点（python：ssl + server_hostname，见本节末脚本要点）
#    GET /api/WarSeason/GalacticWarEffects
#    GET /api/WarSeason/801/Status      ← 必须带 Accept-Language: en-US
# 3) 本地 presence 表 -> murmur32 对表
python - <<'PY'
import sys; sys.path.insert(0, r"D:/mod/work/repo-datamined/tools")
import planet_tables as P, pathlib, struct
from planet_index import murmur32
P.PLAIN = pathlib.Path(r"D:/mod/refs/dlbin/plaintext-26568081")
for g in P.parse_groups((P.PLAIN/"generated_galactic_presence_settings.dl_bin").read_bytes()):
    tail = g.payload[1000:]
    print(murmur32([m.group().decode("latin1") for m in __import__("re").finditer(rb"[ -~]{3,}", tail)][0]))
PY
# 4) 目录侧：改 data/sources/variant_overlay.json 后重跑
python tools/gen_catalogs.py
python -m pytest tests/unit/test_variant_catalog.py -q
```

抓取要点（本次实测）：`ssl.create_default_context()` + `wrap_socket(..., server_hostname=域名)`；
响应可能是 `Transfer-Encoding: chunked`（需要自己 dechunk）；`Host` 头必须写域名。

## 6. 本次改动范围与遗留

改动：

- `data/sources/variant_overlay.json`（新）—— 源目录冻结后的增量与改名/别名/分组规则；
- `tools/gen_catalogs.py` —— 读覆盖层；**顺带把引擎目录 `data/legacy/variant_catalog.json` 也纳入生成**
  （以前是手工拷贝，两份目录漂移正是这次「items 有、groups 没有」的直接土壤）；
- `data/catalogs/variants.json`、`data/legacy/variant_catalog.json` —— 重新生成（虫族 5 → 7）；
- `tests/unit/test_variant_catalog.py`（新，23 条）—— 覆盖 wiki 全量清单、两份目录一致性、覆盖层规则。

遗留（下一轮可选，不在本次范围）：

1. `data/catalogs/effects.json` 仍是 26088801 快照（312 条），线上已是 315 条；
   新 id 1432–1434 在效果表里查不到名字（GUI 会显示 `1434 · ?`，不影响注入）。
2. 目录的 `build`/`game_version` 字段仍是源目录的 25988413 / 1.007.200，与实际 build 26568081 不一致
   （`data/catalogs/build.json` 里的 `game_build` 才是现行值）。
3. 若以后每期都要跟线上目录：可把「GWE 快照 + presence 表」做成生成器输入，自动 diff 出新增/下线条目。
