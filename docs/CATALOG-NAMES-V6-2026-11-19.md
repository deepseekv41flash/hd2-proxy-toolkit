# 战备名收尾 v6 + 效果名 target 链（2026-11-19）

> 本轮两件事：① 战备命名收尾（cat11 再补 7、cat10 子行反推 29 ⇒ 命名 2405 → **2441**）；
> ② 全局效果按 `values → 战备 hash` 目标链派生 28 条英文名（效果名 174 → **202** / 312）。
> 口径：**一律英文名**（用户 2026-11-19 定：星球/全局效果等统一英文，中文译名留待本地化批次）。

## 1. 战备命名收尾（+36 行）

### 1.1 cat11 再补 7 条（`name_source=stratagem-client-settings`）

v5 只补了 wiki「已发布 Permit 表」里的 22 条；cat11 还剩 13 行无名，其中 **7 行在客户端
`stratagem_settings` 表里有显示名**（同样走 `+4 == 原生哈希` 那条链），只是不属于 wiki 的
「可解锁战备」清单：

| mix_id | 名字 | client 内部名 | 原生哈希 | 说明 |
|---:|---|---|---|---|
| 8469881 | Eagle Air-to-Air Missiles | `EAGLE. (NOT USED) AIR-TO-AIR MISSLES` | `b2e060bb` | 表内标 (NOT USED) |
| 37634583 | Eagle Rearm | `EAGLE. REARM` | `e4b4f558` | wiki 归 Ship（呼叫类） |
| 879717956 | Resupply | `CONSUMABLES. RESUPPLY` | `33babe96` | 补给呼叫 |
| 2659326411 | Orbital Walking Barrage Smoke | `ORBITAL. WALKING BARRAGE SMOKE` | `e2446220` | 烟幕变体 |
| 3318281709 | Orbital Confetti | `ORBITAL CONFETTI` | `fe5dc262` | Liberty Day 2026 限时 |
| 3705419442 | Eagle Fly By | `EAGLE FLY BY` | `443bc93` | Liberty Day 2026 限时 |
| 3852140214 | Medical Supplies | `CONSUMABLES. HEALTH PACK RACK` | `84df23be` | 补给类消耗品 |

（另 6 行仍无名：5 行 client 无对应哈希 + 1 行 client 名字状态是 `unknown`／显示名为「未知」。）

### 1.2 cat10 记账行反推 29 条（`name_source=stratagem-permit-parent`）

目录里 cat11（战备许可）与 cat10（记账子行）**严格 1:1**（子行 `parent` == 许可 `mixId`）；
v2 的 `stratagem-permit-child` 是「子行名 → 许可行」，这次反向用「许可行名 → 子行」，
纯结构推断、无新数据源：**+29 行**（cat10 有名 73 → **102/111**，剩 9 行是父行无名或无父行）。

新增工具 `tools/apply_cat10_parent_names.py`（只补空位 / 幂等 / 无 parent 或 parent 无名一律跳过 / `--check` 只读）
+ 5 条单测。

## 2. 全局效果：target 链派生 28 条英文名

背景：312 条 GWE 效果里 174 条已有名字（115 条靠 `nameHash` → locid，59 条靠 target 表）。
剩余 138 条的 `nameHash` locid **不在**本机完整英文本地化语料里（v0.4.1-alpha.2 的 v4 已证：
30 个 bundle 全解 → 24,834 locid，与旧 build 逐 id 相同），所以「locid 补名」到此为止。

但效果表里还有**目标语义**可用：

```
effect.values[0]（战备 effect_hash）
  → 目录 cat10 行 mix（cat10.mixId == effect_hash，itemId == native_hash）
  → native_hash → stratagem_settings.csv 的 +4 列
  → client 内部名 → 显示名（英文）
```

- 命名空间交叉验证：type32 的 `values[0]` 15/15、type36 11/14 命中 legacy `effect_hash`；
  用 `cat10` + client 表提升为**英文名**后共 **28 条**（type32 15 + type36 13）。
- **只对语义已验证的类型派生**：type32「临时配发战备 ✓」、type36「DSS 临时装备 ✓」。
  技术上也匹配到 type50（「双 hash ⚠ 未解」）1 条，但语义未验证，**不纳入**。
- 名字直接用客户端英文显示名（不加「临时/临时装备」等修饰——`effect_type`/`target` 字段已表明语境）。
- 数值参数类（type21/25/23/43…）、presence（type71）、tag（type40）**不派生**：
  它们要么没有名字文本，要么目标只是内部键/哈希，硬造名字等于编造。

产物：`data/sources/effect_names_derived.json`（28 行，含 `effect_id / name / value_hex /
ref_mix / ref_native_hash / ref_client_internal_name / old_target`）；
`tools/gen_catalogs.py` 新增覆盖层加载与合并（**只补 name 为空的行，不覆盖任何上游名字**，
写 `name_source="target-chain"` + `name_evidence`）；`tests/unit/test_effect_names.py` 3 条断言。

效果名覆盖：**174 → 202 / 312**；剩余 110 条为纯数值/占位/tag/presence 类（无名字文本）。

## 3. 数据变化

| 项 | 0.4.1-alpha.3 | **0.4.1-alpha.4** |
|---|---|---|
| `items.json` 有名字 | 2405 | **2441**（目录行 2414 / 3020） |
| `items.json` 未解 | 657 | **621** |
| cat11 战备行有名 | 95 / 108 | **102 / 108** |
| cat10 记账行有名 | 73 / 111 | **102 / 111** |
| `effects.json` 有名字 | 174 / 312 | **202 / 312** |
| `name_source` 新增 | `stratagem-client-settings` | **`stratagem-permit-parent`**（items）、**`target-chain`**（effects） |

## 4. 结论：这条路线还能走多远（回答「其它类别能不能也这样解」）

- **能**（本轮已榨干）：战备相关的 cat11/cat10 结构反推 + client 表补充；效果里 target 可解的两类。
- **不能**：
  - cat7/17/18/19/20（135 行）：客户端没有任何「行 id + 名字字段」的表 —— 只能截图 OCR / 线上数据。
  - cat9 余 10、cat23 余 23：locid 文本在完整英文语料里不存在（服务器领先客户端），等新 build。
  - 效果剩余 110 条：`nameHash` locid 无文本 / tag 类设计上无名字 / 数值参数类无名字。
- 剩余 642 → **606** 行目录未名（items 口径 621/3062），瓶颈都在「客户端没有文本」，不是方法问题。

## 5. 复跑

```bash
cd <repo>
python tools/apply_stratagem_client_names.py      # cat11 补名字（29 行数据，幂等）
python tools/apply_cat10_parent_names.py          # cat10 子行反推（结构推断，幂等）
python tools/gen_catalogs.py                      # 重新生成 data/catalogs/*
python -m pytest tests/ -q                        # 486 passed
```

## 6. 产物清单

| 文件 | 作用 |
|---|---|
| `data/sources/stratagem_client_names.json` | cat11 名字 29 行（22 已发布 + 7 收尾），含 client 内部名/哈希 |
| `data/sources/effect_names_derived.json` | 效果名 target 链派生 28 行（含证据链字段） |
| `tools/apply_stratagem_client_names.py` | cat11 补丁工具（已参数化 coverage 更新，供下个工具复用） |
| `tools/apply_cat10_parent_names.py` | cat10 子行反推工具 |
| `tools/gen_catalogs.py` | 新增效果名覆盖层（只补空位 + `name_evidence`） |
| `tests/unit/test_apply_cat10_parent_names.py` | 5 条 |
| `tests/unit/test_effect_names.py` | 3 条 |
