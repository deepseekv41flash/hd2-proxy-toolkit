# v3：从客户端只读数据补目录名字（report-v3）

> 任务：v2 快照还有 856 行无名。API 抓包已确认**没有名字/locid**（只有结构锚点），所以 v3 换了路线：去**客户端本地数据**里找 `mixId -> locid/名字` 映射。
> 结论：**可以**。名字在 `D:\SteamLibrary\steamapps\common\Helldivers 2\data\game\game.dll`（build 26568081，49,075,800 B，与目录 build 一致）的几张静态表里，行 id 与目录 `mixId` **精确相等**；locid 用本机本地化表 `refs/strings-en-26088801.json`（24,834 条）解析。
> 结果：**named 2164 → 2356（+192）**，unresolved 856 → **664**。只读、不联网、未改 `hd2-proxy-toolkit` 与游戏目录。

## 0. 产物

| 文件 | 说明 |
|---|---|
| `resolved_v3.json` | v3 快照：3020 行；结构同 v2（name/name_source/confidence + category_meaning 不变）；只填空位、不覆盖 v2 |
| `resolve_v3.py` | 可复跑解析器（只读、确定性、参数可覆盖路径；内置自检） |
| `merge_strings.py` | 把旧 `.strings` 语料 + 当前 build 临时解包语料合并成 locid→文本 JSON（供补新 locid 用） |
| `_v3_candidates.json` | 每张表的原始提取结果（含 dll offset / locid 字段），供复核 |
| `_v3_scan.json` 等 | 侦察中间产物 |

## 1. 总览（v2 → v3）

| 项 | v2 | v3 |
|---|---:|---:|
| named | 2164 | **2356（+192）** |
| unresolved | 856 | **664** |
| confidence | high 1900 / medium 263 / low 1 / null 856 | **high 2038 / medium 317 / low 1 / null 664** |

v3 新增来源（行数）：

| name_source | 行数 | cat | confidence | 证据 |
|---|---:|---:|---|---|
| `dlbin-banner-table` | 65 | cat9 横幅 | high | game.dll banner 表 @0x2C7FEF0，stride 0x18；`+0x00 mixId / +0x10 大写名 locid / +0x14 标题式名 locid` |
| `dlbin-victory-pose-table` | 27 | cat8 胜利姿势 | high | pose 表 @0x2CB4CF0，stride 0x80；名字 locid 在 `+0x3C/+0x40` |
| `dlbin-voice-table` | 5 | cat13 语音包 | high | voice 表 @0x2CB02C8 起 4 行 + @0x2C6A510 一行；名字 locid `+0x10/+0x14`、描述 `+0x18` |
| `dlbin-resource-sample-table` | 3 | cat15 资源 | high | 样本表 @0x2C953B0，stride 0x40；`+0x04/+0x08` 大写单复数、`+0x0C/+0x10` 标题式 |
| `dlbin-item-pack-table` | 8 | cat21 礼包 | medium | 礼包表 @0x2CAD240，stride 0x38；`+0x0C/+0x10 短名、+0x14 货币名`（行是 store 礼包，名字=礼包显示短名） |
| `dlbin-difficulty-table` | 2 | cat16 | medium | 难度表 @0x2C45FB0 起：`+0x08` 难度名 locid（TRIVIAL/EASY…）、`+0x0C` 序号 locid；只有 2/9 行找到映射 |
| `dlbin-warbond-table` | 26 | cat0 战团购买/代币行 | medium | game.dll 战团表（新表 @0x2C6A600 / 旧结构 0x2079140 一带）给出 26 个 warbond id→名字；再用 SeasonPass 抓包的 `premiumTokenMixId` 对到目录 cat0 行 |
| `locid-id` | 56 | cat23 38 / cat6 13 / cat21 4 / cat0 1 | high(cat23)/medium(其它) | catalog `mixId` 本身就是名字 locid：`strings[mixId]` 直接是显示名 |

> 注：cat23 称号的 38 条样本（如 `926009925 → ADMIRABLE ADMIRAL`）与 lead 在 `avatarCustomization.titleId32` 里观察到的值完全一致，证实「称号 itemId = 名字 locid」这个约定。

