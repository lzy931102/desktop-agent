"""Desktop Agent 智能桌面助手 - 图形界面

界面布局（参考现代 AI 助手对话式设计）：
  顶部：标题 + Ollama 连接状态徽章
  状态卡：大图标显示 当前状态 / 轮次 / 耗时
  中部：执行记录（带时间戳、分类着色的对话式日志）
  底部：示例任务 → 任务输入框 + 开始/停止按钮 → 模型信息
"""
import os
import threading
import queue
import time
import customtkinter as ctk
import agent_vision
from agent_loop import (DesktopAgent, LLMClient, LLMConfig, LLMProvider,
                        build_llm_client)
from core.approval import GuiApprovalBridge
from core.audit import AuditLogger
from core.history import TaskHistory
from core.scheduler import Scheduler
from core.settings import CLOUD_PRESETS, Settings

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5-coder:7b"
MAX_TURNS = 10

# ---------------- 配色（深色主题 · WCAG AA ≥ 4.5:1） ----------------
BG = "#111827"          # 窗口背景（gray-900）
CARD = "#1F2937"        # 卡片背景（gray-800），与主背景明确分区
CARD_OK = "#064E3B"     # 成功状态卡（emerald-900）
CARD_ERR = "#7F1D1D"    # 失败状态卡（red-900）
CARD_RUN = "#172554"    # 执行中状态卡（blue-950）
BORDER = "#4B5563"      # 边框（gray-600），比卡片亮一档保证可见
INPUT_BG = "#374151"    # 输入框背景（gray-700）
ACCENT = "#3B82F6"      # 主色（blue-500）
ACCENT_HOVER = "#2563EB"
TEXT = "#F3F4F6"        # 正文（gray-100）
MUTED = "#9CA3AF"       # 次要文字（gray-400，对比度 7:1）
OK = "#34D399"          # 成功（emerald-400）
ERR = "#F87171"         # 错误（red-400）
WARN = "#FBBF24"        # 警告（amber-400）
AMBER = "#FCD34D"       # 隐私条文字（amber-300）
TOOLC = "#60A5FA"       # 工具调用（blue-400）
TURN = "#9CA3AF"        # 轮次分隔（gray-400）
RESULTC = "#D1D5DB"     # 工具结果（gray-300）

PLACEHOLDER = "用一句话描述你想让我做什么，例如：打开记事本，输入 Hello"

TOOL_NAMES = {
    "open_app": "打开应用", "click": "点击", "type_text": "输入文字",
    "press_key": "按键", "hotkey": "按快捷键", "move_to": "移动鼠标",
    "scroll": "滚动", "screenshot": "截取屏幕", "locate_on_screen": "查找屏幕图像",
    "wait": "等待", "get_mouse_position": "获取鼠标位置", "get_screen_size": "获取分辨率",
    "analyze_screen": "看屏幕", "list_windows": "查看窗口列表",
    "focus_window": "切换窗口", "list_ui_elements": "查看窗口控件",
    "click_ui_element": "点击控件", "clipboard_read": "读取剪贴板",
    "clipboard_write": "写入剪贴板",
}

EXAMPLES = ["打开计算器", "打开记事本，输入 你好", "截取屏幕"]


def tool_display(name: str, args) -> str:
    """把工具名+参数转成人话，如 打开应用(calc)"""
    cn = TOOL_NAMES.get(name, name)
    detail = ""
    if isinstance(args, dict):
        if name == "open_app":
            detail = str(args.get("app_name", ""))
        elif name == "click":
            detail = f"({args.get('x')}, {args.get('y')})"
        elif name == "type_text":
            t = str(args.get("text", ""))
            detail = (t[:20] + "…") if len(t) > 20 else t
    return f"{cn} {detail}".strip()


def classify_log(msg: str):
    """把 agent 日志分类为 (显示文本, 颜色标签)"""
    m = msg.strip()
    if m.startswith("──"):
        return m, "turn"
    if m.startswith("[调用工具]"):
        return "🔧 " + m.replace("[调用工具]", "调用工具：").strip(), "tool"
    if m.startswith("[结果]"):
        return "→ " + m.replace("[结果]", "").strip(), "result"
    if m.startswith("[错误]"):
        return "✗ " + m.replace("[错误]", "").strip(), "error"
    if m.startswith("[拦截]"):
        return "⚠ " + m.replace("[拦截]", "").strip(), "warning"
    if m.startswith("[助手]"):
        return "💬 " + m.replace("[助手]", "").strip(), "assistant"
    if m.startswith("思考用时") or m.startswith("工具执行用时"):
        return "· " + m, "muted"
    return m, "info"


class AgentGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Desktop Agent - 智能桌面助手")
        self.root.geometry("860x740")
        self.root.minsize(780, 660)
        self.root.configure(fg_color=BG)

        self.agent = None
        self.is_running = False
        self.run_start_time = None
        self.current_turn = 0
        self.ollama_ok = None  # None=检测中

        # 企业化基础设施（个人版实现，接口与企业版一致）
        self.audit = AuditLogger()
        self.history = TaskHistory()
        self.approval_bridge = GuiApprovalBridge()
        self.settings = Settings()
        self.scheduler = Scheduler(on_due=self._on_scheduled_task)
        self.scheduler.start()
        self._confirm_open = False
        self.tray = None

        self.log_queue = queue.Queue()

        self._build_header()
        self._build_status_card()
        self._build_log()
        self._build_chips()
        self._build_input_row()
        self._build_privacy_banner()
        self._build_footer()
        self._init_tray()
        self._sync_privacy_banner()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._pump)
        threading.Thread(target=self._check_connection, daemon=True).start()

    # ================= 界面搭建 =================
    def _build_header(self):
        bar = ctk.CTkFrame(self.root, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(18, 6))
        ctk.CTkLabel(
            bar, text="🤖 Desktop Agent 智能桌面助手",
            font=ctk.CTkFont(size=19, weight="bold"), text_color=TEXT,
        ).pack(side="left")
        self.conn_label = ctk.CTkLabel(
            bar, text="○ 正在连接本地 Ollama…",
            font=ctk.CTkFont(size=12), text_color=MUTED,
        )
        self.conn_label.pack(side="right")
        for text, cmd in (("📜 历史", self._show_history),
                          ("⏰ 定时", self._show_scheduler),
                          ("⚙ 设置", self._show_settings)):
            ctk.CTkButton(
                bar, text=text, width=64, height=24, corner_radius=6,
                fg_color="transparent", border_width=1, border_color=BORDER,
                text_color=MUTED, hover_color="#374151",
                font=ctk.CTkFont(size=12), command=cmd,
            ).pack(side="right", padx=(0, 8))

    def _build_status_card(self):
        card = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=24, pady=(4, 10))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=12)

        self.status_icon = ctk.CTkLabel(inner, text="⏳", font=ctk.CTkFont(size=26))
        self.status_icon.pack(side="left", padx=(0, 12))

        col = ctk.CTkFrame(inner, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        self.status_text = ctk.CTkLabel(
            col, text="就绪，输入任务后点「开始执行」",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT, anchor="w",
        )
        self.status_text.pack(fill="x")
        self.status_sub = ctk.CTkLabel(
            col, text="我会像真人一样一步步操作你的电脑，过程都在下方记录",
            font=ctk.CTkFont(size=12), text_color=MUTED, anchor="w",
        )
        self.status_sub.pack(fill="x")

        self.progress_label = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(size=12), text_color=MUTED,
        )
        self.progress_label.pack(side="right")

        self.status_card = card

    def _build_log(self):
        wrap = ctk.CTkFrame(self.root, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        wrap.pack(fill="both", expand=True, padx=24, pady=(0, 10))

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(10, 0))
        ctk.CTkLabel(head, text="执行记录", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self.clear_btn = ctk.CTkButton(
            head, text="清空", width=52, height=22, corner_radius=6,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=MUTED, hover_color="#374151",
            font=ctk.CTkFont(size=11), command=self._clear_log,
        )
        self.clear_btn.pack(side="right")

        self.log_text = ctk.CTkTextbox(
            wrap, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#111827", corner_radius=8, wrap="word", state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        try:
            # 日志行间距 +2px（CTkTextbox 未暴露，直接配置内部 tk.Text）
            self.log_text._textbox.configure(spacing1=2)
        except Exception:
            pass
        for tag, color in (
            ("time", TURN), ("turn", "#C7CBD1"), ("info", TEXT),
            ("assistant", "#FFFFFF"), ("tool", TOOLC), ("result", RESULTC),
            ("error", ERR), ("warning", WARN), ("muted", "#B9C0C9"),
            ("success", OK),
        ):
            # customtkinter 的 tag_config 不允许 font 选项，加粗通过内部 tk.Text 设置
            self.log_text.tag_config(tag, foreground=color)
        for bold_tag in ("assistant", "success", "tool"):
            try:
                self.log_text._textbox.tag_config(
                    bold_tag, foreground={"assistant": "#FFFFFF", "success": OK,
                                          "tool": TOOLC}[bold_tag],
                    font=("Consolas", 12, "bold"))
            except Exception:
                pass
        self._log_welcome()

    def _log_welcome(self):
        """首次打开时的引导信息"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "👋 你好，我是你的桌面助手\n", "assistant")
        self.log_text.insert("end", "   在下方输入你想做的事，我会一步步操作电脑并记录在这里。\n", "info")
        self.log_text.insert("end", "   例如：「打开计算器」「打开记事本，输入 你好」\n", "info")
        self.log_text.insert("end", "   高风险操作（删除、关闭窗口等）我会先征求你的同意。\n", "info")
        self.log_text.configure(state="disabled")

    def _build_chips(self):
        row = ctk.CTkFrame(self.root, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(row, text="试试：", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(side="left")
        for text in EXAMPLES:
            ctk.CTkButton(
                row, text=text, width=10, height=24, corner_radius=12,
                fg_color="#1F2937", hover_color="#374151", text_color="#D1D5DB",
                font=ctk.CTkFont(size=12),
                command=lambda t=text: self._use_example(t),
            ).pack(side="left", padx=(8, 0))

    def _build_input_row(self):
        row = ctk.CTkFrame(self.root, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 8))

        self.input_text = ctk.CTkTextbox(
            row, height=76, font=ctk.CTkFont(size=13), corner_radius=10,
            fg_color=INPUT_BG, border_width=1, border_color=BORDER, wrap="word",
        )
        self.input_text.pack(side="left", fill="both", expand=True)
        self.input_text.tag_config("ph", foreground="#9CA3AF")
        self.input_text.insert("1.0", PLACEHOLDER, "ph")
        self.input_text.bind("<FocusIn>", self._clear_placeholder)
        self.input_text.bind("<FocusOut>", self._restore_placeholder)
        self.input_text.bind("<Control-Return>", lambda e: (self._start_or_stop(), "break")[1])

        self.start_button = ctk.CTkButton(
            row, text="▶ 开始执行", width=118,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._start_or_stop,
        )
        self.start_button.pack(side="right", fill="y", padx=(10, 0))

    def _build_privacy_banner(self):
        """云端模式的隐私提示条（本地模式为空文本不占视觉）"""
        self.privacy_banner = ctk.CTkLabel(
            self.root, text="", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=AMBER, fg_color="#78350F", corner_radius=8,
        )
        self.privacy_banner.pack(fill="x", padx=24, pady=(0, 6), ipady=4)

    def _sync_privacy_banner(self):
        mode = self.settings.get("model_mode", "local")
        if mode == "cloud":
            self.privacy_banner.configure(
                text="⚠️ 云端模式：屏幕数据会上传到模型服务商")
        elif mode == "auto":
            self.privacy_banner.configure(
                text="⚠️ 自动模式：本地失败时会改用云端，屏幕数据可能上传到模型服务商")
        else:
            self.privacy_banner.configure(text="")

    def _build_footer(self):
        ctk.CTkLabel(
            self.root,
            text="能看屏幕 · 能管窗口 · 能点控件按钮 · 本地 Ollama 运行，屏幕数据不上传 · Ctrl+Enter 开始",
            font=ctk.CTkFont(size=11), text_color=MUTED,
        ).pack(pady=(0, 12))

    # ================= 交互 =================
    def _clear_placeholder(self, _=None):
        if self.input_text.get("1.0", "end").strip() == PLACEHOLDER:
            self.input_text.delete("1.0", "end")

    def _restore_placeholder(self, _=None):
        if not self.input_text.get("1.0", "end").strip():
            self.input_text.insert("1.0", PLACEHOLDER, "ph")

    def _use_example(self, text: str):
        self._clear_placeholder()
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", text)
        self.input_text.focus_set()

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, icon, text, sub=None, color=TEXT, card=CARD):
        self.status_icon.configure(text=icon)
        self.status_text.configure(text=text, text_color=color)
        if sub is not None:
            self.status_sub.configure(text=sub)
        self.status_card.configure(fg_color=card)

    def _start_or_stop(self):
        if self.is_running:
            if self.agent:
                self._set_status("⏹", "正在停止…", color=WARN, card=CARD_RUN)
                self.agent.stop()
            return
        task = self.input_text.get("1.0", "end").strip()
        if not task or task == PLACEHOLDER:
            self._set_status("⚠", "请先输入任务", "告诉我你想做什么，例如：打开计算器",
                             color=WARN, card=CARD)
            return
        if self.ollama_ok is False:
            self._log_line("time", time.strftime("%H:%M:%S") + "  Ollama 未连接，正在重新检测…")
            threading.Thread(target=self._check_connection, daemon=True).start()
            self._set_status("⚠", "连不上本地 Ollama", "请确认 Ollama 已启动，我正在重新检测…",
                             color=WARN, card=CARD_ERR)
            return

        self.is_running = True
        self.run_start_time = time.time()
        self.current_turn = 0
        self._set_status("🧠", "开始执行…", "正在和模型沟通任务，请稍候",
                         color=TEXT, card=CARD_RUN)
        self.start_button.configure(text="⏹ 停止", fg_color="#DC2626",
                                    hover_color="#B91C1C")
        self.input_text.configure(state="disabled")
        self._update_tray("Desktop Agent · 执行中")
        mode = self.settings.get("model_mode", "local")
        if mode != "local":
            self._log_line("warning", "⚠️ 云端模式：本次任务的屏幕数据会上传到模型服务商")
        self._log_line("time", time.strftime("%H:%M:%S") + "  📋 任务：" + task)
        threading.Thread(target=self._run_agent, args=(task,), daemon=True).start()

    def _finish(self, ok: bool, text: str, stopped=False):
        """任务结束（成功/失败/停止）统一收尾"""
        self.is_running = False
        self.start_button.configure(text="▶ 开始执行", fg_color=ACCENT,
                                    hover_color=ACCENT_HOVER)
        self.input_text.configure(state="normal")
        elapsed = ""
        if self.run_start_time:
            elapsed = f"，用时 {time.time() - self.run_start_time:.0f} 秒"
        self._update_tray("Desktop Agent · 就绪")
        if self.run_start_time:
            elapsed = f"，用时 {time.time() - self.run_start_time:.0f} 秒"
        if stopped:
            self._set_status("⏹", "已停止", "任务已按你的要求停止" + elapsed,
                             color=WARN, card=CARD)
            self._log_line("warning", "⏹ 任务已停止" + elapsed)
        elif ok:
            brief = text if len(text) <= 60 else text[:60] + "…"
            self._set_status("✓", "任务成功完成", brief or ("全部步骤执行完毕" + elapsed),
                             color=OK, card=CARD_OK)
            self._log_line("success", "✓ 任务完成" + elapsed)
        else:
            self._set_status("✗", "任务执行失败", text if len(text) <= 80 else text[:80] + "…",
                             color=ERR, card=CARD_ERR)
            self._log_line("error", "✗ " + text)

    def _humanize_error(self, error_msg: str) -> str:
        error_translations = {
            "PermissionError": "无法操作，可能需要管理员权限",
            "AccessDenied": "没有权限执行此操作",
            "ConnectionError": "无法连接到 LLM 服务，请确保 Ollama 正在运行",
            "Timeout": "操作超时，请重试",
            "[WinError 5]": "无法操作，可能需要管理员权限",
            "[WinError 32]": "文件被占用，请关闭相关程序",
            "module not found": "缺少必要的模块，请重新安装依赖",
            "api key": "API 密钥配置错误",
        }
        for error_key, human_msg in error_translations.items():
            if error_key in error_msg:
                return human_msg
        return f"发生错误：{error_msg}"

    # ================= 后台 =================
    def _run_agent(self, task):
        try:
            self.agent = build_llm_client(
                self.settings,
                on_fallback=lambda err: self.log_queue.put(
                    ("log", f"⚠ 本地模型调用失败，自动切换云端: {err[:60]}")))
            self.agent = DesktopAgent(self.agent,
                                      auditor=self.audit,
                                      history=self.history,
                                      approval=self.approval_bridge)
            self.agent.on_log = lambda m: self.log_queue.put(("log", m))
            self.agent.on_tool_call = self._on_tool_call
            self.agent.on_tool_result = self._on_tool_result
            self.agent.on_retry = self._on_retry

            result = self.agent.run(task)
            stopped = "停止" in (result or "")
            self.log_queue.put(("done", (not stopped and result is not None, result or "", stopped)))
        except Exception as e:
            self.log_queue.put(("done", (False, self._humanize_error(str(e)), False)))

    def _on_retry(self, tool, attempt, max_retries):
        self.log_queue.put(("status", ("🔄", f"重试中 {attempt}/{max_retries}：{TOOL_NAMES.get(tool, tool)}",
                                       "上一次执行未成功，正在自动重试", WARN, CARD_RUN)))

    def _on_scheduled_task(self, sched_task: dict):
        """定时任务到点触发（scheduler 后台线程回调）"""
        task = sched_task.get("task", "")
        if self.is_running:
            self.log_queue.put(("log", f"⏰ 定时任务到点但助手正忙，已跳过：{task}"))
            self.scheduler.set_last_status(sched_task["id"], "skipped-忙")
            return
        self.log_queue.put(("log", f"⏰ 定时任务触发：{task}"))
        self.log_queue.put(("sched_run", task))

    def _on_tool_call(self, name, args):
        self.log_queue.put(("status", ("⚙", f"正在执行：{tool_display(name, args)}",
                                       "工具正在操作你的电脑", TEXT, CARD_RUN)))

    def _on_tool_result(self, name, args, result):
        self.log_queue.put(("status", ("🧠", "执行完成，思考下一步…",
                                       None, TEXT, CARD_RUN)))

    def _check_connection(self):
        try:
            client = build_llm_client(self.settings)
            ok, info = client.check_connection()
        except RuntimeError as e:
            ok, info = False, str(e)
        vision_ok = agent_vision.get_vision().is_available() if ok else False
        if ok:
            extra = "，支持看屏分析" if vision_ok else ""
            self.log_queue.put(("conn", (True, info + extra)))
        else:
            self.log_queue.put(("conn", (False, info)))

    # ================= 定时泵：队列 + 计时 + 确认请求 =================
    def _pump(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._log_line(*classify_log(payload))
                elif kind == "conn":
                    ok, info = payload
                    self.ollama_ok = ok
                    if ok:
                        self.conn_label.configure(text=f"● Ollama 已连接 · {info}",
                                                  text_color=OK)
                    else:
                        self.conn_label.configure(text=f"○ Ollama 未连接（{info}）",
                                                  text_color=ERR)
                elif kind == "status":
                    self._set_status(*payload)
                elif kind == "sched_run":
                    self.is_running = True
                    self.run_start_time = time.time()
                    self.current_turn = 0
                    self._set_status("🧠", "开始执行定时任务…", payload,
                                     color=TEXT, card=CARD_RUN)
                    self.start_button.configure(text="⏹ 停止", fg_color="#DC2626",
                                                hover_color="#B91C1C")
                    self.input_text.configure(state="disabled")
                    self._update_tray("Desktop Agent · 执行中")
                    threading.Thread(target=self._run_agent, args=(payload,),
                                     daemon=True).start()
                elif kind == "done":
                    self._finish(*payload)
        except queue.Empty:
            pass

        # agent 工作线程请求确认高危操作 → 主线程弹窗
        if not self._confirm_open:
            req = self.approval_bridge.pending()
            if req:
                self._confirm_open = True
                self._show_confirm(req)

        if self.is_running and self.run_start_time:
            elapsed = int(time.time() - self.run_start_time)
            turn = f"第 {self.current_turn}/{MAX_TURNS} 轮" if self.current_turn else "准备中"
            self.progress_label.configure(text=f"{turn} · 已用 {elapsed} 秒")
        else:
            self.progress_label.configure(text="")

        self.root.after(120, self._pump)

    def _log_line(self, tag, text):
        self.log_text.configure(state="normal")
        if tag == "time":
            self.log_text.insert("end", text + "\n", "time")
        elif tag == "turn":
            self.log_text.insert("end", "\n" + text + "\n", "turn")
        else:
            self.log_text.insert("end", time.strftime("%H:%M:%S") + "  ", "time")
            self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ================= 确认弹窗（高危操作） =================
    def _show_confirm(self, req: dict):
        dlg = ctk.CTkToplevel(self.root, fg_color=CARD)
        dlg.title("⚠ 需要你的确认")
        dlg.geometry("480x320")
        dlg.attributes("-topmost", True)
        dlg.resizable(False, False)
        dlg.grab_set()

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=18)

        ctk.CTkLabel(body, text="⚠ 助手想执行一个高风险操作",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=WARN).pack(anchor="w")
        ctk.CTkLabel(body, text="原因：" + req["reason"],
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=420, justify="left").pack(anchor="w", pady=(6, 12))

        card = ctk.CTkFrame(body, fg_color=INPUT_BG, corner_radius=8)
        card.pack(fill="both", expand=True)
        ctk.CTkLabel(card, text=f"工具：{req['tool']}",
                     font=ctk.CTkFont(family="Consolas", size=12),
                     text_color=TOOLC, anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(card, text=f"参数：{req['args']}",
                     font=ctk.CTkFont(family="Consolas", size=12), text_color=TEXT,
                     anchor="w", wraplength=400, justify="left").pack(fill="x", padx=12, pady=(0, 12))

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", pady=(14, 0))
        ctk.CTkButton(
            btns, text="✗ 拒绝", width=130, height=38, corner_radius=8,
            fg_color="#DC2626", hover_color="#B91C1C",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._answer_confirm(dlg, req, False),
        ).pack(side="right")
        ctk.CTkButton(
            btns, text="✓ 允许执行", width=130, height=38, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self._answer_confirm(dlg, req, True),
        ).pack(side="right", padx=(0, 10))

        dlg.protocol("WM_DELETE_WINDOW", lambda: self._answer_confirm(dlg, req, False))

    def _answer_confirm(self, dlg, req: dict, allowed: bool):
        GuiApprovalBridge.complete(req, allowed)
        self._confirm_open = False
        dlg.grab_release()
        dlg.destroy()
        self._log_line("info" if allowed else "warning",
                       ("✓ 已允许执行" if allowed else "✗ 已拒绝执行") + f"（{req['tool']}）")

    # ================= 历史面板 =================
    def _show_history(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("任务历史")
        dlg.geometry("720x480")
        dlg.grab_set()

        head = ctk.CTkFrame(dlg, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))
        ctk.CTkLabel(head, text="📜 最近任务", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(head, text=f"记录存放：{self.history.path.parent}",
                     font=ctk.CTkFont(size=10), text_color=MUTED).pack(side="right")

        box = ctk.CTkTextbox(dlg, font=ctk.CTkFont(family="Consolas", size=12),
                             fg_color="#111827", corner_radius=10, wrap="word",
                             state="disabled")
        box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        rows = self.history.recent(50)
        text = ""
        for r in rows:
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

    # ================= 系统托盘 =================
    def _init_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw

            img = Image.new("RGB", (64, 64), ACCENT)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((10, 14, 54, 50), radius=8, fill="#0F2A4A")
            d.ellipse((22, 24, 30, 32), fill="#7FD1FF")   # 左眼
            d.ellipse((34, 24, 42, 32), fill="#7FD1FF")   # 右眼
            d.rounded_rectangle((22, 38, 42, 44), radius=3, fill="#7FD1FF")  # 嘴
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
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    # ================= 设置页（模型切换等） =================
    def _show_settings(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("设置")
        dlg.geometry("620x760")
        dlg.grab_set()

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=14)

        ctk.CTkLabel(body, text="⚙ 设置", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")

        # ---- 模型模式 ----
        ctk.CTkLabel(body, text="模型模式", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", pady=(12, 2))
        mode_var = ctk.StringVar(value=self.settings.get("model_mode", "local"))
        mode_row = ctk.CTkFrame(body, fg_color="transparent")
        mode_row.pack(anchor="w")
        for label, val in (("只用本地", "local"), ("只用云端", "cloud"), ("自动（本地优先）", "auto")):
            ctk.CTkRadioButton(mode_row, text=label, variable=mode_var, value=val,
                               command=lambda: sync_mode_ui(),
                               text_color=TEXT, fg_color=ACCENT).pack(side="left", padx=(0, 14))

        # ---- 本地配置 ----
        ctk.CTkLabel(body, text="本地模型（Ollama，数据不出本机）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(anchor="w", pady=(12, 2))
        model_var = ctk.StringVar(value=self.settings.get("local", {}).get("model",
                                  self.settings.get("model", MODEL_NAME)))
        model_menu = ctk.CTkOptionMenu(body, values=["加载中…"], variable=model_var,
                                       width=320, fg_color=INPUT_BG,
                                       button_color=ACCENT, button_hover_color=ACCENT_HOVER)
        model_menu.pack(anchor="w")
        local_hint = ctk.CTkLabel(body, text="正在读取模型列表…",
                                  font=ctk.CTkFont(size=11), text_color=MUTED)
        local_hint.pack(anchor="w", pady=(4, 0))

        def refresh_models():
            models = LLMClient(LLMConfig(provider=LLMProvider.OLLAMA,
                                         base_url=OLLAMA_URL)).list_models()
            if models:
                model_menu.configure(values=models)
                if model_var.get() not in models:
                    model_var.set(models[0])
                local_hint.configure(text=f"共 {len(models)} 个本地模型可用")
            else:
                local_hint.configure(text="读不到模型列表，请确认 Ollama 正在运行")

        # ---- 云端配置 ----
        cloud_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                 border_width=1, border_color=BORDER)
        cloud_box.pack(fill="x", pady=(14, 0))
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
        cbase_var = ctk.StringVar(value=cloud_cfg.get("base_url",
                                  CLOUD_PRESETS["智谱"]["base_url"]))

        prow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        prow.pack(fill="x", padx=14)
        ctk.CTkLabel(prow, text="服务商", font=ctk.CTkFont(size=11),
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
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(8, 2))
        api_entry = ctk.CTkEntry(cloud_box, textvariable=api_var, show="*",
                                 width=340, fg_color=INPUT_BG, border_color=BORDER)
        api_entry.pack(anchor="w", padx=14)

        crow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        crow.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(crow, text="模型名", font=ctk.CTkFont(size=11),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cmodel_var, width=170,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left", padx=(8, 12))
        ctk.CTkLabel(crow, text="接口地址", font=ctk.CTkFont(size=11),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cbase_var, width=250,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left", padx=(8, 0))

        test_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        test_row.pack(fill="x", padx=14, pady=(6, 12))
        test_result = ctk.CTkLabel(test_row, text="", font=ctk.CTkFont(size=11),
                                   text_color=MUTED, anchor="w")
        env_hint = ""
        preset = CLOUD_PRESETS.get(provider_var.get(), {})
        if preset and os.environ.get(preset["env"]):
            env_hint = "（检测到环境变量，优先使用）"

        def run_test():
            test_result.configure(text="测试中…", text_color=MUTED)
            def work():
                cfg = LLMConfig(
                    provider=LLMProvider(PROVIDER_ENUM.get(
                        provider_by_name.get(provider_var.get(), "zhipu"), "other")),
                    api_key=api_var.get().strip() or resolve_api_key({
                        "provider": provider_by_name.get(provider_var.get(), "zhipu")}),
                    base_url=cbase_var.get().strip(),
                    model=cmodel_var.get().strip(),
                )
                ok, msg = LLMClient(cfg).ping()
                test_result.configure(text=("✓ " if ok else "✗ ") + msg,
                                      text_color=OK if ok else ERR)
            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(test_row, text="测试连接", width=100, height=26,
                      corner_radius=6, fg_color="#374151", hover_color="#4B5563",
                      text_color=TEXT, command=run_test).pack(side="left")
        test_result.pack(side="left", padx=10)
        if env_hint:
            test_result.configure(text="✓ " + env_hint.strip("（）"), text_color=OK)

        # ---- 隐私提示 ----
        privacy = ctk.CTkLabel(body, text="",
                               font=ctk.CTkFont(size=11), text_color=WARN,
                               wraplength=560, justify="left", anchor="w")

        def sync_mode_ui():
            privacy.configure(text="" if mode_var.get() == "local" else
                              "⚠️ 云端模式：屏幕数据会上传到模型服务商")
        privacy.pack(anchor="w", pady=(10, 0))
        sync_mode_ui()

        # ---- 其他 ----
        tray_var = ctk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        ctk.CTkSwitch(body, text="关闭窗口时最小化到系统托盘", variable=tray_var,
                      progress_color=ACCENT, text_color=TEXT,
                      font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(14, 0))

        def save():
            self.settings.set("model_mode", mode_var.get())
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
            self.settings.set("minimize_to_tray", bool(tray_var.get()))
            self._log_line("info", f"⚙ 设置已保存：模式 {mode_var.get()}")
            self._check_connection_async()
            self._sync_privacy_banner()
            dlg.destroy()

        ctk.CTkButton(body, text="保存", width=170, height=38, corner_radius=8,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=save).pack(anchor="w", pady=(16, 0))

        body.after(200, refresh_models)

    def _check_connection_async(self):
        threading.Thread(target=self._check_connection, daemon=True).start()

    # ================= 定时任务面板 =================
    def _show_scheduler(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("定时任务")
        dlg.geometry("720x560")
        dlg.grab_set()

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(16, 10))

        ctk.CTkLabel(body, text="⏰ 定时任务", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")

        # ---- 新建表单 ----
        form = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10)
        form.pack(fill="x", pady=(10, 8))
        task_var = ctk.StringVar()
        type_var = ctk.StringVar(value="每天")
        time_var = ctk.StringVar(value="08:30")
        weekday_var = ctk.StringVar(value="星期一")
        interval_var = ctk.StringVar(value="30")

        ctk.CTkEntry(form, textvariable=task_var, placeholder_text="到点执行的任务，如：打开计算器",
                     width=330, fg_color=INPUT_BG, border_color=BORDER).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 6))
        type_menu = ctk.CTkOptionMenu(form, values=["每天", "每周", "间隔分钟"],
                                      variable=type_var, width=110,
                                      fg_color=INPUT_BG, button_color=ACCENT)
        time_entry = ctk.CTkEntry(form, textvariable=time_var, width=90,
                                  fg_color=INPUT_BG, border_color=BORDER,
                                  placeholder_text="08:30")
        weekday_menu = ctk.CTkOptionMenu(form, values=["星期一", "星期二", "星期三", "星期四",
                                                       "星期五", "星期六", "星期日"],
                                         variable=weekday_var, width=110,
                                         fg_color=INPUT_BG, button_color=ACCENT)
        interval_entry = ctk.CTkEntry(form, textvariable=interval_var, width=90,
                                      fg_color=INPUT_BG, border_color=BORDER)
        type_menu.grid(row=1, column=0, sticky="w", padx=12, pady=4)
        time_entry.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        weekday_menu.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        interval_entry.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        ctk.CTkButton(form, text="＋ 添加", width=80, height=28, corner_radius=6,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self._add_scheduled(
                          dlg, task_var, type_var, time_var, weekday_var, interval_var,
                          time_entry, weekday_menu, interval_entry)
                      ).grid(row=1, column=2, sticky="e", padx=12, pady=4)

        def on_type_change(_=None):
            if type_var.get() == "每天":
                time_entry.grid(); weekday_menu.grid_remove(); interval_entry.grid_remove()
            elif type_var.get() == "每周":
                time_entry.grid(); weekday_menu.grid(); interval_entry.grid_remove()
            else:
                time_entry.grid_remove(); weekday_menu.grid_remove(); interval_entry.grid()
        type_menu.configure(command=on_type_change)
        on_type_change()

        # ---- 任务列表 ----
        ctk.CTkLabel(body, text="现有任务", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", pady=(6, 2))
        self.sched_list_frame = ctk.CTkFrame(body, fg_color="#111827", corner_radius=10)
        self.sched_list_frame.pack(fill="both", expand=True)
        self._render_sched_list(self.sched_list_frame)
        body.pack_configure(expand=True)

    def _add_scheduled(self, dlg, task_var, type_var, time_var, weekday_var,
                       interval_var, time_entry, weekday_menu, interval_entry):
        task = task_var.get().strip()
        if not task:
            return
        stype = {"每天": "daily", "每周": "weekly", "间隔分钟": "interval"}[type_var.get()]
        rec = self.scheduler.add(
            task, stype,
            time_str=time_var.get().strip() if time_entry.winfo_ismapped() else "",
            weekday={"星期一": "monday", "星期二": "tuesday", "星期三": "wednesday",
                     "星期四": "thursday", "星期五": "friday", "星期六": "saturday",
                     "星期日": "sunday"}.get(weekday_var.get(), "") if weekday_menu.winfo_ismapped() else "",
            interval_minutes=int(interval_var.get() or 0) if interval_entry.winfo_ismapped() else 0,
        )
        self._log_line("info", f"⏰ 已添加定时任务（{Scheduler.describe(rec)}）：{task}")
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
            row = ctk.CTkFrame(parent, fg_color="#1F2937", corner_radius=8)
            row.pack(fill="x", padx=10, pady=4)
            mark = "🟢" if t.get("enabled") else "⚪"
            last = time.strftime("%m-%d %H:%M", time.localtime(t["last_run"])) \
                if t.get("last_run") else "未执行过"
            info = (f"{mark} {Scheduler.describe(t)} ｜ {t['task'][:26]}\n"
                    f"    上次：{last} {t.get('last_status', '')}")
            ctk.CTkLabel(row, text=info, font=ctk.CTkFont(size=11),
                         text_color=TEXT if t.get("enabled") else MUTED,
                         justify="left", anchor="w").pack(side="left", padx=10, pady=6)
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=8)
            ctk.CTkButton(btns, text="禁用" if t.get("enabled") else "启用", width=48,
                          height=22, corner_radius=6, fg_color="#374151",
                          hover_color="#4B5563", text_color=TEXT,
                          command=lambda tid=t["id"], en=not t.get("enabled"), d=parent:
                          (self.scheduler.set_enabled(tid, en),
                           [c.destroy() for c in d.winfo_children()],
                           self._render_sched_list(d))).pack(side="left", padx=2)
            ctk.CTkButton(btns, text="删除", width=48, height=22, corner_radius=6,
                          fg_color="#DC2626", hover_color="#B91C1C", text_color=TEXT,
                          command=lambda tid=t["id"], d=parent:
                          (self.scheduler.remove(tid),
                           [c.destroy() for c in d.winfo_children()],
                           self._render_sched_list(d))).pack(side="left", padx=2)

    def _on_close(self):
        if self.is_running:
            self._set_status("⚠", "任务进行中，请先停止再关闭",
                             "点击「⏹ 停止」结束当前任务", color=WARN, card=CARD)
            return
        if self.tray and self.settings.get("minimize_to_tray", True):
            self.root.withdraw()  # 收进托盘，程序继续驻留
            self._update_tray("Desktop Agent · 就绪（已最小化到托盘）")
            return
        self._real_exit()


if __name__ == "__main__":
    import sys
    app = AgentGUI()
    if len(sys.argv) >= 3 and sys.argv[1] == "--debug-open":
        panel = sys.argv[2]  # settings / scheduler / history
        app.root.after(1500, getattr(app, f"_show_{panel}"))
    app.root.mainloop()
