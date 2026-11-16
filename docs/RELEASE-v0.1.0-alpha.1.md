# v0.1.0-alpha.1 — 首个可分发预览版（2026-11-16）

> **这是 alpha 预览版**：6 项核心能力已在 M4 逐项实机验证（见
> [验收记录](ACCEPTANCE-M4.md)），但更多机型 / 网络环境 / 游戏更新后的全流程稳定性
> 尚未充分验证；接口与 profile 结构在 0.x 阶段可能变动。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.0-alpha.1-windows-x64.zip` | onedir 分发包（解压即用，约 15 MB） |
| `SHA256SUMS.txt` | 校验和（zip + 主程序） |

**系统要求**：Windows 10/11 x64；不需要安装 Python。日常运行不需要管理员，
只有「安装 / 还原」各弹一次 UAC。

校验和：以下载附件 `SHA256SUMS.txt` 为准（PowerShell 校验）：

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.0-alpha.1-windows-x64.zip -Algorithm SHA256
```

## 快速开始

```bat
:: 0) 解压后进入 hd2proxy 目录
:: 1) 自检（不需要管理员、不需要游戏）
hd2proxy.exe info
hd2proxy.exe preview --profile data\acceptance\m4-b.json

:: 2) 图形界面（推荐）
hd2proxy.exe gui

:: 3) 安装（hosts + 本机 CA 信任；一次 UAC）——GUI「总览」里也有按钮
hd2proxy.exe install --profile <你的 profile.json>

:: 4) 启动引擎（GUI 里点「启动引擎」等价）
hd2proxy.exe engine --profile <你的 profile.json>

:: 5) 验完还原（hosts + 证书；GUI「还原」按钮等价）
hd2proxy.exe uninstall
```

首次使用建议顺序：`info` → `gui` → 设置页保存 profile → 总览页「安装计划 dry-run」看一眼 →
`install` → 启动引擎 → 游戏内验证 → `uninstall`。
配置/证书/日志都在 `%LOCALAPPDATA%\HD2ProxyStudio\`；程序目录里的 `data/` 可以直接改
（catalogs、samples、acceptance 都是纯文本/JSON）。

## 本版包含

- 本机 MITM 引擎（443）+ 本地 CRL（8080），单域名白名单 + 仅本机来源；控制面 `127.0.0.1 + token`。
- schema v2 单一 profile、热重载、旧 `config.json/runtime/*.json` 一键迁移。
- ca 模式会话证书（SAN 单域名、≤2 天、签完删 CA 私钥）+ 剩余 <12h 自动续期 + preflight。
- hosts 原子写/备份；UAC 自提升安装与还原；成败以回读系统状态为准。
- Tk GUI 五页（总览/战况改写/物品与战备/抓包与日志/设置），关窗不停引擎。
- **6 项能力模板**：变种词条 / 全局效果 / 战备试用 / 物品解锁 / 休眠星四件套 / 生态借用；
  延后项（防守战役/城市分区/L2 改装）折叠在「扩展 / 实验」并标验证状态。
- **离线预演**：`preview` 对真实抓包裁剪样本输出「会改什么 / 为什么没生效」，不开游戏。
- `data/` 内置 438 星球目录（含**游戏索引**映射，避免行号≠游戏索引的坑）、312 效果、58 战备、
  25 变种、1671 物品条目 + 预演样本 + M4 验收配置。

## M4 实机验收结论（6/6 PASS）

变种词条（PARTION → PREDATOR STRAIN）· 全局效果（轨道加特林变燃烧）· 战备试用（MG-43/M-105）·
物品解锁（P-41 / SG-8F / LAS-22 / LAS-13 TRIDENT）· 休眠星（BICEP 出现、有连线、可选中；
完整结算在研究阶段已实机通过）· 生态借用（TRANDOR → 落叶林）。
安装→三连验证→游戏内验证→还原闭环跑通，还原后 hosts 域名行 0、证书存储 0。
逐项证据：[ACCEPTANCE-M4.md](ACCEPTANCE-M4.md)。

## 已知限制（alpha）

- **抓包文件是改写前的原始响应**（用于分析服务端数据）；改写证据看 `logs/proxy.log` 的
  `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连/会话恢复）服务端返回 `8012016`，v0.1 不承诺重连可用。
- 物品目录名不全（约 391/1671 有名字），其余按 id/类别显示。
- **settingsHash 决定星球身份**：生态借用后源星名字会「变成」目标生态那颗星（预期副作用）。
- 休眠星节点号由用户自选（如 BICEP=300），坐标/hash 需按当前 build 的 live warinfo 核对。
- 仅 Windows x64；未做代码签名，首次运行可能被 SmartScreen 提示（「更多信息 → 仍要运行」）。
- 单机使用；不是开放代理，非白名单 SNI 直接拒绝。

## 卸载

- 程序内 `hd2proxy.exe uninstall`（或 GUI「还原」）会移除 hosts 行与证书信任；
  证书文件仍保留在 `%LOCALAPPDATA%\HD2ProxyStudio\certs`（≤2 天，可手工删）。
- 删除程序目录即完成卸载；`%LOCALAPPDATA%\HD2ProxyStudio` 下是配置/日志/备份，按需保留或删除。

## 构建

本包由仓库源码用 PyInstaller 6.16 onedir 构建（`python tools/build_dist.py`），
门禁：`python tools/check_gate.py`（297 单元测试 + 5 个离线自检 + 语法/路径检查）。