## 2. 验证样本（与 lead 已核实值对照）

| 来源 | 目录行 | v3 名字 | 验证 |
|---|---|---|---|
| banner 表 | mix 3460374366（cat9） | **Patient Zero's Rememberance** | 与 avatarCustomization.banner 一致；表内 `+0x10` 大写、`+0x14` 标题式两路 locid 同时命中 |
| 称号 locid | mix 926009925（cat23） | **ADMIRABLE ADMIRAL** | 与 avatarCustomization.titleId32 一致 |
| voice 表 | mix 4010084743（cat13） | **Default Helldiver Voice 2** | 与 voice_pack_set 一致 |
| 姿势表 | mix 4693889（cat8） | **At Ease** 等 27/27 全部命中 | 行 id 与 catalog cat8 全等 |
| 样本表 | mix 2985106497（cat15） | **Rare Sample** | 行 id = catalog mixId |
| 礼包表 | mix 115015730（cat21） | **Helldivers Mobilize!** | 行内 locid |
| 战团表 | premiumTokenMixId 684418136（cat0） | **Chemical Agents** | warbond id 4150031036 → 名字；由 SeasonPass API 配对 |
| 难度表 | mix 4184663652（cat16） | **TRIVIAL** | 行 id + 难度名 locid |

## 3. 分类型结果（v3）

| cat | 行数 | v1 | v2 | **v3** | v3 仍缺 | 说明 |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 173 | 0 | 0 | **27** | 146 | 只有 26 个 warbond premium token + 1 条 locid 行；其余战团记账/代币行客户端无名字表 |
| 1 | 115 | 21 | 107 | **107** | 8 | LoadoutEntry 表已穷尽 |
| 2 | 1455 | 1404 | 1404 | **1404** | 51 | 新改装选项不在本机 option 表 |
| 3 | 427 | 367 | 367 | **367** | 60 | 外观表未命名的 33 行 + 无套装件的披风等 |
| 4 | 196 | 2 | 120 | **120** | 76 | v2 的父级推断 |
| 5 | 30 | 20 | 20 | **20** | 10 | 本地无定义 Booster |
| 6 | 23 | 0 | 0 | **13** | 10 | 13 条 mixId 本身是 locid（如 STAMINA BOOST） |
| 7 | 32 | 0 | 0 | **0** | 32 | **未找到客户端映射**（详见 §4） |
| 8 | 27 | 0 | 0 | **27** | 0 | 全解 |
| 9 | 103 | 0 | 0 | **65** | 38 | 表内 75 行、65 行能在旧 strings 解析；**28 条目录行根本不在客户端 banner 表** |
| 10 | 111 | 32 | 73 | **73** | 38 | v2 战备子项 |
| 11 | 108 | 0 | 73 | **73** | 35 | v2 许可子行推断 |
| 13 | 5 | 0 | 0 | **5** | 0 | 全解 |
| 15 | 10 | 0 | 0 | **3** | 7 | 只有 COMMON/RARE/SUPER SAMPLE 3 行有名字字段 |
| 16 | 9 | 0 | 0 | **2** | 7 | 只有 TRIVIAL/EASY 两行在客户端难度表 |
| 17 | 2 | 0 | 0 | **0** | 2 | **未找到**（详见 §4） |
| 18 | 15 | 0 | 0 | **0** | 15 | 只出现在货币 id 数组，无名字字段 |
| 19 | 49 | 0 | 0 | **0** | 49 | 无名字表（只出现在 package 奖励结构） |
| 20 | 36 | 0 | 0 | **0** | 36 | 无名字表（只出现在 ship 区域页的 id 列表） |
| 21 | 32 | 0 | 0 | **12** | 20 | 8 行礼包表 + 4 行 locid；其余只出现在礼包内容数组 |
| 23 | 61 | 0 | 0 | **38** | 23 | 旧 strings 语料只有 38 个 locid；其余疑似本 build 新增（等当前 strings） |
| 合计 | 3020 | 1932 | 2164 | **2356** | 664 | |

## 4. 失败路径（已核实，不是没试）

