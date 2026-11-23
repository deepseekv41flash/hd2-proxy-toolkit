"""路径与运行期目录（M1 从 legacy_proxy.py 抽出）。

原则：**所有路径都不写死**，按「仓库位置 + 环境变量」推导，便于测试、便携部署与多实例。

环境变量（测试/多实例用）：
  HD2PROXY_ROOT   仓库根（默认 src/hd2proxy/engine/paths.py 往上三级）
  HD2PROXY_DATA   数据目录（默认 <仓库根>/data）
  HD2PROXY_STATE  本机状态目录（默认 %LOCALAPPDATA%/HD2ProxyStudio）
  HD2PROXY_CERTS  证书目录（默认 <仓库根>/certs）
  VMOD_DATA       运行期数据根（logs/runtime；研究线遗留，测试用它做隔离）
"""

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()

if getattr(sys, "frozen", False):
    # PyInstaller onedir：sys._MEIPASS = <bundle>/_internal（--add-data 的 data 在这里）；
    # 如果用户把 data/ 放在 exe 旁边（便携改配置），优先用 exe 旁边那份。
    _EXE_DIR = Path(sys.executable).resolve().parent
    _BUNDLE = Path(getattr(sys, "_MEIPASS", _EXE_DIR))
    _ROOT = _EXE_DIR if (_EXE_DIR / "data").is_dir() else _BUNDLE
else:
    _ROOT = _HERE.parents[3]

# 仓库根 / 数据目录
REPO_ROOT = Path(os.environ.get("HD2PROXY_ROOT") or _ROOT)
DATA_DIR = Path(os.environ.get("HD2PROXY_DATA") or (REPO_ROOT / "data"))
LEGACY_DIR = DATA_DIR / "legacy"          # 研究线原始目录（引擎兼容层读这里）
CATALOGS_DIR = DATA_DIR / "catalogs"      # 产品规范化目录（GUI 用）
SAMPLES_DIR = DATA_DIR / "samples"        # 离线预演用的样本响应（裁剪过、无账号字段）

