# 从 gui.py 抽出的格式化工具函数。
# T4 Phase 1 纯搬运，零内容变更；gui.py 经兼容层再导出这些名字。
import time

from core.settings import MAX_TURNS
from ui.theme import TOOL_NAMES

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


# 工具成功 → 一句人话（T24 过程卡片的结果摘要）。不在表里的工具回落「已完成」，
# 与 TOOL_CHIP 的状态章（✓ 完成）互补：章说状态，这行说干了什么
_RESULT_VERBS = {
    "open_app": "已打开", "open_url": "已打开", "close_app": "已关闭",
    "click": "已点击", "click_ui_element": "已点击", "type_text": "已输入",
    "press_key": "已按键", "hotkey": "已按快捷键", "scroll": "已滚动",
    "screenshot": "已截图保存", "analyze_screen": "已看清屏幕内容",
    "list_windows": "已列出窗口", "focus_window": "已切到目标窗口",
    "list_ui_elements": "已列出控件", "clipboard_read": "已读取剪贴板",
    "clipboard_write": "已写入剪贴板", "wait": "已等待",
    "send_feishu_message": "已发送", "verify_message_sent": "已核对发送结果",
    "create_folder": "文件夹已备好", "locate_on_screen": "已查找",
    "move_to": "已移动鼠标", "install_skill": "技能包已装好",
    "get_mouse_position": "已获取", "get_screen_size": "已获取",
}


def result_summary(name: str, text: str, ok: bool) -> str:
    """工具结果 → 一句大白话（T24 任务 2 的「结果摘要」）。

    成功给动词短语（如 open_app → 已打开）；失败把引擎的中文报错
    剥掉「错误: 」前缀取前 80 字（原文本就说人话，翻译表反而丢信息）。
    技术全文不丢：运行日志区始终有完整一行。
    """
    if not ok:
        reason = str(text).strip()
        for pfx in ("错误:", "错误："):
            if reason.startswith(pfx):
                reason = reason[len(pfx):].strip()
                break
        return ("没成功：" + reason[:80]) if reason else "没成功"
    return _RESULT_VERBS.get(name, "已完成")


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
    # 未命中翻译表的兜底（UX-P1-9）：异常原文常带 NoneType/KeyError 这类类名
    # 和技术细节，对非技术用户是天书。改成"发生了什么 + 能做什么"；原文打到
    # 控制台备查（源码运行可看，打包版无控制台——原文本也无补于用户自救）
    print(f"[unhandled-error] {error_msg}")
    return ("出了点问题，这一步没能完成。可以重试一次，或把任务拆得更简单些；"
            "反复出现的话请重启程序再试")


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


def _effective_max_turns(settings) -> int:
    """轮次上限显示的单一来源（T7）：settings["max_turns"]，缺省回落 MAX_TURNS。
    与 agent_loop.DesktopAgent 的取值逻辑保持一致。"""
    try:
        return max(1, int(settings.get("max_turns", MAX_TURNS)))
    except (TypeError, ValueError):
        return MAX_TURNS
