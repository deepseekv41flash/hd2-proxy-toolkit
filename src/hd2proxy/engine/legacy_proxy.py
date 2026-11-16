"""兼容入口（M1）：M0 的 1846 行单文件已拆到 `hd2proxy.engine.*` 各模块。

保留本文件的原因：
  * M0 的 5 个离线自检（tests/selftest*.py）按「脚本路径」启动引擎，本文件保证它们不用改启动方式；
  * 研究线脚本/文档里调用 `war_proxy.py` 的方式可以平移到 `legacy_proxy.py`（含常用函数名再导出）。

真正的实现在 `hd2proxy.engine.server`；重构前后的行为基线见 `tests/fixtures/golden/`。

以脚本方式直接运行时（`python src/hd2proxy/engine/legacy_proxy.py ...`），
会自动把 `src/` 加进 sys.path，所以不需要先 pip install。
"""

import sys
from pathlib import Path

if __package__ in (None, ""):      # 作为脚本直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hd2proxy.engine.server import main   # noqa: E402

# ---- 研究线兼容再导出（旧脚本/自检按模块属性访问这些名字） -------------------
from hd2proxy.engine.catalog import (FACTION_AUTOMATON, FACTION_ILLUMINATE,  # noqa: E402,F401
                                     FACTION_TERMINID, FACTION_UNIVERSAL,
                                     MAX_STRATAGEMS, OWNER_FACTIONS,
                                     owner_faction, variant_faction)
from hd2proxy.engine.model import Mod, resolve_plan, rewrite_status  # noqa: E402,F401
from hd2proxy.engine.upstream import doh_resolve, upstream_addr  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(main())
