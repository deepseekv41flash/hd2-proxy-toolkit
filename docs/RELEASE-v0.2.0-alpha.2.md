# v0.2.0-alpha.2 — 修复「目录里没有的武器解锁不生效」（Shear 等三把未发布武器）(2026-11-17)

> **alpha 预览版 · 仅修 bug**：版本位不变，`0.2.0-alpha.1` → `0.2.0-alpha.2`。

## 问题（用户报）

「物品与战备 · 武器」把 **Shear**（mixId `2112173638`）加到库存后，游戏里不出现；
而同样操作的 **Bolt Pistol**（`3271863995`）、**Melta Mine**（`1339288659`）正常。
抓取 profile 与引擎日志确认：

- profile 里 `inventory.weapons` 有这三条，但 `items = {"add": [], "template": null}`；
- 引擎日志**一条 `ITEMS REWRITE` 都没有** —— 目录行从来没注入过。

## 根因：库存行必须与目录行「成对」注入

| 武器 | 服务端目录（`/api/Progression/items`） | 只注库存行 | 结果 |
|---|---|---|---|
| Bolt Pistol / Melta Mine | **已有**这一条 | 够用 | 游戏显示 ✓ |
| Shear / P-41 Ombudsman / SG-8F Punisher Fire of Liberty | **没有**（未发布） | 客户端不认 | 不显示 ✗ |

客户端要看到一件物品，要求「库存里有」+「服务端目录里有」两者同时成立。目录里没有的物品
必须**克隆一条同族已存在的目录记录、只改 `itemId`/`mixId`** 补上（`items.add` 里的
`{"id": mixId, "template": 模板 itemId}`）；模板行本身必须在服务端目录响应里，否则引擎会跳过。

产品现状的问题是：「物品与战备」四个 tab 的「添加到库存」只写库存行，「目录追加」tab 才写目录行
——按普通物品的方式添加未发布武器时，目录行就漏了。

## 本版修复

1. **添加库存时自动配对目录行**：物品在 `items.json` 里带 `unlock_template`（= 服务端目录缺失）
   时，自动写 `profile["items"]["add"] = [{"id": mixId, "template": 模板 itemId}]`；
   已发布物品（目录里本来就有）不会被写入多余目录行。
2. **移除时对称撤回**：从库存列表删掉这类物品时，一并撤掉配对的目录行。
3. **「目录追加」tab 自动带模板**：选中这类物品追加时不再需要手填全局模板 itemId。
4. **老 profile 自愈**：打开「物品与战备」页时，库存里已有这类物品但缺目录行的自动补齐，
   用户不必删掉重加（幂等，重复打开不会重复写）。
5. **数据化**：新增 `data/sources/unreleased_items.json`（三把武器的模板配对，值来自研究线
   M4 实机验证）；`tools/gen_catalogs.py` 会校验「模板行确实在当前目录快照里」，再写进
   `items.json` 的 `unlock_template` 字段 —— 换 build 后模板失效会在生成阶段报错，而不是等
   用户发现「加了但不出现」。

## 验证

- 引擎级离线预演（真实抓包 3020 行目录作样本）：profile 里写
  `items.add = [{"id": 2112173638, "template": 3866352840}]` → 预演报告
  「物品目录补 itemId 2112173638（克隆模板 3866352840），1 处新增」；
- 单测 **386 → 394**：模板数据一致性、模板行在目录快照里、与 GUI 模板清单不漂移、
  加库存自动配对、已发布武器不写多余目录行、移除对称撤回、目录追加 tab 带模板、老 profile 自愈幂等；
- 门禁/自检与上一版一致（版本一致性 + 语法 + 路径 + 单测 + 5 个离线自检）。

## 升级后怎么用

直接在「物品与战备 · 武器」里正常添加 Shear 即可（会自动配对目录行）；**已经在库存里的**也
会被自愈补上。改完点右上角「应用配置」热更新引擎；如果引擎没在跑，先启动引擎再进游戏。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.2.0-alpha.2-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.2.0-alpha.2-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。
注意：更新 `D:\mod\release-test` 前先关掉正在运行的 GUI（它会锁住 `current/` 里的文件）。

## 已知限制（alpha）

- 只有这三把「目录缺失」的武器有验证过的克隆模板；未来新 build 若再出现同类武器，需要在
  `data/sources/unreleased_items.json` 里补配对值（工具会校验模板是否还在目录里）；
- 3 把武器的 `parent_name` 级内部名缺失、51 条附件无名、战备 30 条无名等数据缺口同上一版；
- 抓包保存的是**改写前**原始响应；`Mission/Session`（重连）`8012016` 不承诺。
