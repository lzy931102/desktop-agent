"""定时任务面板（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_show_scheduler/_add_scheduled/_render_sched_list 原样保留 self 语义，
AgentGUI 在 gui.py 里经 Mixin 组合继承；到点回调（_on_scheduled_task 族）
属主窗口核心装配，仍留在 gui.py。"""
import time
from tkinter import messagebox

import customtkinter as ctk

from core.scheduler import Scheduler
from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD, CARD_2,
                      INPUT_BG, MUTED, SIDEBAR, TEXT)
from ui.chat_stream import attach_modal_dialog

class SchedulerPanelMixin:
    def _show_scheduler(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("定时任务")
        dlg.geometry("720x560")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 10))
        ctk.CTkLabel(body, text="⏰ 定时任务", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")

        form = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
        form.pack(fill="x", pady=(10, 8))
        task_var = ctk.StringVar()
        type_var = ctk.StringVar(value="每天")
        time_var = ctk.StringVar(value="08:30")
        weekday_var = ctk.StringVar(value="星期一")
        interval_var = ctk.StringVar(value="30")

        ctk.CTkEntry(form, textvariable=task_var,
                     placeholder_text="到点执行的任务，如：打开计算器",
                     width=330, fg_color=INPUT_BG,
                     border_color=BORDER).grid(row=0, column=0, columnspan=3,
                                               sticky="w", padx=12, pady=(12, 6))
        type_menu = ctk.CTkOptionMenu(form, values=["每天", "每周", "间隔分钟"],
                                      variable=type_var, width=110,
                                      fg_color=INPUT_BG, button_color=ACCENT)
        time_entry = ctk.CTkEntry(form, textvariable=time_var, width=90,
                                  fg_color=INPUT_BG, border_color=BORDER,
                                  placeholder_text="08:30")
        weekday_menu = ctk.CTkOptionMenu(
            form, values=["星期一", "星期二", "星期三", "星期四", "星期五",
                          "星期六", "星期日"],
            variable=weekday_var, width=110, fg_color=INPUT_BG, button_color=ACCENT)
        interval_entry = ctk.CTkEntry(form, textvariable=interval_var, width=90,
                                      fg_color=INPUT_BG, border_color=BORDER)
        type_menu.grid(row=1, column=0, sticky="w", padx=12, pady=4)
        time_entry.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        weekday_menu.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        interval_entry.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        ctk.CTkButton(form, text="＋ 添加", width=80, height=28, corner_radius=6,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self._add_scheduled(
                          task_var, type_var, time_var, weekday_var, interval_var,
                          time_entry, weekday_menu, interval_entry)
                      ).grid(row=1, column=2, sticky="e", padx=12, pady=4)

        def on_type_change(_=None):
            if type_var.get() == "每天":
                time_entry.grid()
                weekday_menu.grid_remove()
                interval_entry.grid_remove()
            elif type_var.get() == "每周":
                time_entry.grid()
                weekday_menu.grid()
                interval_entry.grid_remove()
            else:
                time_entry.grid_remove()
                weekday_menu.grid_remove()
                interval_entry.grid()
        type_menu.configure(command=on_type_change)
        on_type_change()

        ctk.CTkLabel(body, text="现有任务", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", pady=(6, 2))
        self.sched_list_frame = ctk.CTkFrame(body, fg_color=SIDEBAR, corner_radius=10)
        self.sched_list_frame.pack(fill="both", expand=True)
        self._render_sched_list(self.sched_list_frame)


    def _add_scheduled(self, task_var, type_var, time_var, weekday_var,
                       interval_var, time_entry, weekday_menu, interval_entry):
        task = task_var.get().strip()
        if not task:
            return
        stype = {"每天": "daily", "每周": "weekly", "间隔分钟": "interval"}[
            type_var.get()]
        rec = self.scheduler.add(
            task, stype,
            time_str=time_var.get().strip() if time_entry.winfo_ismapped() else "",
            weekday={"星期一": "monday", "星期二": "tuesday", "星期三": "wednesday",
                     "星期四": "thursday", "星期五": "friday", "星期六": "saturday",
                     "星期日": "sunday"}.get(weekday_var.get(), "")
            if weekday_menu.winfo_ismapped() else "",
            interval_minutes=int(interval_var.get() or 0)
            if interval_entry.winfo_ismapped() else 0,
        )
        s = self.active
        if s:
            s.add("system",
                  text=f"⏰ 已添加定时任务（{Scheduler.describe(rec)}）：{task}",
                  tone="info")
            if self.active is s:
                self.chat.append(s.events[-1])
        for w in self.sched_list_frame.winfo_children():
            w.destroy()
        self._render_sched_list(self.sched_list_frame)


    def _render_sched_list(self, parent):
        tasks = self.scheduler.load()
        if not tasks:
            ctk.CTkLabel(parent, text="还没有定时任务，用上方表单添加",
                         font=ctk.CTkFont(size=12), text_color=MUTED).pack(pady=16)
            return
        for t in tasks:
            row = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=10, pady=4)
            mark = "🟢" if t.get("enabled") else "⚪"
            last = time.strftime("%m-%d %H:%M", time.localtime(t["last_run"])) \
                if t.get("last_run") else "未执行过"
            info = (f"{mark} {Scheduler.describe(t)} ｜ {t['task'][:26]}\n"
                    f"    上次：{last} {t.get('last_status', '')}")
            ctk.CTkLabel(row, text=info, font=ctk.CTkFont(size=13),
                         text_color=TEXT if t.get("enabled") else MUTED,
                         justify="left", anchor="w").pack(side="left", padx=10,
                                                          pady=6)
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=8)
            ctk.CTkButton(btns, text="禁用" if t.get("enabled") else "启用", width=48,
                          height=22, corner_radius=6, fg_color=CARD_2,
                          hover_color=BORDER, text_color=TEXT,
                          command=lambda tid=t["id"], en=not t.get("enabled"),
                          d=parent: (self.scheduler.set_enabled(tid, en),
                                     [c.destroy() for c in d.winfo_children()],
                                     self._render_sched_list(d))).pack(
                side="left", padx=2)
            def remove_one(tid=t["id"], d=parent, task_text=t["task"]):
                # 二次确认（对齐删技能包）：删除不可恢复，防手滑
                if messagebox.askyesno(
                        "删除确认",
                        f"确定删除这条定时任务吗？\n「{task_text[:30]}」删了得重新添加",
                        parent=d):
                    self.scheduler.remove(tid)
                    [c.destroy() for c in d.winfo_children()]
                    self._render_sched_list(d)

            ctk.CTkButton(btns, text="删除", width=48, height=22, corner_radius=6,
                          fg_color="#DC2626", hover_color="#B91C1C", text_color=TEXT,
                          command=remove_one).pack(side="left", padx=2)
