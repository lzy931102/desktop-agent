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
import traceback
import webbrowser
import customtkinter as ctk
import agent_vision
import tkinter as tk
from tkinter import messagebox
from agent_loop import (DesktopAgent, LLMClient, LLMConfig, LLMProvider,
                        build_llm_client, final_reply_failed)
from core import blackbox
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
                      MSG_BLOCKED_SUB, MSG_CONFIRM_HEAD, MSG_INPUT_HINT,
                      WELCOME_CARD_HEAD, WELCOME_CARD_LINES,
                      WELCOME_CARD_BUTTON, MSG_RESHOW_WELCOME)
from ui.formatters import (short_title, rel_time, fmt_tokens,
                            tool_display, humanize_error, parse_log,
                            result_summary, _effective_max_turns)
from ui.sessions import TaskSession
from ui.chat_stream import ChatStream, attach_modal_dialog
from ui.runners import PhoneTaskRunner, MailTaskRunner
from ui.panels.phone import PhoneSectionMixin
from ui.panels.mail import MailSectionMixin
from ui.panels.plugins import PluginsMixin
from ui.panels.tasks import TasksMixin
from ui.panels.scheduler import SchedulerPanelMixin
from ui.panels.settings import SettingsMixin
# ---- T4 Phase 2（纯搬运零逻辑变更）：面板实现拆至 ui/ 各模块，Mixin 组合
from ui.dialogs import DialogsMixin

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


