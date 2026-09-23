import customtkinter as ctk
import threading
import queue
import sys
from pathlib import Path
from agent_loop import DesktopAgent, LLMClient, load_config

# 设置 CustomTkinter 主题
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AgentGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Desktop Agent - 智能桌面助手")
        self.root.geometry("750x650")
        self.root.minsize(700, 550)

        # 队列用于线程间通信
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.agent = None
        self.is_running = False

        # 创建界面
        self._create_widgets()

        # 启动状态检查线程
        self._start_status_checker()

        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_widgets(self):
        """创建界面组件"""
        # 主容器
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # ==================== 标题区 ====================
        title_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        title_frame.pack(pady=(0, 15), fill="x")

        ctk.CTkLabel(
            title_frame,
            text="你想让我做什么？",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack()

        # ==================== 输入区 ====================
        input_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_frame.pack(pady=(0, 15), fill="x")

        # 输入框
        self.input_text = ctk.CTkTextbox(
            input_frame,
            height=100,
            font=ctk.CTkFont(size=14),
            corner_radius=8,
            border_width=2,
            border_color="#3B8ED0"
        )
        self.input_text.pack(fill="x", pady=(0, 10))
        self.input_text.insert("0.0", "例如：打开记事本，输入 Hello")
        self.input_text.bind("<FocusIn>", lambda e: self._clear_placeholder())

        # 占位符提示
        placeholder_label = ctk.CTkLabel(
            input_frame,
            text="用自然语言描述你的任务",
            font=ctk.CTkFont(size=11, weight="normal"),
            fg_color="transparent",
            text_color="#888888"
        )
        placeholder_label.pack(anchor="w")

        # ==================== 按钮区 ====================
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(pady=(0, 15), fill="x")

        self.start_button = ctk.CTkButton(
            button_frame,
            text="▶ 开始执行",
            font=ctk.CTkFont(size=18, weight="bold"),
            height=50,
            corner_radius=10,
            fg_color="#3B8ED0",  # 蓝色
            hover_color="#2A7BC8",
            command=self._start_agent
        )
        self.start_button.pack(fill="x")

        # ==================== 状态区 ====================
        status_frame = ctk.CTkFrame(
            main_frame,
            fg_color="#1E1E1E",
            corner_radius=12,
            height=80
        )
        status_frame.pack(pady=(0, 15), fill="x")

        # 状态图标和文字
        self.status_label = ctk.CTkLabel(
            status_frame,
            text="⏳ 就绪",
            font=ctk.CTkFont(size=18, weight="bold"),
            fg_color="transparent"
        )
        self.status_label.place(relx=0.1, rely=0.5, anchor="center")

        self.step_label = ctk.CTkLabel(
            status_frame,
            text="等待任务...",
            font=ctk.CTkFont(size=14),
            fg_color="transparent"
        )
        self.step_label.place(relx=0.4, rely=0.5, anchor="center")

        # ==================== 日志区 ====================
        log_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        log_frame.pack(pady=(0, 15), fill="both", expand=True)

        ctk.CTkLabel(
            log_frame,
            text="执行日志",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", pady=(0, 8))

        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=8,
            height=200,
            bg_color="#1E1E1E"
        )
        self.log_text.pack(fill="both", expand=True)

        # ==================== 结果区 ====================
        result_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        result_frame.pack(pady=(0, 0), fill="x")

        self.result_label = ctk.CTkLabel(
            result_frame,
            text="",
            font=ctk.CTkFont(size=14),
            fg_color="transparent"
        )
        self.result_label.pack(pady=5)

    def _clear_placeholder(self):
        """清除占位符文本"""
        if self.input_text.get("0.0", "end").strip() == "例如：打开记事本，输入 Hello":
            self.input_text.delete("0.0", "end")

    def _start_agent(self):
        """开始执行 Agent"""
        task = self.input_text.get("0.0", "end").strip()
        if not task or task == "例如：打开记事本，输入 Hello":
            self._show_status("✗", "请输入任务", "error")
            return

        # 禁用按钮
        self.start_button.configure(state="disabled")
        self.start_button.configure(text="⏸ 执行中...")
        self.input_text.configure(state="disabled")
        self.is_running = True

        # 清空界面
        self.log_text.configure(state="normal")
        self.log_text.delete("0.0", "end")
        self.log_text.configure(state="disabled")

        # 启动后台线程
        thread = threading.Thread(target=self._run_agent, args=(task,))
        thread.daemon = True
        thread.start()

    def _run_agent(self, task):
        """后台执行 Agent"""
        try:
            # 创建配置（使用 Ollama，本地运行）
            from agent_loop import LLMProvider, LLMConfig
            config = LLMConfig(
                provider=LLMProvider.OLLAMA,
                base_url="http://localhost:11434",
                model="qwen2.5-coder:7b",
                temperature=0.1
            )

            # 创建 Agent
            self.agent = DesktopAgent(LLMClient(config))
            self.agent.on_log = self._on_log
            self.agent.on_tool_call = self._on_tool_call
            self.agent.on_tool_result = self._on_tool_result

            # 记录开始时间
            import time
            start_time = time.time()

            # 调用 Agent
            result = self.agent.run(task)

            # 计算耗时
            elapsed_time = time.time() - start_time

            # 格式化结果
            result_text = f"✓ 任务完成！\n耗时：{elapsed_time:.1f}秒\n\n{result}"
            self.result_queue.put(("✓", result_text, "success"))

        except Exception as e:
            error_msg = self._humanize_error(str(e))
            self.result_queue.put(("✗", error_msg, "error"))
        finally:
            self.is_running = False

    def _humanize_error(self, error_msg: str) -> str:
        """人性化错误信息"""
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

    def _on_log(self, message: str):
        """日志回调"""
        self.log_queue.put(message)

    def _on_tool_call(self, tool_name: str, args: dict):
        """工具调用回调 - 人性化"""
        human_msg = self._humanize_tool(tool_name, args)
        self.log_queue.put((human_msg, "INFO"))

    def _on_tool_result(self, tool_name: str, args: dict, result: str):
        """工具结果回调 - 人性化"""
        human_msg = self._humanize_result(tool_name, result)
        self.log_queue.put((human_msg, "SUCCESS"))

    def _humanize_tool(self, tool_name: str, args: dict) -> str:
        """人性化工具调用信息"""
        translations = {
            "click": "正在点击",
            "type_text": "正在输入文字",
            "press_key": "正在按键",
            "hotkey": "正在使用组合键",
            "move_to": "正在移动鼠标",
            "scroll": "正在滚动",
            "screenshot": "正在截图",
            "locate_on_screen": "正在找图标",
            "wait": "正在等待",
            "open_app": "正在打开应用",
            "get_mouse_position": "正在获取鼠标位置",
            "get_screen_size": "正在获取屏幕信息",
        }

        text = translations.get(tool_name, f"正在执行 {tool_name}")
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        return f"{text} ({args_str})"

    def _humanize_result(self, tool_name: str, result: str) -> str:
        """人性化工具结果信息"""
        result_short = result[:60] + "..." if len(result) > 60 else result
        return f"✓ {result_short}"

    def _start_status_checker(self):
        """启动状态检查器"""
        def check():
            while True:
                try:
                    # 处理日志队列
                    while True:
                        try:
                            item = self.log_queue.get_nowait()
                            if isinstance(item, tuple):
                                msg, log_type = item
                            else:
                                msg = item
                                log_type = "INFO"

                            # 设置日志颜色
                            if log_type == "ERROR":
                                self.log_text.configure(state="normal")
                                self.log_text.insert("end", f"❌ {msg}\n", "error")
                                self.log_text.tag_config("error", foreground="#FF5555")
                            elif log_type == "SUCCESS":
                                self.log_text.configure(state="normal")
                                self.log_text.insert("end", f"✓ {msg}\n", "success")
                                self.log_text.tag_config("success", foreground="#2CC985")
                            elif log_type == "WARNING":
                                self.log_text.configure(state="normal")
                                self.log_text.insert("end", f"⚠ {msg}\n", "warning")
                                self.log_text.tag_config("warning", foreground="#FFB800")
                            else:
                                self.log_text.configure(state="normal")
                                self.log_text.insert("end", f"• {msg}\n", "info")
                                self.log_text.tag_config("info", foreground="white")

                            self.log_text.see("end")
                            self.log_text.configure(state="disabled")
                        except queue.Empty:
                            break

                    # 处理状态队列
                    while True:
                        try:
                            icon, text, status = self.status_queue.get_nowait()
                            self.status_label.configure(text=f"{icon} {text}")
                            if status == "success":
                                self.step_label.configure(text="✓ 任务成功完成！")
                            elif status == "error":
                                self.step_label.configure(text="✗ 任务执行失败")
                            else:
                                self.step_label.configure(text="执行中...")
                        except queue.Empty:
                            break

                    # 处理结果队列
                    while True:
                        try:
                            icon, text, status = self.result_queue.get_nowait()
                            self.result_label.configure(text=f"{icon} {text}")
                            if status == "success":
                                self._show_status("✓", "任务完成", "success")
                            elif status == "error":
                                self._show_status("✗", text, "error")
                        except queue.Empty:
                            break

                    # 检查是否完成
                    if not self.is_running and self.agent is not None:
                        self.start_button.configure(state="normal")
                        self.start_button.configure(text="▶ 开始执行")
                        self.input_text.configure(state="normal")
                        self.input_text.focus()

                except Exception as e:
                    pass

                self.root.after(100, check)

        check()

    def _show_status(self, icon: str, text: str, status: str):
        """显示状态"""
        self.status_queue.put((icon, text, status))

    def _on_close(self):
        """窗口关闭事件"""
        if self.is_running:
            if self.agent:
                # Agent 正在运行，不允许关闭
                self._show_status("✗", "任务进行中，请等待完成", "error")
                return
        self.root.destroy()
        sys.exit(0)

    def run(self):
        """运行 GUI"""
        self.root.mainloop()


if __name__ == "__main__":
    app = AgentGUI()
    app.run()
