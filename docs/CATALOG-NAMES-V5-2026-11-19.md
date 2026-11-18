# 战备名字补全 v5：wiki 已发布清单对账（2026-11-19）

> 结论先说：wiki 7 个 Permit 表里 **95 条已发布战备全部能在服务端目录找到行（id 已知）**，
> 其中 73 条已有名字 —— 剩下 **22 条只缺名字**。这 22 条的名字在客户端 `stratagem_settings`
> 静态表里齐全，已补进快照（`name_source="stratagem-client-settings"`，high）。

## 1. 任务与口径

用户要求「对照 wiki 的 Stratagems 页，找出已发布但我们没找到 id↔名字对应关系的战备」，
并明确排除 `Other` / `Unavailable` 类型与 `Orbital Confetti`、`Eagle Fly By`。

| 口径 | 取值 |
|---|---|
| wiki 侧 | 7 个 Permit 表（Orbital / Eagle / Support Weapon / Backpack / Vehicle / Sentry / Emplacement），去重后 **95** 条 |
| 本地侧 | `data/catalogs/items.json` 的 `stratagem` 类 = cat11 战备许可行，**108** 行（v3 时 73 有名 / 35 无名） |
| 「有对应关系」 | 目录行（mix_id）+ 名字（name）两者都有 |

排除项核对：`Other` 类型只有 `Orbital Illumination Flare` 一条；`Unavailable` 是 Cargo 表里
`stratagem_type` 为空的三条（`Rapid Acquisition` / `Seize Industrial Complex` / `Spread Democracy`）；
section 9 是 Mission Stratagems 表（Ship/Objective）。都不计入 95。

## 2. wiki 取数：别抓渲染 HTML，走 Cargo API

`Stratagems` 页的表格是 Cargo 模板生成的（`Template:Stratagem Table` →
`Module:Cargo Template Utilities|stratagemTable`）：

- ❌ 直接 fetch 渲染页面：只在 ~50KB 处截断（读到 Support Weapons 一半）。
- ✅ `api.php?action=parse&prop=sections` 可拿到分节索引（6/7/8 = 三个 Permit 分节，9 = Other）。
- ✅ **`api.php?action=cargoquery&tables=Stratagems`** 直接拿结构化行，一次全量。
  字段：`image, _pageName, stratagem_code, base_cooldown, unlock_cost, unlock_level, source, stratagem_type`。
  表里**没有** id / hash 列（试过 `id` / `stratagem_id` / `mix_id` / `hash`，全部 MWException），
  所以对账只能靠名字。
- 注意 Cloudflare：本机 `curl` 与 PowerShell 直连均 403，**走本地 Clash 代理**
  （`curl -x http://127.0.0.1:7897`）可通。

## 3. 本地对账链（每跳都有证据）

```
cat11 行 mix_id
  --parent-->  cat10 子行 item（uint32 原生哈希）
  --(+4 列)--> repo-datamined/refs/exports/stratagem_settings.csv 的 client 行
  --> client 内部名（如 "SENTRYS. AUTOCANNON"）
  --> refs/stratagem-display-names.json 的 display_name / wiki_title
```

列语义已验证：`stratagem_settings.csv` 的 **`+4` 列 == 旧 `data/legacy/stratagem_catalog.json`
的 `native_hash`**，153 行里 58 条逐一对上（该文件恰好就是那 58 条战备的完整表）。
`+248` 列不是 `effect_hash`（0 命中，别用）。

用这条链把 108 条 cat11 行反查 client 名：**100/108 命中**（8 条 client 侧没有对应哈希，
是未发布/占位行），再与 95 条 wiki 名做归一匹配。

### 3.1 名字漂移（踩坑记录）

client `display_name` 是**旧名**（`Machine Gun` / `Grenade Launcher` / `Commando` / `Guard Dog`），
wiki 已加代号前缀（`MG-43 Machine Gun` / `GL-21 Grenade Launcher` / `MLS-4X Commando`）。
归一化时只能剥「首词且首词含数字」的代号前缀；早期的正则把 `EMS`/`Heavy` 这类普通大写词
也当代号剥掉，导致 `EMS Mortar Sentry` / `Gas Mortar Sentry` / `Mortar Sentry` 三行互撞。
修正后 92/95 直接命中，剩 3 条按名字唯一对应（见 §5）。

## 4. 结果：22 条只缺名字（本次补全对象）

`name` 取 wiki 全名（含代号，与当前游戏内显示一致）；`client_display_name` 同时留档。

