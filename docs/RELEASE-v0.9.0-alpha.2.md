# v0.9.0-alpha.2 — 修复：settlements 测试对时区敏感（alpha.1 tag CI 红灯）（2026-11-24）

> **bug 修复版**：只动 `alpha.N`（`0.9.0-alpha.1` → **`0.9.0-alpha.2`**）。

## 一、问题

`v0.9.0-alpha.1` 的 GitHub Actions 在 **unit-tests** 一步失败：

```
FAILED tests/unit/test_settlements.py::test_repeated_export_is_idempotent
```

本地（Asia/Shanghai）全绿、CI（UTC）红 —— 根因是**测试对时区敏感**：断言里硬编码了 `+08:00`，
而 `_iso_explicit()` 对旧账本的本地时间戳按**运行机时区**补偏移（CI 上是 `+00:00`）。
产品行为本身正确（契约 J08 只要求"带显式时区"，不限具体偏移）；是测试写死了环境。

## 二、修复

`tests/unit/test_settlements.py` 改为**时区无关**断言：

- 时间部分仍精确断言（如 `startswith("2026-11-24T13:39:43")`）；
- 偏移改为正则校验 `(Z|[+-]HH:MM)$`（新增 `_has_explicit_tz` 帮助函数，覆盖 3 处硬编码）。

## 三、测试与发布

- 全量 **738 passed**、`GATE=PASS`；本版 tag 的 CI 预期转绿（`v0.9.0-alpha.1` 的 tag 红灯为环境性测试问题，非产品缺陷）。
- 无功能变更：`settlements.jsonl` / `mission_end.json` / 导出行为与 alpha.1 完全一致。
- 规则：bug 修复只动 `alpha.N`：`0.9.0-alpha.1` → **`0.9.0-alpha.2`**。

## 四、升级

无需升级（纯测试修复）；若已装 alpha.1，功能与 alpha.2 等价。
