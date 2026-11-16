"""GUI 主题：颜色、字体、ttk 样式与常用小部件构造。

观感基线见 research/screenshots/tk_prototype.png（深色 + HD2 金色强调）。
只依赖标准库 tkinter/ttk —— 与选型结论一致（Tk 31.7MB / 1 进程 / 0% 空闲 CPU）。
"""

import tkinter as tk
from tkinter import ttk

# ---- 调色板 -----------------------------------------------------------------
BG = "#0f141a"
PANEL = "#161d26"
PANEL2 = "#1b2431"
PANEL3 = "#222c3a"
BORDER = "#263341"
FG = "#e6edf3"
MUTED = "#8b98a5"
DIM = "#5f6f7e"
GOLD = "#ffd500"
GREEN = "#78dc8c"
RED = "#ff6b6b"
BLUE = "#6cb6ff"

FONT = "Microsoft YaHei UI"
F_T = (FONT, 17, "bold")
F_H = (FONT, 11, "bold")
F_B = (FONT, 10)
F_S = (FONT, 9)
F_MONO = ("Cascadia Mono", 9)
F_MONO_S = ("Cascadia Mono", 8)


def apply_theme(root: tk.Misc):
    """统一 ttk 样式（clam 主题改色；Treeview/Notebook/Scrollbar/Combobox）。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL2,
                    bordercolor=BORDER, lightcolor=PANEL2, darkcolor=PANEL2,
                    troughcolor=PANEL2, font=F_B)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=BG, foreground=FG, font=F_B)
    style.configure("Panel.TLabel", background=PANEL, foreground=FG)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=F_S)
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=F_S)
    style.configure("H.TLabel", background=BG, foreground=FG, font=F_H)
    style.configure("CardValue.TLabel", background=PANEL, foreground=FG,
                    font=(FONT, 19, "bold"))
    style.configure("CardTitle.TLabel", background=PANEL, foreground=MUTED, font=F_S)
    style.configure("CardSub.TLabel", background=PANEL, foreground=DIM, font=F_S)

    style.configure("TButton", background=PANEL2, foreground=FG, borderwidth=1,
                    focuscolor=BG, padding=(12, 6), font=F_B)
    style.map("TButton",
              background=[("active", PANEL3), ("disabled", PANEL2)],
              foreground=[("disabled", DIM)])
    style.configure("Primary.TButton", background=GOLD, foreground="#12161c",
                    font=F_H, padding=(16, 7))
    style.map("Primary.TButton", background=[("active", "#ffdf33")],
              foreground=[("disabled", DIM)])
    style.configure("Danger.TButton", background="#3a1f22", foreground=RED)
    style.map("Danger.TButton", background=[("active", "#4a262a")])

    style.configure("TCheckbutton", background=BG, foreground=FG, font=F_B)
    style.configure("Panel.TCheckbutton", background=PANEL, foreground=FG, font=F_B)
    style.configure("TEntry", fieldbackground=PANEL2, foreground=FG,
                    insertcolor=FG, bordercolor=BORDER)
    style.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                    foreground=FG, arrowcolor=MUTED, bordercolor=BORDER)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL2)],
              foreground=[("readonly", FG)])
    style.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                    padding=(14, 6), font=F_B)
    style.map("TNotebook.Tab", background=[("selected", PANEL2)],
              foreground=[("selected", FG)])
    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    font=F_B, rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED,
                    font=F_S, relief="flat")
    style.map("Treeview", background=[("selected", "#2a3b50")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=PANEL,
                    bordercolor=BORDER, arrowcolor=MUTED)
    style.configure("TScale", background=BG, troughcolor=PANEL2)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    foreground=MUTED, font=F_S)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=F_S)
    return style


# ---- 小部件工厂 -------------------------------------------------------------


def card(parent, title, value="—", sub="", accent=FG, width=None):
    """状态卡：标题 + 大数字 + 说明。返回 (frame, value_label, sub_label)。"""
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1,
                 padx=14, pady=10)
    if width:
        f.configure(width=width)
    tk.Label(f, text=title, bg=PANEL, fg=MUTED, font=F_S).pack(anchor="w")
    val = tk.Label(f, text=value, bg=PANEL, fg=accent, font=(FONT, 19, "bold"))
    val.pack(anchor="w", pady=(2, 0))
    sub_l = tk.Label(f, text=sub, bg=PANEL, fg=DIM, font=F_S, justify="left",
                     anchor="w", wraplength=210)
    sub_l.pack(anchor="w", fill="x")
    return f, val, sub_l


def section(parent, title, sub=None):
    """带标题与说明的区块（返回内容 frame）。"""
    wrap = tk.Frame(parent, bg=BG)
    head = tk.Frame(wrap, bg=BG)
    head.pack(fill="x")
    tk.Label(head, text=title, bg=BG, fg=FG, font=F_H).pack(side="left")
    if sub:
        tk.Label(head, text="  " + sub, bg=BG, fg=DIM, font=F_S).pack(side="left")
    body = tk.Frame(wrap, bg=BG)
    body.pack(fill="both", expand=True, pady=(6, 0))
    return wrap, body


def table(parent, columns, width=None, height=6):
    """只读表：columns = [(标题, 宽度), ...]；返回 (frame, Treeview)。"""
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    tv = ttk.Treeview(f, columns=[c[0] for c in columns], show="headings", height=height)
    for name, w in columns:
        tv.heading(name, text=name)
        tv.column(name, width=w, anchor="w")
    tv.pack(fill="both", expand=True, padx=1, pady=1)
    if width:
        f.configure(width=width)
    return f, tv


def fill_table(tv, rows):
    tv.delete(*tv.get_children())
    for row in rows:
        tv.insert("", "end", values=row)


def pill(parent, text="", fg=MUTED, bg=PANEL2):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=F_S, padx=10, pady=3)


def button(parent, text, command=None, primary=False, danger=False, width=None):
    style = "Primary.TButton" if primary else ("Danger.TButton" if danger else "TButton")
    b = ttk.Button(parent, text=text, command=command, style=style)
    if width:
        b.configure(width=width)
    return b


def entry(parent, textvariable=None, width=16):
    return ttk.Entry(parent, textvariable=textvariable, width=width)


class ScrollText(tk.Frame):
    """只读滚动文本（日志/输出）。"""

    def __init__(self, parent, height=12, mono=True, wrap="none"):
        super().__init__(parent, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1)
        self.text = tk.Text(self, height=height, bg=PANEL, fg=FG, bd=0,
                            font=F_MONO if mono else F_B, wrap=wrap,
                            insertbackground=FG, state="disabled")
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        sb.pack(side="right", fill="y")

    def set_text(self, content: str, see_end=True):
        """换内容。see_end=False 用于报告/计划（先看开头），默认滚到末尾（日志）。"""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.see("end" if see_end else "1.0")
        self.text.configure(state="disabled")

    def append(self, line: str):
        self.text.configure(state="normal")
        self.text.insert("end", line.rstrip("\n") + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")
