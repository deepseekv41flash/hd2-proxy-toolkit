# v0.6.0-alpha.2 — 修复：`/api/Progression/inventory` 响应没套账本（服务端给得少时看不到本机库存）（2026-11-23）

> **bug 修复版**：只动 `alpha.N`（`0.6.0-alpha.1` → **`0.6.0-alpha.2`**）。

## 一、问题：live 链路漏接了一处存档合并

`0.5.4-alpha.3` 把 `saves.apply_to_inventory` 改成**只抬不降**（`max(服务端, 账本)`），
但那次只修了**纯函数**；引擎的响应改写链里只有 `Progression` 根响应 / `Stats` / 成就 / 结算
这几处接了账本，**`/api/Progression/inventory` 这一处一直没接**（只有 `save-preview` 在用它）。

后果（服务端给得少时才会暴露）：

- 离线 / 私服 / 回滚 / mock 验收场景里，上游返回的 `items` 很少或为空 ⇒
  游戏里**看不到本机账本里已有的货币与物品行**（存档层"兜底"能力等于没生效）；
- 官方服务器上因为服务端本来就给全量，所以这个缺口一直没被实机发现。

## 二、修复

- 新增 `ActiveSave.apply_inventory(body)`（与 `apply_progression` / `apply_stats` 同一形态：
  读档 → 纯函数合并 → 事件/日志）；
- 引擎响应链在存档层那段接上 `INV_PATH` 分支，语义与全库一致：

| 上游（服务端） | 结果 |
|---|---|
| 数量 ≥ 账本 | **听服务端的**（服务端仍是事实源，绝不改小） |
| 数量 < 账本 | 用账本兜底（只抬不降） |
| 整份没给 `items` | 视为空库存，按账本补行 |
| 与「本地账号」四类库存注入同时生效 | 在**注入后的视图**上合并，互不覆盖 |

- 日志/事件：`SAVE INV +N 行（存档 <saveId>，只抬不降）`；`/status.save.events` 里 `kind=inventory`。

## 三、测试

- **688 → 689 passed**，`GATE=PASS`；
- 新增：
  - `test_active_save.py::test_apply_inventory_raises_and_fills_rows`（抬升 / 补行 / 无改动引用不变 / 没给 items 也能补）；
  - `test_engine_flow.py` 端到端第 9 步：上游 `3901895556=999999` 保留（服务端更大）、
    账本 `718265621=1` 补行、`/status` 出现 `inventory` 事件。

## 四、发现方式（顺带记录一个可复用的 dry-run 手法）

2026-11-23 晚做**离线 mock dry-run**：`profile 模式 + legacy --config 里的 upstreamTest` 同时给 ——

```bash
hd2proxy.exe engine \
  --config  legacy.json       # {"host": "...", "upstreamTest": "127.0.0.1:9099"}
  --profile profile.json      # 正常 profile（saves.enabled=true）
  --cert-dir <临时证书目录> --no-control
```

要点：**legacy 模式单独用不启用存档层**（`spec is None` 时 `proxy.save=None`），
但 `--profile` 会让引擎走 profile 模式（存档层启用），而 `upstreamTest` 仍从 `--config` 生效
⇒ 不用改产品代码就能把上游指到明文 mock，验证「服务端给得少 → 存档层兜底」。
发现：`Progression` 正确兜底（exp 1 → 210、成就 4 条回填），**`inventory` 没兜底** —— 即本次修复。

## 五、升级

直接换包即可（`release-test/current` 已同步）。本机账本格式未变，无需迁移；
无需重导证书（`cert.days=2` 内不会换发 CA；若恰好赶上续期，按 README「常见故障 · Error 60」重跑一次 `install`）。
