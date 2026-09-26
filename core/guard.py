"""危险操作识别规则库（数据驱动，可独立迭代升级规则而不改代码）。

evaluate() 对每次工具调用做风险评估，返回 (risk, reason)：
- "none"   正常操作
- "medium" 敏感操作：记录审计 + 界面提示，不打断
- "high"   危险操作：必须经过 approval 确认才执行

匹配按防对抗标准设计（issue #2，两期），参数值与关键词在比对前做同构归一化：
- 统一小写；
- 分隔符归一化：制表符/换行/半角冒号/分号/逗号及全角冒号/分号/逗号 → 空格，
  连续空白折叠为单空格；
- 中文间隙剔除：夹在两个中文字符之间的标点/符号/空白删除
  （"删 除"→"删除"，"删、除"→"删除"）；字母/数字/汉字不剔
  （"删x除" 不并词，防误伤）；英文词间空格保留（"format C" 不受影响）；
- 组合键按 token 集合匹配：键序无关（["f4","alt"] 命中 "alt+f4"），
  超集命中仅限白名单修饰键（ctrl+shift+w 命中 ctrl+w；ctrl+shift+s 不拦）；
- 含 "/" 的命令关键词（del /f、rd /s）按"命令语境"匹配：/ 两侧空白任意，
  但命令词前不能是单词字符、/ 或 \\（排除路径/URL），旗标后必须是空白、
  结尾或 shell 分隔符（排除 del/file.txt 这类相对路径）。
不入参假设：非 str 工具名或非 dict args 一律视为无法评估，按 high 拒绝
（fail-closed），不抛异常。
"""
import re

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


# 分隔符归一化：这些字符在匹配语境里等价于空格。
# 半角：制表符/换行/冒号/分号/逗号；全角：冒号/分号/逗号（中文输入法自动产生
# 的同族变体，2026-09-26 第二期拍板纳入，如需收窄删对应行即可）。
# 注意不收斜杠/竖线/脱字符等——它们各有独立处理或属待拍板项（见测试 xfail 清单）。
_SEP_TO_SPACE = str.maketrans({
    "\t": " ", "\n": " ", "\r": " ",
    ":": " ", ";": " ", ",": " ",
    "：": " ", "；": " ", "，": " ",
})

# 夹在两个 CJK 字符之间的"非构词字符"剔除：标点/符号/空白（\\W）加下划线。
# 字母、数字、汉字本身是 \\w，不会被剔（"删x除" 不并词）；CJK 统一表意文字
# + 扩展A + 兼容表意文字视为构词。
_CJK_CHARS = "\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
_CJK_NOISE = re.compile(f"([{_CJK_CHARS}])[\\W_]+(?=[{_CJK_CHARS}])")


def _normalize(value) -> str:
    """匹配前归一化：小写 + 分隔符归一 + 空白折叠 + 中文间隙剔除。

    不做 strip：保留首尾空格，使关键词自身的锚点（如 "format " 的尾随
    空格）在值与关键词两侧语义一致。
    """
    text = str(value).lower().translate(_SEP_TO_SPACE)
    text = re.sub(r"\s+", " ", text)
    return _CJK_NOISE.sub(r"\1", text)


# 组合键超集白名单（第二期拍板）：值键集合包含关键词全部键、且多出的键
# 全部落在白名单内才命中；白名单外（如 +esc/+win/+字母键）不命中。
# 只收 ctrl/shift/alt 三个修饰键家族中该组合未用到的键——这三个键叠加
# 不改变"关闭/删除"意图的可辨识度，且这些超集组合无日常良性用途；
# win 系组合多为系统级语义，pyautogui 支持也参差，不纳入。
_COMBO_EXTRA_KEYS = {
    frozenset({"alt", "f4"}): frozenset({"ctrl", "shift"}),
    frozenset({"shift", "delete"}): frozenset({"ctrl", "alt"}),
    frozenset({"ctrl", "w"}): frozenset({"shift", "alt"}),
}

# 含 "/" 的命令关键词匹配缓存（del /f、rd /s）
_slash_pattern_cache = {}


def _slash_regex(keyword: str):
    """命令斜杠关键词 → 带语境锚点的正则。

    - "/" 两侧空白任意（"del /f" "del/ f" "del / f" "del/f" 等价）；
    - 命令词前禁止单词字符、"/" 或 "\\"：排除 /home/del/f.txt、
      C:\\del\\x、toward/south 这类路径与连字词；
    - 旗标后必须是结尾/空白/shell 分隔符：排除 del/file.txt 这类
      "旗标后紧跟路径续文"的相对路径形态。
    """
    pat = _slash_pattern_cache.get(keyword)
    if pat is None:
        body = r"\s*/\s*".join(
            r"\s+".join(re.escape(tok) for tok in part.split())
            for part in keyword.split("/"))
        pat = re.compile(rf"(?<![\w/\\]){body}(?=$|[\s;&|<>])")
        _slash_pattern_cache[keyword] = pat
    return pat


def _combo_tokens(text: str) -> set:
    """组合键 token 集：拆 "+"，逐 token 归一化并去两侧空白。"""
    return {_normalize(t).strip() for t in text.split("+")}


def _hit(value: str, keyword: str) -> bool:
    """单个 contains 关键词是否命中。"""
    if "+" in keyword:
        # 组合键：键序无关 + 白名单超集
        if "+" not in value:
            return False
        kw = _combo_tokens(keyword)
        vt = _combo_tokens(value)
        if not kw <= vt:
            return False
        return (vt - kw) <= _COMBO_EXTRA_KEYS.get(frozenset(kw), frozenset())
    if "/" in keyword:
        # 命令斜杠：限命令语境（见 _slash_regex）
        return _slash_regex(keyword).search(value) is not None
    return keyword in value


def evaluate(tool_name: str, args: dict) -> tuple:
    """返回 (risk, reason)。risk ∈ none/medium/high

    fail-closed：工具名非 str 或 args 非 dict 时无法评估参数内容，
    一律按 high 拒绝（非法入参不抛异常、也不静默放行）。
    """
    if not isinstance(tool_name, str) or not isinstance(args, dict):
        return ("high",
                f"参数类型异常（tool={type(tool_name).__name__}, "
                f"args={type(args).__name__}），无法评估风险，按高危拦截")
    for rule in RULES:
        if tool_name not in rule["tools"]:
            continue
        value = args.get(rule.get("param", ""), "")
        if isinstance(value, (list, tuple)):
            value = "+".join(str(v) for v in value)
        value = _normalize(value)
        if not value:
            continue
        for kw in rule.get("contains", []):
            if _hit(value, _normalize(kw)):
                return rule["risk"], rule["reason"]
        for kw in rule.get("equals", []):
            if value == _normalize(kw):
                return rule["risk"], rule["reason"]
    return "none", ""
