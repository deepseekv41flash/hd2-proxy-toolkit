"""打包体积/启动测试用的最小 Tk 应用（PyInstaller 打包后运行，结果写 JSON 文件）。"""
import json
import os
import sys
import time

T0 = time.time()

import tkinter as tk
from tkinter import ttk


def main():
    root = tk.Tk()
    root.title("bench tk")
    root.geometry("900x600+100+100")
    root.configure(bg="#12161c")
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    tk.Label(root, text="HD2 战况代理工坊 · 变种 / 休眠星 / 生态借用",
             bg="#12161c", fg="#e6edf3",
             font=("Microsoft YaHei UI", 14, "bold")).pack(pady=16)
    tv = ttk.Treeview(root, columns=("a", "b"), show="headings", height=10)
    tv.heading("a", text="星球")
    tv.heading("b", text="效果")
    for r in (("76 TERREK", "PREDATOR STRAIN"), ("100 TRANDOR", "落叶林")):
        tv.insert("", "end", values=r)
    tv.pack(fill="both", expand=True, padx=16, pady=8)
    root.update_idletasks()
    root.update()
    visible = time.time()

    out = {
        "stack": "tkinter",
        "frozen": bool(getattr(sys, "frozen", False)),
        "exe": sys.executable if getattr(sys, "frozen", False) else sys.argv[0],
        "startup_ms": round((visible - T0) * 1000, 1),
        "pid": os.getpid(),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)),
                        "result_tk.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    root.after(1200, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
