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
import customtkinter as ctk
import agent_vision
import tkinter as tk
from tkinter import messagebox
from agent_loop import (DesktopAgent, LLMClient, LLMConfig, LLMProvider,
                        build_llm_client, final_reply_failed)
from core.approval import GuiApprovalBridge
from core.audit import AuditLogger
from core.history import TaskHistory
from core.scheduler import Scheduler
from core.settings import CLOUD_PRESETS, PROVIDER_ENUM, Settings, resolve_api_key

try:
    from PIL import Image
except ImportError:
    Image = None

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5-coder:7b"
MAX_TURNS = 10
DEFAULT_MAX_CONCURRENT = 3

# ---------------- 配色（gray-900 体系 · 对话流补充色 · WCAG AA） ----------------
BG = "#111827"            # 主背景（gray-900）
SIDEBAR = "#0D1526"       # 侧边栏（比主背景更深一档，形成分区）
CARD = "#1F2937"          # 卡片 / Agent 气泡（gray-800）
CARD_2 = "#374151"        # 工具卡片 / 活动高亮（gray-700）
BORDER = "#4B5563"        # 边框（gray-600）
INPUT_BG = "#374151"      # 输入框背景
ACCENT = "#3B82F6"        # 主色（blue-500）
ACCENT_HOVER = "#2563EB"
BUBBLE_USER = "#1E40AF"   # 用户气泡（blue-800）
TEXT = "#F3F4F6"          # 正文（gray-100）
MUTED = "#D1D5DB"         # 次要文字（gray-300）
FAINT = "#9CA3AF"         # 弱化文字（gray-400）
OK = "#34D399"            # 成功（emerald-400）
ERR = "#F87171"           # 失败（red-400）
WARN = "#FBBF24"          # 警告（amber-400）
RUNBLUE = "#60A5FA"       # 执行中（blue-400）
AMBER = "#FCD34D"         # 隐私条文字
TOOLC = "#93C5FD"         # 工具名（blue-300）

STATUS_COLOR = {"draft": FAINT, "queued": FAINT, "running": RUNBLUE,
                "done": OK, "failed": ERR, "stopped": WARN}
STATUS_ICON = {"draft": "○", "queued": "⏸", "running": "⏳",
               "done": "✓", "failed": "✗", "stopped": "⏹"}
STATUS_TEXT = {"draft": "还没开始", "queued": "排队等待中", "running": "执行中",
               "done": "已完成", "failed": "失败", "stopped": "已停止"}

TOOL_CHIP = {  # 工具卡状态 → (文案, 颜色)
    "run": ("⏳ 执行中…", RUNBLUE), "ok": ("✓ 完成", OK),
    "err": ("✗ 出错", ERR), "block": ("🚫 已拦截", WARN),
}

PLACEHOLDER = "用一句话描述你想让我做什么，例如：打开记事本，输入 你好"

TOOL_NAMES = {
    "open_app": "打开应用", "click": "点击", "type_text": "输入文字",
    "press_key": "按键", "hotkey": "按快捷键", "move_to": "移动鼠标",
    "scroll": "滚动", "screenshot": "截取屏幕", "locate_on_screen": "查找屏幕图像",
    "wait": "等待", "get_mouse_position": "获取鼠标位置", "get_screen_size": "获取分辨率",
    "analyze_screen": "看屏幕", "list_windows": "查看窗口列表",
    "focus_window": "切换窗口", "list_ui_elements": "查看窗口控件",
    "click_ui_element": "点击控件", "clipboard_read": "读取剪贴板",
    "clipboard_write": "写入剪贴板", "verify_message_sent": "确认消息已发出",
    "send_feishu_message": "发飞书消息",
}

EXAMPLES = ["打开计算器", "打开记事本，输入 你好", "截取屏幕", "看看现在有哪些窗口"]

# ---------------- 人性化文案 ----------------
WELCOME_HEAD = "👋 你好呀，我是你的桌面助手"
MSG_ON_IT = "收到！马上开始，过程都在下面 👇"
MSG_QUEUED = "现在已经有 {n} 个任务在跑啦，这个先排个队，轮到就自动开始 ⏳"
MSG_DONE_OK = "✓ 搞定！{extra}有别的需要随时叫我。"
MSG_DONE_FAIL = ("抱歉，这次没能完成：{reason}\n"
                 "要不换个说法再试一次？或者把任务拆小一点，我们一步一步来。")
