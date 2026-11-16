<#
.SYNOPSIS
  本机自签代码签名：创建/复用本地代码签名证书，安装信任到当前用户证书库，并给 exe 签名。

.DESCRIPTION
  用途：**只为本机测试方便** —— 未签名的本地 PyInstaller exe 首次运行会弹 SmartScreen
  「Windows 已保护你的电脑」，而且本机某些启动方式还会把它降到 Low 完整性。把本项目
  构建出的 exe 用一张**本机自签**证书签名，并把这证书装进「当前用户」的受信任根 +
  受信任发布者，本机（且只有本机）就会把它当作已知发布者，不再弹 SmartScreen。

  重要边界：
  - 这不是"对外签名"。证书只在本机证书库受信任，别人下载同一 exe 仍会看到未知发布者提示。
  - 装到 CurrentUser 证书库，**不需要管理员/UAC**。
  - 重装系统/换用户后要重跑一次。

.EXAMPLE
  pwsh -File tools/sign_local.ps1 -Install -Files dist\hd2proxy\hd2proxy.exe,dist\hd2proxy\hd2proxy-gui.exe

.EXAMPLE
  pwsh -File tools/sign_local.ps1 -Install -DistDir dist\hd2proxy   # 签目录下所有 exe
#>
param(
    [switch]$Install,
    [string[]]$Files = @(),
    [string]$DistDir = "",
    [string]$Subject = "CN=HD2 Proxy Toolkit Local Dev",
    [switch]$Recreate,
    [switch]$InfoOnly
)

$ErrorActionPreference = 'Stop'
$script:Failed = $false

# certutil 的输出是本机 OEM 代码页（中文 Windows = GBK）；统一按 UTF-8 输出，避免调用方
# （build_dist.py 按 UTF-8 解码）拿到乱码 ✓
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$OutputEncoding = [System.Text.Encoding]::UTF8

function Get-LocalCodeSignCert {
    param([string]$Subj)
    Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -eq $Subj } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
}

function Ensure-Trusted {
    param($Cert)
    # 受信任根：让系统认为这张证书是可信 CA；受信任发布者：让 Authenticode 认发布者。
    # 注意：不能用 Import-Certificate —— 往 Root 库导入会弹确认框，在非交互会话里直接失败
    # （实测报"此操作中不允许使用 UI"）；certutil -user 不会弹，静默写当前用户库 ✓
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("hd2sign-" + [guid]::NewGuid().ToString('N') + ".cer")
    Export-Certificate -Cert $Cert -FilePath $tmp -Type CERT | Out-Null
    try {
        foreach ($storeName in @('Root', 'TrustedPublisher')) {
            $storePath = "Cert:\CurrentUser\$storeName"
            $exists = Get-ChildItem $storePath -ErrorAction SilentlyContinue |
                Where-Object { $_.Thumbprint -eq $Cert.Thumbprint }
            if ($exists) {
                Write-Output ("  [{0}] 已存在信任 ✓" -f $storeName)
                continue
            }
            $out = & certutil -user -addstore $storeName $tmp 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw ("certutil -addstore {0} 失败: {1}" -f $storeName, ($out | Out-String))
            }
            Write-Output ("  [{0}] 已安装信任 ✓" -f $storeName)
        }
    }
    finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- 1. 证书
$cert = $null
if ($Recreate) {
    $old = Get-LocalCodeSignCert -Subj $Subject
    if ($old) {
        Remove-Item ("Cert:\CurrentUser\My\" + $old.Thumbprint) -Force
        Write-Output ("removed old cert " + $old.Thumbprint)
    }
} else {
    $cert = Get-LocalCodeSignCert -Subj $Subject
}

if (-not $cert) {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(3) `
        -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3")
    Write-Output ("创建自签代码签名证书: " + $cert.Thumbprint)
}

Write-Output ""
Write-Output "== 证书 =="
Write-Output ("  主题    : " + $cert.Subject)
Write-Output ("  指纹    : " + $cert.Thumbprint)
Write-Output ("  有效期  : " + $cert.NotBefore.ToString('yyyy-MM-dd') + " → " + $cert.NotAfter.ToString('yyyy-MM-dd'))
if ($InfoOnly) { exit 0 }

if ($Install) {
    Write-Output ""
    Write-Output "== 安装信任（CurrentUser，无需管理员）=="
    Ensure-Trusted -Cert $cert
}

# ---------------------------------------------------------------- 2. 待签文件
$targets = @()
foreach ($f in $Files) { if ($f) { $targets += $f } }
if ($DistDir) {
    $targets += Get-ChildItem -Path $DistDir -Filter *.exe -File | ForEach-Object { $_.FullName }
}
$targets = $targets | Select-Object -Unique

if ($targets.Count -eq 0) {
    Write-Output ""
    Write-Output "没有指定要签名的文件（用 -Files 或 -DistDir）。证书已就绪，可随时签名。"
    exit 0
}

Write-Output ""
Write-Output "== 签名 =="
foreach ($path in $targets) {
    $full = (Resolve-Path $path -ErrorAction SilentlyContinue)
    if (-not $full) { Write-Output ("  [跳过] 不存在: " + $path); $script:Failed = $true; continue }
    $sig = Set-AuthenticodeSignature -FilePath $full.Path -Certificate $cert
    $check = Get-AuthenticodeSignature -FilePath $full.Path
    $ok = $check.Status -eq 'Valid'
    if (-not $ok) { $script:Failed = $true }
    Write-Output ("  [{0}] {1}  (status={2} signer={3})" -f $(if ($ok) { 'OK' } else { 'FAIL' }), $full.Path, $check.Status, $check.SignerCertificate.Thumbprint)
}

if ($script:Failed) { exit 1 }
Write-Output ""
Write-Output "全部签名成功。本机（当前用户）运行这些 exe 将不再触发 SmartScreen 提示。"
