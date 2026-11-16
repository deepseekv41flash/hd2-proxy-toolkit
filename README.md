# hd2-proxy-toolkit —— HD2 本机代理工具箱

《HELLDIVERS 2》**本机 MITM 代理**的成品化实现：在本地改写客户端收到的战况接口响应
（`Status` / `warinfo` / `Progression/*`），**不碰游戏文件、不进进程内存**。

- 研究线与全部证据留档：[hd2-network-proxy](https://github.com/deepseekv41flash/hd2-network-proxy)
- 本仓库只放**产品代码**：代理引擎 + GUI + 配置面 + 打包，研究仓只读引用。
- 开发计划：[PLAN.md](PLAN.md) ｜ 代码来源与哈希：[docs/PROVENANCE.md](docs/PROVENANCE.md)
- GUI 选型实测（稳定性/资源占用）：[research/TECH-STACK-DECISION.md](research/TECH-STACK-DECISION.md)

> **当前状态：M0 完成（2026-11-16）** —— 引擎代码已迁入并可离线自检；
> 控制面 / GUI / 打包按计划 M1–M5 推进。M0 阶段**没有** GUI，别按成品预期使用。

## 现在能做什么

```bash
python -m pip install cryptography          # 唯一运行依赖
python tools/run_selftests.py               # 应输出 GATE=PASS (5/5)
```

自检全部离线（本机假上游 + 临时数据目录 + 临时证书），不需要游戏、不需要联网、不需要管理员。
5 项覆盖：白名单握手 / 非白名单 SNI 拒绝 / Status 改写 / `selection.json` 热重载 / 粘性星球上限 / 阵营隔离。

也可以直接跑引擎（研究模式，等价于研究线的 `war_proxy.py`）：

```bash
python src/hd2proxy/engine/legacy_proxy.py --help
python src/hd2proxy/engine/legacy_proxy.py --config data/legacy/config.example.json \
    --catalog data/legacy/variant_catalog.json --cert-dir certs --port 8443
```

## v0.1 能力范围（6 项核心）

| # | 能力 | 验证状态（研究线） | 落点（M3） |
|---|---|---|---|
| 1 | 变种词条（tag + mechanic 成对） | ✓ 实机 | 战况 · 变种卡 |
| 2 | 全局效果（GWE type94） | ✓ 实机 | 战况 · 全局效果卡 |
| 3 | 战备试用（type32，≤3） | ✓ 实机 | 物品 · 战备 |
| 4 | 物品解锁（武器/配件/外观 + 目录上架） | ✓ 实机 | 物品 · 各分类 |
| 5 | 休眠星可玩化（planetInfo + 节点 + 战役 + 归属） | ✓ 实机 | 战况 · 休眠星模板 |
| 6 | 生态借用（`settingsHash`） | ✓ 实机 | 战况 · 生态卡 |

引擎侧保留研究线的全部钩子（含防守战役、城市分区、L2 改装等），界面在 v0.2 补齐。

## 目录结构

```
src/hd2proxy/engine/legacy_proxy.py   引擎（M0 逐字节迁自研究线 war_proxy.py，仅改路径）
tests/                                5 个离线自检（迁自研究线，仅改路径）
tools/run_selftests.py                自检总入口（独立证书/数据目录，GATE 判定）
tools/gen_session_certs.py            会话证书签发（ca 模式，≤2 天硬上限）
tools/gen_catalogs.py                 数据目录生成（GUI 用，来自研究仓产物）
data/legacy/                          引擎兼容用的原始目录文件（逐字节复制）
data/catalogs/                        规范化目录（变种/战备/效果/星球/物品/build 指纹）
research/                             技术选型实测脚本与结论（可复现）
docs/                                 来源与哈希、后续架构说明
```

## 安全设计（沿用研究线结论，产品化不放松）

- **单域名白名单** + **仅本机来源**：不是开放代理，非白名单 SNI 直接拒绝（自检第 2 项）。
- **会话证书 ca 模式**：SAN 只有 API 域名，默认 1–2 天硬上限，签完立刻删 CA 私钥；
  本地 8080 提供 CRL（Windows Schannel 必需）；启动前 preflight 校验模式/期限/SAN/多余私钥。
- **默认不落请求/响应体**（抓包需显式开启，且会提示含账号 id）。
- **一键还原**：停进程 → 删信任证书 → 删证书文件 → 删 hosts 行。
- 不修改游戏文件、不注入进程 ⇒ 与 EAC 无关（EAC 只查游戏文件）。

## 边界（研究线已定证，别把承诺说过头）

- 只改**客户端收到的**数据；服务端不落账（伪造星球/战役是"客户端侧真实、战局侧幻影"）。
- `Mission/Session` 类会话恢复端点有校验（`errorCode 8012016`），不要承诺重连可用。

## 里程碑

| M | 内容 | 状态 |
|---|---|---|
| M0 | 仓库骨架 + 引擎迁移 + 5 自检绿 + catalogs | ✅ 2026-11-16 |
| M1 | 引擎模块化 + schema v2 配置 + 控制 API + 安装/还原 + 自动续证 | ⏳ |
| M2 | Tk GUI 骨架（5 页） | ⏳ |
| M3 | 6 项能力卡 + 离线预演 | ⏳ |
| M4 | 实机逐项验收 | ⏳ |
| M5 | PyInstaller 打包 + 文档 + Release | ⏳ |

## 许可

MIT（见 [LICENSE](LICENSE)）。代码与数据来自本人研究仓库，未包含任何游戏资产。
