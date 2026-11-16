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
from pathlib import Path

_HERE = Path(__file__).resolve()

# 仓库根 / 数据目录
REPO_ROOT = Path(os.environ.get("HD2PROXY_ROOT") or _HERE.parents[3])
DATA_DIR = Path(os.environ.get("HD2PROXY_DATA") or (REPO_ROOT / "data"))
LEGACY_DIR = DATA_DIR / "legacy"          # 研究线原始目录（引擎兼容层读这里）
CATALOGS_DIR = DATA_DIR / "catalogs"      # 产品规范化目录（GUI 用）

# 运行期数据（logs / runtime）：VMOD_DATA 可覆盖（测试隔离用）
_DATA_HOME = os.environ.get("VMOD_DATA")
BASEDIR = Path(_DATA_HOME) if _DATA_HOME else REPO_ROOT
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


# ---- 本机状态目录（M1 新增：profile / engine.json / 抓包默认目录） ----------
def state_dir() -> Path:
    """本机状态目录：默认 %LOCALAPPDATA%/HD2ProxyStudio，可用 HD2PROXY_STATE 覆盖。"""
    env = os.environ.get("HD2PROXY_STATE")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "HD2ProxyStudio"
    return Path.home() / ".hd2proxy"


def profile_dir() -> Path:
    return state_dir() / "profiles"


def engine_state_file() -> Path:
    return state_dir() / "engine.json"


def capture_default_dir() -> Path:
    return state_dir() / "captures"
