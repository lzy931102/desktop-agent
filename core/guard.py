"""危险操作识别规则库（数据驱动，可独立迭代升级规则而不改代码）。

evaluate() 对每次工具调用做风险评估，返回 (risk, reason)：
- "none"   正常操作
- "medium" 敏感操作：记录审计，不打断
- "high"   危险操作：必须经过 approval 确认才执行
"""

# 规则字段：
#   tools        适用工具名列表
#   param        要检查的参数名（int/str/list 统一转小写文本匹配）
#   contains     出现任一关键词即命中
#   equals       参数整体等于任一值即命中
RULES = [
    {
        "tools": ["press_key"],
        "param": "key",
        "contains": ["delete", "backspace"],
        "risk": "high",
        "reason": "删除类按键，可能造成不可恢复的内容丢失",
    },
    {
        "tools": ["hotkey"],
        "param": "keys",
        "contains": ["alt+f4", "shift+delete", "ctrl+w"],
        "risk": "high",
        "reason": "关闭窗口/删除类组合键",
    },
    {
        "tools": ["click_ui_element"],
        "param": "name",
        "contains": ["删除", "清空", "卸载", "格式化", "退出", "注销", "还原", "重置"],
        "risk": "high",
        "reason": "疑似破坏性按钮",
    },
    {
        "tools": ["type_text"],
        "param": "text",
        "contains": ["rd /s", "del /f", "format ", "rm -rf", "shutdown", "reg delete"],
        "risk": "high",
        "reason": "疑似危险命令文本",
    },
    {
        "tools": ["clipboard_write"],
        "param": "text",
        "contains": ["password", "密码", "身份证", "银行卡"],
        "risk": "medium",
        "reason": "剪贴板内容含敏感词",
    },
]


# 可安全重试的工具（幂等或只读操作）；不在清单内的失败交回模型决策
# analyze_screen 不重试：单次调用可达 1-2 分钟，重试只会加倍等待，失败应让模型换快速通道
RETRYABLE_TOOLS = {
    "click", "type_text", "press_key", "hotkey", "move_to", "scroll",
    "screenshot", "open_app", "wait", "list_windows", "focus_window",
    "list_ui_elements", "click_ui_element", "clipboard_read",
    "clipboard_write", "get_mouse_position", "get_screen_size",
    "locate_on_screen",
}


def is_retryable(tool_name: str) -> bool:
    return tool_name in RETRYABLE_TOOLS


def evaluate(tool_name: str, args: dict) -> tuple:
    """返回 (risk, reason)。risk ∈ none/medium/high"""
    for rule in RULES:
        if tool_name not in rule["tools"]:
            continue
        value = args.get(rule.get("param", ""), "")
        if isinstance(value, (list, tuple)):
            value = "+".join(str(v) for v in value)
        value = str(value).lower()
        if not value:
            continue
        for kw in rule.get("contains", []):
            if kw.lower() in value:
                return rule["risk"], rule["reason"]
        for kw in rule.get("equals", []):
            if value == kw.lower():
                return rule["risk"], rule["reason"]
    return "none", ""
