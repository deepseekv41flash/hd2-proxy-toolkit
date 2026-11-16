# v0.1.0-alpha.3 — 修复 GUI「启动引擎」弹第二个窗口 / 按钮失效（2026-11-17）

> **alpha 预览版**：6 项能力已 M4 逐项实机验证；更多环境/游戏更新的稳定性仍在观察。

## 本版修了什么

**alpha.2 的问题**：打包版 GUI 点「启动引擎」会弹出一个额外的 GUI 窗口；「签发/续期证书、
安装计划、还原计划、验证三连」等按钮也不工作。

**根因**：`gui/client.py` 按源码模式拼命令行：

- 启动引擎：`[sys.executable, legacy_proxy.py, --profile …]`
- CLI 桥（证书/安装/验证）：`[sys.executable, "-m", "hd2proxy", …]`

打包（冻结）后 `sys.executable` 是 **`hd2proxy-gui.exe` 自己**，于是子进程变成
「GUI exe + 一个非法参数」——windowed 版被 PyInstaller 弹错误对话框（看起来就是第二个 GUI 窗口），
并且所有需要调 CLI 的按钮在打包版里全部失效（源码模式正常，所以之前没暴露）。

**修法**：冻结时改用同目录的 **`hd2proxy.exe`** 跑子命令：

- `hd2proxy.exe engine --profile … --cert-dir …`
- `hd2proxy.exe certs renew …` / `install …` / `uninstall …` / `verify` 等

源码模式保持 `python -m hd2proxy` 不变；新增冻结/源码两种模式的 `cli_argv`/`engine_argv` 回归测试。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.0-alpha.3-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.0-alpha.3-windows-x64.zip -Algorithm SHA256
```

## 用法回顾

- 普通用户：双击 **`hd2proxy-gui.exe`**（无控制台）；
- 排障/脚本：`hd2proxy.exe`（CLI，双击也会开 GUI）；
- GUI 内「启动引擎 / 停止引擎 / 切换直通 / 验证三连 / 签发续证 / 安装计划 / 还原计划」本版已恢复；
- 其它与 alpha.2 相同（见 [alpha.2 说明](RELEASE-v0.1.0-alpha.2.md)）。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看 `logs/proxy.log` 的 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 物品目录名不全（约 391/1671 有名字）。
- **settingsHash 决定星球身份**：生态借用后源星名字会变（预期副作用）。
- 休眠星节点号自选，坐标/hash 需按当前 build 的 live warinfo 核对。
- 仅 Windows x64；未签名，首次运行可能有 SmartScreen 提示。
