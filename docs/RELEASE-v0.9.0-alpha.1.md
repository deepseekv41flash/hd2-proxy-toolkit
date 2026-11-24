# v0.9.0-alpha.1 — 结算事件流 `settlements.jsonl`（形态 3）+ manifest 游标（2026-11-24）

> **功能版本**：`X.Y.Z` 变化（`0.8.0-alpha.2` → **`0.9.0-alpha.1`**）。
> 契约：研究线 2026-11-24 JSONL 口径（样例校验 **PASS 9/9**，六条口径已确认）。

## 一、导出物新增：每玩家 `settlements.jsonl`

`hd2proxy save-export` 在导出文档的同时，把该玩家**最近一局结算**追加为一行事件：

```
<data-root>/players/<steamId64>/settlements.jsonl
```

- **append-only**：只追加、不回写历史行；UTF-8 / LF / 无 BOM / 一行一对象（紧凑、不 pretty print）；
- **幂等去重**：按该玩家文件内的 `missionId`；重复导出同一局**不重复追加**；
- 首次有事件才建文件；`--no-optional` 时整体不产（含 `mission_end.json` 与游标）；
- 进程被杀最多丢最后一行；坏行由消费端容忍（我方读取时跳过、**不删**）。

### 行格式（例）

```json
{"schema":1,"event":"settlement","ts":"2026-11-24T13:39:43+08:00","saveId":"steam_76561198968648344","steamId64":"76561198968648344","hd2AccountId":"11893343864225233967","missionId":"22c690d9-51f2-4d4e-be90-22380a69d08a","operationId":1242,"missionIndex":2,"experience":936,"items":{"897894480":7,"3608481516":4434},"packages":{"277818845":{"level":5,"progress":459,"platformAccountId":"11893343864225233967"}},"itemSource":"rewards","catalogBuild":"93e7575a/3021/1007203","source":"mission_end"}
```

| 字段 | 语义 |
|---|---|
| `schema`/`event` | 固定 `1` / `"settlement"`（为未来 `purchase`/`consume` 留位） |
| `ts` | ISO，**始终带显式时区偏移**（旧账本无时区 → 按本机时区补 `+08:00`） |
| `saveId`/`steamId64`/`hd2AccountId` | 身份三件套（与 manifest 一致） |
| `missionId`/`operationId`/`missionIndex` | 去重键 / 审计（老局 `missionIndex` 可为 null） |
| `experience` | 本局经验增量 |
| `items` | **本局物品增量**（`{mixId(str): amount(int)}`，负=消耗） |
| `packages` | 结算后**绝对** `level/progress`（服务端 max 合并、幂等）+ `platformAccountId`=**本玩家** |
| `itemSource` | 限定枚举 `rewards\|badges\|both\|none`（未知值收敛 `none`，不映射成 `mission_end`） |
| `catalogBuild` | 目录版本（审计/跨版本对比） |
| `source` | **每行显式带**：`mission_end`=有完整原始响应；`ledger-only`=老局只有账本增量（`packages:{}`） |

## 二、manifest 新增

```json
"settlements": {"ledgerOnly": 1},
"settlementsCursor": {"lines": 2, "lastMissionId": "…", "lastTs": "…"}
```

游标**导出时按 JSONL 文件重算**（账本不存）；消费端可据此对账（行数/末条 missionId/时间）。

## 三、老账本兼容

- alpha.1 之前的局只有 `missions.last`（无 `last_response`）→ 事件 `source=ledger-only`、
  `packages={}`、`missionIndex` 可为 null；**补发一次**，之后仅追加（时间戳单调）；
- 账本 schema 不变、无需迁移。

## 四、测试

- **728 → 738 passed**，`GATE=PASS`；新增 `tests/unit/test_settlements.py` 10 条：
  字段/枚举/时区、ledger-only 变体、幂等去重、新局追加+游标、manifest 计数、`--no-optional`、
  JSONL 格式（紧凑/LF/无 BOM）、坏行容错、**不变量**（`mission_end.json` 与事件里的
  `platformAccountId` 均等于玩家 identity）。

## 五、研究线校验

样例将放回 `D:\mod\tmp\save-export-sample-mission\`（含 `settlements.jsonl` 与游标），
另放一份 ledger-only 样例；研究线校验器 J01–J10 复跑预期全绿。

## 六、后续

- `shared/` 公共数据拆分：按自建服目录约定加开关（当前只产 `players/` + `index.json`）；
- 结算事件流若后续要 `purchase`/`consume` 事件，沿用 `schema`/`event` 位扩展。
