# data/samples — 离线预演用的样本响应

这 5 份 JSON 是**裁剪过的真实结构响应**，给 `engine/preview.py` 用：不装证书、不开游戏、不改 hosts，
就能把「这个 profile 会改客户端收到的什么」先算出来。

| 文件 | 对应请求 | 内容 |
|---|---|---|
| `status.json` | `GET /api/WarSeason/801/Status` | planetStatus / planetActiveEffects / campaigns / planetEvents / planetRegions / globalEvents / jointOperations |
| `warinfo.json` | `GET /api/WarSeason/801/warinfo` | planetInfos[]（index / settingsHash / position …） |
| `inventory.json` | `GET /api/Progression/inventory` | items[]（mixId）+ customization[] |
| `items.json` | `GET /api/Progression/items` | 物品目录数组（itemId / mixId / progressionCategory / tags …） |
| `customize.json` | `GET /api/Progression/Items/Customize/v2` | items[]（mixId32 / activeIndex / customizations[].slots[8]） |

## 来源与边界

- 原始结构来自研究线的**真实抓包**，来源文件是 `tests/fixtures/inputs/*.json`（同一份拷贝），
  只保留引擎钩子会读的字段，数值/星球/物品 id 做过去相关化：**不含账号信息、设备指纹、token**。
- 样本是裁剪的，所以它不能证明「实机一定生效」，只能证明「本地管线会怎么改」：
  - 样本里没有的星球/物品 → 预演看不到变化，但实机 live 响应里有就可能生效；
    这类情况 `preview()` 会在 `warnings` 里明说，不会假装「不会生效」。
  - 真实响应里还有大量与改写无关的字段（账本、进度、限时活动…），这里不搬运。
- `preview()` 只读这些文件，**不写盘**；跑预演不会碰 `logs/`、`runtime/`、证书目录。

## 怎么换成自己的 live 样本

1. 打开 GUI「抓包」页（或 CLI `python -m hd2proxy engine` 带 `capture.enabled=true`），
   勾选要抓的路径（默认 `api/`），进游戏走一遍让它重新拉这几发响应；
2. 抓包目录里找到上面 5 个 endpoint 对应的响应体；
3. 覆盖 `data/samples/<name>.json` 即可 —— 预演只认文件结构，不认来源；
4. 注意脱敏：真实响应可能带账号/进度字段；只保留钩子会读的部分，别把个人数据提交进仓库。
