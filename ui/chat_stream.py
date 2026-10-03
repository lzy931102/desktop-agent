# 对话流渲染。
# T4 Phase 1 从 gui.py 原样抽出（ChatStream + attach_modal_dialog）。
import json
import os
import sys

import customtkinter as ctk

try:
    from PIL import Image
except ImportError:
    Image = None

from ui.formatters import tool_display
from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, BUBBLE_USER, CARD,
                      CARD_2, DEFAULT_MAX_CONCURRENT, ERR, EXAMPLES, FAINT,
                      MSG_BLOCKED_SUB, MUTED, OK, TEXT, TOOL_CHIP, TOOLC,
                      WARN, WELCOME_HEAD)

class ChatStream:
    """对话流渲染器：渲染单个会话的事件序列，支持卡片原地刷新。"""

    def __init__(self, parent, app):
        self.app = app
        self.frame = ctk.CTkScrollableFrame(parent, fg_color=BG, corner_radius=0)
        self.refs = {}  # id(event dict) → 控件引用（刷新用）

    # ---- 整体重建（切 Tab） ----
    def render_all(self, session):
        for w in self.frame.winfo_children():
            w.destroy()
        self.refs = {}
        if not session.events:
            self._render_welcome(session)
        for ev in session.events:
            self.append(ev, scroll=False)
        self._scroll_end()

    def _render_welcome(self, session):
        max_c = int(self.app.settings.get("max_concurrent", DEFAULT_MAX_CONCURRENT))
        box = ctk.CTkFrame(self.frame, fg_color=CARD, corner_radius=14)
        box.pack(anchor="w", padx=(6, 80), pady=(10, 6))
        ctk.CTkLabel(box, text=WELCOME_HEAD, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT, justify="left", anchor="w").pack(
            anchor="w", padx=16, pady=(12, 4))
        lines = [
            "告诉我一句想做的事就行，比如「打开记事本，输入 你好」，我会一步步操作给你看。",
            f"最多可以同时跑 {max_c} 个任务：点左上角「＋ 新建任务」再开一个。",
            "遇到删除文件、关闭窗口这类有风险的操作，我会先停下来问你。",
        ]
        for line in lines:
            ctk.CTkLabel(box, text="· " + line, font=ctk.CTkFont(size=12),
                         text_color=MUTED, justify="left", anchor="w",
                         wraplength=460).pack(anchor="w", padx=16, pady=1)
        # 示例任务卡片：点一下直接填进输入框
        ctk.CTkLabel(box, text="试试这些任务（点击直接填入）：",
                     font=ctk.CTkFont(size=13), text_color=FAINT,
                     anchor="w").pack(anchor="w", padx=16, pady=(8, 2))
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(anchor="w", padx=12, pady=(2, 10))
        short = ["🧮 打开计算器", "📝 打开记事本", "📷 截取屏幕", "🪟 查看窗口"]
        for i, (label, task) in enumerate(zip(short, EXAMPLES)):
            ctk.CTkButton(grid, text=label, width=170, height=38, corner_radius=10,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          font=ctk.CTkFont(size=12), anchor="w",
                          command=lambda t=task: self.app._use_example(t)
                          ).grid(row=i // 2, column=i % 2, padx=4, pady=4,
                                 sticky="w")
        ctk.CTkLabel(box, text=" ").pack(pady=(0, 6))

    # ---- 单事件渲染 ----
    def append(self, ev, scroll=True):
        kind = ev["kind"]
        if kind == "user":
            self._user(ev)
        elif kind == "assistant":
            self._assistant(ev)
        elif kind == "system":
            self._system(ev)
        elif kind == "turn":
            self._turn(ev)
        elif kind == "tool":
            self._tool(ev)
        elif kind == "confirm":
            self._confirm(ev)
        elif kind == "block":
            self._block(ev)
        if scroll:
            self._scroll_end()

    def refresh(self, ev):
        refs = self.refs.get(id(ev))
        if not refs:
            return
        kind = ev["kind"]
        if kind == "tool":
            text, color = TOOL_CHIP[ev["state"]]
            refs["chip"].configure(text=text, text_color=color)
            if ev.get("result"):
                tone = {"ok": OK, "err": ERR, "block": WARN}.get(ev["state"], MUTED)
                prefix = {"ok": "✓ ", "err": "✗ ", "block": "🚫 "}.get(ev["state"], "")
                refs["result"].configure(text=prefix + ev["result"], text_color=tone)
            if ev.get("note"):
                refs["note"].configure(text=ev["note"])
            if ev.get("img") and not refs.get("img_done"):
                refs["img_done"] = True
                self._attach_image(refs["card"], ev)
        elif kind == "confirm":
            if ev["state"] != "pending" and refs.get("btns"):
                refs["btns"].destroy()
                refs["btns"] = None
                done_text, done_color = (("✓ 已允许执行", OK) if ev["state"] == "allowed"
                                         else ("✗ 已拒绝", ERR))
                refs["state"].configure(text=done_text, text_color=done_color)

    # ---- 各类型卡片 ----
    def _user(self, ev):
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", pady=(8, 2))
        bubble = ctk.CTkFrame(row, fg_color=BUBBLE_USER, corner_radius=14)
        bubble.pack(anchor="e", padx=(90, 8))
        ctk.CTkLabel(bubble, text=ev["text"], font=ctk.CTkFont(size=13),
                     text_color="#FFFFFF", wraplength=440, justify="left").pack(
            padx=14, pady=8)

    def _assistant(self, ev):
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(row, text="🤖 助手", font=ctk.CTkFont(size=12),
                     text_color=FAINT, anchor="w").pack(anchor="w", padx=(8, 0))
        bubble = ctk.CTkFrame(row, fg_color=CARD, corner_radius=14)
        bubble.pack(anchor="w", padx=(8, 90))
        ctk.CTkLabel(bubble, text=ev["text"], font=ctk.CTkFont(size=13),
                     text_color=TEXT, wraplength=440, justify="left").pack(
            padx=14, pady=(8, 4))
        copy_btn = ctk.CTkButton(bubble, text="📋 复制", width=70, height=22,
                                 corner_radius=6, fg_color=CARD_2,
                                 hover_color=BORDER, text_color=MUTED,
                                 font=ctk.CTkFont(size=11),
                                 command=lambda: self._copy_reply(
                                     ev["text"], copy_btn))
        copy_btn.pack(anchor="e", padx=10, pady=(0, 8))

    def _copy_reply(self, text, btn):
        """一键复制助手回复；按钮短暂变成“已复制”给个反馈。"""
        self.app._copy_text(text)
        btn.configure(text="✓ 已复制", text_color=OK)
        self.app.root.after(1500,
                            lambda: btn.configure(text="📋 复制", text_color=MUTED))

    def _system(self, ev):
        color = {"info": MUTED, "ok": OK, "err": ERR,
                 "warn": WARN, "faint": FAINT}.get(ev.get("tone", "info"), MUTED)
        ctk.CTkLabel(self.frame, text=ev["text"], font=ctk.CTkFont(size=12),
                     text_color=color, wraplength=520, justify="left").pack(
            anchor="w", padx=10, pady=(3, 3))

    def _turn(self, ev):
        ctk.CTkLabel(self.frame, text=f"—— 第 {ev['n']} 轮 ——",
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(
            pady=(8, 2))

    def _tool(self, ev):
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 2))
        card = ctk.CTkFrame(row, fg_color=CARD_2, corner_radius=10,
                            border_width=1, border_color=BORDER)
        card.pack(anchor="w", padx=(8, 60), fill="x", expand=False)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(head, text=f"🔧 {tool_display(ev['name'], ev['args'])}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TOOLC, anchor="w").pack(side="left")
        chip_text, chip_color = TOOL_CHIP[ev["state"]]
        chip = ctk.CTkLabel(head, text=chip_text, font=ctk.CTkFont(size=13),
                            text_color=chip_color)
        chip.pack(side="right")

        args_lbl = ctk.CTkLabel(
            card, text="参数：" + json.dumps(ev.get("args", {}), ensure_ascii=False)[:140],
            font=ctk.CTkFont(family="Consolas", size=12), text_color=FAINT,
            wraplength=440, justify="left", anchor="w")
        args_lbl.pack(fill="x", padx=12, pady=(2, 0))

        result_lbl = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=13),
                                  wraplength=440, justify="left", anchor="w")
        result_lbl.pack(fill="x", padx=12, pady=(2, 0))

        note_lbl = ctk.CTkLabel(card, text=ev.get("note", ""),
                                font=ctk.CTkFont(size=13), text_color=WARN,
                                anchor="w")
        note_lbl.pack(fill="x", padx=12, pady=(0, 2))

        refs = {"chip": chip, "result": result_lbl, "note": note_lbl,
                "card": card, "img_done": False}
        self.refs[id(ev)] = refs
        if ev.get("img"):
            refs["img_done"] = True
            self._attach_image(card, ev)
        ctk.CTkLabel(card, text="").pack(pady=(0, 4))

    def _attach_image(self, card, ev):
        """截屏缩略图（点击放大）"""
        if Image is None:
            return
        try:
            path = ev["img"]
            if not os.path.exists(path):
                return
            img = Image.open(path)
            w, h = img.size
            tw = 240
            th = max(60, int(h * tw / w))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(tw, th))
            thumb = ctk.CTkLabel(card, image=ctk_img, text="")
            thumb.pack(anchor="w", padx=12, pady=(4, 6))
            thumb.bind("<Button-1>", lambda _e, p=path: self._show_image(p))
        except Exception:
            pass

    def _show_image(self, path):
        try:
            dlg = ctk.CTkToplevel(self.app.root, fg_color=BG)
            dlg.title("屏幕截图")
            img = Image.open(path)
            w, h = img.size
            scale = min(1.0, 900 / w, 620 / h)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                   size=(int(w * scale), int(h * scale)))
            ctk.CTkLabel(dlg, image=ctk_img, text="").pack(padx=10, pady=10)
            dlg.attributes("-topmost", True)
            dlg.after(200, dlg.lift)
        except Exception:
            pass

    def _confirm(self, ev):
        req = ev["req"]
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 2))
        card = ctk.CTkFrame(row, fg_color=CARD_2, corner_radius=10,
                            border_width=1, border_color=WARN)
        card.pack(anchor="w", padx=(8, 60), fill="x")
        ctk.CTkLabel(card, text="⚠ 需要你的确认",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=WARN, anchor="w").pack(anchor="w", padx=12,
                                                       pady=(8, 2))
        ctk.CTkLabel(card, text=f"我想「{tool_display(req['tool'], req['args'])}」",
                     font=ctk.CTkFont(size=12), text_color=TEXT,
                     wraplength=440, justify="left", anchor="w").pack(
            anchor="w", padx=12)
        ctk.CTkLabel(card, text="原因：" + req["reason"],
                     font=ctk.CTkFont(size=13), text_color=MUTED,
                     wraplength=440, justify="left", anchor="w").pack(
            anchor="w", padx=12, pady=(2, 0))

        state_lbl = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=13, weight="bold"))
        state_lbl.pack(anchor="w", padx=12, pady=(4, 0))
        btns = None
        if ev["state"] == "pending":
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(fill="x", padx=12, pady=(6, 10))
            ctk.CTkButton(btns, text="✗ 拒绝", width=96, height=30, corner_radius=8,
                          fg_color="#7F1D1D", hover_color="#991B1B", text_color=TEXT,
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda: self.app.answer_confirm(ev, False)).pack(
                side="left")
            ctk.CTkButton(btns, text="✓ 允许执行", width=110, height=30, corner_radius=8,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda: self.app.answer_confirm(ev, True)).pack(
                side="left", padx=(8, 0))
        else:
            done_text, done_color = (("✓ 已允许执行", OK) if ev["state"] == "allowed"
                                     else ("✗ 已拒绝", ERR))
            state_lbl.configure(text=done_text, text_color=done_color)
        self.refs[id(ev)] = {"btns": btns, "state": state_lbl}

    def _block(self, ev):
        row = ctk.CTkFrame(self.frame, fg_color="transparent")
        row.pack(fill="x", pady=(4, 2))
        card = ctk.CTkFrame(row, fg_color=CARD_2, corner_radius=10,
                            border_width=1, border_color=WARN)
        card.pack(anchor="w", padx=(8, 60), fill="x")
        ctk.CTkLabel(card, text="🚫 " + ev["text"], font=ctk.CTkFont(size=12),
                     text_color=WARN, wraplength=440, justify="left",
                     anchor="w").pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(card, text=MSG_BLOCKED_SUB, font=ctk.CTkFont(size=13),
                     text_color=FAINT, wraplength=440, justify="left",
                     anchor="w").pack(anchor="w", padx=12, pady=(2, 8))

    def _scroll_end(self):
        try:
            self.frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass


def attach_modal_dialog(dlg, owner):
    """把对话框接成 Windows 原生模态：禁用父窗口，关窗时自动恢复。

    为什么不用 Tk 的 grab_set：grab 在 Windows 上会拦掉对话框标题栏
    「—」的最小化消息（□/× 不受影响），点最小化没有任何反应。
    改用 Win32 模态惯例——父窗口禁输入、对话框可用，标题栏三个按钮
    恢复原生行为；对话框最小化后能从任务栏缩略图预览里点回来。
    """
    if not sys.platform.startswith("win"):
        return
    try:
        owner.attributes("-disabled", True)
    except Exception:
        return   # 平台不支持时退化为非模态，不影响对话框使用

    def restore(event=None):
        # <Destroy> 对每个子控件都会触发，只认对话框自身；
        # 销毁过程中 event.widget 是新建的包装对象，必须按路径比较，
        # 不能用 is/==
        if event is not None and str(event.widget) != str(dlg):
            return
        try:
            owner.attributes("-disabled", False)
        except Exception:
            pass   # 主窗口可能已随应用退出销毁

    dlg.bind("<Destroy>", restore)
