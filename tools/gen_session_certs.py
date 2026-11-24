"""会话证书签发 CLI（M1：实现已并入 hd2proxy.engine.certs，这里只做参数解析）。

命令行保持与研究线一致，便于旧脚本/文档直接沿用：

    python tools/gen_session_certs.py --out-dir certs --mode ca --days 2 --force

安全约束不变：ca 模式 / SAN 单域名 / 有效期 ≤2 天 / 签完立刻删 CA 私钥 / 目录里不留多余私钥。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hd2proxy.engine import certs   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--host", default=certs.DEFAULT_HOST)
    ap.add_argument("--mode", choices=["leaf", "ca"], default="ca",
                    help="默认 ca（游戏只认带 CRL 的 ca 模式；leaf 仅实验）")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="强制重新生成")
    a = ap.parse_args()

    out = Path(a.out_dir).resolve()
    try:
        report = certs.generate_session(out, host=a.host, days=a.days, max_days=a.days,
                                        force=a.force, mode=a.mode)
    except RuntimeError as e:
        print("ERROR: %s" % e)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report.get("reused"):
        print("reused existing session certificate (pass --force to regenerate)")
    return 0 if report.get("self_check") == "OK" else 3


if __name__ == "__main__":
    sys.exit(main())
