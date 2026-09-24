"""Desktop Agent 智能桌面助手 - 图形界面

界面布局（参考现代 AI 助手对话式设计）：
  顶部：标题 + Ollama 连接状态徽章
  状态卡：大图标显示 当前状态 / 轮次 / 耗时
  中部：执行记录（带时间戳、分类着色的对话式日志）
  底部：示例任务 → 任务输入框 + 开始/停止按钮 → 模型信息
"""
import threading
import queue
import time
import customtkinter as ctk
import agent_vision
from agent_loop import DesktopAgent, LLMClient, LLMConfig, LLMProvider

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5-coder:7b"
MAX_TURNS = 10

# ---------------- 配色（深色主题） ----------------
BG = "#1B1B1B"          # 窗口背景
CARD = "#222222"        # 卡片背景
CARD_OK = "#1D2B23"     # 成功状态卡
CARD_ERR = "#2B1D1D"    # 失败状态卡
CARD_RUN = "#1D242B"    # 执行中状态卡
BORDER = "#333333"
INPUT_BG = "#242424"
ACCENT = "#3B82F6"
ACCENT_HOVER = "#2F6FDB"
TEXT = "#EAEAEA"
MUTED = "#8F8F8F"
OK = "#2CC985"
ERR = "#FF6B6B"
WARN = "#FFB800"
TOOLC = "#6AB0F3"
TURN = "#707070"

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

        self.log_queue = queue.Queue()

        self._build_header()
        self._build_status_card()
        self._build_log()
        self._build_chips()
        self._build_input_row()
        self._build_footer()

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
            text_color=MUTED, hover_color="#2A2A2A",
            font=ctk.CTkFont(size=11), command=self._clear_log,
        )
        self.clear_btn.pack(side="right")

        self.log_text = ctk.CTkTextbox(
            wrap, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#191919", corner_radius=8, wrap="word", state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        for tag, color in (
            ("time", TURN), ("turn", TURN), ("info", TEXT),
            ("assistant", TEXT), ("tool", TOOLC), ("result", "#B9B9B9"),
            ("error", ERR), ("warning", WARN), ("muted", "#666666"),
            ("success", OK),
        ):
            # customtkinter 的 tag_config 不允许 font 选项（与缩放冲突），只着色
            self.log_text.tag_config(tag, foreground=color)
        self._log_welcome()

    def _log_welcome(self):
        """首次打开时的引导信息"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", "👋 你好，我是你的桌面助手\n", "assistant")
        self.log_text.insert("end", "   在下方输入你想做的事，我会一步步操作电脑并记录在这里。\n", "muted")
        self.log_text.insert("end", "   例如：「打开计算器」「打开记事本，输入 你好」\n", "muted")
        self.log_text.configure(state="disabled")

    def _build_chips(self):
        row = ctk.CTkFrame(self.root, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 6))
        ctk.CTkLabel(row, text="试试：", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(side="left")
        for text in EXAMPLES:
            ctk.CTkButton(
                row, text=text, width=10, height=24, corner_radius=12,
                fg_color="#262626", hover_color="#303030", text_color="#BBBBBB",
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
        self.input_text.tag_config("ph", foreground="#6A6A6A")
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
        self.start_button.configure(text="⏹ 停止", fg_color="#7A3B3B",
                                    hover_color="#964646")
        self.input_text.configure(state="disabled")
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
            config = LLMConfig(
                provider=LLMProvider.OLLAMA,
                base_url=OLLAMA_URL,
                model=MODEL_NAME,
                temperature=0.1
            )
            self.agent = DesktopAgent(LLMClient(config))
            self.agent.on_log = lambda m: self.log_queue.put(("log", m))
            self.agent.on_tool_call = self._on_tool_call
            self.agent.on_tool_result = self._on_tool_result

            result = self.agent.run(task)
            stopped = "停止" in (result or "")
            self.log_queue.put(("done", (not stopped and result is not None, result or "", stopped)))
        except Exception as e:
            self.log_queue.put(("done", (False, self._humanize_error(str(e)), False)))

    def _on_tool_call(self, name, args):
        self.log_queue.put(("status", ("⚙", f"正在执行：{tool_display(name, args)}",
                                       "工具正在操作你的电脑", TEXT, CARD_RUN)))

    def _on_tool_result(self, name, args, result):
        self.log_queue.put(("status", ("🧠", "执行完成，思考下一步…",
                                       None, TEXT, CARD_RUN)))

    def _check_connection(self):
        config = LLMConfig(provider=LLMProvider.OLLAMA, base_url=OLLAMA_URL, model=MODEL_NAME)
        ok, info = LLMClient(config).check_connection()
        vision_ok = agent_vision.get_vision().is_available() if ok else False
        if ok:
            extra = "，支持看屏分析" if vision_ok else "（未装视觉模型，看屏功能不可用）"
            self.log_queue.put(("conn", (True, info + extra)))
        else:
            self.log_queue.put(("conn", (False, info)))

    # ================= 定时泵：队列 + 计时 =================
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
                elif kind == "done":
                    self._finish(*payload)
        except queue.Empty:
            pass

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

    def _on_close(self):
        if self.is_running:
            self._set_status("⚠", "任务进行中，请先停止再关闭",
                             "点击「⏹ 停止」结束当前任务", color=WARN, card=CARD)
            return
        self.root.destroy()


if __name__ == "__main__":
    app = AgentGUI()
    app.root.mainloop()
