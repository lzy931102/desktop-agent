"""core/guard + core/approval 安全层回归测试（pytest）。

替代 v1 T10 的场景覆盖思路（拦截 / 放行 / 绕过尝试），
断言目标是现行 API，不依赖 v1 的 SecurityModule 接口。

被测契约：
- guard.evaluate(tool_name, args) -> (risk, reason)，risk ∈ none/medium/high
- guard.is_retryable(tool_name) -> bool
- GuiApprovalBridge：工作线程 decide() 阻塞，主线程 pending()/complete() 放行，
  超时视为拒绝
- AutoDenyPolicy：无界面环境默认全拒

issue #2 第一期已修复 4 项缺口（修复前行为见各用例 docstring）：
- hotkey 组合键乱序/大小写/含空格 → 按 token 集合匹配，键序无关
- type_text 分隔符变体（制表符/冒号/连续空白）→ 匹配前分隔符归一化
- click_ui_element 名称插空白 → 中文间隙剔除（英文词间空格保留）
- evaluate 非 dict args / 非 str 工具名 → fail-closed 返回 high，不抛异常

第二期（2026-09-26）闭环 6 类变体：
- 分号/逗号/全角冒号/全角分号/全角逗号 → 纳入分隔符归一化集合
- 斜杠位移 → 命令语境锚点匹配（del/f、del/ f 命中；路径/URL 绝对不动）
- 组合键超集 → 白名单修饰键（ctrl+shift+w 命中；ctrl+shift+s 不拦）
- CJK 间标点/符号插入 → 中文间隙剔除升级（删、除 命中；删x除 明确不修）
- 裸词 → 判定表决策（format 不拦、shutdown 维持裸词命中）

仍存在的绕过变体用 xfail 固化：字母/数字插入（明确不修）、多旗标连写
（del/faq）、cmd 脱字符转义（d^el）——后两者为第二期新发现，待拍板。
"""
import threading
import time

import pytest

from core import guard
from core.approval import AutoDenyPolicy, GuiApprovalBridge


# ==================== 高危操作：必须拦截 ====================

@pytest.mark.parametrize("tool,args", [
    ("press_key", {"key": "delete"}),
    ("press_key", {"key": "Delete"}),              # 大小写不敏感
    ("press_key", {"key": "backspace"}),
    ("hotkey", {"keys": "alt+f4"}),                # 字符串形式
    ("hotkey", {"keys": ["alt", "f4"]}),           # 列表以 + 连接
    ("hotkey", {"keys": ["shift", "delete"]}),
    ("hotkey", {"keys": ["ctrl", "w"]}),
    ("hotkey", {"keys": "ALT+F4"}),                # 大小写不敏感
    ("click_ui_element", {"name": "删除"}),
    ("click_ui_element", {"name": "格式化磁盘"}),
    ("click_ui_element", {"name": "还原默认设置"}),
    ("click_ui_element", {"name": "退出登录"}),
    ("type_text", {"text": "rm -rf /"}),
    ("type_text", {"text": "del /f a.txt"}),
    ("type_text", {"text": "shutdown /s"}),
    ("type_text", {"text": "reg delete HKLM"}),
])
def test_high_risk_blocked(tool, args):
    risk, reason = guard.evaluate(tool, args)
    assert risk == "high"
    assert reason


# ==================== 正常操作：不误伤 ====================

@pytest.mark.parametrize("tool,args", [
    ("press_key", {"key": "enter"}),
    ("press_key", {"key": "pagedown"}),            # 不含 delete/backspace 子串
    ("hotkey", {"keys": ["ctrl", "c"]}),
    ("click_ui_element", {"name": "保存"}),
    ("type_text", {"text": "hello world"}),
    ("clipboard_write", {"text": "hello"}),
    ("open_app", {"app_name": "calc"}),
    ("screenshot", {}),                            # 空参数
    ("press_key", {}),                             # 参数缺失
    ("press_key", {"key": ""}),                    # 空值跳过
    ("press_key", {"key": 123}),                   # 非字符串值归一化后不命中
    ("unknown_tool", {"key": "delete"}),           # 未登记工具不套规则
    ("press_key", {"text": "delete"}),             # 参数名不匹配（规则查 key）
])
def test_safe_operations_allowed(tool, args):
    assert guard.evaluate(tool, args) == ("none", "")


# ==================== medium：剪贴板敏感词 ====================

@pytest.mark.parametrize("text", [
    "my password is 123",
    "身份证复印件",
    "银行卡号",
    "请查收密码",
])
def test_medium_clipboard_sensitive(text):
    assert guard.evaluate("clipboard_write", {"text": text})[0] == "medium"


