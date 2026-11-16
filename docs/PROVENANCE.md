# 代码来源与可核对哈希（Provenance）

> 目的：本仓库的引擎与自检**不是重写**，而是从研究线逐字节迁移；任何"行为变了"的怀疑，
> 都应该先核对这份文档，再对照 [PLAN.md](../PLAN.md) 的 M1 重构计划。

## 1. 引擎

| 项 | 值 |
|---|---|
| 迁移源 | `D:\Downloads\variant_mod\tools\war_proxy.py`（研究线实机在跑的工作副本） |
| 同源副本 | `hd2-network-proxy` 仓库 `tools/war_proxy.py`（内容一致） |
| 字节数 / 行数 | 81,976 B / 1,846 行 |
| sha256（源） | `662af7d6fa8fb0ab49bc5a308031177dfa09347e65f10c992668e696beff7bbe` |
| 迁移目标 | `src/hd2proxy/engine/legacy_proxy.py` |
| 迁移日期 | 2026-11-16（M0） |

### 1.1 相对源文件改了什么（只有路径解析，逻辑零改动）

改动集中在文件头部的 `M0 迁移 shim` 区块与 `main()` 的三个 argparse 默认值：

| 原 | 新 | 原因 |
|---|---|---|
| `ROOT = HERE.parents[1]` | `ROOT = Path(os.environ.get("HD2PROXY_ROOT") or HERE.parents[3])` | 源码位置从 `tools\` 变成 `src\hd2proxy\engine\`，向上三级才是仓库根 |
| — | `_DATADIR = Path(os.environ.get("HD2PROXY_DATA") or (ROOT / "data"))` | 新增：数据根可覆盖（测试/便携部署） |
| `STRATAGEM_CATALOG = ROOT / "stratagem_catalog.json"` | `STRATAGEM_CATALOG = _DATADIR / "legacy" / "stratagem_catalog.json"` | 目录文件挪到 `data/legacy/` |
| `--config` 默认 `ROOT/config.json` | `_DATADIR/legacy/config.example.json` | 同上 |
| `--catalog` 默认 `ROOT/variant_catalog.json` | `_DATADIR/legacy/variant_catalog.json` | 同上 |

其余（TLS 服务、钩子顺序、改写逻辑、抓包、证书 preflight、CRL、热重载、粘性星球、阵营过滤）**一行未动**。

### 1.2 如何核对

```bash
# 有研究线工作副本时（本机）：
python - <<'EOF'
import hashlib, pathlib
a = pathlib.Path(r"D:\Downloads\variant_mod\tools\war_proxy.py").read_bytes()
b = pathlib.Path("src/hd2proxy/engine/legacy_proxy.py").read_bytes()
print("源  CRLF sha256:", hashlib.sha256(a).hexdigest())
print("源  LF   sha256:", hashlib.sha256(a.replace(b'\r\n', b'\n')).hexdigest())
print("新  CRLF sha256:", hashlib.sha256(b).hexdigest())
print("新  LF   sha256:", hashlib.sha256(b.replace(b'\r\n', b'\n')).hexdigest())
EOF
```

> `.gitattributes` 为 `* text=auto eol=lf`：git 里存 LF，Windows 工作副本可能是 CRLF。
> 因此核对时**必须**同时看 CRLF/LF 两个哈希，否则会把换行差异误判成内容不一致。

### 1.3 换行归一化后的哈希（git blob 里就是 LF 这一份）

| 文件 | CRLF sha256（工作副本） | LF sha256（git 存储 / 跨平台核对用） |
|---|---|---|
| `src/hd2proxy/engine/legacy_proxy.py`（M0 版本，见 git 历史） | `58d1960f6d64a9f6…` | `add4d28950655219…` |
| `data/legacy/variant_catalog.json` | `b9683fb2f92d1c49…` | `8a1b5b29d35253a1…` |
| `data/legacy/stratagem_catalog.json` | `c4a6de4ebc90b09b…` | `90fa19e4dd9bab68…` |
| `data/legacy/config.example.json` | `b423ca8235c626dc…` | `2319a9e829ad1de8…` |

（源文件 CRLF sha256 = `662af7d6…` 见 §1；其 LF 归一化后与上表第一行的迁移目标**不同**，因为 shim 改了路径那几行。）

### 1.4 M1 重构（2026-11-16）后的读法

M1 把 M0 的 1846 行单文件拆成 `engine/` 下 17 个模块（见 [ARCHITECTURE.md](ARCHITECTURE.md)），
`legacy_proxy.py` 现在是**兼容入口**（只负责把脚本方式启动转发到 `server.main`，并再导出旧函数名）。

为了保证「拆分/加 `spec` 参数」没有改变行为，M1 建立了**黄金回归**：

- `tests/fixtures/make_golden.py` 从 **git 历史里的 M0 实现**（commit `826ba04`）生成基准，
  产物在 `tests/fixtures/golden/`；
- `tests/unit/test_hooks.py` 让重构后的钩子分别用「显式 spec」和「旧环境变量/runtime 文件」
  两条路径跑同一输入，输出必须与 golden **逐字段一致**；
- 5 个脚本式自检（`tests/selftest*.py`）保持原断言，验证传输层/热重载/粘性/阵营隔离。

> 所以本文件的哈希核对仍然有效：**M0 那版实现**作为行为基线被固化在 git 与 golden 里；
> 当前代码的等价性由测试保证，而不是靠"看起来一样"。


## 2. 数据文件（`data/legacy/`，逐字节复制）

| 新路径 | 来源 | sha256 |
|---|---|---|
| `data/legacy/variant_catalog.json` | `variant_mod\variant_catalog.json` | `b9683fb2f92d1c49…` |
| `data/legacy/stratagem_catalog.json` | `variant_mod\stratagem_catalog.json` | `c4a6de4ebc90b09b…` |
| `data/legacy/config.example.json` | `variant_mod\config.json` | `b423ca8235c626dc…` |

`data/catalogs/*.json` 是**规范化后的产品目录**，由 `tools/gen_catalogs.py` 从研究仓产物生成
（生成逻辑与条目数见 `data/catalogs/README.md`），与上面的 legacy 文件用途不同：
引擎读 legacy，GUI 读 catalogs。

## 3. 工具

| 新路径 | 来源 | 说明 |
|---|---|---|
| `tools/gen_session_certs.py` | `variant_mod\tools\gen_session_certs.py`（sha256 `594ecabdf8632516…`，逐字节一致） | 证书签发；ca 模式为唯一可用形态 |
| `tools/run_selftests.py` | 新写 | 串行跑 5 个自检，独立临时证书/数据目录，输出 `GATE=PASS` |

## 4. 自检（`tests/`）

| 新文件 | 来源 | 改动 |
|---|---|---|
| `tests/selftest_rewrite.py` | `variant_mod\tools\selftest_rewrite.py` | 仅路径（引擎/目录/测试证书目录）+ `crlPort:0` 隔离 |
| `tests/selftest_hot_reload.py` | 同上 | 同上 |
| `tests/selftest_sticky.py` | 同上 | 同上 |
| `tests/selftest_faction.py` | 同上 | 仅 import 路径与 catalog 路径 |
| `tests/selftest.py` | `variant_mod\tools\selftest.py` | **改为自包含**：原版要求外部已起代理，新版自己起代理+假上游；断言语义不变（SNI 拒绝 / 白名单握手 / 上游可达 / 改写生效 / 原有条目保留） |

测试证书生成到 `build/test-certs/`（gitignore），**不碰** `certs/` 下的实机会话证书；
每个自检用独立 `VMOD_DATA` 临时目录，跑完即删（`--keep` 可保留）。

## 5. 研究资产（`research/`）

本轮技术选型的实测脚本与结论，保留可复现：
`bench_gui.py` / `bench_gui2.py`（内存与启动实测）、`buildtest/`（PyInstaller 打包验证）、
`prototype_tk.py` + `screenshots/tk_prototype.png`（界面原型）、`TECH-STACK-DECISION.md`（结论）。

## 6. 勘误纪律

若发现研究线文档/注释有错：在本仓库记录勘误点 → 经用户确认后才回改研究仓，
**不在产品仓库里直接改研究结论**（两边分工：研究仓留证据，本仓留产品）。
