# v0.7.0-alpha.1 — 自建服导出（`save-export`）+ 身份头盖章（2026-11-24）

> **功能版本**：`X.Y.Z` 变化（`0.6.0-alpha.3` → **`0.7.0-alpha.1`**）。
> 契约来源：研究线 `SELFHOST-SAVE-CONTRACT-2026-11-24`（形态 2 主 + 形态 3 辅）。本版只做**最小切片**：
> 合并后的三个端点文档 + manifest + index，**外加**多人自建服必需的身份头盖章。

## 一、`hd2proxy save-export`：基线 ⊕ 本机账本 → 自建服可回放的响应文档

### 用法

```bash
hd2proxy save-export \
  --save-file "%LOCALAPPDATA%\HD2ProxyStudio\runtime\saves\steam_76561198968648344.json" \
  --baseline  <自建服提供的基线目录> \
  --data-root <自建服数据根> \
  [--no-optional] [--json]
# 也支持 --save <saveId>（默认取 _last.json 指向的档）
```

基线目录里放端点响应体即可，文件名兼容两套：

| 端点 | 可接受文件名 | 输出 |
|---|---|---|
| Progression | `progression.json` / `api_Progression.json` | `progression.json` |
| Inventory | `inventory.json` / `api_Progression_inventory.json` | `inventory.json` |
| Stats/profile | `stats_profile.json` / `api_Stats_profile_summary.json` | `stats_profile.json` |
| Stats/profile/<war>（可选） | `stats_profile_801.json` / `api_Stats_profile_801_summary.json` | `stats_profile_war.json` |
| Items/Customize/v2（可选） | `customize_v2.json` / `api_Progression_Items_Customize_v2.json` | `customize_v2.json` |

**可选端点默认导出**（研究线建议：都是按玩家数据，缺省会让服务端回落公共数据、把 A 玩家的数据给 B 看）。

### 输出布局（服务端直接加载）

```
<data-root>/
  index.json                              # 玩家映射索引（schema:1）
  players/<steamId64>/
    manifest.json
    progression.json  inventory.json  stats_profile.json
    stats_profile_war.json  customize_v2.json     # 基线有就导出
```

`manifest.json`：

```json
{
 "schema": 1,
 "saveId": "steam_76561198968648344",
 "identity": {"steamId64": "76561198968648344", "hd2AccountId": "11893343864225233967"},
 "catalogBuild": "93e7575a/3021/1007203",
 "generatedAt": "2026-11-24T13:06:23+08:00",
 "engine": {"version": "0.7.0-alpha.1", "mergePolicy": "max-monotonic/v1"},
 "source": {
   "baselineSha256": "…", "baselineId": "fresh",
   "baselineDir": "<调用时传入>", "baselineDirResolved": "<绝对规范化路径>",
   "baselineFiles": {"progression": {"name": "progression.json", "sha256": "…"}, "…": "…"},
   "ledgerSha256": "…"
 },
 "counts": {"experience": 210, "achievements": 4, "inventoryRows": 56,
            "statsNonZero": 23, "missions": 1}
}
```

### 保证（研究线 §5 硬要求）

- **shape 保真**：输出 = 基线**深拷贝只改值**（复用引擎 `saves.apply_to_*`，不按语义重建 JSON）；
  顶层键序 / 成就数组元素 `{id,value}` / 统计 27 键集 / 库存行 `{mixId,amount,isDiscovered}` 全部保持基线形状；
- **合并语义**：单调量 `max`（experience / 统计 / 成就 / 包进度）、库存款**只抬不降**、集合类并集；
- **原子写**（`.tmp` → rename），失败不留半截文件；
- **可复现**：同 baseline+ledger 两次导出，端点文件**逐字节一致**，manifest 仅 `generatedAt` 不同；
- 研究线校验器 `validate_save_export.py` 实测：样例 A **PASS 36/0**、样例 B **PASS 19/0**。

## 二、身份头盖章：`X-HD2-Account`（多人自建服分档）

**问题**（研究线实测）：客户端登录体里**没有账号 id**；`/api/Progression` 在登录后 ~1 s 就读，
而身份头要到 ~21 s 的 lobby 请求才出现 ⇒ 多人自建服在"首屏读档"那一刻无法分辨是谁。

**方案**（产品侧拍板 v1 = 引擎盖章）：引擎对**所有上游请求**补两个头：

```
X-HD2-Account: 76561198968648344          # 优先 SteamID64；无则 HD2 20 位 id
X-HD2-Account-Source: prebind|getmotd|getmessages
```

- `prebind` = 仅按 `_last.json` 预绑定（尚未校验，服务端可自行决定信不信）；
- `getmotd` / `getmessages` = 本局已观测/校验的身份，可信；
- 客户端 lobby 请求**自带**该头时引擎**不重复添加**（多值头会让服务端取错）；
- 只对上游生效；官方服务器忽略未知头，无副作用。

边界：头可伪造 ⇒ 仅适用于**可信自建服**（自己人/朋友）。产品化正解（Steam ticket 校验）列入后续。

## 三、测试

- **708 → 718 passed**，`GATE=PASS`；
- 新增：`save-export` 13 条（合并值 / shape 保真 / manifest 自描述 / 确定性 / 幂等 / 原子写 / 基线缺失 / 未识别档回退 / CLI）、
  身份头 8 条（prebind / getmotd / 换号 / 仅 HD2 / 无身份 / 盖章纯函数 / 不重复）；
- e2e 增补：假上游记录请求头 → 断言预绑定阶段 `source=prebind`、`GetMotd` 校验后 `source=getmotd`。

## 四、已知边界（本版不做）

- `mission_end.json`（每玩家最近一局结算响应体）：账本只存增量，重建不出完整响应体 → 后续从"捕获的完整响应 + 账本"做；
- JSONL 结算事件流（形态 3）：下一版；
- `shared/` 公共数据拆分：服务端自备；
- HTTP 拉取导出接口：暂不做（自建服是启动时文件加载）。

## 五、升级

换包即可；无需改 profile。`save-export` 为新增子命令，旧行为不变。