class AgentGUI(DialogsMixin, SettingsMixin, SchedulerPanelMixin, TasksMixin, PluginsMixin, MailSectionMixin, PhoneSectionMixin):
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
        self._welcome_open = False          # T24 欢迎卡正在显示（挂起路线卡用）
        self._pending_onboarding = False    # 欢迎卡关闭后要补弹的模型路线卡
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
        self.root.after(600, self._maybe_show_welcome)  # T24：首启「怎么用」卡
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

        # ---- 输入区（T24 任务 3：加大占主位，上方一行小字指明「在哪输入」） ----
        self._add_chip_rows(main, EXAMPLES)

        ctk.CTkLabel(main, text=MSG_INPUT_HINT, font=ctk.CTkFont(size=12),
                     text_color=FAINT, anchor="w").pack(fill="x", pady=(8, 2))

        row = ctk.CTkFrame(main, fg_color="transparent")
        row.pack(fill="x", pady=(2, 0))
        self.input_text = ctk.CTkTextbox(
            row, height=72, font=ctk.CTkFont(size=14), corner_radius=10,
            fg_color=INPUT_BG, border_width=2, border_color=BORDER, wrap="word",
            text_color=TEXT)
        self.input_text.pack(side="left", fill="both", expand=True)
        self.input_text.tag_config("ph", foreground=FAINT)
        self.input_text.insert("1.0", PLACEHOLDER, "ph")
        self.input_text.bind("<FocusIn>", self._clear_placeholder)
        self.input_text.bind("<FocusOut>", self._restore_placeholder)
        self.input_text.bind("<Control-Return>",
                             lambda e: (self._start_or_stop(), "break")[1])

        self.start_button = ctk.CTkButton(
            row, text="▶ 开始执行", width=132, height=72, corner_radius=10,
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
        elif kind == "thought":
            # T24 过程卡片：模型每轮动手前那句「为什么」。剥 💭 前缀截短，
            # 一次一条，跟在轮次线后、工具卡前
            text = str(payload).strip()
            if text.startswith("💭"):
                text = text[1:].strip()
            text = text[:120]
            if text:
                ev = s.add("thought", text=text)
                s.current_action = "💭 " + text[:40]
                if self.active is s:
                    self.chat.append(ev)
        elif kind == "tool_call":
            name, args = payload
            step = sum(1 for e in s.events if e.get("kind") == "tool") + 1
            ev = s.add("tool", name=name, args=args, state="run",
                       result="", note="", img=None, step=step)
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
            s.current_action = f"🧠 第 {n}/{_effective_max_turns(self.settings)} 轮思考中…"
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
            ev.update(state="ok" if ok else "err", result=text,
                      summary=result_summary(name, text, ok))
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
        if s.status != "running":
            return  # T23 终态幂等：僵尸复位与真实收尾撞车时，以先到者为准
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
        try:
            for s in list(self.sessions.values()):
                try:
                    while True:
                        try:
                            kind, payload = s.ui_queue.get_nowait()
                        except queue.Empty:
                            break
                        try:
                            self._apply(s, kind, payload)
                        except Exception:
                            # T23：单条事件渲染失败只丢这一条，泵必须活着
                            blackbox.write("pump._apply",
                                           traceback.format_exc())
                            self._log_line(s, "⚠ 界面更新一条事件失败"
                                              "（已记入黑匣子，任务不受影响）")
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
        except Exception:
            # T23：泵体内任何一段炸掉都记入黑匣子，续链在 finally 里照常执行
            blackbox.write("pump.body", traceback.format_exc())
        finally:
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
        # 瞬时失败不弹模态卡（徽章随时可手动唤出）。
        # T24：欢迎卡显示中时不叠弹——先记账，欢迎卡关闭时补弹，两张卡
        # 首次启动撞在同一秒（模态互踩、标题栏抢焦点）是 2026-10-04 沙箱实测
        if ok is False and first_check and not self._onboarding_auto_shown:
            self._onboarding_auto_shown = True
            if should_show_onboarding(self.settings, ok):
                if self._welcome_open:
                    self._pending_onboarding = True
                else:
                    self.root.after(400, self._show_onboarding, True)

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


def ensure_single_instance(app_name="DesktopAgent", window_title=None):
    """单实例锁（T21）：已有实例在跑时返回 False，并尽量把已有主窗口带到前台。

    - Windows 用命名 Mutex 判活；句柄故意保持打开直到进程退出，锁随进程自动释放
    - Global 命名空间创建失败（如非管理员无 SeCreateGlobalPrivilege）降级
      Local（同会话内仍互斥）；再失败则放行启动——锁绝不阻塞正常启动
    - 非 Windows 平台直接放行
    - 找得到已有窗口就带到前台；找不到（如已在别的会话）只退出，不切焦点
    """
    if os.name != "nt":
        return True
    try:
        kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = _ctypes.WinDLL("user32", use_last_error=True)
        kernel32.CreateMutexW.restype = _ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [_ctypes.c_void_p, _ctypes.c_int,
                                          _ctypes.c_wchar_p]
        user32.FindWindowW.restype = _ctypes.c_void_p
        user32.FindWindowW.argtypes = [_ctypes.c_wchar_p, _ctypes.c_wchar_p]
    except Exception:
        return True  # ctypes 不可用：降级为直接启动
    for prefix in ("Global\\", "Local\\"):
        mutex = kernel32.CreateMutexW(None, False,
                                      f"{prefix}{app_name}_SingleInstance")
        if _ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            # 标题须与 AgentGUI.__init__ 的 root.title 保持一致
            title = window_title or f"Desktop Agent v{APP_VERSION} - 智能桌面助手"
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            return False
        if mutex:
            break  # 锁到手，允许启动
    return True


if __name__ == "__main__":
    import sys
    if not ensure_single_instance():
        sys.exit(0)  # 已有实例在跑：函数内已尽力把旧窗口带到前台，本进程退出
    # T23 黑匣子：窗口版 exe 的 stderr 无人接收，界面/线程崩溃堆栈全部丢失——
    # 重定向到本地日志，配合 Tk 回调钩子与 threading.excepthook 全部留痕
    try:
        _gui_log = open(blackbox.path(), "a", encoding="utf-8", buffering=1)
        sys.stdout = _gui_log
        sys.stderr = _gui_log
    except Exception:
        pass  # 黑匣子不可用不影响启动
    sys.excepthook = lambda t, v, tb: blackbox.write(
        "sys.excepthook", "".join(traceback.format_exception(t, v, tb)))
    threading.excepthook = lambda a: blackbox.write(
        f"thread<{a.thread.name}> died",
        "".join(traceback.format_exception(a.exc_type, a.exc_value,
                                           a.exc_traceback)))
    app = AgentGUI()
    app.root.report_callback_exception = lambda e, v, tb: blackbox.write(
        "tkCallback", "".join(traceback.format_exception(e, v, tb)))
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
