"""Desktop Agent 智能桌面助手 - 图形界面（多任务并行版）

布局（Windsurf 多 Tab + Claude Code 侧栏任务列表 + UI-TARS 对话流的融合）：
  顶栏：标题 + Ollama 连接徽章 + 定时 / 历史
  左侧栏：＋ 新建任务、任务列表（状态实时刷新）、底部 设置 / 任务表
  主区：Tab 栏（每个任务一个 Tab，可并行）→ 对话流（气泡 + 工具卡 + 确认卡 +
        截屏缩略图）→ 输入区（示例任务 + 开始/停止 + 轮次/耗时/Token）
多任务：每个任务一个 TaskSession（独立 DesktopAgent 实例与线程），并发上限
  默认 3（设置里可调 1-5），超出的任务自动排队，轮到即自动开始。
"""
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
import customtkinter as ctk
import agent_vision
import tkinter as tk
from tkinter import messagebox
from agent_loop import (DesktopAgent, LLMClient, LLMConfig, LLMProvider,
                        build_llm_client, final_reply_failed)
from core.approval import GuiApprovalBridge
from core.audit import AuditLogger
from core.history import TaskHistory
from core.retry import is_failed_result
from core.scheduler import Scheduler
from core.settings import (CLOUD_PRESETS, MAX_TURNS, PROVIDER_ENUM,
                           VISION_MODEL_OPTIONS, Settings, resolve_api_key,
                           should_show_onboarding)

try:
    from plugin_system import PluginManager
except ImportError:
    PluginManager = None  # 插件系统未安装，fallback 到纯内置工具

try:
    from skill_system import SkillManager
except ImportError:
    SkillManager = None  # 技能系统未安装，fallback 到无技能模式

try:
    from phone_bridge import (PhoneBridge, ST_FAILED, ST_RUNNING, ST_STARTING,
                              ST_STOPPED)
    from phone_bridge.contract import (EVENT_ERROR, EVENT_INFO, EVENT_RESULT,
                                       EVENT_TOOL, EVENT_TURN, STATE_DONE,
                                       STATE_FAILED, STATE_STOPPED)
except ImportError:
    PhoneBridge = None  # 手机连接组件未装齐（如缺 segno），设置面板不显示该分区

from mail_remote import MailConfigError, MailRemote  # 邮件远程（独立模块，纯标准库）

# ---- T4 Phase 1 兼容层（纯搬运零逻辑变更）：常量与工具函数已原样拆至 ui/ 包，
# ---- 此处再导出，保证 gui.py 内部与既有测试的引用路径完全不变。
from ui.theme import (APP_VERSION, OLLAMA_URL, MODEL_NAME,
                      DEFAULT_MAX_CONCURRENT, OLLAMA_DOWNLOAD_URL,
                      CLOUD_TUTORIAL_URL, BG, SIDEBAR, CARD, CARD_2,
                      BORDER, INPUT_BG, ACCENT, ACCENT_HOVER,
                      BUBBLE_USER, TEXT, MUTED, FAINT, OK, ERR, WARN,
                      RUNBLUE, AMBER, TOOLC, STATUS_COLOR, STATUS_ICON,
                      STATUS_TEXT, TOOL_CHIP, PLACEHOLDER, TOOL_NAMES,
                      EXAMPLES, WELCOME_HEAD, MSG_ON_IT, MSG_QUEUED,
                      MSG_DONE_OK, MSG_DONE_FAIL, MSG_STOPPED,
                      MSG_NEED_INPUT, MSG_APPROVED, MSG_DENIED,
                      MSG_BLOCKED_SUB, MSG_CONFIRM_HEAD)
from ui.formatters import (short_title, rel_time, fmt_tokens,
                            tool_display, humanize_error, parse_log,
                            _effective_max_turns)

# 高分屏清晰度修复：不声明 DPI 感知时，Windows 会把整个窗口位图拉伸放大，
# 文字就像隔着毛玻璃（用户反馈"字非常模糊"）。声明后按真实像素渲染，
# 再按系统缩放比例放大控件，字既清晰又不变小。
import ctypes as _ctypes
try:
    _ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI aware
except Exception:
    try:
        _ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    from PIL import Image
except ImportError:
    Image = None


class TaskSession:
    """一个任务会话 = 一个 Tab。只管状态与线程，Tk 渲染全在主线程。"""
    _seq = 0

    def __init__(self, title="新任务"):
        TaskSession._seq += 1
        self.id = f"t{TaskSession._seq}"
        self.title = title
        self.status = "draft"          # draft/queued/running/done/failed/stopped
        self.task_text = ""
        self.draft = ""                # 切走 Tab 时暂存输入框内容
        self.events = []               # 事件序列（tool/confirm 卡原地更新）
        self.ui_queue = queue.Queue()  # 工作线程 → 主线程 pump
        self.agent = None
        self.turn = 0
        self.start_time = None
        self.elapsed = None
        self.tokens = 0
        self.approval = GuiApprovalBridge()  # 每个任务独立审批桥，互不串扰
        self.stop_flag = False
        self.log_lines = []            # 实时日志（滚动区展示，可选中复制）
        self.current_action = ""       # 当前步骤描述（状态条展示）
        self.closing = False           # 已确认关闭、等线程收尾后再从列表摘除
        self.stop_requested_at = None  # 请求停止的时刻（30 秒兜底提示用）
        self.phone_task_id = None      # 手机下发的任务号（hub 对照）；本地任务为 None
        self.mail_task_id = None       # 邮件远程下发的任务号；本地任务为 None

    # ---- 事件（主线程调用） ----
    def add(self, kind, **kw):
        ev = {"kind": kind}
        ev.update(kw)
        self.events.append(ev)
        return ev

    def last_tool_event(self, name):
        for ev in reversed(self.events):
            if ev.get("kind") == "tool" and ev.get("name") == name \
                    and ev.get("state") in ("run", "err"):
                return ev
        return None

    # ---- 执行（工作线程） ----
    def launch(self, app):
        self.status = "running"
        self.start_time = time.time()
        self.turn = 0
        self.closing = False
        self.stop_requested_at = None
        threading.Thread(target=self._run, args=(app,), daemon=True).start()

    def _run(self, app):
        try:
            llm = build_llm_client(
                app.settings,
                on_fallback=lambda err: self.ui_queue.put(
                    ("log", f"⚠ 本地模型调用失败，自动切换云端：{err[:60]}")))

            # 插件管理器（可选）：有插件目录就创建，没有则跳过
            plugins = None
            if PluginManager is not None:
                from core.paths import plugins_dir
                plugins = PluginManager(app.settings, directory=plugins_dir())

            # 技能包管理器（可选）：技能/专家包指南注入 + install_skill 工具
            skills = None
            if SkillManager is not None:
                from core.paths import skills_dir
                skills = SkillManager(app.settings, directory=skills_dir())

            agent = DesktopAgent(llm, auditor=app.audit, history=app.history,
                                 approval=self.approval, plugins=plugins,
                                 skills=skills,
                                 max_turns=_effective_max_turns(app.settings))
            agent.on_log = lambda m: self.ui_queue.put(("log", m))
            agent.on_tool_call = lambda n, a: self.ui_queue.put(("tool_call", (n, a)))
            agent.on_tool_result = lambda n, a, r: self.ui_queue.put(
                ("tool_result", (n, a, r)))
            agent.on_retry = lambda n, i, mx: self.ui_queue.put(("retry", (n, i, mx)))
            self.agent = agent
            result = agent.run(self.task_text)
            self.tokens = agent.total_tokens
            stopped = "停止" in (result or "")
            # 防假成功：流程走完 ≠ 任务成功，最终回复带失败信号按失败处理
            ok = (result is not None and not stopped
                  and not final_reply_failed(result))
            self.ui_queue.put(("done", (ok, result or "", stopped)))
        except Exception as e:
            self.ui_queue.put(("done", (False, humanize_error(str(e)), False)))

    def stop(self):
        self.stop_flag = True
        if self.agent:
            self.agent.stop()


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