| # | 战备 | 类别 | mix_id | client 内部名 | 原生哈希 |
|---:|---|---|---:|---|---|
| 1 | Orbital 120mm HE Barrage | Orbital | 2273387135 | `ORBITAL. 120MM HE STRIKE` | `3f6103f6` |
| 2 | Orbital Airburst Strike | Orbital | 4266803236 | `ORBITAL. AIRBURST STRIKE` | `5d020fdd` |
| 3 | Orbital Precision Strike | Orbital | 1497469599 | `ORBITAL. PRECISION STRIKE` | `d2062cbc` |
| 4 | Eagle Airstrike | Eagle | 2474408748 | `EAGLE. AIRSTRIKE` | `49cfda04` |
| 5 | Eagle Cluster Bomb | Eagle | 4102799034 | `EAGLE. CLUSTERBOMBS` | `d9efc7d3` |
| 6 | Eagle Strafing Run | Eagle | 1726445906 | `EAGLE. AIR SUPPORT` | `a7619b75` |
| 7 | B/FLAM-80 Cremator | Support Weapon | 1256411515 | `TEAM WEAPONS. HEAVY FLAMETHROWER` | `8763e173` |
| 8 | MS-11 Solo Silo | Support Weapon | 699439563 | `TEAM WEAPONS. MINI MISSILE SILO` | `4fb52679` |
| 9 | PLAS-45 Epoch | Support Weapon | 1598175737 | `TEAM WEAPONS. PLASMA BLASTER` | `fe02c2e3` |
| 10 | AX/AR-23 Guard Dog | Backpack | 4111938309 | `BACKPACK. GUARD DOG (Drone)` | `1cf5bd48` |
| 11 | AX/FLAM-75 Hot Dog | Backpack | 1522042130 | `BACKPACK. GUARD DOG FLAMETHROWER (Drone)` | `4312d593` |
| 12 | SH-20 Ballistic Shield Backpack | Backpack | 4062012700 | `BACKPACK. BALLISTIC SHIELD BACKPACK` | `c7e2797b` |
| 13 | EXO-51 Lumberer Exosuit | Vehicle | 1868571870 | `VEHICLES. COMBAT WALKER LUMBERER` | `b7f54989` |
| 14 | EXO-55 Breakthrough Exosuit | Vehicle | 4190666565 | `VEHICLES. COMBAT WALKER BREACHER` | `219bb243` |
| 15 | TD-220 Bastion MK XVI | Vehicle | 815654998 | `VEHICLES. BASTION(tank)` | `7756f32c` |
| 16 | A/AC-8 Autocannon Sentry | Sentry | 2393461238 | `SENTRYS. AUTOCANNON` | `32ef9ab3` |
| 17 | A/FLAM-40 Flame Sentry | Sentry | 3721265441 | `SENTRYS. FLAMETHROWER` | `1c4bb6bd` |
| 18 | A/LAS-98 Laser Sentry | Sentry | 133465871 | `SENTRIES. LASER CANNON SENTRY` | `393e6019` |
| 19 | A/M-12 Mortar Sentry | Sentry | 689724506 | `SENTRYS. MORTAR` | `5e52ffca` |
| 20 | A/MG-43 Machine Gun Sentry | Sentry | 1565347406 | `SENTRYS. MACHINEGUN` | `fcb5ffa9` |
| 21 | A/MLS-4X Rocket Sentry | Sentry | 3847625280 | `SENTRYS. ROCKET` | `2ac7580f` |
| 22 | E/AT-12 Anti-Tank Emplacement | Emplacement | 3559742963 | `EMPLACEMENTS. ANTI TANK EMPLACEMENT` | `2d741bf8` |

**没有一条已发布战备缺 id** —— 缺口 100% 在名字侧。补完后 cat11 = **95/108 有名**。

其余 13 行 cat11 不是已发布战备：`Eagle Rearm` / `Resupply` / `Medical Supplies` /
`Eagle (NOT USED) Air-to-Air Missiles` / `(NOT USED) Additional Strafing Runs` /
`Orbital Walking Barrage Smoke` / `Orbital Confetti` / `Eagle Fly By` + 5 行 client 侧无对应哈希的
疑似占位行。

## 5. 3 条曾被误判为「缺行」的（复核记录）

`S-11 Speargun`（mix 1348724067）/ `Eagle 110mm Rocket Pods`（2975812841）/
`LIFT-850 Jump Pack`（2981920770）的 client 哈希对不上 cat11 子行，名字匹配阶段没命中；
但本地本来就有行且有中文名（`name_source="stratagem-permit-child"`），**不属于缺口**。
它们的 client 侧哈希分别是 `d76f4b`（`TEAM WEAPONS. HARPOON GUN`）/ `48826cf`
（`EAGLE. 110mm ROCKET PODS`）/ `41a5797`（`BACKPACK. JUMPPACK BACKPACK`），
在 3020 行目录里确实不存在 —— 说明这几行的目录 id 与 client 原生哈希不同源，不是缺行。

## 6. 产物与集成

| 文件 | 作用 |
|---|---|
| `data/sources/stratagem_client_names.json` | 22 条补丁数据（mix_id → 英文名 + client 内部名/哈希/wiki 名，证据字段齐全） |
| `tools/apply_stratagem_client_names.py` | 把补丁数据写进快照：只补空位、同名跳过（幂等）、异名报错（不覆盖）、同步 coverage 并记 `coverage.name_patches` |
| `tests/unit/test_apply_stratagem_client_names.py` | 6 条单测：补空位 / 幂等 / 拒绝覆盖 / `--check` 只读 / 缺证据报错 / 类别不符报错 |

集成方式说明：快照是「`resolve_catalog_names.py` 基线 + 客户端静态表增量补丁」两段式
（v3 那批 dlbin 名字也是补丁方式加上去的，保留分源归因）。本工具的补丁记录会落在
`coverage.name_patches` 里，`--check` 可只校验不写盘。

## 7. 边界与后续

- 名字目前是**英文名**。现有 73 条是中文名（旧 `stratagem_catalog.json` + GWE 效果名），
  所以目录里现在是中英混排；中文译名留待后续批次（用户明确「先只补英文名」）。
- wiki 侧无 id/hash 字段，对账只能靠名字；因此「已发布清单」这一侧的证据强度是
  「名字唯一对应」而不是哈希等值（92/95 是哈希链直证，3 条按名字唯一对应）。
- 5 行 cat11（mix 1132456535 / 1384485193 / 2779327431 / 4047793312 / 4114345722）既不在 wiki
  已发布清单、也没有任何本地名字来源，疑似未发布/占位，未动。