def test_medium_is_not_high():
    """medium 只分级提示，不得升级为 high 拦截（agent_loop 对 medium 走
    "审计 + 提示放行" 路径，见 test_agent_loop_guard.py）。"""
    risk, _ = guard.evaluate("clipboard_write", {"text": "password"})
    assert risk == "medium"


# ==================== equals 分支（当前 RULES 未使用，注入临时规则覆盖路径） ====================

def test_equals_branch_hit(monkeypatch):
    monkeypatch.setattr(guard, "RULES", [
        {"tools": ["open_app"], "param": "app_name", "equals": ["calc"],
         "risk": "high", "reason": "测试规则"}])
    assert guard.evaluate("open_app", {"app_name": "calc"}) == ("high", "测试规则")


def test_equals_branch_partial_match_not_hit(monkeypatch):
    """equals 是全等匹配，包含关系不算命中。"""
    monkeypatch.setattr(guard, "RULES", [
        {"tools": ["open_app"], "param": "app_name", "equals": ["calc"],
         "risk": "high", "reason": "测试规则"}])
    assert guard.evaluate("open_app", {"app_name": "calc.exe"}) == ("none", "")


def test_equals_branch_case_insensitive(monkeypatch):
    monkeypatch.setattr(guard, "RULES", [
        {"tools": ["open_app"], "param": "app_name", "equals": ["calc"],
         "risk": "high", "reason": "测试规则"}])
    assert guard.evaluate("open_app", {"app_name": "CALC"}) == ("high", "测试规则")


# ==================== 修复验证：issue #2 的绕过变体，修复前均返回 none ====================

@pytest.mark.parametrize("keys", [
    ["f4", "alt"],            # 修复前：列表乱序连接成 "f4+alt"，不命中 "alt+f4" → 绕过
    "f4+alt",                 # 修复前：字符串乱序同样绕过
    "F4+ALT",                 # 修复前：大小写变化 + 乱序双重变体绕过
    "alt + f4",               # 修复前："+" 两侧带空格，子串不命中 → 绕过
    ["DELETE", "SHIFT"],      # 修复前：shift+delete 的乱序大写变体绕过
])
def test_fix_hotkey_order_insensitive(keys):
    """组合键匹配改为 token 集合比对（键序无关），任意排列均命中。"""
    risk, reason = guard.evaluate("hotkey", {"keys": keys})
    assert risk == "high"
    assert reason == "关闭窗口/删除类组合键"


