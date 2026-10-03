"""任务表与历史面板（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_show_tasks_table/_show_history 原样保留 self 语义，AgentGUI 在 gui.py 里
经 Mixin 组合继承；数据来自 self.sessions 与 self.history，零状态迁移。"""
import time

import customtkinter as ctk

from ui.theme import (BG, BORDER, CARD, CARD_2, FAINT, MUTED, SIDEBAR,
                      STATUS_COLOR, STATUS_ICON, STATUS_TEXT, TEXT)
from ui.formatters import rel_time, _effective_max_turns
from ui.chat_stream import attach_modal_dialog

class TasksMixin:
    def _show_tasks_table(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("任务表")
        dlg.geometry("980x560")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(14, 12))

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="📋 任务表", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text="本会话 + 历史记录，按时间倒序",
                     font=ctk.CTkFont(size=13), text_color=FAINT).pack(
            side="left", padx=12)
        ctk.CTkButton(head, text="↻ 刷新", width=64, height=24, corner_radius=6,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      font=ctk.CTkFont(size=13),
                      command=lambda: render(dlg, table)).pack(side="right")

        table = ctk.CTkScrollableFrame(body, fg_color=SIDEBAR, corner_radius=10)
        table.pack(fill="both", expand=True, pady=(10, 0))

        def chip(parent, status_key):
            icon, color = STATUS_ICON[status_key], STATUS_COLOR[status_key]
            f = ctk.CTkFrame(parent, fg_color="transparent", width=86, height=30)
            f.pack_propagate(False)
            ctk.CTkLabel(f, text=f"{icon} {STATUS_TEXT[status_key]}",
                         font=ctk.CTkFont(size=13), text_color=color).pack(
                anchor="w", padx=6)
            return f

        def render(dlg, table):
            for w in table.winfo_children():
                w.destroy()
            cols = [("状态", 90), ("任务", 260), ("轮次", 52), ("耗时", 68),
                    ("时间", 110), ("结果", 320)]
            header = ctk.CTkFrame(table, fg_color=CARD_2, corner_radius=6)
            header.pack(fill="x", pady=(2, 4))
            for name, width in cols:
                ctk.CTkLabel(header, text=name, width=width,
                             font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=MUTED, anchor="w").pack(
                    side="left", padx=2)

            def add_row(status_key, task, turns, elapsed, when, result):
                row = ctk.CTkFrame(table, fg_color=CARD, corner_radius=6)
                row.pack(fill="x", pady=1)
                chip(row, status_key).pack(side="left", padx=2, pady=4)
                ctk.CTkLabel(row, text=task, width=260, font=ctk.CTkFont(size=13),
                             text_color=TEXT, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=turns, width=52, font=ctk.CTkFont(size=13),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=elapsed, width=68, font=ctk.CTkFont(size=13),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=when, width=110, font=ctk.CTkFont(size=13),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                brief = result if len(result) <= 46 else result[:46] + "…"
                ctk.CTkLabel(row, text=brief, width=320, font=ctk.CTkFont(size=13),
                             text_color=FAINT, anchor="w").pack(side="left", padx=2)

            for s in reversed(list(self.sessions.values())):
                if s.status == "draft" and not s.task_text:
                    continue
                turns = (f"{s.turn}/{_effective_max_turns(self.settings)}"
                         if s.turn else "-")
                elapsed = f"{s.elapsed:.0f}秒" if s.elapsed else \
                    (f"{int(time.time() - s.start_time)}秒…" if s.start_time else "-")
                when = rel_time(time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(s.start_time))) if s.start_time else "-"
                result = s.events[-1]["text"] if s.events and \
                    s.events[-1]["kind"] == "system" else ""
                add_row(s.status, s.title, turns, elapsed, when, result)

            hist = self.history.recent(100)
            for r in hist:
                status_key = {"success": "done", "error": "failed",
                              "failed": "failed", "stopped": "stopped",
                              "max_turns": "failed", "empty_reply": "failed",
                              "running": "running"}.get(r.get("status", ""), "draft")
                if status_key == "running":
                    continue  # 本会话区已展示活任务，历史里残留的 running 是上次异常退出
                elapsed = f"{r['elapsed_s']:.0f}秒" if r.get("elapsed_s") else "-"
                result_txt = r.get("result", "")
                # 发现 D（2026-10-01）：status=success 但 tool_calls=0 = 对话
                # 完成却没动手（如模型纯文本拒做），标注出来避免统计失真
                if status_key == "done" and r.get("tool_calls") == 0:
                    result_txt = "⚠未调用工具　" + result_txt
                add_row(status_key, r.get("task", "")[:32],
                        str(r.get("turns", "-")) if r.get("turns") else "-",
                        elapsed, rel_time(r.get("ts", "")),
                        result_txt)

        render(dlg, table)


    def _show_history(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("任务历史")
        dlg.geometry("720x480")
        attach_modal_dialog(dlg, self.root)

        head = ctk.CTkFrame(dlg, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(head, text="📜 最近任务", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text=f"记录存放：{self.history.path.parent}",
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(side="right")

        box = ctk.CTkTextbox(dlg, font=ctk.CTkFont(family="Consolas", size=12),
                             fg_color=SIDEBAR, corner_radius=10, wrap="word",
                             state="disabled")
        box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        text = ""
        for r in self.history.recent(50):
            mark = {"success": "✓", "error": "✗", "stopped": "⏹",
                    "running": "⏳"}.get(r.get("status", ""), "·")
            elapsed = f"  {r.get('elapsed_s', 0):.0f}秒" if r.get("elapsed_s") else ""
            task = r.get("task", "")
            if len(task) > 40:
                task = task[:40] + "…"
            text += f"{mark} {r.get('ts', '')}  {task}{elapsed}\n"
        box.configure(state="normal")
        box.insert("1.0", text or "还没有任务记录")
        box.configure(state="disabled")
