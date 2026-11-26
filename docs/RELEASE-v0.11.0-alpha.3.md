# v0.11.0-alpha.3 — 修：CRL 端口绑不上（WinError 10013）把引擎带崩

> 2026-11-27 · 预发布（alpha）· 纯 bug 修复（`0.11.0-alpha.2` → `0.11.0-alpha.3`）

## 现象（用户报障截图）

双击启动后立刻弹「引擎启动失败：进程退出或 30 秒内未就绪」，日志尾部是：

```
  File "...\hd2proxy\engine\server.py", line 930, in cmd_engine
    crl_srv = certs.serve_crl(cert_dir, crl_port)
  File "...\hd2proxy\engine\certs.py", line 96, in serve_crl
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
PermissionError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

同屏还能看到 `证书 reused（剩余 48.0 小时）`、`存档：无历史档` —— 说明证书与存档都没问题，
**死在最后一步「开 CRL 服务」**。

## 根因

三件事叠在一起：

1. **`serve_crl()` 没有异常兜底**，而它在 `cmd_engine` 里也不在 try 内 ⇒ bind 失败 = 进程退出。
2. **10013 不是「端口被占用」**，是**权限 / 保留端口段**拒绝。装了 Hyper-V / WSL / Docker 的机器
   会保留一段动态端口，8080 落进去就谁也 bind 不了（`SO_REUSEADDR` 也抢不到）：
   ```
   netsh int ipv4 show excludedportrange protocol=tcp
   ```
3. **证书里的 CRL 分发点（CDP）硬编码 8080**：就算用户把 `proxy.crl_port` 改成别的，
   证书仍指向 8080，Schannel 取不到 CRL → `CRYPT_E_NO_REVOCATION_CHECK` 拒绝握手。
   所以"改配置"在旧版里根本不解决问题。

## 修法

- **端口自动降级**：启动先探一次，`8080` 不可绑就依次试 `18080 / 28080 / 38080 / 48080`；
  日志写清「为什么换、换成哪个」，并把**实际端口**记进 `engine.json` 与 `/status`。
  自动续证开启时会按新端口**重签**（`session.json` 记 `crl_port`，端口不一致即作废旧证）。
- **CDP 跟随端口**：签发/续签都用 `cdp_url(crl_port)` 写进证书（叶证书、CA 都带），
  不再有"证书指 A、服务听 B"的错位。
- **绑不上不崩引擎**：`serve_crl()` 内部 `try/except OSError` → 一条告警（看保留段 / 改
  `proxy.crl_port` / 重启）+ 返回 None；`server.py` 再兜一层。CRL 起不来最多是握手失败，
  不该连引擎一起丢。
- **诊断页对齐**：引擎在跑时「CRL 端口」以 `engine.json` 的实际值为准（以前读 profile 旧值，
  换了端口后会误报「空闲 / 冲突」）。

## 验证

- 单测 **+12**：`cdp_url` 跟随端口、CA 与叶证书的 CDP 文本、端口降级、全不可用、`serve_crl`
  被占时返回 None（不再抛）、`serve_crl` 正常提供 `ca.crl`、端口变化触发 `existing_ok` 作废 /
  `ensure_session` 重签、诊断取实际端口。
- **引擎端到端回归 +1**：先把「配置里的 CRL 端口」占住再起引擎 —— 引擎必须照常就绪、
  `engine.json` 的 `crl_port` 指向备用端口、`http://127.0.0.1:<该端口>/ca.crl` 返回 200。
  修复前这条会直接失败（引擎起不来）。
- 全量 **802 passed、GATE=PASS**。
- **打包 exe 实机验证**（`0.11.0-alpha.3` 产物，临时证书目录 + 端口桩，不碰系统状态）：
  占住 `127.0.0.1:8080` 后起引擎 —— 引擎照常就绪（rc=0 退出）、日志
  `CRL 端口不可绑（8080(10048)）→ 改用 18080`、`engine.json` 的 `crl_port=18080`、
  `http://127.0.0.1:18080/ca.crl` 取到的字节与 `certs/ca.crl` 完全一致。

## 升级后第一次启动会做什么（重要）

端口从 8080 换到别处时，**CRL 分发点在证书里**，所以引擎会**重签一次证书**（`session.json`
的 `crl_port` 随之变化）。重签会换发 CA，日志会明确说：

```
⚠ 证书续期换发了新 CA（08FDBC4E80C2 → 72475D124D28）：旧 CA 仍在信任库但已不匹配
  —— 需重新运行 install / GUI「安装 / 修复」，否则游戏会报 Error 60
```

所以现场顺序是：**升级 → 启动引擎（它会自己换端口并重签）→ 在 GUI 点一次「安装 / 修复」→ 重进游戏**。
之后证书稳定在新端口，不再重签、也不需要重复安装。

## 已经遇到这个错、但暂时不想升级的处置

```bat
netsh int ipv4 show excludedportrange protocol=tcp
```

看 8080 是否在保留段里；是的话：

1. 打开 `%LOCALAPPDATA%\HD2ProxyStudio\profiles\default.json`，把 `proxy.crl_port` 改成 `18080`；
2. **必须在 GUI 里点一次「签发 / 续期证书」**（旧版证书的 CDP 写死 8080，不重签换了端口也没用）；
3. 再启动引擎。

## 部署说明

`D:\mod\release-test\current` 会在确认没有 `hd2proxy*` 进程运行时再同步到本版。
在那之前想立刻用上 → 解压 `dist/hd2proxy-toolkit-v0.11.0-alpha.3-windows-x64.zip` 到任意目录运行。
