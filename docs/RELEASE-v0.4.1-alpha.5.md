# v0.4.1-alpha.5 — 加速器共存修复（TUN/路由模式监听 IP、hosts 注释识别、启动自检）（2026-11-20）

> **alpha 预览版 · 只修 bug（不改功能）**：只动 `alpha.N`（`0.4.1-alpha.4` → **`0.4.1-alpha.5`**）。

## 背景

现场把 Clash Verge 切到 **TUN 模式**、再换 **UU 路由模式**测试时，注入链路出现三处故障。
逐项定位后确认都是本工具在「非普通网络环境」下的**健壮性缺陷**，不是代理模式本身不可共存：

1. **监听地址选到虚拟网卡**：TUN/路由模式把默认路由转到其虚拟网卡，`listen_ip="auto"` 采信默认路由 IP
   → 引擎绑到 `198.18.0.1`（Clash TUN）或 UU Wintun 地址，而 hosts 指向 LAN IP → 游戏连不上；
   `install` 未传 `--listen-ip` 时会同样把 **hosts 写成虚拟网卡地址**（实测日志见下）。
2. **hosts 被加速器注释**：UU 路由模式启用瞬间把我们的行改成
   `#uu_acc100.67.169.17 api.live... # hd2proxy` —— 整行变注释，游戏绕过代理；
   旧版只有 `commented` 状态，不告诉用户是哪个软件干的。
3. **切换模式后老引擎上游被拒**：UU 路由模式（WFP 内核过滤）启用后，**切换前**启动的引擎其 DoH 上游
   全部 `ConnectionRefused(10061)`；重启引擎即恢复。旧版没有任何提示。

## 本版修复

| # | 修复 | 位置 |
|---|---|---|
| 1 | 默认路由 IP **仅当落在物理网卡上才采信**；虚拟网卡关键词扩充（`mihomo` / `meta tunnel` / `wintun` / `sing-box` / `v2ray` / `xray` / `uu wintun` / `加速器` 等） | `engine/sysprobe.py` |
| 2 | `install` 未传 `--profile` 时**回退读取默认 profile 的 `listen_ip`**（不再直接 auto） | `__main__.py` |
| 3 | hosts 诊断新增 `comment_prefix`，识别 `#uu_acc` / `#g_acc`；报错文案点明加速器保护 + 「重写后需重启引擎」 | `engine/diagnostics.py` |
| 4 | 引擎启动时新增 hosts 自检：缺失 / 被注释 / 指向旧 IP 都在 `proxy.log` 打 `⚠` 并给修复动作 | `engine/server.py` |
| 5 | 文档：新增三种模式实测对照与操作纪律；README 增加「加速器 / 代理共存」小节 | `docs/ACCELERATOR-COMPAT-2026-11-20.md`、README |

### 现场证据（修复前）

```
00:43:06 hd2proxy engine  host=api.live.prod.thehelldiversgame.com  listen=198.18.0.1:443
00:43:39 hd2proxy engine  host=api.live.prod.thehelldiversgame.com  listen=100.67.169.17:443   ← 显式 IP 后正常
```

```
hosts: #uu_acc100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy   （被 UU 注释）
```

```
# UU 路由模式 + 切换前启动的引擎
doh 223.5.5.5 failed: URLError(ConnectionRefusedError(10061, ...))
doh cloudflare-dns.com failed: URLError(ConnectionRefusedError(10061, ...))
```

## 修复后验收（同一台机器）

| 场景 | 结果 |
|---|---|
| Clash TUN + 显式 LAN IP + hosts 正确 | 三连 PASS；WarId 200 / 0.81 s |
| UU 路由模式 + hosts 重写 + 重启引擎 | 三连 PASS；WarId 200 / 1.60 s |
| 自动解析（本版修复后，UU 路由模式下） | `resolve_listen_ip("auto")` → LAN IP（不再选 UU Wintun 地址） |
| hosts 被注释（合成文本） | 自检/引擎日志报出 `#uu_acc` 前缀与修复动作 |

## 操作纪律（写进 README）

**切换代理/加速器模式（系统代理 ↔ TUN ↔ 路由模式）后：① 重写 hosts → ② 重启引擎 → ③ 再启动游戏。**
三步缺一：只重写 hosts 会被"老引擎上游被拒"坑；只重启引擎会让 hosts 仍处于被注释状态。

## 数据变化

无（本版不涉及目录/名字数据；`items.json` 命名仍为 2441、`effects.json` 202）。

## 测试

- 单测 **486 → 493 passed**（+7：虚拟默认路由跳过 / 枚举为空回退 / install 默认 profile /
  hosts 前缀识别 / 启动建议 / 注释态报错文案 / 加速器网卡名识别）。
- `tools/check_gate.py` **GATE=PASS**。

## 打包版实测（本机，UU 路由模式运行中）

- 构建：`HD2PROXY_SIGN=1 python tools/build_dist.py` → 双 exe 本机自签 Valid，zip 17.7 MB，
  sha256 `7be71aa25ec22d8fe5094f36c15d976d530b8c3272c7bb7502cf1983e6908aa7`；
  干净路径解压后 `hd2proxy.exe preview` 正常、两个 exe 窗口存活（build 脚本内自检）。
- **修复 2 验证**：`hd2proxy.exe install --dry-run`（**不传** `--profile`）解析出
  `listenIp=100.67.169.17`（读默认 profile，而不是 auto 选虚拟网卡），hosts 判定 `noop`。
- **修复 1/4 验证**：打包版引擎启动日志
  `listen=100.67.169.17:443`、无 `⚠`（hosts 正常时保持安静）。
- **三连验收**：`hd2proxy.exe verify` → overall ok=True（TLS / CRL / Status 改写全 PASS）；
  游戏视角 `GET /api/WarSeason/current/WarId` → 200 · 1.19 s。
- **修复 3**：hosts 注释态（`#uu_acc` / `#g_acc`）由单测覆盖；现场用真实 `#uu_acc` 行确认
  `hosts_diag` 能取出前缀并给出「重写 hosts 后需重启引擎」的提示。

## 安装

同前：下载 `hd2proxy-toolkit-v0.4.1-alpha.5-windows-x64.zip` + `SHA256SUMS.txt`，
解压后运行 `hd2proxy_gui.exe`；证书信任/续期流程见 README「快速开始」。
若刚切换过 TUN/路由模式，按上面「操作纪律」三步走一次。
