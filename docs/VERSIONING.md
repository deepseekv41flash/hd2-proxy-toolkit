# 版本规则（本项目自定，2026-11-17 起执行）

## 一句话

**前三位 `X.Y.Z` 只在「功能/能力」变化时动；只修 bug 就只动 `alpha.N` / `rc.N` 这一位。**
功能刚加、bug 较多 → `alpha`；用户实机验证过、已知 bug 不影响正常使用 → `rc`；
功能做完、bug 修得差不多 → 去掉后缀发 GA。

## 版本号结构

```
X.Y.Z-alpha.N     X.Y.Z-rc.N     X.Y.Z
└─┬─┘ └──┬──┘     └─┬─┘ └┬┘      └─ GA（正式版，无后缀）
  │      │          │    └─ 同一阶段内第 N 次「只修 bug」的发布
  │      │          └─ 发布候选阶段
  │      └─ alpha 阶段（新功能刚落地，可能有 bug）
  └─ 功能/能力版本（只有功能或能力变化才动）
```

PEP 440 元数据（`pyproject.toml`）写法：`0.1.0-alpha.4` → `0.1.0a4`；`0.2.0-rc.2` → `0.2.0rc2`；`1.0.0` → `1.0.0`。
`tools/check_version.py` 会校验这两处一致。

## 什么时候动哪一位

| 变更内容 | 版本变化 | 例 |
|---|---|---|
| 新增能力 / 新页面 / 新模板 / 新 CLI 子命令 / 改变行为语义 | `X.Y.Z` 变化，阶段重置为 `alpha.1` | `0.1.0-alpha.4` → `0.2.0-alpha.1` |
| 只修 bug（不改功能、不改行为语义） | 同 `X.Y.Z`，`alpha.N` 或 `rc.N` +1 | `0.1.0-alpha.4` → `0.1.0-alpha.5` |
| 用户实机验收通过，转发布候选 | `alpha` → `rc`，`rc.1` | `0.1.0-alpha.5` → `0.1.0-rc.1` |
| rc 阶段只修 bug | `rc.N` +1 | `0.1.0-rc.1` → `0.1.0-rc.2` |
| 功能完成、无阻断 bug | 去掉后缀发 GA | `0.1.0-rc.2` → `0.1.0` |
| 破坏性改动（1.0 前不承诺） | `X` +1，回 `alpha.1` | `0.x` → `1.0.0-alpha.1` |

阶段判定参考（什么时候算 `alpha` / `rc`）：

- **alpha**：新功能刚加进来、还没在用户实机上跑过全流程；"能跑但可能有坑"。
- **rc**：用户已按 `docs/ACCEPTANCE-*.md` 在真机（含游戏内）验证过核心链路；已知问题
  都不影响正常使用；此后只允许修 bug，再改功能就回 alpha。
- **GA**：既定功能集完成、bug 收敛；首个 GA 里程碑为 `1.0.0`（由项目所有者拍板）。

## 历史版本合规性

| 版本 | 核心 `X.Y.Z` | 本版变更 | 阶段 | 是否合规 |
|---|---|---|---|---|
| v0.1.0-alpha.1 | 0.1.0 | 首个可分发预览（M0–M5 功能集） | alpha | ✓ |
| v0.1.0-alpha.2 | 0.1.0 | 只修 bug：双击 exe 直接退出 | alpha | ✓ |
| v0.1.0-alpha.3 | 0.1.0 | 只修 bug：CLI 桥 / 冻结编码 / 日志路径 | alpha | ✓ |
| v0.1.0-alpha.4 | 0.1.0 | 只修 bug：直通写回 / 提示文案 / 弹窗换行（+ 本机签名工具） | alpha | ✓ |

## 怎么操作（工具化，别手改散落的版本串）

```powershell
python tools/bump_version.py fix            # alpha.N/rc.N +1（只修 bug）
python tools/bump_version.py fix --dry-run  # 只看会变成什么
python tools/bump_version.py promote-rc     # alpha.N → rc.1（用户实机验收通过后）
python tools/bump_version.py ga             # rc.N → X.Y.Z
python tools/bump_version.py feature --minor   # 功能更新：0.1.0 → 0.2.0-alpha.1
python tools/bump_version.py feature --patch   # 小幅功能扩展：0.1.1-alpha.1
python tools/bump_version.py feature --major   # 破坏性：1.0.0-alpha.1
```

工具会把 `src/hd2proxy/__init__.py`（`__version__`）和 `pyproject.toml`（PEP 440）一起改，
并打印接下来要补的 CHANGELOG 条目 / Release Notes 文件名。

发版完整流程见 `PLAN.md` §14；要点：**bump → 补 CHANGELOG/Release Notes → 门禁 →
构建（`HD2PROXY_SIGN=1`）→ 推送 → `gh release create --prerelease`（rc 也仍是 prerelease，
GA 才取消）→ 同步 release 测试区**。

## 门禁怎么保证不漏

`tools/check_gate.py` 的第 5 步会跑 `tools/check_version.py`，检查：

1. `__version__` 符合 `X.Y.Z` / `X.Y.Z-alpha.N` / `X.Y.Z-rc.N`；
2. `pyproject.toml` 的 PEP 440 写法与之一致；
3. `CHANGELOG.md` 里有对应 `## v<version>` 条目；
4. 该版本若已打 tag，则 `docs/RELEASE-v<version>.md` 必须存在。

版本串散落处（README/下载链接/Release Notes 标题）由 bump 工具的提示清单人工核对。