- **cat7（Emote，32 行）**：32 个 mixId 在 `game.dll`/`runtime.dll`/`helldivers2.exe`/`generated_entities.dl_bin`/其余 55 个 `data/game/*.dl_bin` 中**只有 1 次假阳性**（0x1B530E7，上下文全是随机哈希，不是表）。客户端可能把 emote 定义放在 bundle 资源（`.unit`）而非 game.dll 静态表；本轮未定位。
- **cat17（内衬，2 行）**：只出现在 `generated_body_settings.dl_bin`（116 B 的 LDBL 表，2 行 = 2 个 mixId + 若干浮点参数），**没有 locid/名字字段**；其它所有二进制/表均无这两个 id。
- **cat19（49）/ cat20（36）**：只作为 ProgressionPackages 奖励 id 数组/舰船区域页的 id 列表出现；周围有 `BRIDGE/HANGAR/ORBITAL CANNONS` 等区域名，但没有逐行名字字段 → **无客户端名字可提**。
- **cat18（15 货币）**：只在货币 id 数组 `0x1FEAD00` 附近出现，无名字字段。
- **cat9 缺 38**：28 条目录行在客户端 banner 表里**不存在**（疑似未发布/未来战团内容；服务器目录比客户端内容超前）；另 10 行表内存在但旧 strings 语料缺 locid 文本（等当前 build strings）。
- **cat23 缺 23**：不是 id 结构缺失，而是旧 strings 语料（26088801 build，2026-10-22 抽取）没有这些 locid 文本；当前 build 的 `.strings` 正在解包（见 §5）。
- **cat0 缺 146**：只解到 26 个 warbond 购买 token；战团内的记账/代币行（medalsSpent 等）在客户端不出现（premiumTokenMixId/medalsSpentMixId 在 game.dll 里 0 命中）。

## 5. 未完成：当前 build 的 `.strings` 语料解包中的下一步

旧语料 `refs/strings-en-26088801.json` 是 **26088801** build 的 24,834 条；本次已用脚本 `unpack_strings_current.sh` 把当前 build（26568081）的 30 个 `bundles.NN.nxa` 按 `--type strings` 解到 `v3/strings-current/`（每 bundle 约 10 分钟；已解出 bundle 00/02/03，其余在跑）。解完后：

```bash
python merge_strings.py --root <mod>/refs/strings-probe/all --root <mod>/refs/strings-probe/bundles \
                        --root <mod>/tmp/catalog-names/v3/strings-current --out _strings_merged.json
python resolve_v3.py --strings _strings_merged.json --out resolved_v3.json
```

预计可再补：cat9 表内 10 行、cat23 剩余 23 条（若确为本 build 新增且已本地化）；对 cat7/17/19/20/18 无帮助（它们缺的是表/字段，不是 locid 文本）。**本条链路未跑完，故 v3 数字是保守值。**

## 6. 复跑 / 只读 / 确定性

```bash
cd <mod>/tmp/catalog-names/v3
python resolve_v3.py \
  --work-root <mod>/work \
  --dll "D:/SteamLibrary/steamapps/common/Helldivers 2/data/game/game.dll" \
  --strings <mod>/refs/strings-en-26088801.json \
  --v2 <mod>/tmp/catalog-names/resolved_v2.json \
  --out <mod>/tmp/catalog-names/v3/resolved_v3.json
```

- **只读**：输入只以读模式打开；只写 `--out` / `--candidates-out`；不写游戏目录、不写 `<mod>/work`。
- **不联网**：无网络调用、纯标准库。
- **确定性**：无随机/时间戳；输入 sha256 记入 `resolved_v3.json.sources`。
- **自检**（失败即非零退出）：3020 行；`sum(by_cat.rows)==3020`；`sum(by_source)==named`；`named+unresolved==3020`；有名必有来源、confidence ∈ {high,medium,low,null}；`category_meaning` 沿用 v2 未改。
- 实测：`python -c "...assert len(rows)==3020; print(coverage)"` 通过；v3 相对 v2 的差异只有 192 行新增名字（其余行逐字段相同），来源冲突 0。

## 7. 证据文件哈希

`resolved_v3.json.sources` 内记录了 dll / strings / v2 / catalog 的 sha256；侦察用的 dll 是本机安装目录的当前 build（`Steam appmanifest buildid=26568081`，与目录 build 一致）。
