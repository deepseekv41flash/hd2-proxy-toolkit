# v0.1.1-alpha.2 — 武器内部名补齐：走 dlbin 只读路线（2026-11-17）

> **alpha 预览版**：alpha.1 补了「附件 + 外观」的内部名（1520/1671），本版把**武器类**也补上，
> 覆盖到 **1544/1671**。仍是数据补全，只动 `alpha.N`。

## 本版改了什么

alpha.1 之后，「物品与战备」里主武器 / 副武器 / 投掷物 / 背包仍显示 `xxx · 武器（内部名未解）`。
本版用 **dlbin 只读路线**从客户端本地数据里把名字解出来：

| 环节 | 做法 |
|---|---|
| 数据表 | `generated_entities.dl_bin` 的 `LoadoutEntryComponentData`（块 `0x4F2CF417`，199 行 × 32 B） |
| 行字段 | `+0x00` = **后端物品 id**，正好等于服务端 `/api/Progression/items` 目录行的 `itemId` |
| 名字 | 该行所属实体（哈希图键）在 `EncyclopediaEntryComponentData` 里的内部名 |
| 例子 | `Veto`、`Gallant`、`Shear`（LAS-22 Shear ✓）、`Smokescreen`、`Pineapple`、`Missile Pistol` … |

- 新增工具 `tools/extract_item_names.py`（只读）：读 `refs/dlbin/plaintext-<build>/generated_entities.dl_bin`
  + 类型库 + 研究仓（hd2-datamined）的实体名，产出 `data/sources/item_names_derived.json`
  （build **26568081**：199 行，**191 行有名字 / 177 个唯一 itemId**）；
- `tools/gen_catalogs.py` 增加第 4 条名字规则（`name_source = loadout-entity`），只填空缺、不覆盖；
- 效果：名字覆盖 **1520 → 1544 / 1671**；武器 tab 直接显示名字，搜索框可搜 `veto` / `gallant` / `shear`。

## 为什么是「只读路线」

2026-11-13 起**写**游戏 `data/game/*.dl_bin` 会被 EAC 判「未知的文件版本」（连 1 bit 差分也拦），
但**读**一直可用：解包密钥在 `refs/dlbin/keys/`，明文缓存在 `refs/dlbin/plaintext-<build>/`。
所以本版只做只读提取；换 build 后重跑：

```powershell
python tools/extract_item_names.py            # 默认取 plaintext-* 里最大的 build
python tools/gen_catalogs.py                  # 重新生成 items.json
```

工具会打印 LoadoutEntry 的几何自证结果；几何对不上（typelib 与 build 漂移）会直接报错，不会静默出错数据。

## 已知限制

- **战备（30 条）仍无内部名**：目录 cat 11 的解锁 `itemId` 在本地 **55 张数据表 + 实体库**里都搜不到映射
  （全表 u32/u64 扫描 0 命中，仅 9 处偶然命中），说明客户端靠**服务端 / 商店响应**关联；
  当前抓包集合里没有 store/season 响应。要补齐需要抓一次「战备/商店」页面（本工具的抓包功能可以做），
  下一版再处理。界面明确显示「内部名未解」，不编造。
- 剩余无名字 127 条：战备 30、新版附件 49（当前 build 改装选项表里也没有这些 id）、其它目录外条目 48。
- 实体名来自 hd2-datamined 用 `.strings` 语料解析的 `entity-locid-names.json`（build 26088801）；
  26568081 新增实体可能缺失（本次 8 行无名），不影响已有条目。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.1-alpha.2-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.1-alpha.2-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。打开「物品与战备」→ 武器 tab，
现在能直接看到 `Veto` / `Gallant` / `Shear` 等内部名；搜索框支持按名字搜。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看日志里 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 效果目录 `effects.json` 仍是 26088801 快照（312 条）。
