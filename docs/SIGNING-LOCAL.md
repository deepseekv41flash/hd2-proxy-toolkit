# 本机自签代码签名（仅本地测试用）

> **这不是"对外发布签名"**。证书只装在你自己的「当前用户」证书库里受信任：
> 本机跑本项目的 exe 不再弹 SmartScreen；别人下载同一个 exe 仍会看到未识别发布者提示。
> 对外分发想要免提示，只有买 OV/EV 证书或（开源项目）申请 SignPath Foundation 之类的免费签名服务。

## 它解决什么

从 GitHub 下载/本地构建出来的 `hd2proxy.exe`、`hd2proxy-gui.exe` 是**未签名**的，本机首次运行时
Windows SmartScreen 会弹「Windows 已保护你的电脑」，要点「更多信息 → 仍要运行」；自动化测试
（computer use）里这个对话框还点不动，直接挡住 GUI 验证。

把 exe 用一张**本机自签**证书签名，并把该证书装进当前用户的「受信任根 + 受信任发布者」，
本机就会把它当已知发布者 → 不再弹窗。

## 一次性：生成证书 + 装信任

```powershell
pwsh -File tools/sign_local.ps1 -Install
```

- 证书：`CN=HD2 Proxy Toolkit Local Dev`，RSA 3072 / SHA-256，有效期 3 年，私钥在当前用户证书库
  （`Cert:\CurrentUser\My`）。
- 信任：把公钥证书装进 `Cert:\CurrentUser\Root` 与 `Cert:\CurrentUser\TrustedPublisher`
  —— 都是**当前用户**库，**不需要管理员/UAC**。
- 装信任用 `certutil -user -addstore`：`Import-Certificate` 往 Root 库导入会弹确认框，
  非交互会话里会直接失败（实测报「此操作中不允许使用 UI」）。

## 每次构建后：签名

```powershell
# 方式 A：构建时就签（推荐）
$env:HD2PROXY_SIGN = "1"
python tools/build_dist.py

# 方式 B：给已有 dist 补签
pwsh -File tools/sign_local.ps1 -DistDir dist\hd2proxy
```

签名后自检：

```powershell
Get-AuthenticodeSignature dist\hd2proxy\hd2proxy-gui.exe | Format-List Status, SignerCertificate
# Status 应为 Valid（因为根证书已在本机受信任库）
```

## 卸载/重来

```powershell
# 删信任
Get-ChildItem Cert:\CurrentUser\Root, Cert:\CurrentUser\TrustedPublisher |
  Where-Object { $_.Subject -eq 'CN=HD2 Proxy Toolkit Local Dev' } | Remove-Item

# 删证书+私钥
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
  Where-Object { $_.Subject -eq 'CN=HD2 Proxy Toolkit Local Dev' } | Remove-Item

# 重建（旧证书会被替换）
pwsh -File tools/sign_local.ps1 -Recreate -Install
```

## 边界与注意

- **只对本机（当前用户）有效**；换 Windows 账号、重装系统后要重跑 `-Install`。
- 自签证书**不提升**对外可信度，也不能替代正式代码签名；不要把它当作对外发布的签名。
- 签名会改变 exe 的 SHA-256（`dist/SHA256SUMS.txt` 是签名之后生成的，仍与产物一致）。
- 如果拿到的是「别的机器签的、你这台没装信任」的 exe，`Get-AuthenticodeSignature` 会显示
  `NotTrusted`（签名结构有效但链不受信任）——这是预期行为。
