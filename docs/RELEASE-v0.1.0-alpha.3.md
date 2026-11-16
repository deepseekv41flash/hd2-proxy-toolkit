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

## 打包 GUI 实测又抓到两个问题（同版本一并修掉）

发布前用 computer-use 在**打包后的 exe** 上逐页实测，另外发现两处冻结模式才有的毛病：

1. **子进程中文变成一串 `?`**：冻结版 PyInstaller 引导器的 stdout 编码由控制台代码页决定
   （中文 Windows = cp936），`PYTHONUTF8` / `PYTHONIOENCODING` 对冻结进程**不生效**
   （四种组合实测输出字节完全相同），而 GUI 按 UTF-8 解码 → 「安装计划（dry-run）」整段乱码。
   现在 GUI 收原始字节：先按 UTF-8 解，失败回退 GBK；引擎日志流同样处理。
2. **日志目录跟着 exe 走**：冻结版把 `logs/`、`runtime/` 写在 exe 旁边，若整个目录被放到
   Program Files / 只读位置会静默写失败——日志丢失、点「打开日志」直接弹
   `FileNotFoundError(2, '系统找不到指定的文件。')` 原文。现在冻结版这两类目录统一落在
   `%LOCALAPPDATA%\HD2ProxyStudio`（源码模式仍在仓库内），并且文件不存在时给一句人话提示。

## 打包版 GUI 逐页实测（computer use，2026-11-17）

在**解压后的 `hd2proxy-gui.exe`** 上逐页点击验证（不是源码模式）：

| 项 | 结果 | 证据 |
|---|---|---|
| 5 页导航（总览/战况改写/物品与战备/抓包与日志/设置） | ✅ 全部可切换、内容正确 | `research/screenshots/alpha3-gui-*.png` |
| 战况改写：应用模板 | ✅ 内存生效（顶栏变「未保存」+ 说明弹窗） | — |
| 战况改写：离线预演 | ✅ 打开报告窗（直通模式不改写、samples 路径、增量说明） | — |
| 总览：安装计划（dry-run） | ✅ CLI 桥走通，中文输出正常（本版修复后） | `alpha3-gui-install-plan.png` |
| 抓包与日志页 / 设置页渲染 | ✅ 字段与目录全部正确 | `alpha3-gui-capture.png` / `alpha3-gui-settings.png` |
| 打开日志（文件还没生成） | ✅ 一句人话提示，不再抛 `FileNotFoundError` 原文 | — |
| 保存配置 / 启动引擎 / 签发证书 | ⚠ 本次测试环境不可用（见下） | — |

> **测试环境限制（不是产品缺陷）**：本机把从 agent shell 启动的**未签名本地 PyInstaller exe**
> 放在 **Low 完整性级别**（实测令牌 integrity RID=4096，而 python/pwsh 是 Medium 8192），
> Low IL 无权写 `%LOCALAPPDATA%` → 保存配置/写 profile/启动引擎在本环境必然 `PermissionError(13)`。
> 同一台机器上用 Medium 权限跑同一段保存逻辑是成功的，真实用户双击运行是 Medium，
> 因此这三项归为「本次环境测不到」，不是 alpha.3 的回归。

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
