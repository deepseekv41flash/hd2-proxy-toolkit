# v0.10.0-alpha.1 — 证书有效期策略：默认 2 天 / 显式可放宽到 7 天硬上限

> 2026-11-25 · 预发布（alpha）· 策略/能力变更（`0.9.0-alpha.2` → `0.10.0-alpha.1`）

## 一句话

会话证书**默认仍是 2 天**（行为不变）；现在可以**显式**配置到最长 **7 天**，把"每 ~36 小时续一次证 + 重装一次信任"
降到"每周一次"。硬上限 7 天**不可被参数突破**。

## 为什么要改

会话证书 2 天有效、剩余 <12h 自动续期 ⇒ 实际约每 **36 小时**就要续一次。
而本工具的安全模型是**签完立刻删 CA 私钥**，所以每次续期都必然**换发新 CA** ⇒ 必须重装一次信任（一次 UAC）。
跨两天的测试/演示窗口几乎必然撞上一次轮换。

2026-11-25 与研究线双端定案：**放宽有效期上限**（不改变 CA 生成/删除模型），默认值保持 2 天不动。

## 怎么用（三处入口语义一致）

| 入口 | 用法 | 说明 |
|---|---|---|
| profile | `"cert": {"days": 7, ...}` | 默认 2；允许 1..7；>7 校验报错 |
| CLI | `hd2proxy certs renew --days 7` | `--days` 默认 2；超过 7 按 7 处理 |
| GUI | 设置 → 证书 → 有效期（天） | 下拉 1..7，文案注明"默认 2、显式可到 7 硬上限" |
| 引擎自愈 | profile `cert.auto_renew` | 启动前续期沿用同一策略值 |

## 不变的部分（重要）

1. **默认行为不变**：不配置就是 2 天。
2. **安全模型不变**：ca 模式、SAN 单域名、**签完立刻删 CA 私钥**、目录不留多余私钥。
3. **续期仍会换发新 CA** ⇒ 换发后依然**必须重装信任**，否则游戏报 `Error 60`。
   现有告警（`⚠ 证书续期换发了新 CA…`）与 `ca-history.json` 留痕均保留，未淡化。
4. **硬上限 7 天**：`clamp_days(days, max_days) = min(days, min(max_days(默认 2), 7))` ——
   即使调用方传 `max_days=99` 也只能到 7（不是"只校验 `days <= max_days`"）。

## 实现要点

- `engine/certs.py`：新增 `MAX_DAYS_DEFAULT=2` / `MAX_DAYS_HARD=7` / `effective_max_days()` / `clamp_days()`；
  `generate_session()`、`ensure_session()` 增加 `max_days` 参数并钳制；`build_leaf_mode()` / `build_ca_mode()`
  再按硬上限兜底（防止绕过公开入口直接调 builder）。
- `engine/config.py`：`cert.days` 校验由 `>2 报错` 改为 `>7 报错`（默认值仍 2）。
- `engine/server.py`：启动自愈按 profile 的有效值透传 `max_days`（显式 7 天不会被压回 2）。
- `__main__.py` / `tools/gen_session_certs.py`：CLI 与工具透传策略值。
- `preflight()` / `describe()`：由"超 2 天拒绝"改为"超 7 天拒绝"。

## 验证

- 新增 6 条单测（`tests/unit/test_certs.py`）：默认 2 天 / 显式 7 天放行 / 只给 days 不给 max_days 仍 2 天 /
  硬上限不可被参数突破 / `preflight` 7 天放行 8 天拒绝 / `ensure_session` 7 天 / profile 校验 1..7 且默认 2。
- 既有用例同步到新策略（`preflight`/`config` 里"5 天非法"改为"8 天非法"）。
- 全量 **744 passed**、`tools/check_gate.py` **GATE=PASS**（5/5 selftests）。

## 升级注意

- 本版**不自动**把现有证书升级成 7 天：需要显式配置（profile `cert.days` / `--days 7`）。
- 换 7 天后**下一次续期**仍会换发新 CA（模型未变），届时仍需重装一次信任；之后每 ~7 天一次。
- 研究线 A 机侧已同步放宽（其 `mock/certs.py` 同口径：默认 2 / 硬上限 7）。

## 已知限制 / 未做

- **持久根 CA（1 年）+ 短命会话 CA** 方案（可让续期完全不触发重装信任）**未做**：与"签完即删 CA 私钥"
  的现有安全模型直接冲突，留作后续产品化议题。
