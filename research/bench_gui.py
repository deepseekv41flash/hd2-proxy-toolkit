"""GUI 技术栈实测：Tkinter vs pywebview(WebView2) 的稳定性和资源占用。

只测两件事（不做花活）：
  1. 冷启动到窗口可见的耗时；
  2. 空闲稳定后的工作集内存：本进程 + 子进程树（WebView2 的那堆 msedgewebview2）。

用法：
  python bench_gui.py tk        # Tkinter 窗口 6 秒
  python bench_gui.py webview   # pywebview(WebView2) 窗口 6 秒
  python bench_gui.py deps      # 只测 import 开销

输出：单行 JSON，便于粘进报告。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------- 内存统计


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def proc_mem_kb(pid):
    """单进程工作集（KB），失败返回 None。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    PROCESS_QUERY_INFORMATION = 0x0400
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return None
        return pmc.WorkingSetSize // 1024
    finally:
        k32.CloseHandle(h)


def image_mem_kb(image_name):
    """按镜像名汇总工作集（KB）。tasklist 输出第 5 列是 "123,456 K"。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq %s" % image_name, "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="ignore", timeout=10,
        ).stdout or ""
    except Exception:
        return 0, 0
    total, count = 0, 0
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.strip().split('","')]
        if len(parts) < 5 or not parts[0].lower().startswith(image_name.split(".")[0].lower()):
            continue
        try:
            total += int(parts[4].replace(",", "").split()[0])
            count += 1
        except (ValueError, IndexError):
            continue
    return total, count


def webview2_mem_kb():
    return image_mem_kb("msedgewebview2.exe")


# ---------------------------------------------------------------- 场景 1: Tk


def run_tk(hold_seconds=6):
    import tkinter as tk
    from tkinter import ttk

    t0 = time.time()
    root = tk.Tk()
    root.title("GUIBench · Tkinter")
    root.geometry("1000x700+120+120")
    root.configure(bg="#12161c")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    head = tk.Frame(root, bg="#12161c")
    head.pack(fill="x", padx=16, pady=(16, 8))
    tk.Label(head, text="HD2 战况代理工坊", bg="#12161c", fg="#e6edf3",
             font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
    tk.Label(head, text="  中文渲染测试 · 战况 / 变种 / 休眠星 / 生态借用",
             bg="#12161c", fg="#8b98a5", font=("Microsoft YaHei UI", 10)).pack(side="left")

    body = tk.Frame(root, bg="#1a2028")
    body.pack(fill="both", expand=True, padx=16, pady=8)
    cols = ("星球", "生态", "效果", "状态")
    tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
    for c in cols:
        tree.heading(c, text=c)
        tree.column(c, width=180)
    sample = [
        ("76 TERREK", "terminid", "PREDATOR STRAIN", "待注入"),
        ("100 TRANDOR", "deciduous", "生态借用", "已注入"),
        ("300 BICEP", "lava", "休眠星四件套", "预演通过"),
    ]
    for row in sample:
        tree.insert("", "end", values=row)
    tree.pack(fill="both", expand=True, padx=8, pady=8)

    foot = tk.Frame(root, bg="#12161c")
    foot.pack(fill="x", padx=16, pady=(4, 16))
    ttk.Button(foot, text="启动代理", width=14).pack(side="left")
    ttk.Button(foot, text="停止", width=10).pack(side="left", padx=8)
    ttk.Button(foot, text="验证三连", width=14).pack(side="left")

    root.deiconify()
    root.update_idletasks()
    root.update()
    t_visible = time.time()

    result = {}

    def finish():
        pid = os.getpid()
        result.update({
            "stack": "tkinter",
            "tk_version": tk.TkVersion,
            "pid": pid,
            "startup_to_visible_ms": round((t_visible - t0) * 1000),
            "self_ws_kb": proc_mem_kb(pid),
            "webview2_ws_kb": webview2_mem_kb()[0],
            "children_ws_kb": 0,
            "total_ws_kb": (proc_mem_kb(pid) or 0),
            "process_count": 1,
        })
        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        root.destroy()

    root.after(int(hold_seconds * 1000), finish)
    root.mainloop()


# ---------------------------------------------------------------- 场景 2: pywebview

HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:#12161c;color:#e6edf3;
            font-family:"Microsoft YaHei UI","Segoe UI",sans-serif}
  .head{display:flex;align-items:center;gap:14px;padding:16px 20px 8px}
  .title{font-size:20px;font-weight:700}
  .sub{color:#8b98a5;font-size:13px}
  .card{margin:8px 16px;padding:14px 16px;background:#1a2028;border:1px solid #2a333d;
        border-radius:10px}
  .row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #222b34}
  .row:last-child{border-bottom:none}
  .muted{color:#8b98a5}
  .badge{padding:1px 8px;border-radius:10px;font-size:12px}
  .ok{background:#1d3a26;color:#78dc8c}.warn{background:#3a341d;color:#ffd500}
  .bar{display:flex;gap:10px;padding:12px 16px}
  button{background:#1f2a36;color:#e6edf3;border:1px solid #33404d;border-radius:8px;
         padding:8px 18px;font-size:14px;font-family:inherit}
  button.primary{background:#ffd500;color:#12161c;border-color:#ffd500;font-weight:700}
</style></head><body>
  <div class="head"><div class="title">HD2 战况代理工坊</div>
    <div class="sub">中文渲染测试 · 战况 / 变种 / 休眠星 / 生态借用</div></div>
  <div class="card">
    <div class="row"><span>变种词条 · 76 TERREK</span><span><b>PREDATOR STRAIN</b>
      <span class="badge ok">已注入</span></span></div>
    <div class="row"><span>生态借用 · 100 TRANDOR</span><span>落叶林
      <span class="badge warn">预演</span></span></div>
    <div class="row"><span>休眠星 · 300 BICEP</span><span class="muted">四件套齐全</span></div>
  </div>
  <div class="bar"><button class="primary">启动代理</button><button>停止</button>
    <button>验证三连</button></div>
</body></html>"""


