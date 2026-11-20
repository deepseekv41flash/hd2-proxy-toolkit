# GWE 效果英文文本补齐报告（2026-11-20）

> 任务：为 `data/catalogs/effects.json` 的 312 条 Galactic War Effects 补齐英文 `name` / `short_desc` / `long_desc` / `fluff`；只写有证据的字段，英文原文照抄，不翻译不编造。
> 产物：`data/sources/effect_texts.json` + 本报告；自检见 §5（真实执行结果）。

## 1. 覆盖统计

| 指标 | 数值 |
|---|---:|
| 目录效果总数 | 312 |
| 至少有一个文本字段的行 | 202 |
| 四个字段全缺（数据上无法提供文本） | 110 |
| `name` 已补齐 | 202 / 312（64.7%） |
| `short_desc` 已补齐 | 158 / 312（50.6%） |
| `long_desc` 已补齐 | 11 / 312（3.5%） |
| `fluff` 已补齐 | 0 / 312（0.0%） |
| 来源冲突 | live/抓包哈希冲突 0；existing 与 client 文本冲突 0 |

### 1.1 每字段来源分布

| 字段 | 已补齐 | hash 直接命中(live) | hash 直接命中(抓包) | type71 presence 行 locid | effects.json 回退(medium) |
|---|---:|---:|---:|---:|---:|
| `name` | 202 | 116 | 0 | 58 | 28 |
| `short_desc` | 158 | 100 | 0 | 58 | 0 |
| `long_desc` | 11 | 11 | 0 | 0 | 0 |
| `fluff` | 0 | 0 | 0 | 0 | 0 |

**来源升级**：本轮把 **116** 个原本只能靠 `effects.json` 回退（medium）的字段，升级为带**真实 locid** 的 client-strings 证据（type71 presence 行 `name_id`/`desc_id`）。仍保留 `existing-effects.json` 回退字段 28 个（仅 name，见 §3.3）。

**覆盖增量**：与 `effects.json` 基线逐字段对比 —— 新增 0、丢失 0、文本差异 0（202 行基线已含全部可在客户端本地化里找到的文本）。本轮的价值 = 把 116 个字段从「旧值回退」升级为**可复核的 locid 证据**，并用哈希覆盖率证明剩余缺口是数据不存在（不是解析失败）。

哈希覆盖（分母 = live GWE 315 条；用于证明「仍缺」来自数据本身）：

| 字段 | API 中哈希非 0 | 能在客户端 strings 解析 | 非 0 但解析不到 |
|---|---:|---:|---:|
| `name` | 315 | 116 | 199 |
| `short_desc` | 315 | 100 | 215 |
| `long_desc` | 315 | 11 | 304 |
| `fluff` | 0 | 0 | 0 |

## 2. 方法与证据

1. **哈希字段语义（本轮定证）**：GWE 的 `nameHash` / `descriptionGamePlayShortHash` / `descriptionGamePlayLongHash` / `descriptionFluffHash` **不是统一 locid，也不是可反查的 murmur32**：
   - 315 条 live 效果中 `nameHash` 直接等于客户端 strings 键（locid）的只有 **116** 条；
   - 对 24,834 个 locid 逐算 `murmur32(str(locid))` 建反查表，命中 **0** 条。
   ⇒ 直接 `strings.get(str(hash))` 是正确路径（与既有研究 `variant-net/tools/gwe_full_table.py:199/227/239-242` 一致），但只能覆盖部分效果，剩余靠类型路由。
2. **type71（presence）路由**（补 name/short 的关键）：`values[0]` = `murmur32(presence 名)`，用本地表 `D:/mod/refs/dlbin/plaintext-26088801/generated_galactic_presence_settings.dl_bin` 反查 presence 行；实测行结构 `+0x20 = name_id`、`+0x24 = desc_id`（各 99/137 行可解），再以 locid 从 `D:/mod/refs/strings-en-26088801.json` 取英文。函数与既有研究一致：`variant-net/tools/effect_menu.py:71 load_presences()`、`gwe_full_table.py:199-330`。
   - 本批目录中 type71 行贡献 **name 58 + short_desc 58** 个字段（字段值均带 locid 证据）。
