# v0.3.0-alpha.3 — 修复「续期证书后游戏报 Error 60 / Status -1」（CA 未受信 + GUI 缺真安装入口）（2026-11-17）

> **alpha 预览版 · 只修 bug**：版本位不变（`0.3.0-alpha.2` → `0.3.0-alpha.3`）。

## 现象

游戏里弹：

```
ERROR
Request: 649,790,637
Error: 60
Status: -1
Something unexpected went wrong while trying to communicate with our server. Try again in a few seconds.
```

重启游戏、切账号、关代理都无效；而同一时刻本机网络、hosts、证书文件、CRL 服务看起来都正常。

## 根因

**不是网络问题，是「换了新 CA 但没有重新导入受信任根存储」。**

现场取证链：

| 证据 | 结果 |
|---|---|
| 引擎 `/status` | `req=0  deny=3  rewrite=0` —— 一个请求都没成功过 |
| `proxy.log` | `TLS REJECTED … SSLZeroReturnError('TLS/SSL connection has been closed (EOF)')` ×3 —— **客户端在握手阶段主动断开** |
| `certs/session.json` | 当前 CA 是当天 **16:06:42 重新生成的**（指纹 `CD4F0C7D…`） |
| `Cert:\LocalMachine\Root` | 只有更早的旧 CA，**没有当前 CA** |
| `hd2proxy.exe install --dry-run` | `hosts_ok=true`、**`cert_trusted=false`** |

为什么会这样：GUI 里点「签发 / 续期证书」会**换一张新的会话 CA**，但当时 GUI 只有
「安装计划（dry-run）」，**没有真安装入口**；证书状态里也没有「是否受信任」这一项，
系统自检、总览红字、引擎日志都不会提示「证书未受信」。于是用户只看到客户端侧的通用网络错误。

## 本版修复（四项）

### 1. 证书信任状态可见

- `certs.cert_status(..., check_trust=True)` 新增 `trusted` / `trust_scope`（查 LocalMachine 与
  CurrentUser 两个根存储）；未受信时 `warnings` 给出可操作文案；
- `sysprobe.cert_trusted()` 带 **3 秒缓存** —— 一次检查要 spawn `certutil`，不能让诊断反复跑；
- 控制面 `/status` **保持默认不查**（GUI 0.6 秒轮询的热路径，绝不能把 certutil spawn 塞进去）。

### 2. 诊断升级为阻塞级 error

`diagnostics.evaluate()` 把「证书未受信」列为 **error**（原来只有「证书不可用」的 warn）：

> 证书未受信任：当前 CA 不在受信任根存储（指纹 …）→ 游戏 TLS 握手会被拒绝（引擎日志 TLS REJECTED）。
> 点「安装 / 修复」重新导入信任

总览页红字与「系统自检」报告都会直读这条。

### 3. GUI 补上真安装入口 + 续期后自动引导

- 总览页新增 **「安装 / 修复（UAC）」** 按钮：真改 hosts + 导入当前证书信任（一次 UAC）；
- 「签发 / 续期证书」成功后会**自动检测信任**：未受信就弹一次确认并一键导入（只问一次，
  不会连弹两个确认框）；导入后清掉信任缓存并强制重算现场检查。

### 4. 引擎侧提示

- 引擎启动时检测到 CA 未受信 → 打印 `⚠ 证书未受信任：… 修复：hd2proxy.exe install 或 GUI「安装 / 修复」`；
- TLS 拒绝日志追加可操作提示：`（多为客户端不信任本机 CA：点 GUI「安装 / 修复」或运行 hd2proxy.exe install 重新导入信任）`。

## 验证

- 单测 **434 → 445**：
  - `certs.cert_status` 信任三态（未受信 / CurrentUser 受信 / 默认不查信任）；
  - `sysprobe.cert_trusted` 缓存命中、按范围区分、`clear_caches` 后重查；
  - 诊断：未受信 → `ok=False` 且 error 文案含指纹；受信 → 无假报；
  - GUI：真安装调用 CLI 参数、取消不动作、续期后只问一次并自动 install、已受信不打扰。
- 源码实测（真实系统状态）：
  - 未受信临时证书目录 → `trusted=False`、自检 error、引擎启动 ⚠ 两行提示；
  - 用 `curl`（不信任该临时 CA）触发握手失败 → 引擎日志 `TLS REJECTED …（多为客户端不信任本机 CA…）`；
  - 真实证书目录 → `trusted=True`（`LocalMachine`），自检无误报。
- 门禁：`python tools/check_gate.py` → **GATE=PASS**；GUI 冒烟 5 页截图正常（总览多出「安装 / 修复（UAC）」按钮）。

## 打包版实机验证（计算机操作，非源码版）

用打包后的 `dist\hd2proxy\hd2proxy-gui.exe` 实测。为复现「未受信」态，把 `%LOCALAPPDATA%\HD2ProxyStudio\certs`
临时替换为一张**未导入根存储**的临时 CA（测试后已还原）：

| 场景 | 结果 |
|---|---|
| 未受信证书 + 启动 GUI | 总览红字出现：「证书未受信任：当前 CA 不在受信任根存储（指纹 24B65223E38F）→ 游戏 TLS 握手会被拒绝（引擎日志 TLS REJECTED）」✓ |
| 点「系统自检」 | 证书分节显示 `· 证书未受信任…`；结论区同时列出 `✗ 证书未受信任…`（error 级）✓ |
| 点新按钮「安装 / 修复（UAC）」 | 弹出确认框「将把游戏域名指向本机，并把当前会话证书导入受信任根存储。需要一次 UAC 确认。继续吗？」；点「否」无任何系统改动 ✓ |
| 还原真实（已受信）证书后重启 GUI | 红字只剩 hosts/引擎那条，**没有证书未受信**；新按钮在位 ✓ |
| 切页「设置 ↔ 总览」两次（间隔 3.2s，触发真实诊断） | 20ms 采样 **2142 次**，控制台窗口 **0 个**（alpha.2 的隐藏窗口修复未回归；新增的 certutil 检查同样无窗口）✓ |

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.3.0-alpha.3-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，签名之后计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.3.0-alpha.3-windows-x64.zip -Algorithm SHA256
```

## 升级提示

覆盖安装即可（配置与证书在 `%LOCALAPPDATA%\HD2ProxyStudio`，不受影响）。
升级后如果总览出现「证书未受信任」红字，点新加的「安装 / 修复（UAC）」一次即可。

## 已知限制（alpha）

- 旧的会话 CA 会残留在受信任根存储里（本机已积累十来张），本版不自动清理，留待后续版本做幂等清理；
- 信任检查用 `certutil`（带 3 秒缓存）；极短窗口内刚导入的信任可能仍显示旧状态，点「系统自检」会强制重算；
- 引擎侧的上游偶发超时（多 IP 重试）仍是待办，未包含在本版。
