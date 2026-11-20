# v0.4.1-alpha.6 — 实机复验暴露的缺陷修复（靶星陷阱 / 状态文件被覆盖 / 401 无提示）（2026-11-20）

> **alpha 预览版 · 只修 bug（不改功能）**：只动 `alpha.N`（`0.4.1-alpha.5` → **`0.4.1-alpha.6`**）。

## 背景

v0.4.1-alpha.5 在**真实 UU 路由模式**下做整链路实机复验（登录 / 主界面 / 军械库 / 星球卡面）。
库存注入一次通过，但**变种词条首轮看不到**；排查过程中又撞上一个「状态文件被另一个引擎实例覆盖」的
现场故障。两个都是**产品缺陷**，不是配置问题。

1. **靶星 0 陷阱**：profile 的 `status.planet_effects` 靶星写成了 `index 0`。`0 = SUPER EARTH`
   （星图 hub）——**没有卡面、没有战役**，效果注进去客户端也不渲染。日志却一切正常
   （`REWRITE-EXTRA 星球 0 += effect 1243/1245`、`REWRITE +2 entries`），现场只能靠「游戏里看不到」猜。
   这个坑是 GUI 星球选择器默认值带来的：选择器按游戏索引排序，**默认选中 0 号母星**，
   模板一应用就把效果注到母星上。
2. **状态文件被覆盖 → GUI/CLI 全部 401**：另一个引擎实例把控制面端口 17897「抢占」了
   （Windows `SO_REUSEADDR` 默认允许），并覆盖 `engine.json`；运行中引擎的随机 token 随之丢失。
   结果：GUI 误显示「引擎未运行 / 请求 0 / 抓包关」，`hd2proxy status|verify` 全部
   `{"error":"unauthorized"}`，而真正服务游戏的引擎仍在正常跑（游戏内注入不受影响）。

## 本版修复

| # | 修复 | 位置 |
|---|---|---|
| 1 | GUI 星球选择器**排除 0 号**（SUPER EARTH 不进可选列表；标签解析仍可用） | `gui/catalogs.py` |
| 2 | 星球类模板 `_need_planet(0)` 直接拒绝，提示「母星没有卡面/战役，请选有战役可点的星球」 | `gui/templates.py` |
| 3 | `config.validate` 对 `planet_effects` 指向 0 号给 **warning**（不阻止保存，但保存时就能看见） | `engine/config.py` |
| 4 | 控制面 HTTP 服务**端口独占**（`allow_reuse_address=False` + `SO_EXCLUSIVEADDRUSE`），第二个实例起不来 | `engine/control.py` |
| 5 | 覆盖 `engine.json` 前，若旧文件指向**仍在运行**的引擎 → 先备份 `engine.json.bak` + 日志告警 | `engine/control.py` |
| 6 | CLI `status/verify/shutdown` 遇 401 → 直接给「状态文件与运行中引擎不匹配，重启引擎」的可执行提示 | `__main__.py` |
| 7 | GUI 遇 401 → 顶部 pill 显示「引擎 状态文件不匹配（请重启）」而不是「未运行」（避免用户再起一个实例） | `gui/client.py`、`gui/app.py` |
| 8 | `certs status` 改为实际查询一次根存储（`trusted` 不再恒为 `null`；控制面 `/status` 热路径仍不查） | `__main__.py` |

## 实机验证（2026-11-20 · build 26568081 · war 801 · UU 路由模式）

| 项 | 结果 |
|---|---|
| 库存注入 | `INV REWRITE +103 -0 items`（121 个 mixId 中上游缺 103 个，全部补齐）→ 用户确认**解锁正常** |
| 变种词条（首轮） | 靶星 0（SUPER EARTH）→ 注入下发成功但**卡面不可见** ❌ |
| 变种词条（修正后） | 靶星 **269 BRILLIANCE**（当天有战役的虫族星）→ 卡面出现 **PREDATOR STRAIN** ✅ |

```
12:38:38 REWRITE-EXTRA 星球 269 += effect 1243（raw，绕阵营过滤）
12:38:38 REWRITE-EXTRA 星球 269 += effect 1245（raw，绕阵营过滤）
12:38:38 REWRITE +2 entries (extra: campaigns/owner)
12:38:38 verify: PASS  （TLS 200 / CRL 369 B / Status 56,917 B）
```

截图（用户实机）：[`research/screenshots/real-brilliance-predator-strain-20261120.png`](../research/screenshots/real-brilliance-predator-strain-20261120.png)
（卡面：LIBERATION BRILLIANCE / enemy territory / RESISTANCE **LOW (1.25%)** / **PREDATOR STRAIN** /
`SELECT CAMPAIGN`，同卡面还带服务器原生的 CAUSTIC STRAIN 作对照）。

## 机制结论（写进文档）

- `planet_effects` 是**原始通道**：不按 owner（阵营）过滤，人类星/虫族星都能挂；
- 但**靶星必须「可点」**——有战役的星球卡面才渲染效果；**母星 0 永远不显示**；
- `status.variants` 那条通道才按 owner 过滤，人类星会被丢掉（M4 §2.1 已证）。

## 数据 / 兼容性

- 无数据表变化（`data/catalogs/*`、`data/sources/*` 未动）；
- profile 兼容：历史 profile 里若靶星是 0，本版只在保存时给 warning，不强制改；
- 控制面协议不变（仅绑定方式与错误文案变化）。

## 测试与验收

- 单测 **494 → 500 passed**（+6：控制面端口独占 / 状态文件备份（活/死两种）/ 星球 0 拒绝 /
  config warning / CLI 401 提示 / GUI 401 提示）；
- `check_gate.py` **GATE=PASS**（含 5/5 离线自检：basic / rewrite / hot_reload / sticky / faction）。

## 升级建议

- 已在用 alpha.5 的用户直接覆盖解压即可（profile/证书目录不变）；
- 若你的 profile 里 `status.planet_effects` 指向 0 号，换成**当天有战役**的星球；
- 遇到 GUI「引擎未运行」但游戏注入仍生效：说明状态文件不匹配，按 GUI 顶部提示重启引擎即可。