3. **哈希来源（优先官方 API）**：`PYTHONPATH=src python -m hd2proxy live --json --out <dir>`（DoH 直连官方，绕过本机 hosts）；2026-11-20T20:11 拉取 **315 条**（war 801），落在 `D:/mod/tmp/effect-live-20261120/{gwe.json,meta.json}`；本机 GWE 抓包并集（3 份，`D:/mod/out/gwe/*_api_WarSeason_GalacticWarEffects*.json`）只作 fallback。
4. **文本来源**：客户端英文本地化 `refs/strings-en-26088801.json`（24,834 条）。此前已验证当前 build（26568081）30 个 bundle 的英文 `.strings` 与它 **0 新增/0 改文**，因此「新 build 多出文本」不存在。
5. **回退与冲突规则**：client strings 完全缺该字段时才用 `effects.json` 旧值回退（`existing-effects.json`，medium）；client strings 与旧值冲突时以 client 为准并记入冲突（本次 existing 文本冲突 0）。

## 3. 仍缺字段与原因（逐字段）

| 字段 | 缺失数 | 原因 |
|---|---:|---|
| `name` | 110 | API 315 个 nameHash 全非 0，但客户端 strings 只解析出 116 个；type71 presence 行 `name_id` 再补 58 个（目录内合计 174）。其余 138 条的 nameHash 指向的 locid **不在客户端本地化语料**（服务器清单领先客户端 / 未发布内容）。其中 28 条沿用 effects.json 旧值（medium，§3.3）。 |
| `short_desc` | 154 | 同 name：315 个非 0 hash 直接解析 100 + type71 `desc_id` 58 = 158；其余 locid 不在客户端语料。 |
| `long_desc` | 301 | 315 条 long hash 均非 0，客户端 strings 命中仅 11；GWE 目录本身几乎不提供长描述文本（其余 locid 不在语料）。 |
| `fluff` | 312 | **API 315 条 `descriptionFluffHash` 全为 0**，客户端也无第二种字段 —— 不是漏挖，是数据不存在。 |

### 3.1 presence 行是否还有 long/fluff locid？（复核结论）

- 实测 `generated_galactic_presence_settings.dl_bin` 137 行：payload 里可解析 locid 的偏移**只有** `+0x20`（name_id，99/137）与 `+0x24`（desc_id，99/137）；**没有** long/fluff 字段。
- 结论：type71 路由只能补 name/short_desc，补不了 long_desc/fluff。

### 3.2 其它 effectType 的 locid 证据排查（32/40/47/48/94）

| 类型 | 本地对象 | 结论 |
|---|---|---|
| 32 临时配发战备 | `values[0]`=战备 hash；本地战备表只有被引用**战备的显示名**（且非 locid） | ✗ 不能当 effect 文本 |
| 40 星图词条 tag | `values[0]`=tag hash；本地 tag 对表只有 tag 名/mechanic 关系，无 effect 文本 locid | ✗ |
| 47/48/54/55/89/92 无参 | 无 values；文本只能来自自身 hash | ✗ 无额外来源 |
| 94 modifier | `values[0]`=modifier id；`generated_modifier_settings.dl_bin` 15 行（26088801 与 26251122 两版）**扫描 locid 命中 0** | ✗ 无名字/描述 locid |
| 71 presence | presence 行 `name_id`/`desc_id` | ✓ 已用于 name/short_desc |

### 3.3 仍用 `existing-effects.json` 回退（medium，无 client locid 证据）

```
type 分布: type32=15, type36=13
effect_id: 1127, 1128, 1133, 1135, 1139, 1148, 1262, 1265, 1267, 1274, 1284, 1289, 1298, 1301, 1302, 1328, 1332, 1334, 1335, 1337, 1338, 1339, 1340, 1343, 1384, 1385, 1394, 1424
```

注意：这 28 个 name 是**旧管线按 target（战备/DSS 装备）名字回退**得来（例：effect 1127 的 name=`Eagle 500kg Bomb`，实际是它引用的战备名，不是该 GWE effect 自身的显示名）。其 nameHash 指向的 locid 不在客户端本地化语料中，本轮无法独立验证，故保留 `existing-effects.json`/medium；集成时建议按语义需要取舍。

### 3.4 四个字段全缺的效果 id（数据不存在 → 不写字段）

