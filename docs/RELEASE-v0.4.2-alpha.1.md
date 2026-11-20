# v0.4.2-alpha.1 — 无需游戏拉取当前战况（CLI `live` + GUI 推荐靶星）（2026-11-20）

> **功能版本**：`X.Y.Z` 变化（`0.4.1-alpha.6` → **`0.4.2-alpha.1`**）。

## 背景

选靶星、离线预演、效果菜单都要看「当前战况」，但以前只能等游戏启动后由引擎抓包得到。
实测确认：官方 API 的这三个端点是**免登录的公共只读接口**（不需要 Steam 票据 / sessionId），
而且直拉到的 `GalacticWarEffects` 与游戏内经过引擎抓包的数据 **sha256 完全一致**
（`b87f679b…`，2026-11-20）。既然如此，就没必要为了看战况去开游戏。

## 新能力

| 入口 | 用法 |
|---|---|
| CLI | `hd2proxy.exe live`（默认可读文本；`--json` 机器可读；`--out <dir>` 落盘快照） |
| GUI | 战况改写页 → 星球词条卡片 →「**拉取战况·推荐靶星**」 |
| 库 | `hd2proxy.engine.live`：`fetch()` / `summarize()` / `campaign_targets()` / `suggest_targets()` |

### CLI 示例

```bat
:: 需要网络能到官方 API（DoH 会绕开 hosts，不会打到本机引擎）
hd2proxy.exe live
hd2proxy.exe live --faction terminid --limit 5
hd2proxy.exe live --json --out D:\mod\out\live
```

输出（节选，2026-11-20 实拉）：

```
战况快照（无需游戏）
  主机 api.live.prod.thehelldiversgame.com · 出口 172.200.240.121 · 用时 7.9s · 2026-11-20T13:13:03+08:00
  战局 war 801 · status time 87210980
  273 星球 / 41 战役 / 166 个星球效果 / 61 条攻击边 / GWE 315 条

推荐靶星（有战役=卡面可点，按阵营）：
  · 虫族 TRANDOR            index=100 campaign=51692
  · 虫族 BORE ROCK          index=124 campaign=51769
  · 虫族 NIVEL 43           index=211 campaign=51758
  · 虫族 OVERGOE PRIME      index=213 campaign=51780
  · 虫族 PEACOCK            index=216 campaign=51781
  · 虫族 OMICRON            index=259 campaign=51428
  · 虫族 LUXURIANT          index=268 campaign=51715
  · 虫族 BRILLIANCE         index=269 campaign=51778

提示：靶星必须卡面可点（有战役）；0 号 SUPER EARTH 母星永远不显示。
```

### 技术要点

- **必须 DoH**：hosts 把这个域名指向本机引擎，系统解析会自环；先 DoH 拿真实 IP，
  再 **SNI = 域名 + 真实 IP** 直连，官方证书正常校验（不像游戏那样走本地 MITM）；
- 只发 GET，不带 `Accept-Encoding`（拿明文 JSON）；响应上限 8 MiB；默认 15 s 超时；
- 「推荐靶星」规则来自实机结论（`docs/ACCEPTANCE-M4.md` §2.1 / §7）：**只有有战役的星球卡面
  才能显示星球词条/变种效果**，母星 `0` 永远不显示；推荐列表把前线（敌方占有 owner 2/3/4）排前面。

### GUI 用法

1. 打开 GUI →「战况改写」页 → 星球词条卡片 →「拉取战况·推荐靶星」；
2. 后台拉取（不要求引擎在跑，也不要求游戏在跑）；
3. 弹窗列出候选靶星（阵营 + 名字 + 索引），填/选一个 → 自动填入星球选择器；
4. 选 effect →「添加词条」→ 右上「应用配置」热更新。

## 兼容性与边界

- 只读：不改任何服务端数据、不改 profile、不写 hosts；
- 需要网络能访问官方 API（当前 UU 路由模式下实测通）；官方不可达时不可用（那属于离线/私服研究线）；
- 端点免登录，但仍建议低频使用（本工具只在手动点击/命令时拉取，无后台轮询）；
- 无数据表变化；profile 格式不变。

## 测试与验收

- 单测 **500 → 511 passed**（新增 11 条：摘要 / 战役靶星 / 阵营过滤 / 名称标注 / 落盘 /
  DoH 失败 / WarId 解析 / CLI json·text·失败路径）；
- 实拉验证：GWE 315 条、Status 273 星球 / 41 战役 / 166 星球效果，与游戏内抓包逐字节一致；
- `check_gate.py` GATE=PASS。

## 升级建议

- 直接覆盖解压即可；CLI 新命令 `hd2proxy.exe live`，GUI 新增按钮；
- 若你想继续手选靶星：记住「有战役的星球才显示」，用 `live` 命令先看一眼当天可点的星。
