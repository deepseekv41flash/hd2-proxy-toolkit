"""Tk 界面原型（静态 mock，只为看观感 + 出截图，不接后端）。

跑法： python prototype_tk.py            # 显示 3 秒后自动截图并退出
产物： research/screenshots/tk_prototype.png
"""

import ctypes
import os
import sys

# 高分屏清晰：先声明 DPI 感知，再建 Tk
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk

BG = "#0f141a"
PANEL = "#161d26"
PANEL2 = "#1b2431"
BORDER = "#263341"
FG = "#e6edf3"
MUTED = "#8b98a5"
DIM = "#5f6f7e"
GOLD = "#ffd500"
GREEN = "#78dc8c"
RED = "#ff6b6b"
BLUE = "#6cb6ff"

F = "Microsoft YaHei UI"
F_T = (F, 17, "bold")
F_H = (F, 11, "bold")
F_B = (F, 10)
F_S = (F, 9)
F_MONO = ("Cascadia Mono", 9)


def pill(parent, text, fg=GREEN, bg="#1a2b20"):
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg, font=F_S, padx=10, pady=3)
    return lbl


def stat_card(parent, title, value, sub, accent=FG, bar=None):
    card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    tk.Label(card, text=title, bg=PANEL, fg=MUTED, font=F_S).pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(card, text=value, bg=PANEL, fg=accent, font=(F, 20, "bold")).pack(anchor="w", padx=14)
    tk.Label(card, text=sub, bg=PANEL, fg=DIM, font=F_S).pack(anchor="w", padx=14, pady=(2, 12))
    if bar:
        canvas = tk.Canvas(card, height=4, bg=PANEL, highlightthickness=0)
        canvas.pack(fill="x", padx=14, pady=(0, 12))
        canvas.create_rectangle(0, 0, 400, 4, fill=PANEL2, outline="")
        canvas.create_rectangle(0, 0, 400 * bar, 4, fill=accent, outline="")
    return card