def run_webview(hold_seconds=6):
    import webview

    base_v2, base_n = webview2_mem_kb()
    t0 = time.time()
    window = webview.create_window(
        "GUIBench · pywebview", html=HTML, width=1000, height=700, background_color="#12161c",
    )
    state = {"visible": None}
    result = {}

    def probe():
        # 等窗口起来 + GPU 进程稳定
        time.sleep(max(2.5, hold_seconds * 0.6))
        state["visible"] = time.time()
        pid = os.getpid()
        self_kb = proc_mem_kb(pid) or 0
        wv_kb, wv_n = webview2_mem_kb()
        result.update({
            "stack": "pywebview(WebView2)",
            "webview_version": getattr(webview, "__version__", "?"),
            "pid": pid,
            "startup_to_visible_ms": round((state["visible"] - t0) * 1000),
            "self_ws_kb": self_kb,
            "webview2_ws_kb": wv_kb,
            "webview2_proc_count": wv_n,
            "webview2_baseline_ws_kb": base_v2,
            "children_ws_kb": wv_kb,
            "total_ws_kb": self_kb + wv_kb,
            "process_count": 1 + wv_n,
        })
        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        try:
            window.destroy()
        except Exception:
            os._exit(0)

    threading.Thread(target=probe, daemon=True).start()
    try:
        webview.start()
    except Exception as e:
        print(json.dumps({"stack": "pywebview(WebView2)", "error": repr(e)}, ensure_ascii=False))
        return


# ---------------------------------------------------------------- 场景 3: import 开销


def run_deps():
    import importlib
    out = {}
    for name in ("tkinter", "webview", "clr", "cryptography"):
        t0 = time.time()
        try:
            importlib.import_module(name)
            out[name] = round((time.time() - t0) * 1000)
        except Exception as e:
            out[name] = "ERR:%r" % (e,)
    print(json.dumps({"stack": "imports", "import_ms": out}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "deps"
    hold = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
    {"tk": run_tk, "webview": run_webview, "deps": lambda h: run_deps()}[cmd](hold)