def _state_home() -> Path:
    """本机状态目录：默认 %LOCALAPPDATA%/HD2ProxyStudio，可用 HD2PROXY_STATE 覆盖。"""
    env = os.environ.get("HD2PROXY_STATE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "HD2ProxyStudio"
    return Path.home() / ".hd2proxy"


# 运行期数据（logs / runtime）：VMOD_DATA 可覆盖（测试隔离用）。
# 冻结版一律放状态目录：打包后 REPO_ROOT = exe 所在目录，用户可能把它放在 Program Files
# 或只读盘里，那里写 logs/runtime 会静默失败（日志丢失）✓ 源码模式仍写仓库内，方便开发查看。
_DATA_HOME = os.environ.get("VMOD_DATA")
if _DATA_HOME:
    BASEDIR = Path(_DATA_HOME)
elif getattr(sys, "frozen", False):
    BASEDIR = _state_home()
else:
    BASEDIR = REPO_ROOT
LOGDIR = BASEDIR / "logs"
PROXY_LOG = LOGDIR / "proxy.log"
AUDIT_LOG = LOGDIR / "audit.log"
RUNTIME = BASEDIR / "runtime"
SELECTION = RUNTIME / "selection.json"
STRATAGEM_SELECTION = RUNTIME / "stratagems.json"
STATUS_FILE = RUNTIME / "status.json"
PROXY_PID = LOGDIR / "proxy.pid"
STRATAGEM_CATALOG = LEGACY_DIR / "stratagem_catalog.json"

# 证书目录
CERT_DIR = Path(os.environ.get("HD2PROXY_CERTS") or (REPO_ROOT / "certs"))

# ---- HTTP 端点标记 ----------------------------------------------------------
STATUS_MARK = "/api/WarSeason/801/Status"
ALLOWED_PATH = STATUS_MARK
# DSH-WARINFO-SETTINGS-V1
# 行星的关卡生成"设置"由服务器 warinfo 的 planetInfos[].settingsHash 指定（不是本地 planet_data 的
# setup 串）。本地 planet_data 尾部 438×8 B 的每项高 4 字节就是该行的 settingsHash，与 warinfo 的
# index 一一对应 ⇒ 改写 settingsHash 就能把 A 星的生态/地形借给 B 星。
WARINFO_MARK = "/api/WarSeason/801/warinfo"
INV_PATH = "/api/Progression/inventory"
ITEMS_PATH = "/api/Progression/items"
CUSTOMIZE_PATH = "/api/Progression/Items/Customize/v2"

# ---- G2 存档层：这几条必须**精确匹配**（`/api/Progression` 是上面几条的前缀！） ----
PROG_PATH = "/api/Progression"                 # 根进度响应：一次会话只拉一次 → 存档首屏
GETMOTD_MARK = "/api/Pes/GetMotd"             # 响应 accountId = SteamID64（存档主键来源）
GETMESSAGES_MARK = "/api/Pes/GetMessages"     # 响应 accountId = HD2 20 位 id（只作别名）
LOGIN_PATH = "/api/Account/Login"             # 请求体带 clientVersion（catalog_build 辅字段）
# G3：结算响应 = 本局奖励增量的源头（experience / badges[].itemRewards / rewards / 包进度）
MISSION_END_MARK = "/api/Operation/Mission/end"
# G4：终身统计（纯展示的单调计数器；`/api/Stats/war/801/summary` 另算，暂不碰）
STATS_PROFILE_MARKS = ("/api/Stats/profile/summary",
                       "/api/Stats/profile/801/summary")
# G5：客户端结算后主动上报成就累计值（响应恒为空 `{}`，值在**请求体**里）
ACHIEVEMENTS_PATH = "/api/Progression/Achievements"

# ---- 运行期状态文件（热重载：每个响应到达时现读） ---------------------------
INV_STATE = RUNTIME / "inventory_inject.json"
# 附件解锁注入（独立开关）：附件在服务端是 inventory 里的一行，mixId = 附件在该武器上的库存键，
# 行内容见 /api/Progression/items 里 progressionCategory==2 且带 parentId 的记录
# （itemId = 附件 optionId，parentId = 武器 mixId）。两者可分别开关，便于做单变量实验。
ATTACH_STATE = RUNTIME / "inventory_attach_inject.json"
# 外观（护甲/头盔/披风/横幅等 progressionCategory=3/9 的商店物品）注入：同样是 inventory 一行
COSMETIC_STATE = RUNTIME / "inventory_cosmetic_inject.json"
# 战备解锁物品（progressionCategory=11）：来自战团详情 GET /api/SeasonPass/<id> 的 itemMixId，
# 真实解锁 = POST /api/SeasonPass/item/buy → 响应 items[] 里 +1（2026-11-06 实证）
STRATAGEM_STATE = RUNTIME / "inventory_stratagem_inject.json"
# 类别探针（B 实验）：每个未知 progressionCategory 各取 1 件，观察客户端在哪个界面认它
PROBE_STATE = RUNTIME / "inventory_probe_inject.json"
ITEMS_STATE = RUNTIME / "items_inject.json"
# DSH-GWE-CUSTOMIZE-V1：L2（玩家当前改装槽快照）
#   GET /api/Progression/Items/Customize/v2
#   -> {items:[{mixId32, modes[4], activeIndex, customizations:[{index, slots[8]}]}]}
#   slots[i] = 附件 optionId（与 L0 同一 id 空间）；槽下标 = 槽号-1，实测 0=下挂 1=光学 4=弹匣/散热。
CUSTOMIZE_STATE = RUNTIME / "customize_inject.json"

# 存档层（G1）：每玩家一份 earned 账本；单文件 JSON + .bak，saveId 参数化
SAVES_DIR = RUNTIME / "saves"


# ---- 本机状态目录（M1 新增：profile / engine.json / 抓包默认目录） ----------
def state_dir() -> Path:
    """本机状态目录：默认 %LOCALAPPDATA%/HD2ProxyStudio，可用 HD2PROXY_STATE 覆盖。"""
    return _state_home()


def profile_dir() -> Path:
    return state_dir() / "profiles"


def engine_state_file() -> Path:
    return state_dir() / "engine.json"


def capture_default_dir() -> Path:
    return state_dir() / "captures"
