# v0.1.1-alpha.3 — 修复「物品与战备」四个 tab 不按类别筛选（2026-11-17）

> **alpha 预览版**：只修界面筛选行为，不动数据格式与能力。按规则只动 `alpha.N`。

## 本版修了什么

用户报：「物品与战备」的**外观** tab 里会出现 `TUBE REDDOT 1,5x`、`Vertical Grip` 这类明显属于
**附件**的条目。

**根因**：四个 tab（武器 / 附件 / 外观 / 战备）原来共用**同一份全量列表**，只是标题不同；
列表填充与搜索都没有用物品的 `category` 字段。所以：
- 外观里混进附件、战备里混进外观；
- 严重时能把附件加到「外观」的库存列表（写进 `profile.inventory.cosmetics`，语义就错了）。

**修复**：

| 位置 | 改动 |
|---|---|
| `gui/catalogs.py` | `search_items(..., category=...)` 支持类别过滤；新增 `item_category(mixId)` |
| `gui/pages/inventory.py` | 四个 tab 各自只显示对应类别：武器 24 / 附件 1176 / 外观 426 / 战备 30 |
| 搜索 | 也带类别过滤：附件 tab 搜 `grip` → 112 条；外观 tab 搜 `grip` → 0 条 |
| 兜底 | 「添加到库存」前校验类别，异类条目拒绝并提示它属于哪一类 |

说明：15 条来自探测文件（`inventory_probe_inject.json`）的混类条目（`category=None`）不属于四类，
仍然只在「目录追加」tab 出现；数据本身没有改，`items.json` 的 `category` 一直是准的。

## 验证

- 单测 **375 → 379**：
  - `tests/unit/test_gui_pages.py`：tab 只显示本类（外观里断言不出现 `TUBE REDDOT` / `Vertical Grip`）、
    搜索不越界、跨类添加被拒；
  - `tests/unit/test_item_names.py`：分类筛选的数据层保证（四类互不重叠、外观不含附件名）。
- GUI 实拍（真 GUI + 真引擎 + 假上游）：外观 tab 现在只有护甲/披风/外观名，例如
  `SS-500 Pale Prosecutor`、`Thundering Hooves of Loyalty`、`Arctic Decree`。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.1-alpha.3-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.1-alpha.3-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。打开「物品与战备」，
四个 tab 现在各自只列本类物品；搜索框也只在本类里搜。

## 已知限制（alpha）

- 战备（30 条）仍显示「内部名未解」（解锁 itemId 与本地数据无已知映射，需抓 store/season 响应再做）。
- 抓包保存的是**改写前**原始响应；改写证据看日志里 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 效果目录 `effects.json` 仍是 26088801 快照（312 条）。
