"""core/guard + core/approval + core/scheduler 回归测试（pytest）。

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

仍存在的绕过变体用 xfail 固化（第三期均已拍板，理由见各用例 docstring）：
字母/数字插入——明确不修；多旗标连写（del/faq）——接受残余；
cmd 脱字符转义（d^el）——不修。
"""
import threading
import time

import pytest

from core import guard
from core.approval import AutoDenyPolicy, GuiApprovalBridge
from core.scheduler import Scheduler


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


@pytest.mark.xfail(reason="决策（第三期拍板）：接受残余，不修。多旗标连写 del/faq 即 "
                          "del /f /a /q；要拦它必须放松『旗标后须空白』的路径保护，"
                          "会重新误伤 del/file.txt 这类相对路径，收益不抵风险", strict=True)
@pytest.mark.parametrize("text", ["del/faq a.txt", "rd/sq c:\\x"])
def test_bypass_glued_multi_flag(text):
    """决策：接受残余，不修。

    修复需要放开斜杠命令匹配的"旗标后边界"约束（当前要求旗标后是
    空白/结尾/shell 分隔符，正是这条约束把 del/file.txt 相对路径排除在
    命令判定之外）。放开后 del/faq 能拦，但 del/file.txt 会重新误伤。
    两害相权：放过多旗标连写（对抗性构造，真实 LLM 少见），保住路径
    硬约束（日常任务高频形态）。本用例固化该残余，若未来匹配策略
    升级使它转正，strict xfail 会报错提醒更新本决策。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.xfail(reason="决策（第三期拍板）：不修。^ 在正常文本合法且常见（a^b、"
                          "数学异或、正则、LaTeX），拉丁词内剔除字符误伤面大；"
                          "属对抗性构造，非常见变体", strict=True)
@pytest.mark.parametrize("text", ["d^el /f a.txt", "del ^/f a.txt"])
def test_bypass_cmd_caret_escape(text):
    """决策：不修。

    cmd 的 ^ 是转义符，d^el 执行时等价 del，理论上可绕过关键词匹配。
    但拦截它需要对拉丁词内做"剔除 ^ 再匹配"，而 ^ 在正常文本里合法
    （异或表达式、正则、LaTeX、URL 转义残留），误伤面大。且本产品定位
    是防"被诱导执行"——本机用户若刻意对抗，绕过路径远不止这一条
    （见 docs/issues/issue-3-guard-多步走私.md 的同类边界讨论）。
    本用例固化该已知残余。"""
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


def test_case_change_is_not_a_bypass():
    """对照用例：改大小写不构成绕过（匹配前统一归一化小写）。"""
    assert guard.evaluate("press_key", {"key": "DELETE"})[0] == "high"
    assert guard.evaluate("type_text", {"text": "RM -RF /"})[0] == "high"


# ==================== is_retryable ====================

def test_analyze_screen_is_retryable():
    """v2.0.14 决策反转：看屏幕改走云端（2~6 秒）后纳入重试清单。
    v2.0.5 的「不重试」只对本机 qwen-vl（107 秒/次）成立，前提已变。"""
    assert guard.is_retryable("analyze_screen") is True


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


# ==================== core/scheduler：去重集合不增长 + 错过提示 ====================
# （修复任务列表任务 13：_fired_this_minute 只增不减的泄漏 + daily 错过无提示）

def _mk_sched(tmp_path, on_due, on_missed=None):
    return Scheduler(on_due=on_due, file_path=tmp_path / "scheduled_tasks.json",
                     on_missed=on_missed)


def _ts(*args):
    return time.mktime(args + (0, 0, -1))


def test_scheduler_fired_set_does_not_grow_across_minutes(tmp_path):
    """换分钟后去重集合清空重填：跨天常驻也不再随分钟数无限增长。"""
    fired = []
    s = _mk_sched(tmp_path, fired.append)
    s.add("说话", "interval", interval_minutes=1)
    t0 = _ts(2026, 1, 5, 9, 0, 0)
    for i in range(3):
        s.check_due(now=t0 + i * 60)
        assert len(s._fired_this_minute) <= 1
    assert len(fired) == 3  # 清理不误伤：每分钟照常触发


def test_scheduler_same_minute_dedup_intact(tmp_path):
    """同一分钟内多轮 check_due（15 秒一轮的语义）仍只触发一次。"""
    fired = []
    s = _mk_sched(tmp_path, fired.append)
    s.add("说话", "interval", interval_minutes=1)
    t0 = _ts(2026, 1, 5, 9, 0, 0)
    s.check_due(now=t0)
    s.check_due(now=t0 + 10)
    s.check_due(now=t0 + 20)
    assert len(fired) == 1


def test_scheduler_missed_daily_notified_once_not_caught_up(tmp_path):
    """错过当天时刻的 daily：提示一次、不补跑、不动 last_run，次日照常触发。"""
    fired, missed_seen = [], []
    s = _mk_sched(tmp_path, fired.append, on_missed=missed_seen.append)
    s.add("晨报", "daily", "09:00")
    late = _ts(2026, 1, 5, 10, 5, 0)  # 09:00 已过才启动
    s.check_due(now=late)
    assert not fired                     # 不自动补跑
    assert len(missed_seen) == 1
    rec = s.load()[0]
    assert rec["last_status"] == "missed"
    assert rec["last_run"] == 0          # 错过不算跑过，明天判定不受影响
    s.check_due(now=late + 60)           # 同一天再查：不重复提示
    assert len(missed_seen) == 1
    s.check_due(now=_ts(2026, 1, 6, 9, 0, 0))
    assert len(fired) == 1               # 次日到点正常触发
    assert s.load()[0]["last_status"] == "triggered"


def test_scheduler_daily_before_time_not_missed(tmp_path):
    """时刻未到不算错过；时刻字段缺失/异常的 daily 不误报。"""
    missed_seen = []
    s = _mk_sched(tmp_path, lambda t: None, on_missed=missed_seen.append)
    s.add("晨报", "daily", "09:00")
    s.add("坏时间", "daily", "")
    s.check_due(now=_ts(2026, 1, 5, 8, 55, 0))
    assert not missed_seen
    statuses = {t["task"]: t["last_status"] for t in s.load()}
    assert statuses == {"晨报": "", "坏时间": ""}


# ==================== core/verify：click 校验分级（REL-P1-4，任务 17） ====================

from core import verify as core_verify


class _FakeEl:
    """UIAElementInfo / 原始 COM 元素桩：control_type + runtime_id + name"""

    def __init__(self, control_type, rid, name=""):
        self.control_type = control_type
        self._rid = rid
        self.name = name

    def GetRuntimeId(self):
        return self._rid

    @property
    def runtime_id(self):
        return self._rid


class _FakeIUIA:
    """IUIA 桩：生产代码只调 get_focused_element()"""

    def __init__(self, focused=None):
        self._focused = focused

    def get_focused_element(self):
        return self._focused


@pytest.fixture
def no_sleep(monkeypatch):
    """校验里的 1.2s 反应窗口与重试退避全部归零（不真等）"""
    monkeypatch.setattr(core_verify.time, "sleep", lambda s: None)


def test_capture_click_target_classifies(monkeypatch):
    """点击前目标分类：控件白名单 → critical；面板/空白 → plain；
    UIA 查询异常 → unavailable（回退像素并标注弱校验）。"""
    from pywinauto.uia_element_info import UIAElementInfo

    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: _FakeEl("Button", [42], "确定")))
    monkeypatch.setattr("pywinauto.uia_defines.IUIA",
                        lambda: _FakeIUIA(_FakeEl("Button", [1])))
    status, info = core_verify.capture_click_target(10, 20)
    assert status == "critical"
    assert info["runtime_id"] == [42] and info["name"] == "确定"
    assert info["was_focused"] is False          # 焦点在别的控件上

    # 点击前焦点已在目标上：was_focused=True（迁移信号随之不可用）
    monkeypatch.setattr("pywinauto.uia_defines.IUIA",
                        lambda: _FakeIUIA(_FakeEl("Button", [42])))
    _, info2 = core_verify.capture_click_target(10, 20)
    assert info2["was_focused"] is True

    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: _FakeEl("Pane", [7])))
    assert core_verify.capture_click_target(10, 20) == ("plain", None)

    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: (_ for _ in ()).throw(OSError("UIPI 拒答"))))
    status, reason = core_verify.capture_click_target(10, 20)
    assert status == "unavailable" and "OSError" in reason


def test_verify_click_strong_matrix(monkeypatch, no_sleep):
    """强校验判定矩阵：强两路 / 确定落空 / 弱通过 / 回退档（设计文档第 5 节）"""
    from pywinauto.uia_element_info import UIAElementInfo

    pre = {"x": 1, "y": 2, "runtime_id": [42], "control_type": "Button",
           "name": "确定", "was_focused": False}

    # 强信号一：目标元素被替换（典型：确认弹窗关闭）
    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: _FakeEl("Pane", [999])))
    monkeypatch.setattr("pywinauto.uia_defines.IUIA",
                        lambda: _FakeIUIA(_FakeEl("Button", [1])))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (True, "strong") and "消失/被替换" in detail

    # 强信号二：焦点迁移到目标控件
    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: _FakeEl("Button", [42])))
    monkeypatch.setattr("pywinauto.uia_defines.IUIA",
                        lambda: _FakeIUIA(_FakeEl("Button", [42])))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (True, "strong") and "焦点" in detail

    # 元素原样 + 界面在动（动画/计时器）→ 弱通过：不作为落地证据，不触发重试
    monkeypatch.setattr("pywinauto.uia_defines.IUIA",
                        lambda: _FakeIUIA(_FakeEl("Button", [1])))
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (True, "界面已变化"))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (True, "weak") and "弱校验" in detail

    # 元素原样 + 界面无变化 → 确定落空 → fail（交既定重试策略）
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (False, "界面无变化"))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (False, "fail") and "确定落空" in detail

    # after 阶段元素断言不可用 → 回退像素档并标注弱校验（回退档里像素失败也判失败）
    monkeypatch.setattr(UIAElementInfo, "from_point",
                        classmethod(lambda cls, x, y: (_ for _ in ()).throw(OSError("查询失败"))))
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (True, "界面已变化"))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (True, "weak") and "回退" in detail
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (False, "界面无变化"))
    ok, detail, tier = core_verify.verify_click_strong(pre, None)
    assert (ok, tier) == (False, "fail") and "回退" in detail


def test_runtime_id_handles_both_shapes():
    """实机回归（任务 17）：runtime id 在原始 COM 元素（GetRuntimeId 方法）与
    UIAElementInfo 包装对象（runtime_id 属性）两种形态上都取得——修复前包装
    形态 AttributeError 被吞成 None，critical 分类整体失效；COMError 哨兵 0
    视为无信号。"""
    class _Raw:
        def GetRuntimeId(self):
            return (42, 7)

    class _Wrapped:
        @property
        def runtime_id(self):
            return (42, 7)

    class _SentinelZero:
        @property
        def runtime_id(self):
            return 0

    class _Dead:
        pass

    assert core_verify._runtime_id(_Raw()) == [42, 7]
    assert core_verify._runtime_id(_Wrapped()) == [42, 7]
    assert core_verify._runtime_id(_SentinelZero()) is None
    assert core_verify._runtime_id(_Dead()) is None


def test_pixel_changed_basics(monkeypatch, no_sleep):
    """像素比对本体：同图判无变化、异图判有变化、截图异常返回 None"""
    from PIL import Image

    def _img(color):
        return Image.new("L", (256, 144), color)

    before = _img(30)
    monkeypatch.setattr(core_verify.pyautogui, "screenshot", lambda: _img(30))
    assert core_verify._pixel_changed(before) == (False, "界面无变化（差异 0.0%）")
    monkeypatch.setattr(core_verify.pyautogui, "screenshot", lambda: _img(220))
    ok, detail = core_verify._pixel_changed(before)
    assert ok is True and "100.0%" in detail

    def _boom():
        raise RuntimeError("截图失败")
    monkeypatch.setattr(core_verify.pyautogui, "screenshot", _boom)
    ok, detail = core_verify._pixel_changed(before)
    assert ok is None and "跳过" in detail


def test_verify_click_non_critical_unchanged(monkeypatch, no_sleep):
    """回归：非关键点击的旧校验路径行为不变（像素证据决定通过/失败）"""
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (False, "界面无变化（差异 0.0%）"))
    ok, detail = core_verify.verify_click(None)
    assert ok is False and "点击可能未生效" in detail
    monkeypatch.setattr(core_verify, "_pixel_changed",
                        lambda img, t=0.004: (True, "界面已变化（差异 2.0%）"))
    assert core_verify.verify_click(None) == (True, "界面已变化（差异 2.0%）")