@pytest.mark.parametrize("text", [
    "format\tC:",             # 修复前：制表符替代空格，不命中 "format " → 绕过
    "format:C:",              # 修复前：冒号变体绕过
    "format\t\tC:",           # 修复前：连续制表符变体绕过
    "del  /f a.txt",          # 修复前：关键词内部双空格，不命中 "del /f" → 绕过
    "reg\tdelete HKLM",       # 修复前：制表符变体绕过
    "shutdown\t/s",           # 修复前：制表符变体绕过
])
def test_fix_separator_variants_blocked(text):
    """分隔符归一化（制表符/换行/冒号 → 空格，连续空白折叠）后再匹配。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.parametrize("name", [
    "删 除",                  # 修复前：单空格插字，不含连续 "删除" → 绕过
    "删  除",                 # 修复前：多空格插字绕过
    "删\u3000除",             # 修复前：全角空格插字绕过
    "删\n除",                 # 修复前：换行插字绕过
    "格式化 磁盘",
    "退 出 登 录",
])
def test_fix_cjk_whitespace_injection_blocked(name):
    """中文间隙剔除：夹在两个中文字符之间的空白删除后再匹配。"""
    assert guard.evaluate("click_ui_element", {"name": name})[0] == "high"


def test_fix_cjk_whitespace_keeps_latin_word_gaps():
    """对照：中文间隙剔除不得影响英文词间空格 —— "format C" 仍保留空格且正常匹配，
    "reformat C" 的 "format " 锚点语义不变（尾随空格未被剥离）。"""
    assert guard.evaluate("type_text", {"text": "format C:"})[0] == "high"
    assert guard.evaluate("type_text", {"text": "rm -rf /home"})[0] == "high"
    # 英文单词中间的空格未被剔除，因此不会把 "de leted" 之类误并成关键词
    assert guard.evaluate("press_key", {"key": "de lete"}) == ("none", "")


def test_fix_medium_rule_whitespace_variant():
    """medium 规则同样受益：剪贴板敏感词插空格 "银 行 卡" 命中（修复前 none）。"""
    risk, reason = guard.evaluate("clipboard_write", {"text": "银 行 卡 号"})
    assert risk == "medium"
    assert reason == "剪贴板内容含敏感词"


# ==================== 健壮性：非法入参 fail-closed，不抛异常 ====================

@pytest.mark.parametrize("args", [None, "delete", ["delete"], 123, ("delete",)])
def test_invalid_args_fail_closed(args):
    """修复前：args 非 dict 时 AttributeError 直接崩溃（None/str/list/int 均复现）。
    修复后：无法评估参数内容 → 一律按 high 拒绝（fail-closed）。"""
    risk, reason = guard.evaluate("press_key", args)
    assert risk == "high"
    assert reason


def test_invalid_args_rule_free_tool_fail_closed():
    """无规则覆盖的工具遇到非法 args 同样 fail-closed：无法评估 ≠ 静默放行。"""
    assert guard.evaluate("screenshot", None)[0] == "high"
    assert guard.evaluate("unknown_tool", "whatever")[0] == "high"


def test_invalid_tool_name_fail_closed():
    """修复前：tool_name=None 不崩溃但静默返回 none（防对抗缺口）。
    修复后：非 str 工具名按 high 拒绝。"""
    risk, reason = guard.evaluate(None, {"key": "delete"})
    assert risk == "high"
    assert reason
    assert guard.evaluate(123, {"key": "delete"})[0] == "high"


def test_valid_args_still_work_after_type_guard():
    """类型守卫不影响正常路径：合法 dict 入参照常评估。"""
    assert guard.evaluate("press_key", {"key": "delete"})[0] == "high"
    assert guard.evaluate("screenshot", {}) == ("none", "")


# ==================== 第二期：分号/逗号/全角分隔符（修复验证） ====================

@pytest.mark.parametrize("text", [
    "format;C:",              # 修复前：分号不在分隔符集合，不命中 "format " → 绕过
    "format, C:",             # 修复前：逗号变体绕过
    "format；C:",             # 修复前：全角分号变体绕过
    "format，C:",             # 修复前：全角逗号变体绕过
    "reg,delete HKLM",        # 修复前：逗号拆散 "reg delete" → 绕过
])
def test_fix_semicolon_comma_variants_blocked(text):
    """分号/逗号（含全角族）纳入分隔符归一化，与制表符/冒号同机制。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.parametrize("text", [
    "format：C:",             # 修复前：全角冒号不在集合 → 绕过
    "del：/f a.txt",          # 修复前：全角冒号拆散 "del /f" → 绕过
    "shutdown：/s",           # 修复前：同上
])
def test_fix_fullwidth_colon_variants_blocked(text):
    """全角冒号（中文输入法自动产生）纳入分隔符归一化。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.parametrize("text", [
    "hello, world",                  # 正常英文逗号句
    "time: 12:30; meeting room",     # 时间表达
    "注意：今晚八点开会",             # 中文冒号句
    "C:/Users/foo; D:/bar",          # 盘符路径列表
])
def test_separator_expansion_no_false_positives(text):
    """对照：分隔符集合扩展不得误伤正常含分号/逗号/冒号/盘符的文本。"""
    assert guard.evaluate("type_text", {"text": text}) == ("none", "")


# ==================== 第二期：斜杠位移（命令语境限定修复） ====================

@pytest.mark.parametrize("text", [
    "del/ f a.txt",           # 修复前：斜杠后置空格，子串不命中 → 绕过
    "del / f a.txt",          # 修复前：两侧空格 → 绕过
    "del/f a.txt",            # 修复前：零空格 → 绕过（del/f 是可执行命令形态）
    "rd/s c:\\temp",          # 修复前：rd 零空格 → 绕过
])
def test_fix_slash_displacement_blocked(text):
    """含 / 的命令关键词（del /f、rd /s）改为命令语境匹配：/ 两侧空白任意。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.parametrize("text", [
    "echo hi && del /f x",    # 命令链中段（修前即命中，回归对照）
    "del /f",                 # 结尾形态（修前即命中，回归对照）
])
def test_slash_command_context_controls_blocked(text):
    """对照：常规命令形态在锚点化之后仍命中，不因语境限定漏掉。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.parametrize("text", [
    "/home/del/f.txt",                # unix 绝对路径
    "del/file.txt",                   # 相对路径（旗标后紧跟路径续文）
    "https://example.com/del/file",   # URL
    "https://example.com/rd/status",  # URL 路径段含 rd/s
    "C:\\del\\file.txt",              # windows 反斜杠路径
    "toward/south",                   # 英文连字词（rd/s 语境不成立）
    "copy C:/data /backup",           # 正常路径操作
])
def test_slash_hard_constraint_paths_urls_untouched(text):
    """硬约束：路径/URL 里的 / 绝对不当命令分隔处理——命令词锚点 + 旗标后边界。"""
    assert guard.evaluate("type_text", {"text": text}) == ("none", "")


# ==================== 第二期：组合键超集白名单（修复验证） ====================

@pytest.mark.parametrize("keys", [
    ["ctrl", "shift", "w"],      # 修复前：超集不命中 ctrl+w → 绕过（Chrome 关整个窗口）
    ["alt", "ctrl", "f4"],       # 修复前：超集不命中 alt+f4 → 绕过
    ["delete", "shift", "ctrl"], # shift+delete+ctrl（清除浏览数据家族）乱序
    ["w", "shift", "ctrl"],      # 同上乱序
])
def test_fix_combo_superset_whitelist_blocked(keys):
    """组合键超集白名单：多出的键全部在白名单修饰键内才命中，键序无关。"""
    assert guard.evaluate("hotkey", {"keys": keys})[0] == "high"


@pytest.mark.parametrize("keys", [
    ["ctrl", "shift", "s"],      # 另存为，良性
    ["ctrl", "alt", "delete"],   # 系统安全屏组合（pyautogui 亦无法发送）
    ["alt", "f4", "esc"],        # 白名单外功能键，无标准危险语义
    ["alt", "f4", "win"],        # win 系组合不纳入白名单
    ["ctrl", "w", "q"],          # 白名单外字母键
])
def test_combo_superset_no_overreach(keys):
    """反例：超集白名单不得误拦良性/系统组合（判定表的"不命中"侧）。"""
    assert guard.evaluate("hotkey", {"keys": keys}) == ("none", "")


# ==================== 第二期：CJK 间标点剔除（修复验证） ====================

@pytest.mark.parametrize("name", [
    "删、除",                 # 修复前：顿号插字 → 绕过
    "删。除",                 # 修复前：句号插字 → 绕过
    "删，除",                 # 修复前：全角逗号插字 → 绕过
    "删-除",                  # 修复前：连字符插字 → 绕过
    "删/除",                  # 修复前：斜杠插字 → 绕过
    "退!出",                  # 修复前：感叹号插字 → 绕过
    "格,式,化",               # 修复前：逗号插字（经分隔符归一化后仍需中文间隙剔除收尾）
    "格.式.化",               # 修复前：点号插字 → 绕过
])
def test_fix_cjk_punctuation_injection_blocked(name):
    """中文间隙剔除升级：两个中文字符之间的标点/符号/空白一并剔除。"""
    assert guard.evaluate("click_ui_element", {"name": name})[0] == "high"


# ==================== 第二期：裸词判定（决策固化，非缺陷修复） ====================

def test_decision_bare_format_not_blocked():
    """裸词判定（拍板：不拦）：format 危险语义在 "format <目标>"，裸词命中会
    误伤 reformat/formats 等高频正常文本；关键词 "format " 的尾随空格锚点保留。"""
    assert guard.evaluate("type_text", {"text": "format"}) == ("none", "")
    assert guard.evaluate("type_text", {"text": "reformat"}) == ("none", "")
    assert guard.evaluate("type_text", {"text": "formats"}) == ("none", "")


def test_decision_bare_shutdown_blocked():
    """裸词判定（拍板：维持现状）：shutdown 关键词本就无锚点（裸词命中是
    既有行为而非本期改动）， specificity 高、误伤面小，维持。"""
    assert guard.evaluate("type_text", {"text": "shutdown"})[0] == "high"
    assert guard.evaluate("type_text", {"text": "shutdown -s"})[0] == "high"


# ==================== 第三期：format 目标形态校验（误伤修复） ====================

@pytest.mark.parametrize("text", [
    "date format: YYYY-MM-DD",   # 修复前：冒号归一化后命中 "format " → 误判 high
    "the format is ISO-8601",    # 修复前：前缀子串命中 → 误判 high
    "format: utf-8 编码",         # 修复前：冒号变体命中 → 误判 high
    "xformat c:",                # 修复前：xformat 的子串命中（非命令）→ 误判 high
    "reformat c:",               # 修复前：reformat 子串命中（非命令）→ 误判 high
])
def test_fix_format_target_form_no_false_positive(text):
    """format 升级为目标形态校验：只有 format + 分隔符 + 盘符（可带旗标）才拦，
    普通文本里的 format 字样不再误判（修复前均误判 high）。"""
    assert guard.evaluate("type_text", {"text": text}) == ("none", "")


@pytest.mark.parametrize("text", [
    "format C:",              # 基准危险形态
    "format /q d:",           # 盘符前带旗标
    "format /fs:ntfs e:",     # 长旗标（含冒号）
    "format c:\\users",       # 盘符后跟路径
    "format d:",              # 换盘符
])
def test_format_target_form_still_blocked(text):
    """危险语义不变：format + 分隔符 + 盘符仍判 high。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


