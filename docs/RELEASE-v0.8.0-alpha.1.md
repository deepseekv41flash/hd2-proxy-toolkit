# v0.8.0-alpha.1 — 每玩家结算响应体 `mission_end.json` + 身份头 uncertain 细化（2026-11-24）

> **功能版本**：`X.Y.Z` 变化（`0.7.0-alpha.2` → **`0.8.0-alpha.1`**）。
> 契约：研究线 `SELFHOST-SAVE-CONTRACT-2026-11-24` §7 后续项第 1 条（`mission_end.json` 每玩家响应体）。

## 一、`mission_end.json`：每玩家最近一局**完整原始结算响应**

### 为什么存原始响应而不是"重建"

账本只存增量（经验/物品/包进度），按语义重建响应体必然与官方 shape 漂移（客户端对缺字段敏感）。
从 v0.8.0 起引擎在 `Mission/end` 入账时**把完整原始响应整份落盘**到该玩家账本：

```
earned.missions.last_response      # 最近一局的完整响应体（dict，~2 KB）
earned.missions.last_response_at   # 落盘时间
```

- 只在**首见**该 `missionId` 时写入（同 missionId 重试直接跳过，不覆盖）；
- 解析失败不入账也不存（不影响游戏）；
- 只留最近一局，体积有界。

`hd2proxy save-export` 若发现账本里有该字段 → 直接写 `players/<steamId64>/mission_end.json`（shape 原样，不重建、不合并）。
没有则跳过该文件（契约里它是可选端点）。`--no-optional` 可整体关闭可选端点（含本文件）。

### 端到端验证（隔离引擎 + 本地明文 mock，2026-11-24）

- mock 返回真实结算模板 `12b9a872`（1614 B，exp=936）；经引擎转发后账本记录
  `last_response`（17 键、exp 936、missionId `22c690d9…`）；
- 导出样例：`D:\mod\tmp\save-export-sample-mission\players\76561198968648344\`
  （含 `mission_end.json` 2236 B；**键集与顺序与模板逐项一致**；counts exp=1146、结算 2 局）；
- 单测/e2e：`record_mission_end` 落盘原始响应、重复 missionId 不覆盖、导出有/无/关闭三态。

## 二、身份头 `uncertain` 细化（研究线建议）

v0.7.0-alpha.2 起「身份校验失败 → 完全不盖头」。研究线指出：完全不盖会让自建服落到 **IP 映射兜底**，
而该客户端本局早前可能学过一个可信身份 ⇒ 有把旧身份当当前身份的风险。

v0.8.0 起改为：身份不可信时**只发**

```
X-HD2-Account-Source: uncertain      # 不带 X-HD2-Account
```

自建服据此**跳过 IP 映射与唯一玩家兜底、直接回落公共数据**（研究线覆盖层已实现该路径）。
客户端自带 `X-HD2-Account`（lobby 请求）时仍不追加任何头。

## 三、测试

- **720 → 727 passed**，`GATE=PASS`；
- 新增：结算原始响应落盘/去重/导出三态（5 条）+ uncertain 头两条 + e2e 原始响应断言。

## 四、升级

换包即可；账本 schema 向后兼容（老档无 `last_response` 时只是不导出 `mission_end.json`，
该玩家下次打一局后自动具备）。自建服侧无需改动（覆盖层早已支持该文件名）。

## 五、后续

- JSONL 结算事件流（形态 3）：等 `mission_end.json` 在研究线侧跑通后一起定行格式；
- `shared/` 拆分：按自建服目录约定再加开关。