class PhoneTaskRunner:
    """phone_bridge.hub 的执行方适配器（TaskRunner 协议，任务 16 接线）。

    手机任务落回现有 TaskSession 通道：HTTP 线程只做投递，会话的创建/
    启动/停止一律经 root.after 回主线程（踩坑.md 条目 4），与本地任务
    走同一条"并发上限 + 排队"的路，不另开执行路径。submit 必须立即
    返回（hub 契约：不能阻塞 HTTP 请求线程）。
    """

    def __init__(self, app):
        self.app = app
        # hub 派发后、主线程会话还没建好之前收到的停止请求（见 _create_session）
        self._stop_before_start = set()

    def submit(self, task_id: str, text: str) -> None:
        self.app.root.after(0, lambda: self._create_session(task_id, text))

    def stop(self, task_id: str) -> bool:
        # hub.stop 在持锁状态下调用本方法：只登记 + 投递，绝不在锁内回调 hub
        self._stop_before_start.add(task_id)
        self.app.root.after(0, lambda: self._stop_session(task_id))
        return True

    def _create_session(self, task_id: str, text: str):
        if task_id in self._stop_before_start:
            # 停止请求赶在会话落地前：不建会话，直接按已取消收场
            self._stop_before_start.discard(task_id)
            if self.app.phone_bridge:
                try:
                    self.app.phone_bridge.hub.finish(
                        task_id, STATE_STOPPED, "还没开始就被叫停了")
                except Exception:
                    pass
            return
        s = TaskSession(title="📱 " + short_title(text))
        s.phone_task_id = task_id
        self.app.sessions[s.id] = s
        self.app._phone_tasks[task_id] = s
        s.task_text = text
        s.add("system", text="📱 这条任务来自手机连接", tone="info")
        s.add("user", text=text)
        # 与 _start_or_stop / _run_scheduled 同一条排队规则
        max_c = max(1, min(5, int(self.app.settings.get(
            "max_concurrent", DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.app.sessions.values()
                      if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self.app)
        self.app._select(s)
        self.app._sidebar_dirty = self.app._tabs_dirty = True

    def _stop_session(self, task_id: str):
        s = self.app._phone_tasks.get(task_id)
        if s is None:
            return    # 会话未落地（随 _create_session 的取消路径收场）或已结束
        if s.status == "queued":
            s.status = "draft"
            s.add("system", text="📱 手机端取消了这条任务", tone="info")
            self.app._phone_task_cancelled(s)
            self.app._remove_session(s)
        elif s.status == "running":
            s.stop_requested_at = time.time()
            s.stop()   # 与界面上点「停止」等效，done 事件经 _apply 回流 hub
            s.add("system", text="📱 手机端请求停止：当前这步执行完就停",
                  tone="faint")


class MailTaskRunner:
    """mail_remote 的执行方适配器：与 PhoneTaskRunner 同形（轮询线程只投递，
    会话创建/启停一律经 root.after 回主线程），任务落同一条 TaskSession 通道。

    与手机路径的差异：邮件通道带宽低，事件不做逐条回流——受理确认/查状态/
    停止由 mail_remote 直接回信，任务收尾由 _apply 的一次 done 事件回信结果。
    """

    def __init__(self, app):
        self.app = app

    def submit(self, task_id: str, text: str) -> None:
        self.app.root.after(0, lambda: self._create_session(task_id, text))

    def stop(self, task_id: str) -> bool:
        self.app.root.after(0, lambda: self._stop_session(task_id))
        return True

    def _create_session(self, task_id: str, text: str):
        s = TaskSession(title="✉️ " + short_title(text))
        s.mail_task_id = task_id
        self.app.sessions[s.id] = s
        self.app._mail_tasks[task_id] = s
        s.task_text = text
        s.add("system", text="✉️ 这条任务来自邮件远程", tone="info")
        s.add("user", text=text)
        # 与 _start_or_stop / _run_scheduled 同一条排队规则
        max_c = max(1, min(5, int(self.app.settings.get(
            "max_concurrent", DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.app.sessions.values()
                      if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self.app)
        self.app._select(s)
        self.app._sidebar_dirty = self.app._tabs_dirty = True

    def _stop_session(self, task_id: str):
        s = self.app._mail_tasks.get(task_id)
        if s is None:
            return
        if s.status == "queued":
            s.status = "draft"
            s.add("system", text="✉️ 邮件端取消了这条任务", tone="info")
            if self.app.mail_remote:
                try:
                    self.app.mail_remote.report(task_id, "已停止",
                                                "已在开始前取消")
                except Exception:
                    pass
            self.app._remove_session(s)
        elif s.status == "running":
            s.stop_requested_at = time.time()
            s.stop()
            s.add("system", text="✉️ 邮件端请求停止：当前这步执行完就停",
                  tone="faint")


class AgentGUI:
    def __init__(self):
        # 按系统 DPI 缩放控件（必须在创建窗口前设置）：高分屏不缩放会字太小
        try:
            _dpi = _ctypes.windll.user32.GetDpiForSystem()
            if _dpi and _dpi > 96:
                ctk.set_widget_scaling(_dpi / 96)
        except Exception:
            pass
        self.root = ctk.CTk()
        self.root.title(f"Desktop Agent v{APP_VERSION} - 智能桌面助手")
        self.root.geometry("1180x780")
        self.root.minsize(1020, 680)
        self.root.configure(fg_color=BG)

        # 企业化基础设施（个人版实现，接口与企业版一致）
        self.audit = AuditLogger()
        self.history = TaskHistory()
        self.settings = Settings()
        self.scheduler = Scheduler(on_due=self._on_scheduled_task,
                                   on_missed=self._on_missed_scheduled_task)
        self.scheduler.start()
        self.tray = None

        self.sessions = {}          # id → TaskSession（插入序 = 创建序）
        self.active = None
        self.ollama_ok = None       # None=检测中
        self._onboarding_auto_shown = False  # 本次运行只自动弹一次引导卡
        self._sidebar_dirty = True
        self._tabs_dirty = True

        # 手机连接（任务 16）：不在启动时创建/开启——这是把电脑控制权递出
        # 去的通道，每次启动都由用户在设置面板手动打开，防止忘了它还开着
        self.phone_bridge = None
        self._phone_tasks = {}      # phone task_id → TaskSession（hub 对照）
        self._phone_ui = None       # 打开中的设置面板手机分区刷新回调
        self._phone_ui_pending = False  # 刷新防抖（on_change 高频触发）

        # 邮件远程（mail_remote，任务 18）：同样默认关闭、手动开启；
        # 轮询线程在模块内部，GUI 只负责接线与终态回信
        self.mail_remote = None
        self._mail_tasks = {}       # mail task_id → TaskSession
        self._mail_ui = None        # 打开中的设置面板邮件分区状态回调

        self._build_header()
        self._build_body()
        self._init_tray()
        self._sync_privacy_banner()

        self.new_session()          # 启动即有一个空白任务 Tab
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._pump)
        threading.Thread(target=self._check_connection, daemon=True).start()

    # ================= 布局 =================
    def _build_header(self):
        bar = ctk.CTkFrame(self.root, fg_color="transparent")
        bar.pack(fill="x", padx=18, pady=(14, 2))
        ctk.CTkLabel(bar, text=f"🤖 Desktop Agent 智能桌面助手 v{APP_VERSION}",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self.conn_label = ctk.CTkLabel(bar, text="○ 正在连接本地 Ollama…",
                                       font=ctk.CTkFont(size=12), text_color=MUTED)
        self.conn_label.pack(side="right")
        # 徽章可点：随时唤出首启引导卡（换路线 / 装好 Ollama 后重新检测）
        self.conn_label.configure(cursor="hand2")
        self.conn_label.bind("<Button-1>", lambda e: self._show_onboarding())
        for text, cmd in (("📜 历史", self._show_history),
                          ("⏰ 定时", self._show_scheduler)):
            ctk.CTkButton(bar, text=text, width=64, height=24, corner_radius=6,
                          fg_color="transparent", border_width=1,
                          border_color=BORDER, text_color=MUTED,
                          hover_color=CARD_2, font=ctk.CTkFont(size=12),
                          command=cmd).pack(side="right", padx=(0, 8))

    def _sync_privacy_banner(self):
        """云端模式的隐私提示：窄条文字（在输入框下方），不再占顶部一整行"""
        mode = self.settings.get("model_mode", "local")
        if mode == "cloud":
            self.privacy_banner.configure(text="⚠️ 云端模式：屏幕数据会上传到模型服务商")
        elif mode == "auto":
            self.privacy_banner.configure(
                text="⚠️ 自动模式：本地失败时改用云端，屏幕数据可能上传")
        else:
            self.privacy_banner.configure(text="")

    def _build_body(self):
        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(6, 12))

        # ---- 左侧栏 ----
        sidebar = ctk.CTkFrame(body, fg_color=SIDEBAR, corner_radius=12,
                               border_width=1, border_color="#1F2937")
        sidebar.pack(side="left", fill="y", padx=(0, 12))

        ctk.CTkButton(sidebar, text="＋ 新建任务", height=36, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self.new_session).pack(fill="x", padx=12,
                                                     pady=(12, 8))

        self.task_list = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.task_list.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(bottom, text="📋 任务表", height=40, corner_radius=10,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT, hover_color=CARD_2,
                      font=ctk.CTkFont(size=13), anchor="w",
                      command=self._show_tasks_table).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bottom, text="⚙ 设置", height=40, corner_radius=10,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT, hover_color=CARD_2,
                      font=ctk.CTkFont(size=13), anchor="w",
                      command=self._show_settings).pack(fill="x")
        ctk.CTkButton(bottom, text="🔌 插件", height=40, corner_radius=10,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT, hover_color=CARD_2,
                      font=ctk.CTkFont(size=13), anchor="w",
                      command=self._show_plugins).pack(fill="x", pady=(6, 0))

        # ---- 主区 ----
        main = ctk.CTkFrame(body, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        self.tabbar = ctk.CTkFrame(main, fg_color="transparent", height=40)
        self.tabbar.pack(fill="x", pady=(0, 4))

        self.chat = ChatStream(main, self)
        self.chat.frame.pack(fill="both", expand=True)

        # ---- 状态条：当前步骤 + 脉动进度条（运行时一直有反馈，不再干等） ----
        statusbar = ctk.CTkFrame(main, fg_color=CARD, corner_radius=8)
        statusbar.pack(fill="x", pady=(4, 0))
        self.status_line = ctk.CTkLabel(statusbar, text="",
                                        font=ctk.CTkFont(size=12),
                                        text_color=MUTED, anchor="w")
        self.status_line.pack(side="left", padx=(12, 6), pady=5)
        self.status_bar = ctk.CTkProgressBar(statusbar, height=4,
                                             progress_color=ACCENT,
                                             fg_color=CARD_2)
        self.status_bar.pack(side="right", padx=12, pady=8, fill="x", expand=True)
        self.status_bar.set(0)
        self._bar_t = 0.0

        # ---- 实时日志区：可选中复制、自动滚到最底 ----
        logwrap = ctk.CTkFrame(main, fg_color="transparent")
        logwrap.pack(fill="x", pady=(4, 0))
        loghead = ctk.CTkFrame(logwrap, fg_color="transparent")
        loghead.pack(fill="x")
        ctk.CTkLabel(loghead, text="📜 运行日志（文字可选中复制）",
                     font=ctk.CTkFont(size=12), text_color=FAINT,
                     anchor="w").pack(side="left")
        ctk.CTkButton(loghead, text="🧹 清空", width=56, height=20,
                      corner_radius=6, fg_color=CARD, hover_color=CARD_2,
                      text_color=FAINT, font=ctk.CTkFont(size=11),
                      command=self._clear_log).pack(side="right")
        self.logbox = ctk.CTkTextbox(
            logwrap, height=132, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=SIDEBAR, corner_radius=8, wrap="word", text_color=MUTED)
        self.logbox.pack(fill="x", pady=(2, 0))
        self.logbox.configure(state="disabled")
        self._log_menu = tk.Menu(self.logbox, tearoff=0,
                                 font=("Microsoft YaHei UI", 10))
        self._log_menu.add_command(label="复制选中文字",
                                   command=self._copy_log_selection)
        self._log_menu.add_command(label="全选",
                                   command=lambda: self.logbox.tag_add("sel", "1.0", "end"))
        self.logbox.bind("<Button-3>", self._show_log_menu)

        # ---- 输入区 ----
        self._add_chip_rows(main, EXAMPLES)

        row = ctk.CTkFrame(main, fg_color="transparent")
        row.pack(fill="x", pady=(6, 0))
        self.input_text = ctk.CTkTextbox(
            row, height=56, font=ctk.CTkFont(size=13), corner_radius=10,
            fg_color=INPUT_BG, border_width=1, border_color=BORDER, wrap="word",
            text_color=TEXT)
        self.input_text.pack(side="left", fill="both", expand=True)
        self.input_text.tag_config("ph", foreground=FAINT)
        self.input_text.insert("1.0", PLACEHOLDER, "ph")
        self.input_text.bind("<FocusIn>", self._clear_placeholder)
        self.input_text.bind("<FocusOut>", self._restore_placeholder)
        self.input_text.bind("<Control-Return>",
                             lambda e: (self._start_or_stop(), "break")[1])

        self.start_button = ctk.CTkButton(
            row, text="▶ 开始执行", width=120, height=56, corner_radius=10,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._start_or_stop)
        self.start_button.pack(side="right", padx=(10, 0))

        status_row = ctk.CTkFrame(main, fg_color="transparent")
        status_row.pack(fill="x", pady=(4, 0))
        self.privacy_banner = ctk.CTkLabel(status_row, text="",
                                           font=ctk.CTkFont(size=13),
                                           text_color=WARN)
        self.privacy_banner.pack(side="left")
        self.progress_label = ctk.CTkLabel(status_row, text="",
                                           font=ctk.CTkFont(size=13),
                                           text_color=FAINT, anchor="e")
        self.progress_label.pack(side="right", fill="x", expand=True)

    def _add_chip_rows(self, parent, items):
        """示例任务 chips：按估算宽度自动换行，间距统一 8px"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="试试：", font=ctk.CTkFont(size=12),
                     text_color=FAINT).pack(side="left")
        used = 52
        for text in items:
            est = sum(7 if ord(ch) > 127 else 4 for ch in text) + 44
            if used + est > 620:
                row = ctk.CTkFrame(parent, fg_color="transparent")
                row.pack(fill="x", pady=(4, 0))
                used = 0
            ctk.CTkButton(row, text=text, height=26, corner_radius=13,
                          fg_color=CARD, hover_color=CARD_2, text_color=MUTED,
                          font=ctk.CTkFont(size=12),
                          command=lambda t=text: self._use_example(t)
                          ).pack(side="left", padx=(0, 8), pady=1)
            used += est

    # ================= 会话管理 =================
    def new_session(self):
        s = TaskSession()
        self.sessions[s.id] = s
        self._select(s)

    def _select(self, s):
        if self.active:
            self._save_draft(self.active)
        self.active = s
        self._restore_draft(s)
        self._sync_input_state()
        self.chat.render_all(s)
        self._replay_log(s)
        self._tabs_dirty = self._sidebar_dirty = True

    def _save_draft(self, s):
        content = self.input_text.get("1.0", "end").strip()
        s.draft = "" if content == PLACEHOLDER else content

    def _restore_draft(self, s):
        self.input_text.configure(state="normal")
        self.input_text.delete("1.0", "end")
        if s.draft:
            self.input_text.insert("1.0", s.draft)
        else:
            self.input_text.insert("1.0", PLACEHOLDER, "ph")

    def _sync_input_state(self):
        s = self.active
        running = s.status in ("running",)
        self.input_text.configure(state="disabled" if running else "normal")
        text, color, hover = {
            "draft": ("▶ 开始执行", ACCENT, ACCENT_HOVER),
            "queued": ("⏸ 取消排队", "#6B7280", "#4B5563"),
            "running": ("⏹ 停止", "#DC2626", "#B91C1C"),
            "done": ("▶ 开始执行", ACCENT, ACCENT_HOVER),
            "failed": ("▶ 开始执行", ACCENT, ACCENT_HOVER),
            "stopped": ("▶ 开始执行", ACCENT, ACCENT_HOVER),
        }[s.status]
        self.start_button.configure(text=text, fg_color=color, hover_color=hover)

    def close_session(self, s):
        if s.closing:
            return  # 停止流程已在走，等线程收尾即可
        if s.status == "running":
            if not messagebox.askyesno(
                    "任务还在跑",
                    f"「{s.title}」还在执行中，要停止并关闭它吗？\n"
                    f"（停止不是瞬间生效：当前这步执行完才真正停下）"):
                return
            s.closing = True
            s.stop_requested_at = time.time()
            s.stop()
            s.current_action = "⏹ 正在停止…当前这步跑完就关闭"
            s.add("system", text="已发出停止请求：当前这步执行完就关闭，请稍等。",
                  tone="faint")
            if self.active is s:
                self.chat.append(s.events[-1])
            self._sidebar_dirty = self._tabs_dirty = True
            return
        if s.status == "queued":
            s.status = "draft"
            self._phone_task_cancelled(s)   # 手机任务排队被关闭：hub 落终态
        self._remove_session(s)

    def _remove_session(self, s):
        self.sessions.pop(s.id, None)
        if not self.sessions:
            self.new_session()
        elif self.active is s:
            self._select(next(iter(self.sessions.values())))
        else:
            self._tabs_dirty = self._sidebar_dirty = True

    def rename_session(self, s):
        dlg = ctk.CTkInputDialog(text="给这个任务起个名字：", title="重命名")
        name = dlg.get_input()
        if name and name.strip():
            s.title = name.strip()[:20]
            self._tabs_dirty = self._sidebar_dirty = True

    def _use_example(self, text):
        self._clear_placeholder()
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", text)
        self.input_text.focus_set()

    def _clear_placeholder(self, _=None):
        if self.input_text.get("1.0", "end").strip() == PLACEHOLDER:
            self.input_text.delete("1.0", "end")

    def _restore_placeholder(self, _=None):
        if not self.input_text.get("1.0", "end").strip():
            self.input_text.insert("1.0", PLACEHOLDER, "ph")

    # ================= 开始 / 停止 / 排队 =================
    def _start_or_stop(self):
        s = self.active
        if s.status == "running":
            if s.closing:
                return  # 关闭流程已在走，避免重复停止提示
            s.stop_requested_at = time.time()
            s.stop()
            self.start_button.configure(text="正在停止…")
            s.add("system", text="收到，正在停下…", tone="faint")
            if self.active is s:
                self.chat.append(s.events[-1])
            return
        if s.status == "queued":
            s.status = "draft"
            if s.phone_task_id:
                self._phone_task_cancelled(s)   # 手机任务排队被取消：hub 落终态
            s.add("system", text="好，已取消排队。", tone="faint")
            self._sync_input_state()
            self._sidebar_dirty = self._tabs_dirty = True
            return
        if s.status != "draft" and s.status != "stopped" and s.status != "failed" \
                and s.status != "done":
            return

        task = self.input_text.get("1.0", "end").strip()
        if not task or task == PLACEHOLDER:
            s.add("system", text=MSG_NEED_INPUT, tone="warn")
            if self.active is s:
                self.chat.append(s.events[-1])
            return
        if self.ollama_ok is False:
            threading.Thread(target=self._check_connection, daemon=True).start()
            # ollama_ok 存的是当前模式下的连通状态（云端模式存的是云端连通），
            # 文案要跟模式走，别把用云端的用户指去查 Ollama
            mode = self.settings.get("model_mode", "local")
            if mode == "cloud":
                msg = ("连不上云端模型服务，请在「设置 → 云端模型」检查 API Key 和网络，"
                       "我正在重新检测…")
            elif mode == "auto":
                msg = ("本地和云端都连不上：本地请确认 Ollama 已启动，"
                       "云端请在「设置 → 云端模型」检查 API Key 和网络。我正在重新检测…")
            else:
                msg = "连不上本地 Ollama，请确认它已启动，我正在重新检测…"
            s.add("system", text=msg, tone="err")
            if self.active is s:
                self.chat.append(s.events[-1])
            return

        # 覆盖旧会话重跑：清空上一轮的事件流。清空后先补一条说明，别让用户
        # 对着空对话流以为上一轮记录丢了（render_all 按 events 重建，会渲染它）
        if s.status in ("done", "failed", "stopped"):
            had_history = bool(s.events)
            s.events.clear()
            s.start_time = None
            s.elapsed = None
            s.turn = 0
            if had_history:
                s.add("system", text="已开始新一轮，上一轮记录已收起", tone="faint")
        s.task_text = task
        s.title = short_title(task)
        s.draft = ""
        s.add("user", text=task)

        max_c = max(1, min(5, int(self.settings.get("max_concurrent",
                                                    DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.sessions.values() if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self)
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", PLACEHOLDER, "ph")
        self._sync_input_state()
        self.chat.render_all(s)
        self._sidebar_dirty = self._tabs_dirty = True

    def _launch_next_queued(self):
        max_c = max(1, min(5, int(self.settings.get("max_concurrent",
                                                    DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for s in self.sessions.values() if s.status == "running")
        if running >= max_c:
            return
        for s in self.sessions.values():
            if s.status == "queued":
                s.add("system", text="轮到啦，开始执行 👇", tone="faint")
                s.launch(self)
                self._sidebar_dirty = self._tabs_dirty = True
                if self.active is s:
                    self.chat.append(s.events[-1])
                    self._sync_input_state()
                return

    # ================= 日志区 / 状态条 =================
    def _log_line(self, s, text):
        """往任务日志追加一行（带时间戳），活动会话时写入滚动区并自动滚底。"""
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        s.log_lines.append(line)
        if len(s.log_lines) > 600:            # 防止长任务把内存吃满
            s.log_lines = s.log_lines[-600:]
        if self.active is s:
            self.logbox.configure(state="normal")
            self.logbox.insert("end", line + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")

    def _replay_log(self, s):
        """切回某个会话时，把它的日志重放进滚动区。"""
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        for line in s.log_lines[-600:]:
            self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _clear_log(self):
        s = self.active
        if s:
            s.log_lines = []
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    def _show_log_menu(self, event):
        try:
            self._log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._log_menu.grab_release()
        return "break"

    def _copy_log_selection(self):
        try:
            text = self.logbox.get("sel.first", "sel.last")
        except Exception:
            text = ""
        if not text:
            text = self.logbox.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ================= 事件应用（主线程） =================
    def _apply(self, s, kind, payload):
        if kind == "log":
            self._apply_log(s, payload)
        elif kind == "tool_call":
            name, args = payload
            ev = s.add("tool", name=name, args=args, state="run",
                       result="", note="", img=None)
            s.current_action = f"🔧 正在执行工具：{tool_display(name, args)}"
            self._log_line(s, f"▶ 调用工具 {name}，参数 "
                           + json.dumps(args, ensure_ascii=False)[:120])
            if self.active is s:
                self.chat.append(ev)
        elif kind == "tool_result":
            self._apply_tool_result(s, *payload)
        elif kind == "retry":
            name, attempt, mx = payload
            ev = s.last_tool_event(name)
            if ev:
                ev["note"] = f"↻ 第 {attempt}/{mx} 次重试中…"
                if self.active is s:
                    self.chat.refresh(ev)
        elif kind == "done":
            self._apply_done(s, *payload)
        if s.phone_task_id:
            self._phone_forward(s, kind, payload)   # 手机任务：事件回流 hub
        if s.mail_task_id:
            self._mail_forward(s, kind, payload)    # 邮件任务：终态回信（不逐事件刷）
        self._sidebar_dirty = self._tabs_dirty = True

    def _apply_log(self, s, raw):
        kind, text = parse_log(raw)
        if kind == "noise" or kind == "blocked":
            return  # 拦截结果经 tool_result 呈现，避免重复
        if kind == "turn":
            m = re.search(r"第 (\d+)/", text)
            n = int(m.group(1)) if m else 0
            s.turn = n
            s.current_action = f"🧠 第 {n}/{_effective_max_turns(self.app.settings)} 轮思考中…"
            self._log_line(s, f"—— 第 {n} 轮 ——")
            ev = s.add("turn", n=n)
        elif kind == "assistant":
            s.current_action = "💬 助手回复中…"
            self._log_line(s, f"🤖 {text[:200]}")
            ev = s.add("assistant", text=text)
        elif kind == "error":
            # 工具错误马上会有 tool_result 到来刷新卡片；无卡片时才落一条系统行
            if s.events and s.events[-1].get("kind") == "tool" \
                    and s.events[-1].get("state") == "run":
                return
            s.current_action = "⚠ 出了点问题，正在处理…"
            self._log_line(s, f"✗ {text[:200]}")
            ev = s.add("system", text="✗ " + text, tone="err")
        elif kind == "approved":
            self._log_line(s, "已允许执行")
            ev = s.add("system", text=MSG_APPROVED, tone="ok")
        else:
            self._log_line(s, text[:200])
            ev = s.add("system", text=text, tone="info")
        if self.active is s:
            self.chat.append(ev)

    def _apply_tool_result(self, s, name, args, result):
        text = str(result)
        ev = s.last_tool_event(name)
        if text.startswith("该操作被安全策略拦截"):
            if ev:
                ev.update(state="block", result=text)
                if self.active is s:
                    self.chat.refresh(ev)
            else:
                ev = s.add("block", text=text.replace("该操作被安全策略拦截", "").strip("（）"))
                if self.active is s:
                    self.chat.append(ev)
            return
        # 与重试层（core/retry.run_with_retry）同一判定："failed to connect"
        # 这类不带"错误"前缀的失败也必须在这里判负，不能界面打 ✓ 重试层判败
        ok = not is_failed_result(text)
        s.current_action = ("✓ 工具执行完成，继续下一步…" if ok
                            else f"✗ 工具 {name} 出了问题")
        self._log_line(s, ("✓ " if ok else "✗ ") + f"{name} 完成，结果："
                       + text.replace("\n", " ")[:150])
        if ev:
            ev.update(state="ok" if ok else "err", result=text)
            if name == "screenshot" and ok:
                ev["img"] = self._screenshot_path(args)
            if self.active is s:
                self.chat.refresh(ev)
        else:
            ev = s.add("system", text=("✓ " if ok else "✗ ") + text,
                       tone="ok" if ok else "err")
            if self.active is s:
                self.chat.append(ev)

    def _screenshot_path(self, args):
        p = str((args or {}).get("path", "") or "")
        if not p:
            return None
        path = p if os.path.isabs(p) else os.path.join("screenshots", p)
        return path if os.path.exists(path) else None

    def _apply_done(self, s, ok, result, stopped):
        s.elapsed = (time.time() - s.start_time) if s.start_time else None
        if stopped:
            s.status = "stopped"
            s.current_action = "⏹ 已停止"
            self._log_line(s, "⏹ 任务已停止")
            ev = s.add("system", text=MSG_STOPPED, tone="warn")
        elif ok:
            s.status = "done"
            extra = f"用时 {s.elapsed:.0f} 秒。" if s.elapsed else ""
            s.current_action = f"✓ 完成（{extra or '共用时：'}）"
            self._log_line(s, f"✓ 任务完成，{extra or ''}共 {s.turn} 轮")
            ev = s.add("system", text=MSG_DONE_OK.format(extra=extra), tone="ok")
        else:
            s.status = "failed"
            reason = result if len(result) <= 100 else result[:100] + "…"
            s.current_action = "✗ 失败"
            self._log_line(s, f"✗ 任务失败：{reason}")
            ev = s.add("system", text=MSG_DONE_FAIL.format(reason=reason), tone="err")
        if self.active is s:
            self.chat.append(ev)
            self._sync_input_state()
        self._update_tray("Desktop Agent · %d 个任务运行中" % sum(
            1 for x in self.sessions.values() if x.status == "running"))

    # ================= 手机连接（任务 16 接线） =================
    def _ensure_phone_bridge(self):
        if self.phone_bridge is None:
            self.phone_bridge = PhoneBridge(
                runner=PhoneTaskRunner(self),
                on_change=lambda: self.root.after(0, self._on_phone_change))
        return self.phone_bridge

    def _on_phone_change(self):
        """bridge 状态变了（开关/隧道/任务事件）：设置面板开着就刷新手机分区。
        on_change 从 HTTP/隧道线程高频触发，经 root.after 回主线程并防抖。"""
        if self._phone_ui is None or self._phone_ui_pending:
            return
        self._phone_ui_pending = True

        def run():
            self._phone_ui_pending = False
            cb = self._phone_ui
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass    # 面板可能正在销毁，刷新失败不影响桥接本身
        self.root.after(80, run)

    def _phone_forward(self, s, kind, payload):
        """手机下发的任务：把会话事件回流到 hub，手机端实时看到进展。
        只在主线程（_apply/_pump）执行；回流失败绝不反噬本地任务。"""
        if self.phone_bridge is None:
            return
        tid = s.phone_task_id
        hub = self.phone_bridge.hub
        try:
            if kind == "log":
                k, text = parse_log(payload)
                if k in ("noise", "blocked"):
                    return    # 拦截结果经 tool_result 呈现；重试/校验行不上屏
                hub.publish(tid, {"turn": EVENT_TURN,
                                  "error": EVENT_ERROR,
                                  "assistant": EVENT_RESULT}.get(k, EVENT_INFO),
                            text)
            elif kind == "tool_call":
                name, args = payload
                hub.publish(tid, EVENT_TOOL,
                            f"🔧 {tool_display(name, args)}")
            elif kind == "tool_result":
                name, args, result = payload
                hub.publish(tid, EVENT_TOOL, str(result))
            elif kind == "done":
                ok, result, stopped = payload
                state = (STATE_STOPPED if stopped
                         else STATE_DONE if ok else STATE_FAILED)
                self._phone_tasks.pop(tid, None)
                hub.finish(tid, state, result or "")
        except Exception:
            pass

    def _phone_publish_info(self, s, text):
        if self.phone_bridge is None:
            return
        try:
            self.phone_bridge.hub.publish(s.phone_task_id, EVENT_INFO, text)
        except Exception:
            pass

    def _phone_task_cancelled(self, s):
        """手机任务在排队时被电脑侧取消：hub 里落终态，否则手机端永远
        显示"执行中"（排队会话不会产生 done 事件，必须显式收口）。"""
        if not (s.phone_task_id and self.phone_bridge):
            return
        self._phone_tasks.pop(s.phone_task_id, None)
        try:
            self.phone_bridge.hub.finish(s.phone_task_id, STATE_STOPPED,
                                         "已在电脑上取消")
        except Exception:
            pass

    # ================= 邮件远程（mail_remote，任务 18） =================
    def _ensure_mail_remote(self):
        if self.mail_remote is None:
            self.mail_remote = MailRemote(
                runner=MailTaskRunner(self),
                status_provider=self._mail_status_snapshot,
                on_log=self._mail_log)
        return self.mail_remote

    def _mail_log(self, msg):
        """邮件模块日志：控制台留档 + 设置面板开着时刷新状态行"""
        print(msg)
        cb = self._mail_ui
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _mail_status_snapshot(self):
        """「状态」命令回信的数据源（轮询线程调用，读取要容错）。"""
        try:
            running = [{"title": s.title,
                        "action": s.current_action or "执行中"}
                       for s in list(self.sessions.values())
                       if s.status == "running"]
            queued = sum(1 for s in self.sessions.values()
                         if s.status == "queued")
            return {"running": running, "queued": queued}
        except Exception:
            return {"running": [], "queued": 0}

    def _mail_forward(self, s, kind, payload):
        """邮件任务只在收尾回一次信：受理确认/状态/停止由 mail_remote 自己
        回信，逐工具事件回信会让邮箱刷屏（邮件通道带宽低，与手机路径不同）。"""
        if self.mail_remote is None or kind != "done":
            return
        ok, result, stopped = payload
        state = ("已停止" if stopped else
                 "已完成" if ok else "没做成")
        self._mail_tasks.pop(s.mail_task_id, None)
        try:
            self.mail_remote.report(s.mail_task_id, state, result or "")
        except Exception:
            pass

    def answer_confirm(self, ev, allowed):
        GuiApprovalBridge.complete(ev["req"], allowed)
        ev["state"] = "allowed" if allowed else "denied"
        if self.active and any(e is ev for e in self.active.events):
            self.chat.refresh(ev)
        s = self._session_of(ev)
        if s:
            s.add("system", text=MSG_APPROVED if allowed else MSG_DENIED,
                  tone="ok" if allowed else "warn")
            if self.active is s:
                self.chat.append(s.events[-1])

    def _session_of(self, ev):
        for s in self.sessions.values():
            if any(e is ev for e in s.events):
                return s
        return None

    # ================= 主泵 =================
    def _pump(self):
        for s in list(self.sessions.values()):
            try:
                while True:
                    kind, payload = s.ui_queue.get_nowait()
                    self._apply(s, kind, payload)
            except queue.Empty:
                pass

        # 审批请求 → 确认卡（一次处理一条，弹到对应任务）
        for s in list(self.sessions.values()):
            if s.status != "running":
                continue
            req = s.approval.pending()
            if req:
                ev = s.add("confirm", req=req, state="pending")
                s.current_action = "⏸ 停下来了，等你确认后才继续"
                self._log_line(s, "⏸ 有风险操作，等你确认："
                               + str(req)[:120])
                if s.phone_task_id:
                    # 手机端看不到确认卡：在任务流里明说卡在哪，免得干等
                    self._phone_publish_info(
                        s, "电脑上弹出了确认卡（有风险的操作），"
                           "需要人在电脑前点「允许」才继续")
                if self.active is not s:
                    self._select(s)      # 切到该任务，render_all 已包含确认卡
                else:
                    self.chat.append(ev)
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                self.root.lift()
                self._sidebar_dirty = self._tabs_dirty = True

        # 已确认关闭的会话：等 done 事件落地（线程真正收尾）再从列表摘除，
        # 避免"列表里没了、线程还在跑"的假象
        for s in [x for x in self.sessions.values()
                  if x.closing and x.status != "running"]:
            self._remove_session(s)

        self._launch_next_queued()

        if self._tabs_dirty:
            self._rebuild_tabs()
            self._tabs_dirty = False
        if self._sidebar_dirty:
            self._rebuild_sidebar()
            self._sidebar_dirty = False

        self._update_progress()
        self.root.after(120, self._pump)

    def _update_progress(self):
        s = self.active
        # 脉动进度条：运行时来回游动，完成时满格，其余归零
        if s and s.status == "running":
            self._bar_t = (self._bar_t + 0.045) % 2.0
            v = self._bar_t if self._bar_t <= 1.0 else 2.0 - self._bar_t
            self.status_bar.set(0.06 + 0.88 * v)
        elif s and s.status == "done":
            self.status_bar.set(1.0)
        else:
            self.status_bar.set(0)

        if not s:
            self.status_line.configure(text="")
            self.progress_label.configure(text="")
            return
        if s.status == "running" and s.start_time:
            elapsed = int(time.time() - s.start_time)
            turn = (f"第 {s.turn}/{_effective_max_turns(self.settings)} 轮"
                    if s.turn else "准备中")
            tokens = s.agent.total_tokens if s.agent else 0
            self.progress_label.configure(
                text=f"⏳ {turn} · 已用 {elapsed} 秒 · ⚡ {fmt_tokens(tokens)} tokens")
            if s.stop_requested_at and time.time() - s.stop_requested_at > 30:
                # 停止兜底：长步骤（LLM 推理/看屏）没有边界时，别让人干等
                self.status_line.configure(
                    text="⏹ 已发出停止请求：当前步骤跑完就真停，请稍候…")
            else:
                self.status_line.configure(
                    text=s.current_action or "⟳ 思考中，请稍等…")
        elif s.status == "queued":
            ahead = sum(1 for x in self.sessions.values() if x.status == "running")
            self.progress_label.configure(text=f"⏸ 排队中 · 前面还有 {ahead} 个任务")
            self.status_line.configure(text="⏸ 排队等上一任务跑完…")
        elif s.status in ("done", "failed", "stopped") and s.elapsed:
            tokens = s.tokens or (s.agent.total_tokens if s.agent else 0)
            icon = {"done": "✓", "failed": "✗", "stopped": "⏹"}[s.status]
            self.progress_label.configure(
                text=f"{icon} 用时 {s.elapsed:.0f} 秒 · ⚡ {fmt_tokens(tokens)} tokens")
            self.status_line.configure(text=s.current_action)
        else:
            self.progress_label.configure(text="")
            self.status_line.configure(text="")

    # ================= 侧栏 / Tab 渲染 =================
    def _rebuild_tabs(self):
        for w in self.tabbar.winfo_children():
            w.destroy()
        for s in self.sessions.values():
            active = s is self.active
            tab = ctk.CTkFrame(self.tabbar, fg_color=CARD_2 if active else "transparent",
                               corner_radius=8,
                               border_width=1 if active else 0, border_color=BORDER)
            tab.pack(side="left", padx=(0, 6), pady=2)
            ctk.CTkButton(
                tab, text=f"{STATUS_ICON[s.status]} {s.title}", height=28,
                corner_radius=8, fg_color="transparent", hover_color=CARD_2,
                text_color=TEXT if active else MUTED,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal"),
                command=lambda s=s: self._select(s)).pack(side="left", padx=(10, 0))
            ctk.CTkButton(tab, text="×", width=18, height=18, corner_radius=9,
                          fg_color="transparent", hover_color="#4B5563",
                          text_color=FAINT,
                          font=ctk.CTkFont(size=13),
                          command=lambda s=s: self.close_session(s)).pack(
                side="left", padx=(4, 8))
        ctk.CTkButton(self.tabbar, text="＋", width=30, height=28, corner_radius=8,
                      fg_color="transparent", hover_color=CARD_2,
                      text_color=MUTED, font=ctk.CTkFont(size=14),
                      command=self.new_session).pack(side="left", padx=(0, 6))

    def _rebuild_sidebar(self):
        for w in self.task_list.winfo_children():
            w.destroy()
        for s in reversed(list(self.sessions.values())):  # 新任务在上
            color = STATUS_COLOR[s.status]
            sub = {"running": ("⏹ 正在停止，这步跑完就关" if s.closing
                               else f"第 {s.turn}/{_effective_max_turns(self.settings)} 轮"),
                   "queued": "排队等待中",
                   "done": f"完成 · {s.elapsed:.0f} 秒" if s.elapsed else "完成",
                   "failed": "失败了，点进去看看",
                   "stopped": "已停止",
                   "draft": "还没开始"}.get(s.status, "")
            item = ctk.CTkFrame(self.task_list, fg_color=CARD if s is self.active
                                else "transparent", corner_radius=8)
            item.pack(fill="x", pady=1)
            row = ctk.CTkFrame(item, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(6, 2))
            ctk.CTkLabel(row, text=STATUS_ICON[s.status], width=18,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=color).pack(side="left")
            ctk.CTkButton(row, text=s.title, height=20, corner_radius=4,
                          fg_color="transparent", hover_color=CARD_2,
                          text_color=TEXT if s is self.active else MUTED,
                          anchor="w",
                          font=ctk.CTkFont(size=12, weight="bold" if s is self.active
                                           else "normal"),
                          command=lambda s=s: self._select(s)).pack(
                side="left", fill="x", expand=True)
            ctk.CTkLabel(item, text=sub, font=ctk.CTkFont(size=12),
                         text_color=color, anchor="w").pack(
                fill="x", padx=34, pady=(0, 6))
            self._bind_menu(item, s)

    def _bind_menu(self, widget, s):
        menu = tk.Menu(widget, tearoff=0, font=("Microsoft YaHei UI", 10))
        menu.add_command(label="重命名",
                         command=lambda s=s: self.rename_session(s))
        menu.add_command(label="关闭任务",
                         command=lambda s=s: self.close_session(s))

        def popup(e):
            menu.tk_popup(e.x_root, e.y_root)
        for w in (widget,) + tuple(widget.winfo_children()):
            w.bind("<Button-3>", popup)

    # ================= 连接检测 =================
    def _check_connection(self, extra_done=None):
        mode = self.settings.get("model_mode", "local")
        where = {"cloud": "云端", "auto": "自动切换"}.get(mode, "Ollama")
        try:
            client = build_llm_client(self.settings)
            ok, info = client.check_connection()
        except RuntimeError as e:
            ok, info = False, str(e)
        vis = agent_vision.get_vision()
        if ok:
            sight = vis.describe() if vis.is_available() else "未就绪"
            text = f"● {where}已连接 · 看屏 {sight}"
        else:
            text = f"○ {where}未连接（{info}）"
        self.root.after(0, lambda: self._set_conn(ok, text))
        if extra_done is not None:
            # 供引导卡「重新检测」把结果同步到卡片上的状态行（主线程更新）
            self.root.after(0, lambda: extra_done(ok, text))

    def _set_conn(self, ok, text):
        first_check = self.ollama_ok is None   # 尚无任何检测结果 = 启动首检
        self.ollama_ok = ok
        self.conn_label.configure(text=text, text_color=OK if ok else ERR)
        # 首启引导：只在启动首检就失败时按状态机自动弹一次；会话中途的
        # 瞬时失败不弹模态卡（徽章随时可手动唤出）
        if ok is False and first_check and not self._onboarding_auto_shown:
            self._onboarding_auto_shown = True
            if should_show_onboarding(self.settings, ok):
                self.root.after(400, self._show_onboarding, True)

    # ================= 首启引导卡（UX-P1-6） =================
    def _show_onboarding(self, auto=False):
        """检测不到模型服务时的三选一引导：云端 / 本地 / 稍后再说。

        auto=True 是启动自动弹出，受 onboarding_choice 状态约束（已选过路线
        的老用户不弹；"稍后再说"只再提醒一次）；顶栏徽章点击唤出时
        auto=False，不受约束，随时可看。
        """
        prev_choice = str(self.settings.get("onboarding_choice", "") or "")
        if auto and prev_choice == "later":
            # "稍后再说"后的最后一次自动提醒：先记为已引导——这次无论怎么
            # 关（选别的、点 ×），都不会再有自动弹出；徽章仍可手动唤出
            self.settings.set("onboarding_choice", "dismissed")

        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("欢迎使用 Desktop Agent")
        dlg.geometry("560x440")
        dlg.resizable(False, False)
        attach_modal_dialog(dlg, self.root)
        dlg.attributes("-topmost", True)
        dlg.after(200, dlg.lift)

        def pick(choice):
            self.settings.set("onboarding_choice", choice)

        def pick_later():
            # "" → later：下次启动仍未连上时再提醒一次；已是 later（本次就是
            # 那次提醒，或徽章唤出后再次婉拒）→ dismissed，不再自动弹
            pick("dismissed" if prev_choice == "later" else "later")
            dlg.destroy()

        wrap = ctk.CTkFrame(dlg, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=26, pady=(22, 18))

        def build_home():
            for w in wrap.winfo_children():
                w.destroy()
            connected = bool(self.ollama_ok)
            ctk.CTkLabel(wrap, text="🤖 欢迎使用 Desktop Agent",
                         font=ctk.CTkFont(size=17, weight="bold"),
                         text_color=TEXT).pack(anchor="w")
            ctk.CTkLabel(wrap, text=("✓ 模型服务已连接，可以直接开始用"
                                     if connected else
                                     "○ 还没连上模型服务——连上一个 AI 模型才能开始帮你干活"),
                         font=ctk.CTkFont(size=13),
                         text_color=OK if connected else WARN).pack(
                anchor="w", pady=(6, 0))
            ctk.CTkLabel(wrap, text="选一种方式开始（以后随时可在「设置」里更改）：",
                         font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                anchor="w", pady=(2, 16))
            ctk.CTkButton(wrap, text="☁  我不太懂，用云端（推荐）", height=46,
                          corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=lambda: self._onboarding_pick_cloud(dlg, pick)
                          ).pack(fill="x", pady=(0, 8))
            link = ctk.CTkLabel(wrap, text=f"先看看图文教程（网页）：{CLOUD_TUTORIAL_URL}",
                                font=ctk.CTkFont(size=12), text_color=ACCENT,
                                cursor="hand2")
            link.pack(anchor="w", pady=(0, 14))
            link.bind("<Button-1>", lambda e: webbrowser.open(CLOUD_TUTORIAL_URL))
            ctk.CTkButton(wrap, text="💻  我要用本地（数据不出本机，需先安装 Ollama）",
                          height=46, corner_radius=10,
                          font=ctk.CTkFont(size=13, weight="bold"),
                          fg_color=CARD_2, hover_color=BORDER,
                          command=lambda: self._onboarding_pick_local(wrap, pick)
                          ).pack(fill="x", pady=(0, 8))
            ctk.CTkButton(wrap, text="⏰  稍后再说", height=40, corner_radius=10,
                          font=ctk.CTkFont(size=13),
                          fg_color="transparent", border_width=1,
                          border_color=BORDER, text_color=MUTED,
                          hover_color=CARD_2,
                          command=pick_later).pack(fill="x", pady=(14, 0))

        build_home()

    def _onboarding_pick_cloud(self, dlg, pick):
        """云端路线：记住选择 → 直接打开设置并定位到「云端模型」区"""
        pick("cloud")
        dlg.destroy()
        self._show_settings(focus="cloud")

    def _onboarding_pick_local(self, wrap, pick):
        """本地路线：切到第二步——Ollama 下载直链 + 装好后重新检测"""
        pick("local")
        for w in wrap.winfo_children():
            w.destroy()
        ctk.CTkLabel(wrap, text="💻 用本地模型（数据不出本机）",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(wrap, text="第 1 步：下载并安装 Ollama（约 500MB，装完它会在后台运行）",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(14, 6))
        ctk.CTkButton(wrap, text="打开 Ollama 官方下载页", height=40,
                      corner_radius=10, font=ctk.CTkFont(size=13),
                      fg_color=CARD_2, hover_color=BORDER,
                      command=lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL)
                      ).pack(fill="x")
        ctk.CTkLabel(wrap, text="第 2 步：装好后点下面的按钮重新检测，变绿就能开始用",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(14, 6))
        status_lbl = ctk.CTkLabel(wrap, text="", font=ctk.CTkFont(size=13),
                                  text_color=MUTED, anchor="w", wraplength=480,
                                  justify="left")
        status_lbl.pack(anchor="w", pady=(0, 6))

        dlg = wrap.master

        def recheck():
            status_lbl.configure(text="正在检测…", text_color=MUTED)

            def done(ok, _text):
                status_lbl.configure(
                    text=("✓ 已连上，可以开始用了！窗口马上自动关闭" if ok
                          else "○ 还没连上。请确认 Ollama 已安装并在运行，再点一次重试"),
                    text_color=OK if ok else ERR)
                if ok:
                    dlg.after(1400, dlg.destroy)
            threading.Thread(target=self._check_connection,
                             args=(done,), daemon=True).start()

        ctk.CTkButton(wrap, text="✓ 我装好了，重新检测", height=44,
                      corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=recheck).pack(fill="x")
        ctk.CTkButton(wrap, text="关  闭", height=36, corner_radius=10,
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      border_color=BORDER, text_color=MUTED, hover_color=CARD_2,
                      command=dlg.destroy).pack(fill="x", pady=(14, 0))

    # ================= 高危确认 =================
    def _show_confirm(self, req: dict):
        """兼容旧入口：转成当前活动会话的确认卡"""
        ev = self.active.add("confirm", req=req, state="pending")
        self.chat.append(ev)

    # ================= 定时任务 =================
    def _on_scheduled_task(self, sched_task: dict):
        """定时任务到点：总是新建任务（满了自动排队，不再因忙碌跳过）"""
        task = sched_task.get("task", "")
        self.root.after(0, lambda: self._run_scheduled(task))

    def _on_missed_scheduled_task(self, sched_task: dict):
        """错过的定时任务只提示不补跑（scheduler 已保证每天最多回调一次）"""
        desc = Scheduler.describe(sched_task)
        task = sched_task.get("task", "")
        self.root.after(0, lambda: self._notice_missed_scheduled(desc, task))

    def _notice_missed_scheduled(self, desc, task):
        s = self.active
        if s:
            s.add("system",
                  text=f"⏰ {desc}的定时任务今天已错过：{task}（不补跑，明天照常）",
                  tone="info")
            if self.active is s:
                self.chat.append(s.events[-1])

    def _run_scheduled(self, task):
        s = TaskSession(title=short_title(task))
        self.sessions[s.id] = s
        s.task_text = task
        s.title = short_title(task)
        s.add("system", text=f"⏰ 定时任务到点：{task}", tone="info")
        s.add("user", text=task)
        max_c = max(1, min(5, int(self.settings.get("max_concurrent",
                                                    DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.sessions.values() if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self)
        self._select(s)

    # ================= 系统托盘 =================
    def _init_tray(self):
        try:
            import pystray
            from PIL import ImageDraw

            img = Image.new("RGB", (64, 64), ACCENT)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((10, 14, 54, 50), radius=8, fill="#0F2A4A")
            d.ellipse((22, 24, 30, 32), fill="#7FD1FF")
            d.ellipse((34, 24, 42, 32), fill="#7FD1FF")
            d.rounded_rectangle((22, 38, 42, 44), radius=3, fill="#7FD1FF")
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", self._tray_show, default=True),
                pystray.MenuItem("退出", self._tray_exit),
            )
            self.tray = pystray.Icon("DesktopAgent", img,
                                     "Desktop Agent · 就绪", menu)
            self.tray.run_detached()
        except Exception:
            self.tray = None  # 托盘不可用不影响主功能

    def _update_tray(self, text: str):
        if self.tray:
            try:
                self.tray.tooltip = text
            except Exception:
                pass

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def _tray_exit(self, icon=None, item=None):
        self.root.after(0, self._real_exit)

    def _real_exit(self):
        self.scheduler.stop()
        self.audit.close()
        if self.phone_bridge:
            try:
                self.phone_bridge.stop()   # 手机连接与外网通道一并收掉
            except Exception:
                pass
        if self.mail_remote:
            try:
                self.mail_remote.stop()    # 邮件轮询线程一并收掉
            except Exception:
                pass
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _on_close(self):
        busy = sum(1 for s in self.sessions.values()
                   if s.status in ("running", "queued"))
        # 文案跟实际能力走：只有托盘真的可用才承诺"最小化继续跑"，
        # 否则选「否」就是直接退出——不能许诺做不到的事
        tray_ok = bool(self.tray) and self.settings.get("minimize_to_tray", True)
        if busy:
            if tray_ok:
                detail = "（选「否」可以最小化到托盘让任务继续跑）"
            else:
                detail = "（选「否」会关闭程序，正在执行的任务将中断）"
            if messagebox.askyesno(
                    "还有任务在跑",
                    f"有 {busy} 个任务还没完成。要全部停止并退出吗？\n{detail}"):
                self._real_exit()
                return
            if tray_ok:
                self.root.withdraw()
                self._update_tray(f"Desktop Agent · {busy} 个任务运行中")
                return
            self._real_exit()
            return
        if tray_ok:
            self.root.withdraw()
            self._update_tray("Desktop Agent · 就绪（已最小化到托盘）")
            return
        self._real_exit()

    # ================= 任务表 =================
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

    # ================= 历史 / 设置 / 定时（P3 迁移滑出面板） =================
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

    # ================= 插件中心：技能 / 专家 / 连接器 =================
    def _show_plugins(self):
        """插件中心：三类外部能力统一管理（对齐 WorkBuddy 的 技能/专家/连接器）。

        - 技能：SKILL.md 说明书，教 AI 做某类事（纯文本，不执行代码）
        - 专家：SKILL.md 角色卡，改变 AI 的说话方式与侧重
        - 连接器：.py 工具插件，给 AI 接上外部工具（plugin_system）
        """
        from core.paths import plugins_dir, skills_dir

        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("插件：技能 / 专家 / 连接器")
        dlg.geometry("720x720")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=14)
        ctk.CTkLabel(body, text="🔌 插件中心", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(body,
                     text="技能＝教 AI 做事的说明书　·　专家＝给 AI 换个角色　·　连接器＝给 AI 接外部工具",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(2, 0))

        tabs = ctk.CTkTabview(body, fg_color="transparent",
                              segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color=ACCENT_HOVER,
                              text_color=TEXT)
        tabs.pack(fill="both", expand=True, pady=(12, 0))
        tab_skill = tabs.add("🧭 技能")
        tab_expert = tabs.add("🎭 专家")
        tab_conn = tabs.add("🔌 连接器")

        plugin_manager = (PluginManager(self.settings, directory=plugins_dir())
                          if PluginManager is not None else None)
        skill_manager = (SkillManager(self.settings, directory=skills_dir())
                         if SkillManager is not None else None)

        # ---- 公用小工具 ----

        def reopen():
            """重建面板（刷新/启停/安装后统一走这里，状态一定是最新的）"""
            dlg.destroy()
            self._show_plugins()

        def open_folder(path):
            import subprocess
            try:
                if sys.platform == "win":
                    subprocess.Popen(["explorer", str(path)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    subprocess.Popen(["xdg-open", str(path)])
            except Exception:
                pass

        def note(text, ok=True):
            """往当前任务对话流里加一条系统提示（没有任务就静默跳过）"""
            s = self.active
            if s:
                ev = s.add("system", text=("✓ " if ok else "✗ ") + text,
                           tone="ok" if ok else "err")
                if self.active is s:
                    self.chat.append(ev)

        # ---- 技能/专家包：通用行渲染 ----

        def render_pack_row(parent, info, manager):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=8)

            # 状态徽章（与任务列表同款图标）
            status_icon = STATUS_ICON.get(info.status, "·")
            status_text = STATUS_TEXT.get(info.status, "未知")
            status_color = STATUS_COLOR.get(info.status, FAINT)
            ctk.CTkLabel(row, text=f"{status_icon} {status_text}",
                         font=ctk.CTkFont(size=13),
                         text_color=status_color).pack(side="left", padx=(0, 8))

            # 包信息：名字 + 版本 + 一句话描述 + 什么时候用
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(info_frame, text=info.display_name,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT).pack(anchor="w")
            meta = []
            if info.version:
                meta.append(f"v{info.version}")
            if info.description:
                meta.append(info.description[:46] + "…"
                            if len(info.description) > 46 else info.description)
            if info.triggers:
                meta.append("什么时候用：" + "、".join(info.triggers[:4]))
            if meta:
                ctk.CTkLabel(info_frame, text=" · ".join(meta),
                             font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                    anchor="w", pady=(2, 0))
            if info.error:
                ctk.CTkLabel(info_frame, text=f"错误: {info.error[:70]}",
                             font=ctk.CTkFont(size=12), text_color=ERR).pack(
                    anchor="w", pady=(4, 0))

            # 删除（纯文本包，删了随时能重装；二次确认防手滑）
            def delete(i=info):
                if messagebox.askyesno("删除确认",
                                       f"确定删除「{i.display_name}」吗？",
                                       parent=dlg):
                    ok, msg = manager.remove(i.folder)
                    note(msg, ok=ok)
                    reopen()

            ctk.CTkButton(row, text="🗑", width=36, height=28,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=delete).pack(side="right", padx=(8, 0))

            # 启停开关（对下一个任务生效）
            enabled_var = ctk.BooleanVar(value=info.enabled)
            switch = ctk.CTkSwitch(row, text="", variable=enabled_var,
                                   progress_color=ACCENT, text_color=TEXT,
                                   font=ctk.CTkFont(size=13),
                                   command=lambda i=info, e=enabled_var:
                                   manager.set_enabled(i.folder, e.get()))
            switch.pack(side="right", padx=(8, 0))
            switch.select() if info.enabled else switch.deselect()

        # ---- 技能/专家 Tab（同一套逻辑，类型不同） ----

        def render_pack_tab(tab, kind, sample_label):
            list_frame = ctk.CTkScrollableFrame(
                tab, fg_color=CARD, corner_radius=10,
                border_width=1, border_color=BORDER)
            list_frame.pack(fill="both", expand=True)

            if skill_manager is None:
                ctk.CTkLabel(list_frame, text="技能系统不可用（skill_system 未安装）",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
                return

            packs = skill_manager.list_by_type(kind)
            if not packs:
                ctk.CTkLabel(list_frame,
                             text=f"还没有{sample_label.split('-')[0]}。点下面的「✨ 生成示例」"
                                  f"看个例子，或把别人分享的技能包文件夹放进技能目录",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
            for info in packs:
                render_pack_row(list_frame, info, skill_manager)

            # 按钮两行：管理 + 安装
            btns1 = ctk.CTkFrame(tab, fg_color="transparent")
            btns1.pack(fill="x", pady=(10, 0))
            btns2 = ctk.CTkFrame(tab, fg_color="transparent")
            btns2.pack(fill="x", pady=(8, 0))

            def refresh():
                skill_manager.reload()
                reopen()

            def gen_sample():
                from skill_system.sample import write_sample
                write_sample(kind, skills_dir())
                skill_manager.reload()
                note(f"已生成示例：{sample_label}。可以打开技能目录，照着它的写法做自己的")
                reopen()

            def install_folder():
                from tkinter import filedialog
                src = filedialog.askdirectory(
                    title="选技能包文件夹（里面要有一个 SKILL.md）")
                if not src:
                    return
                ok, msg = skill_manager.install(src)
                note(msg, ok=ok)
                reopen()

            def install_url():
                u = ctk.CTkToplevel(dlg, fg_color=BG)
                u.title("从网址安装技能包")
                u.geometry("500x190")
                attach_modal_dialog(u, dlg)
                ctk.CTkLabel(u, text="粘贴技能包的网址（.zip 或 .md）",
                             font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=TEXT).pack(anchor="w", padx=16, pady=(14, 4))
                ctk.CTkLabel(u, text="只装可信来源的技能包；AI 在任务里也能自己装",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    anchor="w", padx=16)
                entry = ctk.CTkEntry(u, placeholder_text="https://…/技能包.zip",
                                     fg_color=INPUT_BG, border_color=BORDER)
                entry.pack(fill="x", padx=16, pady=(6, 4))

                def do_install():
                    url = entry.get().strip()
                    if not url:
                        return
                    u.destroy()
                    note("正在下载并安装技能包…")

                    def worker():
                        ok, msg = skill_manager.install(url)

                        def done():
                            note(msg, ok=ok)
                            reopen()
                        self.root.after(0, done)
                    threading.Thread(target=worker, daemon=True).start()

                ctk.CTkButton(u, text="安装", width=120, height=34, corner_radius=8,
                              fg_color=ACCENT, hover_color=ACCENT_HOVER,
                              command=do_install).pack(pady=10)

            ctk.CTkButton(btns1, text="📂 打开技能目录", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=lambda: open_folder(skills_dir())).pack(
                side="left", padx=(0, 8))
            ctk.CTkButton(btns1, text="🔄 刷新", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=refresh).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btns1, text="✨ 生成示例", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=gen_sample).pack(side="left")
            ctk.CTkButton(btns2, text="📁 从文件夹安装", height=34,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                          command=install_folder).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btns2, text="🔗 从网址安装", height=34,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                          command=install_url).pack(side="left")

        render_pack_tab(tab_skill, "skill", "示例技能-会议纪要")
        render_pack_tab(tab_expert, "expert", "示例专家-耐心讲解员")

        # ---- 连接器 Tab（.py 工具插件，plugin_system） ----

        conn_list = ctk.CTkScrollableFrame(tab_conn, fg_color=CARD, corner_radius=10,
                                           border_width=1, border_color=BORDER)
        conn_list.pack(fill="both", expand=True)

        if plugin_manager is None:
            ctk.CTkLabel(conn_list, text="插件系统不可用（plugin_system 未安装）",
                         font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                padx=12, pady=16)
        else:
            infos = plugin_manager.list()
            if not infos:
                ctk.CTkLabel(conn_list,
                             text="还没有连接器。点下面的「✨ 生成示例插件」看个例子",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
            for info in infos:
                row = ctk.CTkFrame(conn_list, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=8)

                status_icon = STATUS_ICON.get(info.status, "·")
                status_text = STATUS_TEXT.get(info.status, "未知")
                status_color = STATUS_COLOR.get(info.status, FAINT)
                ctk.CTkLabel(row, text=f"{status_icon} {status_text}",
                             font=ctk.CTkFont(size=13),
                             text_color=status_color).pack(side="left", padx=(0, 8))

                info_frame = ctk.CTkFrame(row, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True)
                ctk.CTkLabel(info_frame, text=info.display_name,
                             font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=TEXT).pack(anchor="w")
                meta = []
                if info.version:
                    meta.append(f"v{info.version}")
                if info.description:
                    meta.append(info.description[:46] + "…"
                                if len(info.description) > 46 else info.description)
                if meta:
                    ctk.CTkLabel(info_frame, text=" · ".join(meta),
                                 font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                        anchor="w", pady=(2, 0))
                if info.error:
                    ctk.CTkLabel(info_frame, text=f"错误: {info.error[:70]}",
                                 font=ctk.CTkFont(size=12), text_color=ERR).pack(
                        anchor="w", pady=(4, 0))

                enabled_var = ctk.BooleanVar(value=info.enabled)
                switch = ctk.CTkSwitch(row, text="", variable=enabled_var,
                                       progress_color=ACCENT, text_color=TEXT,
                                       font=ctk.CTkFont(size=13),
                                       command=lambda i=info, e=enabled_var:
                                       plugin_manager.set_enabled(i.stem, e.get()))
                switch.pack(side="right", padx=(8, 0))
                switch.select() if info.enabled else switch.deselect()

        conn_btns = ctk.CTkFrame(tab_conn, fg_color="transparent")
        conn_btns.pack(fill="x", pady=(10, 0))

        def conn_refresh():
            if plugin_manager is not None:
                plugin_manager.reload()
            reopen()

        def conn_sample():
            from plugin_system.sample import SAMPLE_FILENAME, SAMPLE_PLUGIN_SOURCE
            plugins_dir().mkdir(parents=True, exist_ok=True)
            (plugins_dir() / SAMPLE_FILENAME).write_text(
                SAMPLE_PLUGIN_SOURCE, encoding="utf-8")
            if plugin_manager is not None:
                plugin_manager.reload()
            note(f"已生成示例插件：{SAMPLE_FILENAME}")
            reopen()

        ctk.CTkButton(conn_btns, text="📂 打开插件目录", height=32,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=lambda: open_folder(plugins_dir())).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(conn_btns, text="🔄 刷新", height=32,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=conn_refresh).pack(side="left", padx=(0, 8))
        ctk.CTkButton(conn_btns, text="✨ 生成示例插件", height=32,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                      command=conn_sample).pack(side="left")

    def _show_settings(self, focus=None):
        """设置面板。focus="cloud"：从首启引导「用云端」进来——高亮云端区块
        并滚动到位，让用户一眼看到该填 Key 的地方（UX-P1-6）。"""
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("设置")
        # 小屏（如 1366×768）按屏高压窗口，内容靠滚动条够到；固定 900 会让「保存」够不着
        dlg.geometry(f"620x{min(900, int(dlg.winfo_screenheight() * 0.8))}")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=14)
        ctk.CTkLabel(body, text="⚙ 设置", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")

        # ---- 模型模式 ----
        ctk.CTkLabel(body, text="模型模式", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", pady=(12, 2))
        mode_var = ctk.StringVar(value=self.settings.get("model_mode", "local"))
        mode_row = ctk.CTkFrame(body, fg_color="transparent")
        mode_row.pack(anchor="w")
        for label, val in (("只用本地", "local"), ("只用云端", "cloud"),
                           ("自动（本地优先）", "auto")):
            ctk.CTkRadioButton(mode_row, text=label, variable=mode_var, value=val,
                               text_color=TEXT, fg_color=ACCENT).pack(
                side="left", padx=(0, 14))

        # ---- 并行任务数 ----
        ctk.CTkLabel(body, text="同时执行的任务数（1-5，多任务会排队）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        conc_var = ctk.StringVar(value=str(max(1, min(5, int(
            self.settings.get("max_concurrent", DEFAULT_MAX_CONCURRENT))))))
        ctk.CTkOptionMenu(body, values=["1", "2", "3", "4", "5"],
                          variable=conc_var, width=100, fg_color=INPUT_BG,
                          button_color=ACCENT, button_hover_color=ACCENT_HOVER).pack(
            anchor="w")

        # ---- 单任务最大轮次（T7）----
        # 10 轮对"开网页→看页面→记事本→保存"这类多步任务必顶格失败
        # （2026-09-30 晚 4/6 任务 max_turns），默认 30；复杂任务可再调大
        ctk.CTkLabel(body, text="单个任务最多执行几轮（复杂任务建议 25 以上）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        turns_var = ctk.StringVar(value=str(_effective_max_turns(self.settings)))
        ctk.CTkOptionMenu(body, values=["10", "15", "20", "25", "30", "40", "50"],
                          variable=turns_var, width=100, fg_color=INPUT_BG,
                          button_color=ACCENT, button_hover_color=ACCENT_HOVER).pack(
            anchor="w")

        # ---- 本地配置 ----
        ctk.CTkLabel(body, text="本地模型（Ollama，数据不出本机）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        model_var = ctk.StringVar(value=self.settings.get("local", {}).get(
            "model", self.settings.get("model", MODEL_NAME)))
        model_menu = ctk.CTkOptionMenu(body, values=["加载中…"], variable=model_var,
                                       width=320, fg_color=INPUT_BG,
                                       button_color=ACCENT,
                                       button_hover_color=ACCENT_HOVER)
        model_menu.pack(anchor="w")
        local_hint = ctk.CTkLabel(body, text="正在读取模型列表…",
                                  font=ctk.CTkFont(size=13), text_color=FAINT)
        local_hint.pack(anchor="w", pady=(4, 0))

        def refresh_models():
            # 网络请求放后台线程：Ollama 没开时主线程会冻 5 秒（踩坑.md 条目 4）
            def work():
                models = LLMClient(LLMConfig(
                    provider=LLMProvider.OLLAMA,
                    base_url=OLLAMA_URL)).list_models()

                def done():
                    if models:
                        model_menu.configure(values=models)
                        if model_var.get() not in models:
                            model_var.set(models[0])
                        local_hint.configure(text=f"共 {len(models)} 个本地模型可用")
                    else:
                        local_hint.configure(
                            text="读不到模型列表：本机 Ollama 没连上。请先启动 Ollama"
                                 "（任务栏右下角有它的图标才算在运行），关掉设置窗口重新"
                                 "打开即可刷新；不想装本机模型，也可以在下方「云端模型」"
                                 "填 API Key",
                            wraplength=560)
                self.root.after(0, done)
            threading.Thread(target=work, daemon=True).start()

        # ---- 云端配置 ----
        focus_cloud = (focus == "cloud")
        cloud_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                 border_width=2 if focus_cloud else 1,
                                 border_color=ACCENT if focus_cloud else BORDER)
        cloud_box.pack(fill="x", pady=(14, 0))
        if focus_cloud:
            ctk.CTkLabel(cloud_box, text="↑ 就在这里：选好服务商，粘贴 API Key，"
                                         "拉到底部点「保存」",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=ACCENT).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(cloud_box, text="云端模型", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))

        cloud_cfg = dict(self.settings.get("cloud", {}))
        preset_names = list(CLOUD_PRESETS.keys())
        provider_by_name = {name: CLOUD_PRESETS[name]["provider"]
                            for name in preset_names}
        name_by_provider = {v: k for k, v in provider_by_name.items()}
        provider_var = ctk.StringVar(value=name_by_provider.get(
            cloud_cfg.get("provider", "zhipu"), "智谱"))
        api_var = ctk.StringVar(value=cloud_cfg.get("api_key", ""))
        cmodel_var = ctk.StringVar(value=cloud_cfg.get("model", "glm-4-flash"))
        cbase_var = ctk.StringVar(value=cloud_cfg.get(
            "base_url", CLOUD_PRESETS["智谱"]["base_url"]))

        prow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        prow.pack(fill="x", padx=14)
        ctk.CTkLabel(prow, text="服务商", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        provider_menu = ctk.CTkOptionMenu(prow, values=preset_names,
                                          variable=provider_var, width=130,
                                          fg_color=INPUT_BG, button_color=ACCENT)
        provider_menu.pack(side="left", padx=(8, 0))

        def on_provider_change(_=None):
            preset = CLOUD_PRESETS.get(provider_var.get())
            if preset:
                cbase_var.set(preset["base_url"])
                cmodel_var.set(preset["model"])
        provider_menu.configure(command=on_provider_change)

        ctk.CTkLabel(cloud_box, text="API Key（留空则使用环境变量）",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(8, 2))
        api_entry = ctk.CTkEntry(cloud_box, textvariable=api_var, show="*",
                                 width=340, fg_color=INPUT_BG, border_color=BORDER)
        api_entry.pack(anchor="w", padx=14)

        crow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        crow.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(crow, text="模型名", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cmodel_var, width=170,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 12))
        ctk.CTkLabel(crow, text="接口地址", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cbase_var, width=250,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 0))

        # ---- 看屏幕（视觉理解）----
        # 2026-09-28：看屏幕从「本机 qwen-vl」改走云端（本机一张屏 107 秒，必然超时）
        vision_cfg = dict(self.settings.get("vision", {}) or {})
        _VIS_LABELS = {"auto": "自动（推荐）", "cloud": "只用云端",
                       "local": "只用本机"}
        _VIS_BY_LABEL = {v: k for k, v in _VIS_LABELS.items()}
        vis_mode_var = ctk.StringVar(value=_VIS_LABELS.get(
            vision_cfg.get("mode", "auto"), "自动（推荐）"))
        vis_model_var = ctk.StringVar(value=vision_cfg.get(
            "cloud_model", VISION_MODEL_OPTIONS[0]))

        vrow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        vrow.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(vrow, text="看屏幕", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(vrow, values=list(_VIS_LABELS.values()),
                          variable=vis_mode_var, width=118,
                          fg_color=INPUT_BG, button_color=ACCENT).pack(
            side="left", padx=(8, 12))
        ctk.CTkLabel(vrow, text="视觉模型", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(vrow, values=list(VISION_MODEL_OPTIONS),
                          variable=vis_model_var, width=170,
                          fg_color=INPUT_BG, button_color=ACCENT).pack(
            side="left", padx=(8, 0))
        ctk.CTkLabel(cloud_box,
                     text="看屏幕会把当前截图上传给服务商；选「只用本机」则不上传（慢很多）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(4, 0))

        test_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        test_row.pack(fill="x", padx=14, pady=(6, 12))
        test_result = ctk.CTkLabel(test_row, text="", font=ctk.CTkFont(size=13),
                                   text_color=MUTED, anchor="w")
        preset = CLOUD_PRESETS.get(provider_var.get(), {})
        if preset and os.environ.get(preset["env"]):
            test_result.configure(text="✓ 检测到环境变量，优先使用", text_color=OK)

        def run_test():
            test_result.configure(text="测试中…", text_color=MUTED)

            def work():
                cfg = LLMConfig(
                    provider=LLMProvider(PROVIDER_ENUM.get(
                        provider_by_name.get(provider_var.get(), "zhipu"), "other")),
                    api_key=api_var.get().strip() or resolve_api_key(
                        {"provider": provider_by_name.get(provider_var.get(), "zhipu")})[0],
                    base_url=cbase_var.get().strip(),
                    model=cmodel_var.get().strip(),
                )
                ok, msg = LLMClient(cfg).ping()
                # 后台线程不碰控件，结果投回主线程更新（对齐 _check_connection）
                self.root.after(0, lambda: test_result.configure(
                    text=("✓ " if ok else "✗ ") + msg,
                    text_color=OK if ok else ERR))
            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(test_row, text="测试连接", width=100, height=26,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, command=run_test).pack(side="left")
        test_result.pack(side="left", padx=10)

        # ---- 其他 ----
        tray_var = ctk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        ctk.CTkSwitch(body, text="关闭窗口时最小化到系统托盘", variable=tray_var,
                      progress_color=ACCENT, text_color=TEXT,
                      font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(14, 0))

        # ---- 飞书群通知 ----
        feishu_var = ctk.StringVar(value=self.settings.get("feishu_webhook", ""))
        feishu_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                  border_width=1, border_color=BORDER)
        feishu_box.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(feishu_box, text="飞书群通知（电脑↔手机）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(feishu_box,
                     text="粘贴群机器人的 Webhook 地址后，Agent 可直接给飞书群发消息",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", padx=14)
        ctk.CTkEntry(feishu_box, textvariable=feishu_var,
                     placeholder_text="https://open.feishu.cn/open-apis/bot/v2/hook/…",
                     fg_color=INPUT_BG, border_color=BORDER).pack(
            fill="x", padx=14, pady=(6, 12))

        # ---- 手机连接（任务 16 接线）----
        # 唯一入口就在设置面板：手机连接是把电脑控制权递出去的通道，克制
        # 不加托盘/顶栏快捷入口；开关即时生效、不经「保存」，也**不持久化**——
        # 每次启动重新手动打开（令牌每次启动都是新的，手机重新扫码即可）
        if PhoneBridge is not None:
            phone_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                     border_width=1, border_color=BORDER)
            phone_box.pack(fill="x", pady=(14, 0))
            self._build_phone_section(dlg, phone_box)

            def _phone_ui_gone(event=None):
                # <Destroy> 对每个子控件都触发，只认对话框自身（同模态钩子）
                if event is not None and str(event.widget) != str(dlg):
                    return
                self._phone_ui = None
            dlg.bind("<Destroy>", _phone_ui_gone)

        # ---- 邮件远程（mail_remote 独立模块，任务 18）----
        # 与手机连接同一条拍板：控制权通道默认关闭、手动开启、不持久化；
        # 邮箱授权码照 settings.json 本机留存（同云端 API Key 的凭据策略）
        mail_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                border_width=1, border_color=BORDER)
        mail_box.pack(fill="x", pady=(14, 0))
        self._build_mail_section(dlg, mail_box)

        def _mail_ui_gone(event=None):
            if event is not None and str(event.widget) != str(dlg):
                return
            self._mail_ui = None
        dlg.bind("<Destroy>", _mail_ui_gone)

        def save():
            self.settings.set("model_mode", mode_var.get())
            self.settings.set("max_concurrent", int(conc_var.get()))
            self.settings.set("max_turns", int(turns_var.get()))
            self.settings.set("local", {**self.settings.get("local", {}),
                                        "model": model_var.get(),
                                        "base_url": OLLAMA_URL,
                                        "provider": "ollama"})
            self.settings.set("cloud", {
                "provider": provider_by_name.get(provider_var.get(), "zhipu"),
                "api_key": api_var.get().strip(),
                "base_url": cbase_var.get().strip(),
                "model": cmodel_var.get().strip(),
            })
            self.settings.set("vision", {
                **self.settings.get("vision", {}),
                "mode": _VIS_BY_LABEL.get(vis_mode_var.get(), "auto"),
                "cloud_model": vis_model_var.get().strip(),
            })
            agent_vision.reset_vision()  # 让新的视觉配置立刻生效
            self.settings.set("minimize_to_tray", bool(tray_var.get()))
            self.settings.set("feishu_webhook", feishu_var.get().strip())
            s = self.active
            if s:
                s.add("system", text="⚙ 设置已保存，马上生效。", tone="ok")
                if self.active is s:
                    self.chat.append(s.events[-1])
            self._sync_privacy_banner()
            threading.Thread(target=self._check_connection, daemon=True).start()
            dlg.destroy()

        ctk.CTkButton(body, text="保存", width=170, height=38, corner_radius=8,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=save).pack(anchor="w", pady=(16, 0))
        body.after(200, refresh_models)

        if focus_cloud:
            def scroll_to_cloud():
                dlg.update_idletasks()
                try:
                    canvas = getattr(body, "_parent_canvas")
                    total = max(1, body.winfo_reqheight())
                    canvas.yview_moveto(
                        min(1.0, max(0.0, (cloud_box.winfo_y() - 10) / total)))
                except Exception:
                    pass  # 滚不到就靠高亮边框 + 提示条定位，不影响使用
            dlg.after(180, scroll_to_cloud)

    def _build_phone_section(self, dlg, box):
        """设置面板「手机连接」分区：开关 + 二维码/链接 + 令牌重置 + 外网通道。

        开关即时生效、不经「保存」（开/关控制权通道都该是当下明确的动作）；
        动态区注册到 self._phone_ui，bridge 的 on_change（含隧道状态变化）
        经 _on_phone_change 防抖后到这里刷新。
        """
        ctk.CTkLabel(box, text="📱 手机连接（用手机遥控这台电脑）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(box,
                     text="打开开关后手机扫码连接：在家用同一 WiFi 直连；"
                          "出门在外可开外网通道（地址每次都不同，需重新扫码）。",
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=560, justify="left", anchor="w").pack(
            anchor="w", padx=14)

        sw = ctk.CTkSwitch(box, text="开启手机连接", progress_color=ACCENT,
                           text_color=TEXT, font=ctk.CTkFont(size=13))
        live = ctk.CTkFrame(box, fg_color="transparent")
        live.pack(fill="x", padx=14, pady=(6, 12))

        def refresh():
            try:
                for w in live.winfo_children():
                    w.destroy()
                bridge = self.phone_bridge
                if sw.get() and bridge is not None and bridge.running:
                    self._phone_render_status(live, bridge, refresh)
                else:
                    ctk.CTkLabel(live, text="○ 未开启。打开上面的开关，"
                                           "这里会出现二维码。",
                                 font=ctk.CTkFont(size=13),
                                 text_color=FAINT).pack(anchor="w")
            except Exception:
                self._phone_ui = None    # 面板正在销毁，不再刷新

        def toggle():
            if sw.get():
                try:
                    self._ensure_phone_bridge().start()
                except OSError as e:     # 端口附近全被占
                    messagebox.showerror("手机连接", f"开启失败：{e}",
                                         parent=dlg)
                    sw.deselect()
            else:
                if self.phone_bridge:
                    self.phone_bridge.stop()   # 外网通道一并收掉
            refresh()

        sw.configure(command=toggle)
        sw.pack(anchor="w", padx=14, pady=(8, 2))
        self._phone_ui = refresh
        refresh()

    def _phone_render_status(self, live, bridge, refresh):
        """「手机连接」开启后的动态区：二维码 + 链接 + 钥匙 + 外网通道。"""
        st = bridge.status()

        # ---- 在家（局域网直连，主路径）----
        head = f"✓ 已开启 · 电脑地址 {st['host_ip']}:{st['port']}"
        ctk.CTkLabel(live, text=head, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=OK).pack(anchor="w")
        ctk.CTkLabel(live, text=st.get("network_hint", ""),
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(
            anchor="w")

        qr_row = ctk.CTkFrame(live, fg_color="transparent")
        qr_row.pack(fill="x", pady=(6, 0))
        try:
            img = tk.PhotoImage(data=bridge.qr_base64("lan", scale=5))
            lbl = tk.Label(qr_row, image=img, bg=CARD, bd=0,
                           highlightthickness=0)
            lbl.image = img      # 防 GC：PhotoImage 被回收二维码就花了
            lbl.pack(side="left")
        except Exception:
            ctk.CTkLabel(qr_row, text="二维码生成失败，请用下面这条链接手动打开",
                         font=ctk.CTkFont(size=12), text_color=WARN).pack(
                side="left")

        info = ctk.CTkFrame(qr_row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(14, 0))
        ctk.CTkLabel(info, text="手机扫码，或复制链接到手机浏览器打开",
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=300, justify="left", anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=st["lan_url"],
                     font=ctk.CTkFont(family="Consolas", size=11),
                     text_color=TOOLC, wraplength=300, justify="left",
                     anchor="w").pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(info, text="📋 复制链接", width=88, height=24,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, font=ctk.CTkFont(size=12),
                      command=lambda: self._copy_text(st["lan_url"])
                      ).pack(anchor="w", pady=(4, 0))

        key_row = ctk.CTkFrame(info, fg_color="transparent")
        key_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(key_row, text=f"🔑 {st['token_masked']}",
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(
            side="left")

        def rotate():
            bridge.rotate_token()    # 旧链接/旧二维码立刻作废
            refresh()
        ctk.CTkButton(key_row, text="换一把钥匙", width=96, height=24,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, font=ctk.CTkFont(size=12),
                      command=rotate).pack(side="left", padx=(10, 0))

        # ---- 出门（cloudflared 外网通道，可选）----
        tun = st["tunnel"]
        ctk.CTkLabel(live, text="出门在外（外网通道）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", pady=(12, 0))
        tun_row = ctk.CTkFrame(live, fg_color="transparent")
        tun_row.pack(fill="x", pady=(2, 0))

        def tunnel_on():
            bridge.enable_external()   # 结果经 on_change → refresh 呈现
            refresh()

        def tunnel_off():
            bridge.disable_external()
            refresh()

        if tun.get("has_binary"):
            if tun["state"] == ST_RUNNING:
                ctk.CTkButton(tun_row, text="关闭外网通道", width=110,
                              height=26, corner_radius=6, fg_color=CARD_2,
                              hover_color=BORDER, text_color=TEXT,
                              command=tunnel_off).pack(side="left")
            else:
                ctk.CTkButton(tun_row, text="开启外网通道", width=110,
                              height=26, corner_radius=6, fg_color=ACCENT,
                              hover_color=ACCENT_HOVER,
                              command=tunnel_on).pack(side="left")
        else:
            dl_lbl = ctk.CTkLabel(tun_row, text="", font=ctk.CTkFont(size=12),
                                  text_color=MUTED)
            dl_lbl.pack(side="left", padx=(10, 0))

            def start_download():
                dl_lbl.configure(text="准备下载…", text_color=MUTED)

                def prog(done, total):
                    if not total:
                        return
                    pct = min(100, done * 100 // total)

                    def upd(p=pct):
                        try:
                            if dl_lbl.winfo_exists():
                                dl_lbl.configure(text=f"下载中… {p}%")
                        except Exception:
                            pass
                    self.root.after(0, upd)

                def work():
                    from phone_bridge import fetcher
                    try:
                        fetcher.download_cloudflared(progress=prog)
                    except Exception as e:
                        msg = str(e) or f"下载失败（{type(e).__name__}）"

                        def fail(m=msg):
                            try:
                                if dl_lbl.winfo_exists():
                                    dl_lbl.configure(text=f"✗ {m}",
                                                     text_color=ERR)
                            except Exception:
                                pass
                        self.root.after(0, fail)
                        return

                    def ok():
                        tunnel_on()      # 下完直接开，少一次来回
                    self.root.after(0, ok)

                threading.Thread(target=work, daemon=True).start()

            ctk.CTkButton(tun_row, text="下载外网通道组件（约 60 MB，只下一次）",
                          width=250, height=26, corner_radius=6,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=start_download).pack(side="left")

        tstate = tun["state"]
        if tstate == ST_RUNNING:
            tun_text, tun_color = (f"✓ {tun['message'] or '外网通道已开好'}", OK)
        elif tstate == ST_STARTING:
            tun_text, tun_color = (f"⏳ {tun['message'] or '正在开一条通往外网的路…'}",
                                   WARN)
        elif tstate == ST_FAILED:
            tun_text, tun_color = (f"✗ {tun['message'] or '开启失败'}", ERR)
        else:
            tun_text, tun_color = "○ 未开启", FAINT
        ctk.CTkLabel(live, text=tun_text, font=ctk.CTkFont(size=12),
                     text_color=tun_color, wraplength=560, justify="left",
                     anchor="w").pack(anchor="w", pady=(4, 0))
        if st["wan_url"]:
            ctk.CTkLabel(live, text="出门用这个地址（手机流量也能连；"
                                    "部分家用路由器解析不了它，连不上就回家用上面的码）：",
                         font=ctk.CTkFont(size=12), text_color=MUTED,
                         wraplength=560, justify="left", anchor="w").pack(
                anchor="w")
            ctk.CTkLabel(live, text=st["wan_url"],
                         font=ctk.CTkFont(family="Consolas", size=11),
                         text_color=TOOLC, wraplength=560, justify="left",
                         anchor="w").pack(anchor="w")

        ctk.CTkLabel(live,
                     text="⚠ 链接就是钥匙：二维码和链接只给家里人，别转发。"
                          "手机丢了或转发过截图，点「换一把钥匙」，旧的立刻作废。",
                     font=ctk.CTkFont(size=12), text_color=FAINT,
                     wraplength=560, justify="left", anchor="w").pack(
            anchor="w", pady=(10, 0))

    def _build_mail_section(self, dlg, box):
        """设置面板「邮件远程」分区（任务 18）：开关即时生效、不经「保存」。

        凭据（授权码）照云端 API Key 同一策略落本机 settings.json；
        开关不持久化——每次启动手动开启，与手机连接同一条控制权拍板。
        """
        mail_cfg = dict(self.settings.get("mail_remote", {}) or {})
        ctk.CTkLabel(box, text="✉️ 邮件远程（手机发邮件遥控电脑）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            box,
            text="手机给上面的电脑邮箱发邮件就能下任务、查状态、停止，"
                 "结果自动回信到手机——出门在外不用同一 WiFi、不用隧道。"
                 "主题格式：[da] 任务内容 ／ [da] 状态 ／ [da] 停止",
            font=ctk.CTkFont(size=12), text_color=MUTED,
            wraplength=560, justify="left", anchor="w").pack(
            anchor="w", padx=14)

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(6, 0))
        user_var = ctk.StringVar(value=mail_cfg.get("username", ""))
        code_var = ctk.StringVar(value=mail_cfg.get("auth_code", ""))
        senders_var = ctk.StringVar(value=mail_cfg.get("allowed_senders", ""))
        imap_var = ctk.StringVar(value=mail_cfg.get("imap_host", ""))
        smtp_var = ctk.StringVar(value=mail_cfg.get("smtp_host", ""))
        poll_var = ctk.StringVar(value=str(mail_cfg.get("poll_seconds", 60)))

        def _row(label, var, show="", width=300, placeholder=""):
            r = ctk.CTkFrame(grid, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=13),
                         text_color=MUTED, width=110, anchor="w").pack(
                side="left")
            ctk.CTkEntry(r, textvariable=var, show=show, width=width,
                         fg_color=INPUT_BG, border_color=BORDER,
                         placeholder_text=placeholder).pack(side="left",
                                                            padx=(6, 0))

        _row("电脑邮箱账号", user_var, width=300,
             placeholder="user@qq.com（收任务指令和回信都用它）")
        _row("授权码", code_var, show="*", width=300,
             placeholder="邮箱设置里开启 IMAP/SMTP 后生成，不是登录密码")
        _row("白名单发件人", senders_var, width=300,
             placeholder="手机邮箱，多个用逗号隔开（名单外一律不受理）")
        _row("收件服务器", imap_var, width=300,
             placeholder="留空自动识别（如 imap.qq.com）")
        _row("发件服务器", smtp_var, width=300,
             placeholder="留空自动识别（如 smtp.qq.com）")
        _row("轮询间隔（秒）", poll_var, width=120, placeholder="60")

        sw = ctk.CTkSwitch(box, text="启用邮件远程", progress_color=ACCENT,
                           text_color=TEXT, font=ctk.CTkFont(size=13))
        sw.pack(anchor="w", padx=14, pady=(8, 2))

        status_lbl = ctk.CTkLabel(box, text="", font=ctk.CTkFont(size=12),
                                  text_color=MUTED, wraplength=560,
                                  justify="left", anchor="w")
        status_lbl.pack(anchor="w", padx=14, pady=(4, 10))

        def refresh():
            try:
                if not status_lbl.winfo_exists():
                    return
                if sw.get() and self.mail_remote and self.mail_remote.running:
                    err = self.mail_remote.last_error
                    status_lbl.configure(
                        text=(f"✓ 已开启：{self.mail_remote.username} 正在监听"
                              if not err else f"⚠ 已开启，但最近一次检查失败：{err}"),
                        text_color=OK if not err else WARN)
                else:
                    status_lbl.configure(text="○ 未开启", text_color=FAINT)
            except Exception:
                pass

        def toggle():
            if sw.get():
                cfg = {"username": user_var.get(), "auth_code": code_var.get(),
                       "imap_host": imap_var.get(), "smtp_host": smtp_var.get(),
                       "allowed_senders": senders_var.get(),
                       "poll_seconds": poll_var.get(),
                       "subject_prefix": mail_cfg.get("subject_prefix", "[da]")}
                try:
                    self._ensure_mail_remote().start(cfg)
                except MailConfigError as e:
                    messagebox.showerror("邮件远程", str(e), parent=dlg)
                    sw.deselect()
                except Exception as e:
                    messagebox.showerror("邮件远程",
                                         f"开启失败：{type(e).__name__}: {e}",
                                         parent=dlg)
                    sw.deselect()
                    return
                # 凭据/配置照云端 Key 同策略落本机 settings.json，下次预填
                self.settings.set("mail_remote", {
                    **mail_cfg,
                    "username": user_var.get().strip(),
                    "auth_code": code_var.get().strip(),
                    "imap_host": imap_var.get().strip(),
                    "smtp_host": smtp_var.get().strip(),
                    "allowed_senders": senders_var.get().strip(),
                    "poll_seconds": poll_var.get().strip(),
                })
            else:
                if self.mail_remote:
                    self.mail_remote.stop()
            refresh()

        sw.configure(command=toggle)
        self._mail_ui = refresh
        refresh()

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


if __name__ == "__main__":
    import sys
    app = AgentGUI()
    if len(sys.argv) >= 3 and sys.argv[1] == "--debug-open":
        panel = sys.argv[2]  # settings / scheduler / history / tasks_table
        app.root.after(1500, getattr(app, f"_show_{panel}"))
    if len(sys.argv) >= 3 and sys.argv[1] == "--run":
        task = " ".join(sys.argv[2:])

        def _auto():
            s = TaskSession(title=short_title(task))
            app.sessions[s.id] = s
            s.task_text = task
            s.title = short_title(task)
            s.add("user", text=task)
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(app)
            app._select(s)
            app.root.deiconify()
        app.root.after(2500, _auto)
    app.root.mainloop()