# ==================== 第二期后仍存在的绕过变体：xfail 固化，待拍板 ====================

@pytest.mark.xfail(reason="明确不修（第二期拍板）：字母/数字插入属对抗性构造，"
                          "剔除会误伤正常中英混排（误伤面大），保持现状", strict=True)
@pytest.mark.parametrize("name", ["删x除", "删1除", "删a除"])
def test_wontfix_char_insertion_letters(name):
    assert guard.evaluate("click_ui_element", {"name": name})[0] == "high"


@pytest.mark.xfail(reason="第二期新发现，待拍板：多旗标连写（del/faq 即 del /f /a /q）"
                          "被『旗标后须空白』的路径保护挡住；放开会误伤 del/file.txt 相对路径", strict=True)
@pytest.mark.parametrize("text", ["del/faq a.txt", "rd/sq c:\\x"])
def test_bypass_glued_multi_flag(text):
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.xfail(reason="第二期新发现，待拍板：cmd 脱字符转义（d^el 即 del）需对拉丁词"
                          "内做字符删除，误伤面大（a^b 等正常文本）", strict=True)
@pytest.mark.parametrize("text", ["d^el /f a.txt", "del ^/f a.txt"])
def test_bypass_cmd_caret_escape(text):
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


def test_case_change_is_not_a_bypass():
    """对照用例：改大小写不构成绕过（匹配前统一归一化小写）。"""
    assert guard.evaluate("press_key", {"key": "DELETE"})[0] == "high"
    assert guard.evaluate("type_text", {"text": "RM -RF /"})[0] == "high"


