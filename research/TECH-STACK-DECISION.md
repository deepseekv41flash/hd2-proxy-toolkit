# 技术栈调研：GUI 选型（2026-11-16 实测）

> 目标（用户给定）：**稳定** + **尽量低资源占用**；本机缺的依赖可稍后安装。
> 结论先行：**Tkinter（stdlib + ttk）做 GUI 壳**，引擎与 GUI 分离，未来要换壳不动引擎。
> 全部数字为本机实测（Windows 11，Python 3.13.9），脚本：[`bench_gui2.py`](bench_gui2.py)、[`buildtest/`](buildtest/)。

---

## 1. 结论对比表（同一台机器、同一天、同一测量口径）

| 指标 | **Tkinter 8.6** | pywebview 6.2.1 + WebView2 158 | 备注 |
|---|---|---|---|
| 空闲内存（进程树合计） | **31.7 MB** | **408.4 MB** | 口径：python 根进程 + 全部子孙，`GetProcessMemoryInfo` 求和 |
| 进程数 | **1** | **7** | WebView2 会拉 browser / GPU / renderer / utility 等子进程 |
| 空闲 CPU（5 秒采样） | **0.0 %** | **1.88 %** | `GetProcessTimes` 差值；WebView2 有渲染心跳 |
| 冷启动到窗口可见（源码运行） | **193 ms** | 460 ms | |
| 冷启动（PyInstaller 打包后） | **188 ms** | 未能运行（见 §2） | 两者都是 onedir |
| 打包体积（onedir） | **25 MB** | 34 MB（含未生效的 .NET 依赖） | |
| PyInstaller 打包可行性 | **✓ 开箱通过** | **✗ 开箱失败，`--collect-all` 仍失败** | 见 §2 原始报错 |
| 运行时外部依赖 | **无**（Tcl/Tk 随 Python） | pythonnet + .NET Framework + WebView2 Runtime + Edge 更新策略 | 分发面越少越稳 |
| 中文渲染 | ✓ 微软雅黑 UI 正常 | ✓ 正常 | 截图见 §3 |

**判据**：用户要「稳定 + 低资源」，Tkinter 在内存上是 pywebview 的 **1/13**、进程数 1 vs 7、外部依赖 0 vs 3+，
且打包一次通过。观感差距用配色/间距/字体弥补后**足够体面**（§3 截图）。

---

## 2. pywebview 打包失败证据（这是选型的关键否决项）

`python -m PyInstaller --onedir --name benchWV bench_webview_app.py` → 退出码 0，但**运行时崩溃**：

```
RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from
  ...\dist\benchWV\_internal\pythonnet\runtime\Python.Runtime.dll
  File "clr_loader\netfx.py", line 47, in _get_callable
```

按标准修法重打（`--collect-all pythonnet --collect-all clr_loader --collect-all webview`）→ **同样报错**：

```
RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from
  ...\dist\benchWV2\_internal\pythonnet\runtime\Python.Runtime.dll
[PYI-43392:ERROR] Failed to execute script 'bench_webview_app'
```

即：pywebview 在 Windows 上依赖 **pythonnet → .NET Framework 互操作**，PyInstaller 冻结后 CLR 装配解析失败。
理论上可写专用 hook + 手工塞 `Python.Runtime.dll` 的 runtimeconfig 修好，但那意味着
**每次升级 pythonnet/.NET/Edge 都可能再炸一次**，与「稳定」目标冲突；且分发要额外背 WebView2 Runtime 依赖。

> 附：源码直接跑 pywebview 是正常的（460 ms、408 MB），所以这是**打包/分发**风险，不是功能不可用。

---

## 3. Tk 原型截图（观感基线）

渲染脚本：[`prototype_tk.py`](prototype_tk.py) ｜ 出图：[`screenshots/tk_prototype.png`](screenshots/tk_prototype.png)

原型内容：顶部状态条（代理/证书/hosts/游戏）+ 左侧 5 页导航 + 四张状态卡 + 最近改写事件表 + 6 个快捷模板卡。
配色沿用 HD2 的金色强调（`#ffd500`）与深色底，字体微软雅黑 UI，1180×760。
（截图里的列宽截断/模板卡溢出是原型没做自适应，不是方案限制。）

**Tk 的已知短板与对策**：

| 短板 | 对策 |
|---|---|
| 圆角/阴影/动效做不了 | 用 1px 描边 + 分区底色代替；不做动效（也省资源） |
| 表格样式朴素 | `ttk.Style` + `clam` 主题统一改色/行高；Treeview 列宽支持拖拽 |
| 高分屏模糊 | `SetProcessDpiAwareness(2)` + `tk scaling`（旧面板已验证这套） |
| 中文/emoji 图标缺字形 | 导航图标改用几何符号或内嵌 16×16 PNG（Pillow 已装） |
| 大量控件时布局卡顿 | 用 Treeview/Canvas 承载列表；页面切换用 `pack_forget` 懒加载 |

---

## 4. 其它候选（未实测，仅作背景）

| 方案 | 估算资源 | 为什么不是首选 |
|---|---|---|
| PySide6 / PyQt6 | ~60–120 MB 内存，安装包 ~100–150 MB | 资源中等、打包可行，但**依赖体积翻几倍**；LGPL 合规需注意；对「简洁小工具」属于过度 |
| 本地 HTTP + 浏览器打开 | 增量取决于浏览器标签（~150–300 MB） | 不是独立窗口；要用户开着浏览器；但**可作为未来可选前端**（引擎已暴露控制 API，天然支持） |
| Electron / Tauri | 200 MB+ / 需 Rust 工具链 | 与「低资源」直接冲突；Tauri 仍需 WebView2 |

> 说明：Qt 一组是**估算**，未在本机实测；若后续 Tk 观感被否决，Qt 是第二选择（打包可用性高，资源中等）。

---

## 5. 架构含义（写进计划）

GUI 选 Tk 不影响产品架构：引擎（代理/证书/配置/控制 API）与 GUI 完全分离，
GUI 只是「控制 API 的一个客户端」。因此：

- 未来若换 Qt/Web 前端，**引擎与测试资产 0 改动**；
- headless / CLI / agent 调用与 GUI 走同一套接口；
- GUI 崩溃不打断游戏会话（引擎是独立进程）。

---

## 6. 复现命令

```bash
cd research
python bench_gui2.py tk          # Tk：内存/CPU/启动
python bench_gui2.py webview     # pywebview：内存/CPU/启动
cd buildtest
python -m PyInstaller --noconfirm --clean --onedir --name benchTk bench_tk_app.py
./dist/benchTk/benchTk.exe
python -m PyInstaller --noconfirm --clean --onedir --name benchWV bench_webview_app.py
./dist/benchWV/benchWV.exe        # 观察 CLR 报错
cd ..
python prototype_tk.py            # 出观感截图
```
