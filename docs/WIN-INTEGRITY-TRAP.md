# Windows 完整性标签陷阱：本地测试区里的 GUI 写不了 AppData

> 2026-11-17 实测记录。症状：从 release 测试区双击 `hd2proxy-gui.exe`，界面能开，但
> 「保存配置 / 证书签发 / 启动引擎」全部报 `PermissionError(13, 'Permission denied')`。

## 结论（一句话）

**是文件被打了 Low 完整性标签，不是产品 bug。** 被 Low 进程创建/解压出来的 exe 继承 Low 标签；
Windows 启动进程时完整性取「父进程 IL」与「映像文件 IL」的较小值 → 即使用户在资源管理器里双击，
进程也只有 Low IL，而 `%LOCALAPPDATA%` 是 Medium 标签，写不进去。

## 证据链

1. 现象：GUI 点「证书签发」→ 弹窗 `签发失败：PermissionError(13, 'Permission denied')`。
2. 查进程：GUI 的父进程是 `explorer.exe`（用户真的双击了），但令牌
   `integrity RID = 4096`（Low）；正常用户双击应是 `8192`（Medium）。
3. 查文件：测试区 `current/` 是用**本项目工具在 DSH shell（Low 令牌）里解压**出来的
   → 解压出的文件继承了 Low 标签。
4. 验证：`icacls "D:\mod\release-test\current" /setintegritylevel (OI)(CI)Medium /T /Q`
   → 同一 exe 重新启动，`integrity RID = 8192`（Medium），证书签发成功
   （新证书 `thumbprint 3293D221…`、`self_check: OK`）。

## 已做的修复（工具层自动处理）

- `tools/win_integrity.py`：`set_medium(path)` —— 用 `icacls /setintegritylevel (OI)(CI)Medium /T`
  把目录树（含未来子文件）标回 Medium；非 Windows 直接跳过。
- `tools/sync_release_area.py`：解包测试区后自动调用（连测试区根目录一起标，避免新解压文件再继承 Low）。
- `tools/build_dist.py`：构建/签名完自动把 `dist/` 树标回 Medium（本地双击测试同理受益）。

## 说明

- 这只影响**本机**：zip 里不带 SACL 标签，别的机器解压出来是干净标签；CI 也不受影响。
- 自己解压 zip 到新目录（资源管理器/7-Zip）一般不会有这个问题 —— 因为解压程序是 Medium。
- 如果以后又遇到同类症状，先看进程完整性：
  ```powershell
  # 用 tools 里的思路或 PowerShell 读 token；最直观的是看能否写状态目录
  Test-Path "$env:LOCALAPPDATA\HD2ProxyStudio"
  ```
  确认是 Low IL 就对该目录跑一次：
  ```powershell
  icacls <目录> /setintegritylevel (OI)(CI)Medium /T /Q
  ```
