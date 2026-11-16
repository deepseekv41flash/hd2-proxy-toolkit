# alpha.3 打包版 GUI 实机验收记录（computer use）

- 时间：2026-11-17 01:03–01:25
- 对象：**已发布的 alpha.3 发布包**（用户从 GitHub 下载 zip 解压到 `D:\Downloads\hd2proxy`，
  双击 `hd2proxy-gui.exe` 启动）
- 环境：Windows 11 x64，显示 100% 缩放，GUI 全屏（1920×1080）
- 进程令牌：GUI 为 **Medium 完整性**（双击由 explorer 拉起，正常用户权限）

## 为什么这次能测到「保存 / 启动引擎 / 证书」

此前在 agent shell 里启动同一个 exe 时，本机会把本地未签名 PyInstaller 进程压到
**Low 完整性**（实测令牌 integrity RID=4096，python/pwsh 是 8192），Low IL 无权写
`%LOCALAPPDATA%` → 保存配置/启动引擎必报 `PermissionError(13)`。
用户双击后运行在同一账号的 Medium 令牌下，这几项全部正常 —— 佐证那是环境限制，不是产品缺陷。

## 结果矩阵（全部 PASS）

| # | 功能 | 操作 | 结果证据 |
|---|---|---|---|
| 1 | 5 页导航 | 点击 概览/战况改写/物品与战备/抓包与日志/设置 | 全部切换正常 |
| 2 | 保存配置 | 点顶部「保存配置」 | 状态栏「已保存：…\HD2ProxyStudio\profiles\default.json」 |
| 3 | **启动引擎** | 点「启动引擎」 | 子进程为 `hd2proxy.exe`（**不再弹第二个窗口**）；运行状态=直通；监听 `100.67.169.17:443`；控制面 `127.0.0.1:17897`；证书剩 47.8h |
| 4 | 验证三连 | 点「验证三连」 | `[OK] TLS 握手+白名单域名 · 200 OK · World=801`、`[OK] CRL 服务 · 369 B`、`[OK] Status 回执 · 50449 B 改写后响应` |
| 5 | 切换直通 | 点「切换直通」 | 日志 `passthrough -> False（控制面）`；界面 直通→改写 |
| 6 | 应用配置 | 点「应用配置」 | 日志 `profile 热重载: 默认 · passthrough=True · 生效钩子=(none)` |
| 7 | 签发/续期证书 | 点「签发/续期证书」 | 新证书 `thumbprint_sha1 B3897FDE74E4…`、`self_check: OK`；界面证书信息同步更新 |
| 8 | 停止引擎 | 点「停止引擎」 | 日志 `engine 退出（pid …）`，界面回到未运行 |
| 9 | 安装计划 dry-run | 点「安装计划 (dry-run)」 | 计划弹窗，中文正常（hosts 判定/UAC 提示等） |
| 10 | 还原计划 dry-run | 点「还原计划 (dry-run)」 | 计划弹窗，指纹与当前证书一致 |
| 11 | 应用模板 | 战况改写页「应用模板」 | 弹窗「模板已应用 · 变种词条试用」，顶栏变「未保存」 |
| 12 | 离线预演 | 战况改写页「离线预演」 | 报告：2 处增量、1 类响应会被改写，中文正常 |
| 13 | 抓包设置 | 勾「启用抓包」+「写回 profile」 | 勾选生效；状态栏「抓包设置已写入 profile」 |
| 14 | 运行日志 | 抓包与日志页 | 31 行引擎 stdout，中文全部正常（验证 GBK 解码修复对流式日志生效） |
| 15 | 打开状态目录 / 打开日志 | 设置页两个按钮 | Explorer 分别打开 `HD2ProxyStudio` 与其 `logs` |

## 证据截图

- `research/screenshots/alpha3-fullscreen-overview.png` — 全屏总览（引擎未运行）
- `research/screenshots/alpha3-engine-running.png` — 启动引擎成功（直通/监听/证书）
- `research/screenshots/alpha3-verify-pass.png` — 验证三连三项 OK
- `research/screenshots/alpha3-capture-page.png` — 抓包与日志页（日志中文正常、抓包已勾选）
- `research/screenshots/alpha3-preview-report.png` — 离线预演报告
- `research/screenshots/alpha3-restore-plan.png` — 还原计划 dry-run

## 本轮发现的小问题（候选 alpha.4）

1. 「切换直通」只切换引擎运行时状态（控制面 `/passthrough`），不改 profile；随后点「应用配置」
   会按 profile 把直通恢复，容易让用户以为开关失效。建议 toggle 时同步内存 profile + `mark_dirty`。
2. 证书签发窗「下一步：python -m hd2proxy install …」在打包版里不可执行；应改为
   `hd2proxy.exe install …` 或直接引导到 GUI 的「安装计划」。
3. 离线预演 / 计划 / 证书弹窗长行不换行，左右被裁，看不全内容（轻微 UI 问题）。

## 备注：用 computer use 测打包版 GUI 的经验

- 100% 缩放 + 全屏时坐标最简单：桌面截图即屏幕坐标，用 `SetCursorPos` + `mouse_event` 真实点击。
- 点前先把窗口抬到最前并**校验命中 pid**（Edge/资源管理器可能盖住，Edge 还可能是 topmost）。
- 坐标要从当前截图用像素分析量（按钮边框色 `(38,51,65)`；勾选框在文字左侧约 20px 处）。
  目测预览会差 10–20px，小控件必点空。
- 小控件用「前后截图 diff」判定是否生效，比肉眼看整屏可靠。
