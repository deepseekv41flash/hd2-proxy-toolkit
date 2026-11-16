"""打包体积/启动测试用的最小 pywebview 应用（PyInstaller 打包后运行，结果写 JSON 文件）。"""
import json
import os
import sys
import threading
import time

T0 = time.time()

import webview

HTML = """<!doctype html><meta charset="utf-8"><style>
body{margin:0;height:100vh;background:#12161c;color:#e6edf3;
font-family:"Microsoft YaHei UI",sans-serif;padding:20px}
.t{font-size:20px;font-weight:700}
</style><div class="t">HD2 战况代理工坊 · 中文渲染</div>"""


def main():
    window = webview.create_window("bench webview", html=HTML, width=900, height=600,
                                   background_color="#12161c")
    state = {"loop": None}

    def on_loop():
        state["loop"] = time.time()

        def work():
            time.sleep(1.0)
            out = {
                "stack": "pywebview",
                "frozen": bool(getattr(sys, "frozen", False)),
                "startup_ms": round((state["loop"] - T0) * 1000, 1),
                "pid": os.getpid(),
            }
            base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
            with open(os.path.join(base, "result_webview.json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
            try:
                window.destroy()
            except Exception:
                os._exit(0)

        threading.Thread(target=work, daemon=True).start()

    webview.start(on_loop)


if __name__ == "__main__":
    main()
