# v0.3.0-alpha.2 — 修复切「总览」页卡顿 + 弹几个 PowerShell 窗口（2026-11-17）

> **alpha 预览版 · 只修 bug**：版本位不变（`0.3.0-alpha.1` → `0.3.0-alpha.2`）。
> 用户反馈：「工具 GUI 切总览页会卡住一会，并且弹出几个 powershell 窗口」。

## 现象与根因

两条线索来自同一个原因：**GUI 是 windowed 程序，却 spawn 了一批控制台子进程**。

1. **弹窗**：冻结版 `hd2proxy-gui.exe` 没有自己的控制台（这是设计如此，普通用户不该看到黑框）。
   Windows 上，无控制台的进程启动控制台程序时，系统会**为子进程新开一个控制台窗口**。
   一次现场检查 spawn 7 个，于是「弹出几个 PowerShell 窗口」（Windows 11 默认控制台宿主是
   Windows Terminal，外观就是 PowerShell）。
2. **卡顿**：这 7 个子进程是在 **Tk 主线程同步跑**的，冷启动实测 **755 ms**：
   - 443 / 8080 / 17897 每个端口都要两条 `netstat -ano -p TCP` 与 `-p TCPv6`（共 6 条）；
   - 一条 `tasklist /NH /FO CSV` 查进程名（冷启动 **573 ms**，占了大头）。
   更糟的是总览页每次刷新都会调 `sysprobe.clear_caches()`，端口缓存形同虚设 ——
   每切一次页就重跑整轮。

## 修复（四项）

### 1. 所有外部命令统一隐藏窗口

`engine/sysprobe._run()` 现在给每个子进程带 `CREATE_NO_WINDOW` +
`STARTF_USESHOWWINDOW`/`SW_HIDE`。这一项是**根上**的修复：只加节流、不隐藏窗口，
即使一次 spawn 也会闪一个控制台窗口。

### 2. 端口查一次就够：一条 netstat + 进程名走 Toolhelp

- `netstat -ano`（**不带** `-p`）一条输出天然同时含 TCP 与 TCPv6 监听 → 解析成
  `{端口: [占用者]}` 全量监听表，缓存 3 秒，443/8080/17897 三个端口共用；
- 进程名改用 **`CreateToolhelp32Snapshot` + `Process32FirstW/NextW`（ctypes）**：
  不启子进程、不弹窗、毫秒级；`tasklist` 只在快照失败时兜底。

### 3. 总览页诊断节流，引擎启停时强制重算

- `_refresh_diag()` 加 **2.5 秒节流**（切页、切标签页都走 `refresh`，2.5 s 内的结果够用）；
- 删掉「每次刷新都 `clear_caches()`」；
- 「系统自检」按钮保留**强制**清缓存重算（用户点它就是要此刻的准确状态）；
- 「启动引擎 / 停止引擎」完成后由 App 清缓存并**绕过节流**重算 —— 端口占用者刚变，
  不能让总览继续显示旧状态。

### 4. 另外两条同样会弹控制台窗的路径

- `engine/server.py::port_owner_report`（BIND FAIL 时的占用者报告）改走 `sysprobe`
  （隐藏窗口 + 缓存），不再自己 spawn `netstat`/`tasklist`；
- `gui/client.py::run_cli`（「安装 / 证书续期」等按钮调 CLI）补隐藏窗口参数 ——
  否则这些按钮同样会闪一个控制台窗。

## 实测数据

本机（源码版，同一台机器、同一轮命令）计时：

| 场景 | 修复前 | 修复后 |
|---|---|---|
| `diagnostics.collect()` 冷启动 | **755 ms / 7 次 spawn** | **55 ms / 1 次 spawn**（一条 `netstat -ano`，36 ms） |
| 缓存命中（切页/重绘真实路径） | 每次重跑 | **1 ms / 0 次 spawn** |
| 控制台窗口 | 每个子进程一个 | 0 |

## 验证

- 单测 427 → **434 passed**，新增/更新：
  - **回归断言**：连续查 3 个端口只许 spawn **一条** `netstat -ano`（修复前的 6 条锁死）；
  - `_parse_all_listeners` 多端口 / 通配 / IPv6 / 排除 ESTABLISHED；
  - `_subprocess_kwargs` 在 Windows 返回 `CREATE_NO_WINDOW` + `SW_HIDE`，且 `_run` 真的把它
    传给 `subprocess.run`（防「定义了没接线」）；
  - `clear_caches` 三张缓存（端口 / 进程名 / 监听表）全清；
  - Toolhelp 快照失败时退回 `tasklist` CSV；
  - 总览诊断 2.5 s 内只算一次；警告显示/消失用例改为模拟已过节流窗口。
  - 受进程名实现变化影响的 6 个用例改为注入进程名表，不再依赖本机真实进程。
- 门禁：`python tools/check_gate.py` → **GATE=PASS**（版本 / py_compile / 无绝对路径 / 单测 / 5 个离线自检）。

## 打包版实机验证（计算机操作，非源码版）

对打包后的 `dist\hd2proxy\hd2proxy-gui.exe` 实测。取证方式：20 ms 轮询的独立监控脚本
（`EnumWindows` 记录控制台类窗口 `ConsoleWindowClass` / `CASCADIA_HOSTING_WINDOW_CLASS`，
启动前已存在的终端窗口作基线排除；同时用 Toolhelp 快照记录 GUI 进程的新子进程）。

| 场景 | 结果 |
|---|---|
| 从 dist 冷启动 GUI（windowed，无控制台） | 1648 次采样期间 **0 个控制台窗口** |
| 设置 → 总览 连切两次（每次间隔 3.2 s > 2.5 s 节流） | 抓到 **2 个 GUI 子进程** —— 正好对应两次切页各 1 条**隐藏的** `netstat -ano`（证明现场检查真的重算了，不是被节流跳过后「看起来没事」），期间 **0 个控制台窗口** |
| 点「启动引擎」 | 引擎正常拉起（独立进程），总览显示「运行状态：改写」「监听 100.67.169.17:443 · 控制面 17897」，红字现场检查消失 |
| release-test 区同步后（v0.3.0-alpha.2，sha256 与 Release 资产一致）重启 GUI + 引擎 | 正常；证书剩 46.1 小时、无告警 |

对照修复前：同样的操作会 spawn 7 个带窗口的控制台子进程（每个都闪一个窗口）+ 主线程阻塞 755 ms。


## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.3.0-alpha.2-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.3.0-alpha.2-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。
更新 `D:\mod\release-test` 前先关掉正在运行的 GUI（它会锁住 `current/` 里的文件）。

## 已知限制（alpha）

- 端口/进程探测仍有 3 秒缓存：刚被别的程序抢占的端口最多延迟 3 秒才在界面上反映；
  要立刻确认请点「系统自检」（强制重算）；
- 非 Windows 平台上 `_subprocess_kwargs()` 返回空（该问题只存在于 Windows 的 windowed 程序）；
- 引擎侧上游偶发超时（多 IP 重试）仍是待办，未包含在本版。
