# v0.1.0-alpha.2 — 修复「双击 exe 直接退出、打不开 GUI」（2026-11-17）

> **alpha 预览版**：6 项核心能力已在 M4 实机逐项验证（见 [验收记录](ACCEPTANCE-M4.md)），
> 但更多机型/网络环境/游戏更新后的全流程稳定性仍需观察；0.x 阶段接口与 profile 结构可能变动。

## 本版修了什么

**alpha.1 的问题**：包里的 `hd2proxy.exe` 是命令行入口，双击（无参数）会打印 CLI 帮助后
`exit 2`，控制台窗口随即关闭 —— 看起来就是「打开后自动退出、没有 GUI」。

**alpha.2 的修法**：

1. **无参数默认打开 GUI**：双击 `hd2proxy.exe` 或从命令行不带参数运行，都会直接打开图形界面
   （仍保留控制台窗口，便于排障）；`--help` 才是帮助。
2. **新增 `hd2proxy-gui.exe`**：windowed（无控制台）GUI 入口，普通用户双击这一个即可，
   不会闪黑框；两个 exe 共用同一个 `_internal`，包体积基本不变。
3. 打包流程改为「单 bundle 双 exe」，并在打包冒烟里加入**两个 GUI 入口的存活 + 窗口检查**
   与「无参数打开 GUI」回归断言，避免再发同类问题。

其余功能与 alpha.1 相同（引擎 / GUI 五页 / 6 项能力模板 / 离线预演 / 安装还原 / 证书续期）。

**本版 GUI 实测（打包后的 exe，用 DSH computer use 实际打开并操作）**：

- `hd2proxy-gui.exe` 双击：窗口正常显示五页导航与总览，无控制台窗口；
- 切到「战况改写」页：能力模板条 + 6 张能力卡 + 「离线预演」按钮正常渲染
  （截图 `research/screenshots/alpha2-gui-status.png`）；
- 点「离线预演」：只读窗口正常打开并输出预演结果（截图 `alpha2-gui-preview.png`）；
- `hd2proxy.exe` 无参数：打开 GUI（带控制台，截图 `alpha2-cli-noargs-gui.png`）。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.0-alpha.2-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe） |

**系统要求**：Windows 10/11 x64；不需要装 Python；日常运行不需要管理员（安装/还原各一次 UAC）。

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.0-alpha.2-windows-x64.zip -Algorithm SHA256
```

## 快速开始

```bat
:: 1) 解压后进入 hd2proxy 目录
:: 2) 普通用户：双击 hd2proxy-gui.exe 打开图形界面（无控制台）
::    排障/脚本：hd2proxy.exe 是 CLI，双击它也会打开 GUI（带控制台）
hd2proxy-gui.exe

:: 3) 只检查环境/离线预演（不需要管理员、不需要游戏）
hd2proxy.exe info
hd2proxy.exe preview --profile data\acceptance\m4-b.json

:: 4) 安装（一次 UAC）→ 启动引擎 → 游戏内验证 → 还原
hd2proxy.exe install --profile <你的 profile.json>
hd2proxy.exe engine --profile <你的 profile.json>
hd2proxy.exe uninstall
```

> 从 alpha.1 升级：直接解压 alpha.2 覆盖即可；`%LOCALAPPDATA%\HD2ProxyStudio` 下的配置/证书不受影响。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看 `logs/proxy.log` 的 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连/会话恢复）服务端返回 `8012016`，v0.1 不承诺重连可用。
- 物品目录名不全（约 391/1671 有名字），其余按 id/类别显示。
- **settingsHash 决定星球身份**：生态借用后源星名字会「变成」目标生态那颗星（预期副作用）。
- 休眠星节点号自选（如 BICEP=300），坐标/hash 需按当前 build 的 live warinfo 核对。
- 仅 Windows x64；未做代码签名，首次运行可能被 SmartScreen 提示（更多信息 → 仍要运行）。

## 上一边界（alpha.1）

- [v0.1.0-alpha.1 Release Notes](RELEASE-v0.1.0-alpha.1.md)（功能清单 / 完整已知限制）。
- [M4 实机验收记录](ACCEPTANCE-M4.md)——6 项能力逐项证据。
