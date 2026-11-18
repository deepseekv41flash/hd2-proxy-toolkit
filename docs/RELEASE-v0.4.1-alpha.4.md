# v0.4.1-alpha.4 — 战备命名收尾 + 全局效果 target 链补名（命名 2405 → 2441，效果 174 → 202）（2026-11-19）

> **alpha 预览版 · 数据补全（非新功能）**：只动 `alpha.N`（`0.4.1-alpha.3` → **`0.4.1-alpha.4`**）。

## 背景

alpha.3 把 wiki「已发布战备」缺口 22 条补齐后，目录还有两部分没名字：

1. **战备相关的剩余空位**：cat11 许可行 13 行、cat10 记账子行 38 行；
2. **全局效果（GWE）312 条**里 138 条没有名字 —— 而它们的 `nameHash` locid 在本机**完整的**
   英文本地化语料里不存在（alpha.2 的 v4 已证：30 个 bundle 全解 → 24,834 locid，与旧 build 逐 id 相同），
   locid 路线到此为止。

## 本版做法

### ① 战备命名收尾（+36 行）

| 步骤 | 条数 | 来源 / 方法 |
|---|---:|---|
| cat11 再补 client 表名 | **7** | 同 v5 的 `+4 == 原生哈希` 链；这批不属于 wiki「可解锁战备」清单（Eagle Rearm / Resupply / Medical Supplies / Eagle A2A Missiles / Walking Barrage Smoke / Orbital Confetti / Eagle Fly By） |
| cat10 记账子行反推 | **29** | cat11 许可 ↔ cat10 子行严格 1:1；用已命名许可行的名字反补未命名子行（纯结构推断） |

结果：cat11 **102/108** 有名、cat10 **102/111** 有名（剩 9 行：父行无名 6 + 无父行 3）。

### ② 全局效果：target 链派生 28 条英文名

剩余 138 条效果虽然没名字文本，但不少带**目标语义**：

```
effect.values[0]（战备 effect_hash）
  → 目录 cat10 行 mix（cat10.mixId == effect_hash、itemId == native_hash）
  → native_hash → stratagem_settings.csv 的 +4 列 → client 显示名（英文）
```

- 命名空间交叉验证：type32 `values[0]` 命中 15/15、type36 11/14。
- **只派生语义已验证的类型**：type32「临时配发战备 ✓」15 条、type36「DSS 临时装备 ✓」13 条 = **28** 条。
  type50（「双 hash ⚠ 未解」）技术上匹配 1 条，语义未验证，**不纳入**。
- 纯数值（type21/25/23/43…）、presence（type71）、tag（type40）不派生 —— 没有名字文本，硬造等于编造。
- 名字取客户端英文显示名，不加「临时/临时装备」修饰（`effect_type`/`target` 已表明语境）。

效果名覆盖：**174 → 202 / 312**。

## 数据变化

| 项 | 0.4.1-alpha.3 | **0.4.1-alpha.4** |
|---|---|---|
| `items.json` 有名字 | 2405 | **2441**（目录行 2414 / 3020） |
| `items.json` 未解 | 657 | **621** |
| cat11 战备行有名 | 95 / 108 | **102 / 108** |
| cat10 记账行有名 | 73 / 111 | **102 / 111** |
| `effects.json` 有名字 | 174 / 312 | **202 / 312** |
| 新增 `name_source` | `stratagem-client-settings` | **`stratagem-permit-parent`**（items）、**`target-chain`**（effects） |

## 命名口径（重要）

用户 2026-11-19 定：**星球/全局效果等新增名字统一用英文**，避免中文译名与游戏内本地化不一致
（历史教训：把「光能者」译成「卡牌」）。本版所有新增名字都是英文（客户端/游戏内文本原文），
中文译名统一留待后续本地化批次一次性处理。

## 工具与测试

- 新增 `tools/apply_cat10_parent_names.py`（cat10 子行反推；只补空位 / 幂等 / 无 parent 跳过 / `--check` 只读）。
- `tools/apply_stratagem_client_names.py` 的 coverage 更新参数化（按类别），供新工具复用。
- `tools/gen_catalogs.py` 新增效果名覆盖层（`data/sources/effect_names_derived.json`）：
  **只补 `name` 为空的行，不覆盖任何上游名字**，写 `name_source="target-chain"` + `name_evidence`（可追溯）。
- 新增单测 8 条（cat10 反推 5 + 效果名 3）。**单测 486 passed**（478 + 8）；`check_gate.py` **GATE=PASS**。

## 已知边界（回答「其它类别能不能也这样解」）

- ✅ 能榨干的：战备 cat11/cat10 结构反推、效果里 target 可解的两类 —— 本版已做完。
- ❌ 不能：cat7/17/18/19/20 共 135 行（客户端没有「行 id + 名字字段」表，只能截图 OCR / 线上数据）；
  cat9 余 10、cat23 余 23（locid 文本不存在，服务器领先客户端，等新 build）；
  效果剩余 110 条（纯数值 / 占位 / tag 设计上无名字）。
- 剩余目录未名 642 → **606** 行，瓶颈都是「客户端里没有文本」，不是方法缺失。

## 安装

同前：下载 `hd2proxy-release.zip` + `SHA256SUMS`，解压后运行 `hd2proxy_gui.exe`；
证书信任/续期流程见 README「快速开始」。
