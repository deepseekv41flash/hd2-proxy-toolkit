# v0.7.0-alpha.2 — 身份头安全加固：GetMotd 校验失败时不再断言身份（2026-11-24）

> **bug 修复版**：只动 `alpha.N`（`0.7.0-alpha.1` → **`0.7.0-alpha.2`**）。

## 一、问题（研究线自建服侧提出，按"宁可不盖"原则加固）

v0.7.0-alpha.1 的引擎会给上游补 `X-HD2-Account`（供自建服按玩家分档）。但存在一个信任边界漏洞：

- 若某局 `GetMotd` **已到达**，却因为换号切档异常 / 解析失败 / 落盘失败而没有完成校验，
  引擎会继续用**预绑定（上一账号）**的身份值盖头 —— 自建服可能把别人的档给到当前玩家；
- 研究线建议：**这种时候宁可不盖**，让自建服按"无身份头"回落公共数据（比错给别人的档安全）。

## 二、修复

- `ActiveSave` 记录 `_getmotd_seen` / `_identity_uncertain`；
- `_observe_identity` 包一层异常兜底：校验/切档抛异常 → 标记 `identity_uncertain`，
  日志 WARN `⚠ 身份校验失败（…）：本局不再向上游盖身份头`，事件 `identity-uncertain`（`/status.save.events` 可见）；
- `identity_header()` 守卫：
  - `identity_uncertain` → **不盖**；
  - `GetMotd` 已到但 `verified=False` → **不盖**；
  - 其余情况照旧（`prebind` / `getmotd` / `getmessages` 三态来源标注）；
- 成功校验的路径不受影响（已有测试钉住）。

## 三、测试

- **718 → 720 passed**，`GATE=PASS`；
- 新增：GetMotd 校验失败 → `identity_header()` 返回 None + `identity-uncertain` 事件；
  正常 GetMotd 后仍返回 `(steamId64, "getmotd")`。

## 四、与研究线对齐的其它事项（无需改码）

- 他们复核 alpha.1 样例：A **PASS 42/42**、B **PASS 22/22**（M01–M07 含 `baselineFiles` 结构、
  `baselineSha256` 配方可复算、逐文件与基线核对）；并确认我方 fixtures 与其抓包**同源**（sha256 逐字节相等）。
- `X-HD2-Account-Source` 我方 alpha.1 起就已同时发送（`prebind|getmotd|getmessages`）；
  他们的覆盖层已按此做信任分级（`getmotd/getmessages` 学 IP 映射、`prebind` 不污染 IP 映射、命中不到回落公共数据）。
- 后续：`mission_end.json`、JSONL 结算事件流（等前者稳定后定行格式）、`shared/` 拆分按服务端目录约定。

## 五、升级

换包即可；无配置变化。自建服侧无需改动（只是身份头在异常场景下会消失，回落逻辑已就绪）。