MSG_STOPPED = "⏹ 好的，已经停下。想继续随时说一声。"
MSG_NEED_INPUT = "先告诉我你想做什么吧，比如：打开计算器 😊"
MSG_APPROVED = "✓ 好的，你已允许，我继续了。"
MSG_DENIED = "🚫 收到，这一步我不做了，换个安全的方式试试。"
MSG_BLOCKED_SUB = "没关系，我会换个安全的方式，或者这件事需要你手动处理。"
MSG_CONFIRM_HEAD = "这一步有点风险，需要你点头确认："


def short_title(text: str, n: int = 14) -> str:
    """取任务第一小句做标题：'打开记事本，输入 你好' → '打开记事本'"""
    t = " ".join(str(text).split())
    for sep in "，。！？；\n,!?;":
        i = t.find(sep)
        if i > 0:
            t = t[:i]
            break
    return t if len(t) <= n else t[:n] + "…"


def rel_time(ts: str) -> str:
    """'2026-09-25 14:30:00' → 刚刚 / 3 分钟前 / 今天 14:30 / 昨天 … / 09-20 14:30"""
    try:
        t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return str(ts)
    d = time.time() - t
    if d < 0 or d < 60:
        return "刚刚"
    if d < 3600:
        return f"{int(d // 60)} 分钟前"
    if time.strftime("%Y-%m-%d", time.localtime(t)) == time.strftime("%Y-%m-%d"):
        return f"今天 {ts[11:16]}"
    if d < 172800:
        return f"昨天 {ts[11:16]}"
    return ts[5:16]


def fmt_tokens(n: int) -> str:
    n = int(n or 0)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.2f}M"


def tool_display(name: str, args) -> str:
    """把工具名+参数转成人话，如 打开应用 notepad"""
    cn = TOOL_NAMES.get(name, name)
    detail = ""
    if isinstance(args, dict):
        if name == "open_app":
            detail = str(args.get("app_name", ""))
        elif name == "click":
            detail = f"({args.get('x')}, {args.get('y')})"
        elif name in ("type_text", "clipboard_write", "send_feishu_message"):
            t = str(args.get("text", ""))
            detail = (t[:20] + "…") if len(t) > 20 else t
        elif name == "click_ui_element":
            detail = str(args.get("name", ""))
        elif name == "hotkey":
            detail = str(args.get("keys", ""))
        elif name == "press_key":
            detail = str(args.get("key", ""))
        elif name == "scroll":
            detail = str(args.get("clicks", ""))
        elif name == "wait":
            detail = f"{args.get('seconds', '')} 秒"
        elif name == "analyze_screen":
            q = str(args.get("question", ""))
            detail = (q[:20] + "…") if len(q) > 20 else q
        elif name == "focus_window":
            detail = str(args.get("title", ""))
    return f"{cn} {detail}".strip()


def humanize_error(error_msg: str) -> str:
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