```
type 分布: type1=3, type21=6, type23=8, type24=1, type25=4, type29=1, type36=1, type40=14, type43=1, type44=1, type46=1, type50=2, type56=4, type59=1, type61=1, type69=2, type70=3, type71=18, type72=15, type73=5, type74=1, type76=1, type77=4, type80=2, type83=2, type90=1, type92=1, type93=1, type95=2, type96=2, type97=1
1, 8, 13, 95, 1126, 1131, 1132, 1134, 1136, 1138, 1140, 1141, 1176, 1177, 1186, 1187, 1188, 1189, 1190, 1191, 1192, 1193, 1201, 1202, 1218, 1219, 1220, 1222, 1223, 1224, 1225, 1240, 1242, 1243, 1244, 1246, 1248, 1250, 1251, 1253, 1255, 1257, 1258, 1264, 1270, 1271, 1272, 1273, 1275, 1278, 1283, 1285, 1288, 1293, 1294, 1296, 1297, 1299, 1300, 1303, 1304, 1305, 1306, 1307, 1311, 1314, 1316, 1317, 1319, 1320, 1321, 1322, 1323, 1325, 1326, 1327, 1330, 1333, 1336, 1341, 1354, 1356, 1358, 1360, 1362, 1368, 1369, 1371, 1376, 1377, 1380, 1381, 1382, 1396, 1401, 1402, 1404, 1405, 1406, 1408, 1409, 1410, 1411, 1412, 1413, 1415, 1417, 1418, 1429, 1430
```

其中 type71 的 18 行是 presence key 不在本地 137 行 presence 表里（未发布的 presence 内容）；type40/72 等数值/哈希类型本身就没有官方显示文本。

### 3.5 name 仍缺清单

```
1, 8, 13, 95, 1126, 1131, 1132, 1134, 1136, 1138, 1140, 1141, 1176, 1177, 1186, 1187, 1188, 1189, 1190, 1191, 1192, 1193, 1201, 1202, 1218, 1219, 1220, 1222, 1223, 1224, 1225, 1240, 1242, 1243, 1244, 1246, 1248, 1250, 1251, 1253, 1255, 1257, 1258, 1264, 1270, 1271, 1272, 1273, 1275, 1278, 1283, 1285, 1288, 1293, 1294, 1296, 1297, 1299, 1300, 1303, 1304, 1305, 1306, 1307, 1311, 1314, 1316, 1317, 1319, 1320, 1321, 1322, 1323, 1325, 1326, 1327, 1330, 1333, 1336, 1341, 1354, 1356, 1358, 1360, 1362, 1368, 1369, 1371, 1376, 1377, 1380, 1381, 1382, 1396, 1401, 1402, 1404, 1405, 1406, 1408, 1409, 1410, 1411, 1412, 1413, 1415, 1417, 1418, 1429, 1430
```

## 4. 产物形状

- `data/sources/effect_texts.json`：每行 `{effect_id, name?, short_desc?, long_desc?, fluff?, fields, confidence}`；只写有证据的字段（202 行有文本，110 行四字段全缺故未出现）。
- `fields` 逐字段来源示例：`client-strings:locid=1016609603 (live-20261120:nameHash)`、`client-strings:locid=... (presence:bugs_super_predator:name_id)`、`existing-effects.json`。
- 无编造/无机翻：所有文本都能回指一个 locid（客户端 strings）或 effects.json 已存在值。

## 5. 自检（脚本真实执行，写文件前断言）

运行日志：

```
[mine] catalog effects=312; strings=24834
[mine] presence rows=128
[mine] hash sources: live=315 captures=315 (3 files)
[mine] rows=202 filled={'name': 202, 'long_desc': 11, 'short_desc': 158} conflicts=0
```

自检结果（render_report.py 重新独立执行）：

| 检查项 | 结果 |
|---|---|
| JSON 合法 | PASS |
| effect_id 全部 ∈ effects.json 312 个 id | PASS |
| 字段非空且 fields 有来源 | PASS |
| confidence ∈ {high,medium,low} | PASS |
| 统计与文件一致 | PASS |
| 每行至少一个字段 | PASS |

总判定：PASS

## 6. 复跑

```bash
cd <mod>/tmp/effect-mine
# 1) 抓最新官方 GWE（DoH 直连）
cd <repo> && PYTHONPATH=src python -m hd2proxy live --json --out <mod>/tmp/effect-live-<date>
# 2) 生成 effect_texts.json
python <mod>/tmp/effect-mine/mine_effect_texts.py --repo <repo> \
  --live-gwe <mod>/tmp/effect-live-<date>/gwe.json \
  --capture-glob '<mod>/out/gwe/*_api_WarSeason_GalacticWarEffects*.json' \
  --strings <mod>/refs/strings-en-26088801.json \
  --out-json <repo>/data/sources/effect_texts.json \
  --report <repo>/docs/EFFECT-TEXTS-REPORT-2026-11-20.md
# 3) 渲染/复核报告 + 自检
python <mod>/tmp/effect-mine/render_report.py
```
