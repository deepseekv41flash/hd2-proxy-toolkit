"""页面基类与页面注册。

每个页面：`__init__(master, app)` → 在 `build()` 里构图，`refresh()` 在“显示/配置变更”时调用，
`on_status(status)` 每次轮询拿到引擎状态（None = 引擎未运行）。
"""

import tkinter as tk


class Page(tk.Frame):
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        from .. import theme
        super().__init__(master, bg=theme.BG)
        self.app = app
        self.build()

    def build(self):        # pragma: no cover - 子类实现
        pass

    def refresh(self):      # pragma: no cover - 子类实现
        pass

    def on_status(self, status):    # pragma: no cover
        pass

    # ---- 共用 -------------------------------------------------------
    def header(self, title, subtitle=""):
        import tkinter as tk
        from .. import theme
        head = tk.Frame(self, bg=theme.BG)
        head.pack(fill="x", padx=22, pady=(16, 8))
        tk.Label(head, text=title, bg=theme.BG, fg=theme.FG, font=theme.F_T).pack(side="left")
        if subtitle:
            tk.Label(head, text="  " + subtitle, bg=theme.BG, fg=theme.MUTED,
                     font=theme.F_S).pack(side="left")
        return head