def parse_log(m: str):
    """把 agent 日志行分类为 (kind, payload)，kind 决定它在对话流里的形态"""
    m = m.strip()
    if m.startswith("── 第"):
        return "turn", m
    if m.startswith("[助手]"):
        return "assistant", m.replace("[助手]", "").strip()
    if m.startswith("[错误]"):
        return "error", m.replace("[错误]", "").strip()
    if m.startswith("[拦截]"):
        return "blocked", m.replace("[拦截]", "").strip()
    if m.startswith("[确认]"):
        return "approved", m.replace("[确认]", "").strip()
    if m.startswith(("[重试]", "[校验]", "思考用时", "工具执行用时")):
        return "noise", m
    return "info", m


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
        threading.Thread(target=self._run, args=(app,), daemon=True).start()

    def _run(self, app):
        try:
            llm = build_llm_client(
                app.settings,
                on_fallback=lambda err: self.ui_queue.put(
                    ("log", f"⚠ 本地模型调用失败，自动切换云端：{err[:60]}")))
            agent = DesktopAgent(llm, auditor=app.audit, history=app.history,
                                 approval=self.approval)
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
                     font=ctk.CTkFont(size=11), text_color=FAINT,
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
        ctk.CTkLabel(row, text="🤖 助手", font=ctk.CTkFont(size=10),
                     text_color=FAINT, anchor="w").pack(anchor="w", padx=(8, 0))
        bubble = ctk.CTkFrame(row, fg_color=CARD, corner_radius=14)
        bubble.pack(anchor="w", padx=(8, 90))
        ctk.CTkLabel(bubble, text=ev["text"], font=ctk.CTkFont(size=13),
                     text_color=TEXT, wraplength=440, justify="left").pack(
            padx=14, pady=8)

    def _system(self, ev):
        color = {"info": MUTED, "ok": OK, "err": ERR,
                 "warn": WARN, "faint": FAINT}.get(ev.get("tone", "info"), MUTED)
        ctk.CTkLabel(self.frame, text=ev["text"], font=ctk.CTkFont(size=12),
                     text_color=color, wraplength=520, justify="left").pack(
            anchor="w", padx=10, pady=(3, 3))

    def _turn(self, ev):
        ctk.CTkLabel(self.frame, text=f"—— 第 {ev['n']} 轮 ——",
                     font=ctk.CTkFont(size=10), text_color=FAINT).pack(
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
        chip = ctk.CTkLabel(head, text=chip_text, font=ctk.CTkFont(size=11),
                            text_color=chip_color)
        chip.pack(side="right")

        args_lbl = ctk.CTkLabel(
            card, text="参数：" + json.dumps(ev.get("args", {}), ensure_ascii=False)[:140],
            font=ctk.CTkFont(family="Consolas", size=10), text_color=FAINT,
            wraplength=440, justify="left", anchor="w")
        args_lbl.pack(fill="x", padx=12, pady=(2, 0))

        result_lbl = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11),
                                  wraplength=440, justify="left", anchor="w")
        result_lbl.pack(fill="x", padx=12, pady=(2, 0))

        note_lbl = ctk.CTkLabel(card, text=ev.get("note", ""),
                                font=ctk.CTkFont(size=11), text_color=WARN,
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
                     font=ctk.CTkFont(size=11), text_color=MUTED,
                     wraplength=440, justify="left", anchor="w").pack(
            anchor="w", padx=12, pady=(2, 0))

        state_lbl = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=11, weight="bold"))
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
        ctk.CTkLabel(card, text=MSG_BLOCKED_SUB, font=ctk.CTkFont(size=11),
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


class AgentGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Desktop Agent - 智能桌面助手")
        self.root.geometry("1180x780")
        self.root.minsize(1020, 680)
        self.root.configure(fg_color=BG)

        # 企业化基础设施（个人版实现，接口与企业版一致）
        self.audit = AuditLogger()
        self.history = TaskHistory()
        self.settings = Settings()
        self.scheduler = Scheduler(on_due=self._on_scheduled_task)
        self.scheduler.start()
        self.tray = None

        self.sessions = {}          # id → TaskSession（插入序 = 创建序）
        self.active = None
        self.ollama_ok = None       # None=检测中
        self._sidebar_dirty = True
        self._tabs_dirty = True

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
        ctk.CTkLabel(bar, text="🤖 Desktop Agent 智能桌面助手",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self.conn_label = ctk.CTkLabel(bar, text="○ 正在连接本地 Ollama…",
                                       font=ctk.CTkFont(size=12), text_color=MUTED)
        self.conn_label.pack(side="right")
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
        ctk.CTkLabel(bottom, text="🔌 插件（即将上线）", height=22,
                     font=ctk.CTkFont(size=11), text_color=FAINT).pack(
            anchor="w", pady=(8, 0))

        # ---- 主区 ----
        main = ctk.CTkFrame(body, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        self.tabbar = ctk.CTkFrame(main, fg_color="transparent", height=40)
        self.tabbar.pack(fill="x", pady=(0, 4))

        self.chat = ChatStream(main, self)
        self.chat.frame.pack(fill="both", expand=True)

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
                                           font=ctk.CTkFont(size=11),
                                           text_color=WARN)
        self.privacy_banner.pack(side="left")
        self.progress_label = ctk.CTkLabel(status_row, text="",
                                           font=ctk.CTkFont(size=11),
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
        if s.status == "running":
            if not messagebox.askyesno(
                    "任务还在跑",
                    f"「{s.title}」还在执行中，要停止并关闭它吗？"):
                return
            s.stop()
        elif s.status == "queued":
            s.status = "draft"
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
            s.stop()
            self.start_button.configure(text="正在停止…")
            s.add("system", text="收到，正在停下…", tone="faint")
            if self.active is s:
                self.chat.append(s.events[-1])
            return
        if s.status == "queued":
            s.status = "draft"
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
            s.add("system", text="连不上本地 Ollama，请确认它已启动，我正在重新检测…",
                  tone="err")
            if self.active is s:
                self.chat.append(s.events[-1])
            return

        # 覆盖旧会话重跑：清空上一轮的事件流
        if s.status in ("done", "failed", "stopped"):
            s.events.clear()
            s.start_time = None
            s.elapsed = None
            s.turn = 0
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

    # ================= 事件应用（主线程） =================
    def _apply(self, s, kind, payload):
        if kind == "log":
            self._apply_log(s, payload)
        elif kind == "tool_call":
            name, args = payload
            ev = s.add("tool", name=name, args=args, state="run",
                       result="", note="", img=None)
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
        self._sidebar_dirty = self._tabs_dirty = True

    def _apply_log(self, s, raw):
        kind, text = parse_log(raw)
        if kind == "noise" or kind == "blocked":
            return  # 拦截结果经 tool_result 呈现，避免重复
        if kind == "turn":
            m = re.search(r"第 (\d+)/", text)
            n = int(m.group(1)) if m else 0
            s.turn = n
            ev = s.add("turn", n=n)
        elif kind == "assistant":
            ev = s.add("assistant", text=text)
        elif kind == "error":
            # 工具错误马上会有 tool_result 到来刷新卡片；无卡片时才落一条系统行
            if s.events and s.events[-1].get("kind") == "tool" \
                    and s.events[-1].get("state") == "run":
                return
            ev = s.add("system", text="✗ " + text, tone="err")
        elif kind == "approved":
            ev = s.add("system", text=MSG_APPROVED, tone="ok")
        else:
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
        ok = not text.startswith("错误")
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
            ev = s.add("system", text=MSG_STOPPED, tone="warn")
        elif ok:
            s.status = "done"
            extra = f"用时 {s.elapsed:.0f} 秒。" if s.elapsed else ""
            ev = s.add("system", text=MSG_DONE_OK.format(extra=extra), tone="ok")
        else:
            s.status = "failed"
            reason = result if len(result) <= 100 else result[:100] + "…"
            ev = s.add("system", text=MSG_DONE_FAIL.format(reason=reason), tone="err")
        if self.active is s:
            self.chat.append(ev)
            self._sync_input_state()
        self._update_tray("Desktop Agent · %d 个任务运行中" % sum(
            1 for x in self.sessions.values() if x.status == "running"))

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
                if self.active is not s:
                    self._select(s)      # 切到该任务，render_all 已包含确认卡
                else:
                    self.chat.append(ev)
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                self.root.lift()
                self._sidebar_dirty = self._tabs_dirty = True

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
        if not s:
            self.progress_label.configure(text="")
            return
        if s.status == "running" and s.start_time:
            elapsed = int(time.time() - s.start_time)
            turn = f"第 {s.turn}/{MAX_TURNS} 轮" if s.turn else "准备中"
            tokens = s.agent.total_tokens if s.agent else 0
            self.progress_label.configure(
                text=f"⏳ {turn} · 已用 {elapsed} 秒 · ⚡ {fmt_tokens(tokens)} tokens")
        elif s.status == "queued":
            ahead = sum(1 for x in self.sessions.values() if x.status == "running")
            self.progress_label.configure(text=f"⏸ 排队中 · 前面还有 {ahead} 个任务")
        elif s.status in ("done", "failed", "stopped") and s.elapsed:
            tokens = s.tokens or (s.agent.total_tokens if s.agent else 0)
            icon = {"done": "✓", "failed": "✗", "stopped": "⏹"}[s.status]
            self.progress_label.configure(
                text=f"{icon} 用时 {s.elapsed:.0f} 秒 · ⚡ {fmt_tokens(tokens)} tokens")
        else:
            self.progress_label.configure(text="")

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
                          font=ctk.CTkFont(size=11),
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
            sub = {"running": f"第 {s.turn}/{MAX_TURNS} 轮",
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
            ctk.CTkLabel(item, text=sub, font=ctk.CTkFont(size=10),
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
    def _check_connection(self):
        try:
            client = build_llm_client(self.settings)
            ok, info = client.check_connection()
        except RuntimeError as e:
            ok, info = False, str(e)
        vision_ok = agent_vision.get_vision().is_available() if ok else False
        if ok:
            extra = "，支持看屏分析" if vision_ok else ""
            self.root.after(0, lambda: self._set_conn(True, info + extra))
        else:
            self.root.after(0, lambda: self._set_conn(False, info))

    def _set_conn(self, ok, info):
        self.ollama_ok = ok
        if ok:
            self.conn_label.configure(text=f"● Ollama 已连接 · {info}", text_color=OK)
        else:
            self.conn_label.configure(text=f"○ Ollama 未连接（{info}）", text_color=ERR)

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
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    def _on_close(self):
        busy = sum(1 for s in self.sessions.values()
                   if s.status in ("running", "queued"))
        if busy and messagebox.askyesno(
                "还有任务在跑",
                f"有 {busy} 个任务还没完成。要全部停止并退出吗？\n"
                f"（选「否」可以最小化到托盘让任务继续跑）"):
            self._real_exit()
            return
        if busy:
            if self.tray and self.settings.get("minimize_to_tray", True):
                self.root.withdraw()
                self._update_tray(f"Desktop Agent · {busy} 个任务运行中")
                return
            self._real_exit()
            return
        if self.tray and self.settings.get("minimize_to_tray", True):
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
                     font=ctk.CTkFont(size=11), text_color=FAINT).pack(
            side="left", padx=12)
        ctk.CTkButton(head, text="↻ 刷新", width=64, height=24, corner_radius=6,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      font=ctk.CTkFont(size=11),
                      command=lambda: render(dlg, table)).pack(side="right")

        table = ctk.CTkScrollableFrame(body, fg_color=SIDEBAR, corner_radius=10)
        table.pack(fill="both", expand=True, pady=(10, 0))

        def chip(parent, status_key):
            icon, color = STATUS_ICON[status_key], STATUS_COLOR[status_key]
            f = ctk.CTkFrame(parent, fg_color="transparent", width=86, height=30)
            f.pack_propagate(False)
            ctk.CTkLabel(f, text=f"{icon} {STATUS_TEXT[status_key]}",
                         font=ctk.CTkFont(size=11), text_color=color).pack(
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
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MUTED, anchor="w").pack(
                    side="left", padx=2)

            def add_row(status_key, task, turns, elapsed, when, result):
                row = ctk.CTkFrame(table, fg_color=CARD, corner_radius=6)
                row.pack(fill="x", pady=1)
                chip(row, status_key).pack(side="left", padx=2, pady=4)
                ctk.CTkLabel(row, text=task, width=260, font=ctk.CTkFont(size=11),
                             text_color=TEXT, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=turns, width=52, font=ctk.CTkFont(size=11),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=elapsed, width=68, font=ctk.CTkFont(size=11),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                ctk.CTkLabel(row, text=when, width=110, font=ctk.CTkFont(size=11),
                             text_color=MUTED, anchor="w").pack(side="left", padx=2)
                brief = result if len(result) <= 46 else result[:46] + "…"
                ctk.CTkLabel(row, text=brief, width=320, font=ctk.CTkFont(size=11),
                             text_color=FAINT, anchor="w").pack(side="left", padx=2)

            for s in reversed(list(self.sessions.values())):
                if s.status == "draft" and not s.task_text:
                    continue
                turns = f"{s.turn}/{MAX_TURNS}" if s.turn else "-"
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
                              "max_turns": "failed",
                              "running": "running"}.get(r.get("status", ""), "draft")
                if status_key == "running":
                    continue  # 本会话区已展示活任务，历史里残留的 running 是上次异常退出
                elapsed = f"{r['elapsed_s']:.0f}秒" if r.get("elapsed_s") else "-"
                add_row(status_key, r.get("task", "")[:32],
                        str(r.get("turns", "-")) if r.get("turns") else "-",
                        elapsed, rel_time(r.get("ts", "")),
                        r.get("result", ""))

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
                     font=ctk.CTkFont(size=10), text_color=FAINT).pack(side="right")

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

    def _show_settings(self):
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("设置")
        dlg.geometry("620x900")
        attach_modal_dialog(dlg, self.root)

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
                                  font=ctk.CTkFont(size=11), text_color=FAINT)
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
        cbase_var = ctk.StringVar(value=cloud_cfg.get(
            "base_url", CLOUD_PRESETS["智谱"]["base_url"]))

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
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 12))
        ctk.CTkLabel(crow, text="接口地址", font=ctk.CTkFont(size=11),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cbase_var, width=250,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 0))

        test_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        test_row.pack(fill="x", padx=14, pady=(6, 12))
        test_result = ctk.CTkLabel(test_row, text="", font=ctk.CTkFont(size=11),
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
                test_result.configure(text=("✓ " if ok else "✗ ") + msg,
                                      text_color=OK if ok else ERR)
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
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(
            anchor="w", padx=14)
        ctk.CTkEntry(feishu_box, textvariable=feishu_var, width=560,
                     placeholder_text="https://open.feishu.cn/open-apis/bot/v2/hook/…",
                     fg_color=INPUT_BG, border_color=BORDER).pack(
            anchor="w", padx=14, pady=(6, 12))

        def save():
            self.settings.set("model_mode", mode_var.get())
            self.settings.set("max_concurrent", int(conc_var.get()))
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
            ctk.CTkLabel(row, text=info, font=ctk.CTkFont(size=11),
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
            ctk.CTkButton(btns, text="删除", width=48, height=22, corner_radius=6,
                          fg_color="#DC2626", hover_color="#B91C1C", text_color=TEXT,
                          command=lambda tid=t["id"], d=parent: (
                              self.scheduler.remove(tid),
                              [c.destroy() for c in d.winfo_children()],
                              self._render_sched_list(d))).pack(side="left", padx=2)


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
