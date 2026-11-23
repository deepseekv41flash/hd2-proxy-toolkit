# v0.5.4-alpha.2 — 修复：打包版引擎在中文 Windows 控制台启动即崩（2026-11-23）

> **bug 修复版**：只动 `alpha.N`（`0.5.4-alpha.1` → **`0.5.4-alpha.2`**），无新功能。

## 现场

刚装完（hosts + 证书信任都 OK）后运行：

```bat
hd2proxy.exe engine --profile C:\Users\...\HD2ProxyStudio\profiles\default.json
```

进程立刻退出，只有一行：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0' in position ...: illegal multibyte sequence
[PYI-xxxxx:ERROR] Failed to execute script 'pyinstaller_entry' due to unhandled exception!
```

原因：中文 Windows 控制台默认 **cp936（GBK）**，而引擎启动自检会打印带 `⚠`（U+26A0，GBK 编不出）的警告
（证书信任 / hosts 与监听 IP 不一致等）。`print` 抛 `UnicodeEncodeError`，**把整个引擎进程带走**。

**影响范围**：`0.5.0-alpha.1` ~ `0.5.4-alpha.1` 的**打包版 CLI 起引擎**。
从 GUI 起引擎走另一条子进程路径（环境变量不同），未必暴露，所以之前的实机验收没撞上。

## 修复（两道防线）

1. **启动时切 UTF-8**：新增 `logutil.ensure_utf8_console()`，把 stdout/stderr
   `reconfigure(encoding="utf-8", errors="replace")`。在三个入口都调用：
   - `tools/pyinstaller_entry.py` / `tools/pyinstaller_gui_entry.py`（打包版）
   - `hd2proxy.__main__.main()`（CLI 全部命令）
   - `engine/server.py::main()`（`legacy_proxy.py` 直启引擎 / 打包版 engine 路径）
2. **日志输出不再可能崩**：`log()` 的控制台输出改走 `_safe_print()`：
   - 先正常 `print`；
   - 失败（`UnicodeEncodeError` / `OSError`）→ 用流自己的编码 `errors="replace"` 写 `buffer`；
   - 控制台为 `None`（windowed exe）或彻底不可用 → 静默跳过。
   日志**文件**始终写完整 UTF-8 原文，不受控制台编码影响。

## 回归测试

新增 `tests/unit/test_logutil_encoding.py`（10 条），用假 GBK 控制台**复现现场**：

- `log("⚠ 证书未受信任…")` 不抛；`proxy.log` 里是完整原文；控制台降级写 bytes（`?` 替换）；
- `stdout=None`（windowed exe）/ `OSError` / 没有 `reconfigure` 的对象都不崩；
- `log_throttled` 同样安全；
- 断言 CLI 入口与引擎入口**真的**调用了 `ensure_utf8_console()`（防止以后重构把接线删掉）。

单测 656 → **666 passed**；`GATE=PASS`。

## 升级建议

**0.5.0 ~ 0.5.4-alpha.1 用户请升级到本版**，尤其是在中文 Windows 上用命令行起引擎的用户。

## 兼容性

- 无行为/协议/存档格式变化；纯健壮性修复；
- 控制台显示：UTF-8 输出在传统 GBK 控制台可能仍显示乱码（不影响运行），Windows Terminal / 现代终端正常。
