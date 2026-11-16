"""单元测试包。

把 ``src/`` 放进 ``sys.path``，这样在仓库根直接 ``python -m pytest tests/unit`` 就能导入
``hd2proxy`` —— 仓库没有 conftest.py / pytest 配置（门禁只要求标准库 + 不引入额外配置），
而 ``tests/unit`` 是包（本文件），pytest 会先导入它，正好在这里做路径引导。
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
