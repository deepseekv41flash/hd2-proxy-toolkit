"""GUI 技术栈实测 v2：按「进程树」精确测资源，并采样空闲 CPU。

为什么重测：v1 用全机 msedgewebview2 汇总，本机还有别的 WebView2 应用在跑（基线 37 进程 / 2.2GB），
数字完全失真。v2 用 Toolhelp32 建 pid→ppid 图，只统计「python 根进程 + 它的全部子孙」，
并且用 GetProcessTimes 采样 5 秒空闲 CPU 时间，得到真实空闲占用。

用法：
  python bench_gui2.py tk
  python bench_gui2.py webview
  python bench_gui2.py all
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


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


def snapshot():
    """{pid: (ppid, exe)}"""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value or snap == -1:
        return {}
    out = {}
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(pe)
        ok = k32.Process32First(snap, ctypes.byref(pe))
        while ok:
            out[int(pe.th32ProcessID)] = (
                int(pe.th32ParentProcessID),
                pe.szExeFile.decode("mbcs", "ignore"),
            )
            ok = k32.Process32Next(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


def subtree(root_pid, snap=None):
    snap = snap or snapshot()
    children = {}
    for pid, (ppid, exe) in snap.items():
        children.setdefault(ppid, []).append(pid)
    seen, stack = set(), [root_pid]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack.extend(children.get(pid, []))
    return sorted(seen)


def ws_kb(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return 0
        return pmc.WorkingSetSize // 1024
    finally:
        k32.CloseHandle(h)


def cpu_seconds(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0.0
    try:
        c, e, k, u = (wt.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(k), ctypes.byref(u)):
            return 0.0
        total = (k.dwHighDateTime << 32 | k.dwLowDateTime) + \
                (u.dwHighDateTime << 32 | u.dwLowDateTime)
        return total / 1e7
    finally:
        k32.CloseHandle(h)


def measure_tree(root_pid, sample_seconds=5.0):
    """返回进程树的工作集与空闲 CPU 占用。"""
    pids = subtree(root_pid)
    ws = {p: ws_kb(p) for p in pids}
    cpu0 = {p: cpu_seconds(p) for p in pids}
    time.sleep(sample_seconds)
    pids2 = subtree(root_pid)
    cpu1 = {p: cpu_seconds(p) for p in pids2 if p in cpu0}
    used = sum(max(0.0, cpu1[p] - cpu0[p]) for p in cpu1)
    return {
        "process_count": len(pids),
        "total_ws_kb": sum(ws.values()),
        "processes": [{"pid": p, "exe": snapshot().get(p, (0, "?"))[1], "ws_kb": ws.get(p, 0)}
                      for p in pids],
        "idle_cpu_pct": round(used / sample_seconds * 100, 2),
    }


# --------------------------------------------------------------- Tkinter


def bench_tk():
    import tkinter as tk
    from tkinter import ttk

    t0 = time.time()
    root = tk.Tk()
    root.title("GUIBench · Tkinter")
    root.geometry("1000x700+120+120")
    root.configure(bg="#12161c")
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    tk.Label(root, text="HD2 战况代理工坊 · 中文渲染 · 变种/休眠星/生态借用",
             bg="#12161c", fg="#e6edf3", font=("Microsoft YaHei UI", 14, "bold")).pack(pady=12)
    body = tk.Frame(root, bg="#1a2028")
    body.pack(fill="both", expand=True, padx=16, pady=8)
    tv = ttk.Treeview(body, columns=("a", "b", "c"), show="headings", height=12)
    for c, w in (("a", 200), ("b", 240), ("c", 160)):
        tv.heading(c, text={"a": "星球", "b": "效果", "c": "状态"}[c])
        tv.column(c, width=w)
    for r in (("76 TERREK", "PREDATOR STRAIN", "已注入"),
              ("100 TRANDOR", "落叶林（生态借用）", "预演通过"),
              ("300 BICEP", "休眠星四件套", "待实机")):
        tv.insert("", "end", values=r)
    tv.pack(fill="both", expand=True, padx=8, pady=8)
    bar = tk.Frame(root, bg="#12161c")
    bar.pack(fill="x", padx=16, pady=12)
    ttk.Button(bar, text="启动代理").pack(side="left")
    ttk.Button(bar, text="停止").pack(side="left", padx=8)
    root.update_idletasks()
    root.update()
    t_visible = time.time()
    result = {}
    root.after(int(1000), lambda: None)

    def finish():
        pid = os.getpid()
        info = measure_tree(pid, sample_seconds=5.0)
        result.update({"stack": "tkinter", "tk": tk.TkVersion,
                       "startup_ms": round((t_visible - t0) * 1000), **info})
        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        root.destroy()

    root.after(1500, finish)
    root.mainloop()


# --------------------------------------------------------------- pywebview

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#12161c;color:#e6edf3;
  font-family:"Microsoft YaHei UI","Segoe UI",sans-serif}
.h{padding:16px 20px 6px;display:flex;gap:14px;align-items:baseline}
.t{font-size:20px;font-weight:700}.s{color:#8b98a5;font-size:13px}
.c{margin:8px 16px;padding:14px 16px;background:#1a2028;border:1px solid #2a333d;border-radius:10px}
.r{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #222b34}
.r:last-child{border:none}.m{color:#8b98a5}
.b{padding:1px 8px;border-radius:10px;font-size:12px}
.ok{background:#1d3a26;color:#78dc8c}.w{background:#3a341d;color:#ffd500}
.bar{display:flex;gap:10px;padding:12px 16px}
button{background:#1f2a36;color:#e6edf3;border:1px solid #33404d;border-radius:8px;
  padding:8px 18px;font-size:14px;font-family:inherit}
button.p{background:#ffd500;color:#12161c;border:none;font-weight:700}
</style></head><body>
<div class="h"><div class="t">HD2 战况代理工坊</div>
<div class="s">中文渲染 · 战况 / 变种 / 休眠星 / 生态借用</div></div>
<div class="c">
<div class="r"><span>变种词条 · 76 TERREK</span><span><b>PREDATOR STRAIN</b> <span class="b ok">已注入</span></span></div>
<div class="r"><span>生态借用 · 100 TRANDOR</span><span>落叶林 <span class="b w">预演</span></span></div>
<div class="r"><span>休眠星 · 300 BICEP</span><span class="m">四件套齐全</span></div></div>
<div class="bar"><button class="p">启动代理</button><button>停止</button><button>验证三连</button></div>
</body></html>"""


def bench_webview():
    import webview

    t0 = time.time()
    window = webview.create_window("GUIBench · pywebview", html=HTML,
                                  width=1000, height=700, background_color="#12161c")
    state = {"loop": None}
    result = {}

    def on_loop():
        state["loop"] = time.time()

        def work():
            time.sleep(2.0)          # 等 GPU/渲染进程起齐
            pid = os.getpid()
            info = measure_tree(pid, sample_seconds=5.0)
            result.update({"stack": "pywebview(WebView2)",
                           "startup_ms": round((state["loop"] - t0) * 1000), **info})
            print(json.dumps(result, ensure_ascii=False))
            sys.stdout.flush()
            try:
                window.destroy()
            except Exception:
                os._exit(0)

        threading.Thread(target=work, daemon=True).start()

    try:
        webview.start(on_loop)
    except Exception as e:
        print(json.dumps({"stack": "pywebview(WebView2)", "error": repr(e),
                          "hint": "需要 pythonnet + WebView2 Runtime"}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "tk":
        bench_tk()
    elif cmd == "webview":
        bench_webview()
    else:
        bench_tk()
        bench_webview()