# ==================== is_retryable ====================

def test_analyze_screen_not_retryable():
    """v2.0.5 决策回归：analyze_screen 移出重试清单（重试只会加倍等待）。"""
    assert guard.is_retryable("analyze_screen") is False


def test_common_tools_retryable():
    assert guard.is_retryable("click") is True
    assert guard.is_retryable("list_windows") is True


def test_unknown_tool_not_retryable():
    assert guard.is_retryable("no_such_tool") is False


# ==================== approval：GuiApprovalBridge ====================

def test_approval_allow_path():
    bridge = GuiApprovalBridge()
    out = {}
    t = threading.Thread(target=lambda: out.update(
        ok=bridge.decide("hotkey", {"keys": ["alt", "f4"]}, "high", "关闭窗口组合键")))
    t.start()
    time.sleep(0.2)
    req = bridge.pending()
    assert req is not None and req["tool"] == "hotkey"
    GuiApprovalBridge.complete(req, True)
    t.join(2)
    assert out["ok"] is True


def test_approval_deny_path():
    bridge = GuiApprovalBridge()
    out = {}
    t = threading.Thread(target=lambda: out.update(
        ok=bridge.decide("press_key", {"key": "delete"}, "high", "删除类按键")))
    t.start()
    time.sleep(0.2)
    req = bridge.pending()
    assert req is not None
    GuiApprovalBridge.complete(req, False)
    t.join(2)
    assert out["ok"] is False


def test_approval_pending_empty_returns_none():
    assert GuiApprovalBridge().pending() is None


def test_approval_timeout_defaults_to_deny():
    """超时未确认视为拒绝（安全默认值），且确实阻塞到超时。"""
    bridge = GuiApprovalBridge(timeout=1)
    start = time.time()
    ok = bridge.decide("press_key", {"key": "delete"}, "high", "测试")
    assert ok is False
    assert time.time() - start >= 0.9


# ==================== AutoDenyPolicy：无界面默认全拒 ====================

def test_auto_deny_policy_blocks_everything():
    policy = AutoDenyPolicy()
    assert policy.decide("open_app", {"app_name": "calc"}, "none", "") is False
    assert policy.decide("press_key", {"key": "delete"}, "high", "r") is False