def build():
    root = tk.Tk()
    root.title("HD2 战况代理工坊（界面原型）")
    root.geometry("1180x760+80+60")
    root.configure(bg=BG)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    font=F_B, rowheight=27, borderwidth=0)
    style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED,
                    font=F_S, relief="flat")
    style.map("Treeview", background=[("selected", "#243447")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # ---------------- 顶部状态条 ----------------
    top = tk.Frame(root, bg=PANEL, height=44)
    top.pack(fill="x")
    tk.Frame(top, bg=BORDER, height=1).pack(side="bottom", fill="x")
    tk.Label(top, text="HD2 战况代理工坊", bg=PANEL, fg=FG, font=(F, 12, "bold")).pack(side="left", padx=16)
    tk.Label(top, text="build 26568081 · warId 801", bg=PANEL, fg=DIM, font=F_S).pack(side="left")
    right = tk.Frame(top, bg=PANEL)
    right.pack(side="right", padx=14)
    pill(right, "● 代理 未运行", fg=DIM, bg=PANEL2).pack(side="right", padx=4)
    pill(right, "证书 剩 1天3小时", fg=GOLD, bg="#2c2716").pack(side="right", padx=4)
    pill(right, "hosts 已配置", fg=GREEN, bg="#1a2b20").pack(side="right", padx=4)
    pill(right, "● 游戏 未启动", fg=DIM, bg=PANEL2).pack(side="right", padx=4)

    # ---------------- 主体：左侧导航 + 右侧内容 ----------------
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)

    nav = tk.Frame(body, bg=PANEL, width=196)
    nav.pack(side="left", fill="y")
    nav.pack_propagate(False)
    tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

    items = [("◈", "总览", True), ("◍", "战况改写", False), ("▤", "物品与战备", False),
             ("◫", "抓包与日志", False), ("⚙", "设置", False)]
    for icon, label, active in items:
        row = tk.Frame(nav, bg=PANEL2 if active else PANEL)
        row.pack(fill="x", padx=10, pady=2)
        if active:
            tk.Frame(row, bg=GOLD, width=3).pack(side="left", fill="y")
        tk.Label(row, text=icon, bg=PANEL2 if active else PANEL,
                 fg=GOLD if active else MUTED, font=(F, 12)).pack(side="left", padx=(10, 8), pady=9)
        tk.Label(row, text=label, bg=PANEL2 if active else PANEL,
                 fg=FG if active else MUTED, font=F_H if active else F_B).pack(side="left")

    nav_bottom = tk.Frame(nav, bg=PANEL)
    nav_bottom.pack(side="bottom", fill="x", padx=12, pady=12)
    tk.Label(nav_bottom, text="直通模式（不改写）", bg=PANEL, fg=MUTED, font=F_S).pack(anchor="w")
    tk.Label(nav_bottom, text="v0.1.0 · 仅本机 · 单域名白名单", bg=PANEL, fg=DIM, font=F_S).pack(anchor="w", pady=(6, 0))

    # 内容区（可滚动感用 frame 撑满）
    content = tk.Frame(body, bg=BG)
    content.pack(side="left", fill="both", expand=True)

    head = tk.Frame(content, bg=BG)
    head.pack(fill="x", padx=22, pady=(18, 6))
    tk.Label(head, text="总览", bg=BG, fg=FG, font=F_T).pack(side="left")
    tk.Label(head, text="  点「启动代理」→ 游戏里切一次星球即可生效",
             bg=BG, fg=MUTED, font=F_S).pack(side="left")

    btnbar = tk.Frame(content, bg=BG)
    btnbar.pack(fill="x", padx=22, pady=(6, 14))
    for text, primary in (("启动代理", True), ("直通模式", False), ("验证三连", False),
                          ("安装 / 修复", False), ("彻底还原", False)):
        tk.Label(btnbar, text=text, bg=GOLD if primary else PANEL2,
                 fg="#12161c" if primary else FG, font=F_H if primary else F_B,
                 padx=20, pady=8).pack(side="left", padx=(0, 8))

    # 四张状态卡
    cards = tk.Frame(content, bg=BG)
    cards.pack(fill="x", padx=22)
    for i in range(4):
        cards.columnconfigure(i, weight=1, uniform="c")
    stat_card(cards, "运行状态", "已停止", "443 未监听 · 上次运行 19:31", FG).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    stat_card(cards, "证书有效期", "1天 3小时", "2026-11-17 19:30 · 指纹 B832…", GOLD, bar=0.55).grid(row=0, column=1, sticky="nsew", padx=10)
    stat_card(cards, "本次改写", "0", "Status 0 · warinfo 0 · 库存 0", FG).grid(row=0, column=2, sticky="nsew", padx=10)
    stat_card(cards, "抓包", "关闭", "白名单 api/ · 上限 8 MB", MUTED).grid(row=0, column=3, sticky="nsew", padx=(10, 0))

    # 最近事件
    ev_head = tk.Frame(content, bg=BG)
    ev_head.pack(fill="x", padx=22, pady=(18, 6))
    tk.Label(ev_head, text="最近改写事件", bg=BG, fg=FG, font=F_H).pack(side="left")
    tk.Label(ev_head, text="  （来自 audit.log，实时追加）", bg=BG, fg=DIM, font=F_S).pack(side="left")
    tk.Label(ev_head, text="查看完整日志 ›", bg=BG, fg=BLUE, font=F_S).pack(side="right")

    ev_wrap = tk.Frame(content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    ev_wrap.pack(fill="both", expand=True, padx=22, pady=(0, 8))
    cols = ("时间", "钩子", "星球", "内容", "结果")
    tv = ttk.Treeview(ev_wrap, columns=cols, show="headings", height=8)
    widths = {"时间": 92, "钩子": 130, "星球": 150, "内容": 420, "结果": 110}
    for c in cols:
        tv.heading(c, text=c)
        tv.column(c, width=widths[c], anchor="w")
    rows = [
        ("19:31:04", "status.planet_effects", "76 TERREK", "追加 1243 / 1245（PREDATOR STRAIN）", "✓ 已下发"),
        ("19:31:04", "warinfo.settings_hash", "100 TRANDOR", "settingsHash → 2995599666（落叶林）", "✓ 已下发"),
        ("19:30:58", "status.planet_nodes", "300 BICEP", "补 planetStatus 节点 + 战役 51999", "✓ 已下发"),
        ("19:30:52", "inventory.stratagems", "—", "MG-43 / M-105 战备试用（cat 11）", "✓ 已下发"),
        ("19:30:47", "items.add", "—", "LAS-22 目录追加 3 行", "跳过（已存在）"),
    ]
    for r in rows:
        tv.insert("", "end", values=r)
    tv.pack(fill="both", expand=True, padx=1, pady=1)

    # 快捷模板
    tpl_head = tk.Frame(content, bg=BG)
    tpl_head.pack(fill="x", padx=22, pady=(10, 6))
    tk.Label(tpl_head, text="快捷模板", bg=BG, fg=FG, font=F_H).pack(side="left")
    tk.Label(tpl_head, text="  （v0.1 先做 6 项核心能力，其余进「扩展」页）", bg=BG, fg=DIM, font=F_S).pack(side="left")
    tpl = tk.Frame(content, bg=BG)
    tpl.pack(fill="x", padx=22, pady=(0, 14))
    for name, desc in (("变种词条", "单星球 · 双 id 成对注入"),
                       ("全局效果", "GWE type94 · 全图生效"),
                       ("战备试用", "type32 · 最多 3 条"),
                       ("物品解锁", "武器 / 配件 / 外观"),
                       ("休眠星", "四件套 · 补星球身份"),
                       ("生态借用", "settingsHash 换地貌")):
        card = tk.Frame(tpl, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(side="left", padx=(0, 10))
        tk.Label(card, text=name, bg=PANEL, fg=FG, font=F_H).pack(anchor="w", padx=12, pady=(9, 2))
        tk.Label(card, text=desc, bg=PANEL, fg=DIM, font=F_S).pack(anchor="w", padx=12, pady=(0, 9))

    # 底部状态行
    bottom = tk.Frame(root, bg=PANEL, height=26)
    bottom.pack(fill="x", side="bottom")
    tk.Frame(bottom, bg=BORDER, height=1).pack(side="top", fill="x")
    tk.Label(bottom, text="就绪 · 监听待启动 · 数据目录 %LOCALAPPDATA%\\HD2ProxyStudio",
             bg=PANEL, fg=DIM, font=F_S).pack(side="left", padx=12)
    tk.Label(bottom, text="引擎 未连接", bg=PANEL, fg=MUTED, font=F_S).pack(side="right", padx=12)
    return root


def main():
    root = build()
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "tk_prototype.png")

    def shoot():
        try:
            from PIL import ImageGrab
            root.attributes("-topmost", False)
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out)
            print("saved", out, w, h)
        except Exception as e:
            print("grab failed:", repr(e))
        root.destroy()

    root.after(1800, shoot)
    root.mainloop()


if __name__ == "__main__":
    main()
