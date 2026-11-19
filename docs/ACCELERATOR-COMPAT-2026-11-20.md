# 加速器 / 代理共存实测与操作纪律（2026-11-20）

> 起因：现场开启 Clash Verge TUN 与 UU 路由模式后，本地 MITM 注入链路出现两类故障。
> 本文记录实测结论、根因，以及 `v0.4.1-alpha.5` 里的修复项。

## 0. 一句话结论

**注入链路本身与三种模式都能共存**（前提是绑定/上游正确），真正会打断它的是：

1. **监听 IP 自动选错**（TUN/路由模式把默认路由转到虚拟网卡）；
2. **hosts 被加速器注释**（`#uu_acc` / `#g_acc`）；
3. **引擎在切换代理模式之前启动**（UU 路由模式的 WFP 过滤生效后，老进程的上游会被拒绝）。

## 1. 三种模式对照（同一台机器实测）

| 模式 | 游戏→本机跳 | 引擎→上游 | hosts | 需显式 listen_ip | 切换后需重启引擎 |
|---|---|---|---|---|---|
| Clash Verge 系统代理（非 TUN，rule） | ✅ | ✅ 直连 | 不改 | 否 | 否 |
| Clash Verge TUN（gvisor，auto-route） | ✅ on-link | ✅ 经 TUN（WarId 0.8 s） | 不改 | **是** | 否 |
| UU 路由模式（Wintun Tunnel） | ✅ on-link | ✅ 经 UU 隧道（WarId 1.6 s） | **会被 `#uu_acc` 注释** | 是 | **是** |

共同的网络事实（三种模式都成立）：

- `100.67.169.17`（本机 LAN IP）始终是**以太网 on-link 路由**，TUN/UU 网卡抢不走 → 游戏→引擎这一跳不依赖代理模式；
- 系统 DNS 未被代理接管；hosts 优先级高于 DNS，域名解析始终命中 hosts；
- 系统代理（WinINET）对游戏无效（游戏是原始 Winsock 直连，不读 WinINET/WinHTTP）。

## 2. 故障一：TUN 模式下监听地址选成虚拟网卡（已修）

现场证据（`%LOCALAPPDATA%\HD2ProxyStudio\logs\proxy.log`）：

```
00:43:06 hd2proxy engine  host=api.live.prod.thehelldiversgame.com  listen=198.18.0.1:443
```

- Clash TUN 的默认路由指向 `Mihomo` 网卡（`198.18.0.1`），`resolve_listen_ip("auto")` 采信默认路由 IP → 绑到 TUN 地址；
- 更严重：`install` 不传 `--listen-ip` 时也按同一逻辑把 **hosts 写成 `198.18.0.1`** → 游戏连向 TUN 地址，永远打不到引擎（表现为 `Error 56`）。

修复（v0.4.1-alpha.5）：

1. `sysprobe.resolve_listen_ip`：默认路由 IP 只有在**落在物理网卡**上时才采信；若落在虚拟网卡（TUN/Wintun/加速器），退回「物理网卡优先」枚举；`_VIRTUAL_MARKS` 增加 `mihomo / meta tunnel / wintun / sing-box / v2ray / xray / uu wintun / uu急速器` 等关键词；
2. `install` 在未指定 `--profile` 时**回退读取默认 profile** 的 `listen_ip`（不再直接 `auto`），避免 install 与引擎不一致。

## 3. 故障二：加速器注释 hosts（已加识别与提示）

UU 路由模式启用瞬间（hosts 文件 `LastWriteTime` 比我们写入晚 4 分钟）把行改成：

```
#uu_acc100.67.169.17 api.live.prod.thehelldiversgame.com # hd2proxy
```

`hosts.py` 本来就把「映射部分被 `#` 注释」识别为 `commented=True`，`install` 能幂等重写；
本轮补的是**可读性与及时性**：

- `diagnostics.hosts_diag` 增加 `comment_prefix`（识别出 `#uu_acc` / `#g_acc` 这类前缀）；
- `diagnostics.evaluate` 的报错文案写明「检测到 `#uu_acc`（加速器 hosts 保护）→ 重写 hosts 后需重启引擎」；
- **引擎启动时**新增 hosts 自检（`diagnostics.hosts_startup_advice`）：缺失 / 被注释 / 指向旧 IP 都会在
  `proxy.log` 里打 `⚠` 行并给出修复动作，不再让用户只看到游戏的「与服务器通讯时出错」。

## 4. 故障三：切换模式后引擎必须重启（已写进文档与启动提示）

UU 路由模式（WFP 内核过滤）启用后，**切换前就运行的引擎**其 DoH 上游全部报
`ConnectionRefused(10061)`（对 `223.5.5.5` / `cloudflare-dns.com`），三连验收 FAIL；
同一环境**重启引擎后三连 PASS**、WarId 200。判定为「老进程的网络状态与过滤器重载不一致」。

操作纪律（已写进 README）：

1. 切换加速器/代理模式（系统代理 ↔ TUN ↔ 路由模式）后 → **重写 hosts**（`install` 或 GUI「安装/修复」）；
2. 然后 → **重启引擎**；
3. 最后 → 再启动游戏。

## 5. 验收证据（v0.4.1-alpha.5 前实测）

| 场景 | 结果 |
|---|---|
| Clash TUN + 显式 `listen_ip=100.67.169.17` + hosts 正确 | 三连 PASS；WarId 200 / 0.81 s |
| UU 路由模式 + hosts 重写 + 重启引擎 | 三连 PASS；WarId 200 / 1.60 s |
| UU 路由模式 + 引擎先于 UU 启动 | 三连 FAIL（DoH 全部 10061）；重启引擎即 PASS |
| UU 启用后未重写 hosts | hosts 被注释 → 游戏不会走代理（自检/引擎日志现在会明确报出） |

## 6. 复现 / 自检命令

```bat
:: 重写 hosts（一次 UAC；未传 --profile 时自动读默认 profile 的 listen_ip）
hd2proxy.exe install
:: 三连验收（TLS + CRL + Status 改写）
hd2proxy.exe verify
```

> 现场状态看 GUI：**总览页**的问题红条 + **「系统自检」**弹窗（两者都走
> `engine/diagnostics`），hosts 被注释时会直接给出检测到的加速器前缀（`#uu_acc` / `#g_acc`）。
> 命令行没有等价的诊断子命令（`hd2proxy status` 读的是运行中引擎状态，不含 hosts 检查）。
