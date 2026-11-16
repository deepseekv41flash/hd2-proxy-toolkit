# v0.1.0-alpha.4 — alpha.3 实测发现的 3 个小问题修复 + 本机自签签名（2026-11-17）

> **alpha 预览版**：6 项能力已 M4 逐项实机验证，alpha.3 又在打包版上跑完 15 项 GUI 实测；
> 更多环境/游戏更新的稳定性仍在观察。

## 本版修了什么

alpha.3 发布后用 computer use 在**打包版 GUI**上逐项实测（15 项全 PASS，记录见
[`docs/ACCEPTANCE-alpha3-gui.md`](ACCEPTANCE-alpha3-gui.md)），过程中发现三个小问题，本版修掉：

1. **「切换直通」会被「应用配置」覆盖回去**：切换直通只改运行中的引擎（控制面 `/passthrough`），
   不写回 profile；切到「改写」后再点「应用配置」，会按旧 profile 把直通恢复，看起来像开关失灵。
   现在切换成功即写回内存 profile 并标记「未保存」（点「保存配置」可持久化）。
2. **打包版里证书签发的提示照抄会失败**：弹窗提示「下一步：`python -m hd2proxy install …`」，
   但打包版没有源码树/python 环境。现在冻结模式提示 `hd2proxy.exe …`，源码模式仍是 `python -m hd2proxy …`。
3. **只读弹窗长行被裁**：安装计划 / 还原计划 / 离线预演 / 证书签发窗口原来不换行、没有横向滚动条，
   长行（路径、指纹、JSON）左右看不全；现在按词换行，并默认从开头显示。

## 新增：本机自签代码签名（方便本机测试）

未签名的本地构建 exe 首次运行会弹 SmartScreen，自动化测试里这个对话框还点不动。本版加了：

- `tools/sign_local.ps1`：创建本机自签代码签名证书 → 装进**当前用户**的「受信任根 + 受信任发布者」
  （免管理员）→ 给 dist 里的 exe 签名；
- `tools/build_dist.py` 支持 `HD2PROXY_SIGN=1`：构建完自动签名再打包。

**边界**：自签只对**本机**有效（别人下载仍看到未识别发布者），不能替代正式代码签名。
详见 [`docs/SIGNING-LOCAL.md`](SIGNING-LOCAL.md)。

## 下载

| 文件 | 说明 |
|---|---|
| `hd2proxy-toolkit-v0.1.0-alpha.4-windows-x64.zip` | onedir 分发包（解压即用） |
| `SHA256SUMS.txt` | 校验和（zip + 两个 exe，**签名之后**计算） |

```powershell
Get-FileHash .\hd2proxy-toolkit-v0.1.0-alpha.4-windows-x64.zip -Algorithm SHA256
```

## 用法回顾

- 普通用户：双击 **`hd2proxy-gui.exe`**（无控制台）；
- 排障/脚本：`hd2proxy.exe`（CLI，双击也会开 GUI）；
- 想免除本机 SmartScreen：见 [`docs/SIGNING-LOCAL.md`](SIGNING-LOCAL.md)（一次装信任即可）。

## 已知限制（alpha）

- 抓包保存的是**改写前**原始响应；改写证据看日志里 `REWRITE*` 行 + 游戏内表现。
- `Mission/Session`（重连）服务端返回 `8012016`，v0.1 不承诺。
- 物品目录名不全（约 391/1671 有名字）。
- **settingsHash 决定星球身份**：生态借用后源星名字会变（预期副作用）。
- 休眠星节点号自选，坐标/hash 需按当前 build 的 live warinfo 核对。
- 仅 Windows x64；未签名（自签仅本机有效），首次运行可能有 SmartScreen 提示。
