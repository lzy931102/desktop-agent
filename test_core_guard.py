"""core/guard + core/approval 安全层回归测试（pytest）。

替代 v1 T10 的场景覆盖思路（拦截 / 放行 / 绕过尝试），
断言目标是现行 API，不依赖 v1 的 SecurityModule 接口。

被测契约：
- guard.evaluate(tool_name, args) -> (risk, reason)，risk ∈ none/medium/high
- guard.is_retryable(tool_name) -> bool
- GuiApprovalBridge：工作线程 decide() 阻塞，主线程 pending()/complete() 放行，
  超时视为拒绝
- AutoDenyPolicy：无界面环境默认全拒

issue #2 的 4 项缺口已修复（修复前行为见各用例 docstring）：
- hotkey 组合键乱序/大小写/含空格 → 按 token 集合匹配，键序无关
- type_text 分隔符变体（制表符/冒号/连续空白）→ 匹配前分隔符归一化
- click_ui_element 名称插空格 → 中文间隙剔除（英文词间空格保留）
- evaluate 非 dict args / 非 str 工具名 → fail-closed 返回 high，不抛异常

仍存在的绕过变体用 xfail 固化（分隔符集合扩展、组合键超集、字符插入、
裸关键词），属规则内容/策略扩展，待拍板，不在匹配逻辑修复范围内。
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


# ==================== 仍存在的绕过变体：xfail 固化，待拍板（勿顺手修） ====================
# 这些属于"分隔符集合扩展 / 匹配策略升级 / 规则内容调整"，超出本次匹配逻辑
# 修复范围。修复拍板后：删除对应 xfail 标记并让用例转正。

@pytest.mark.xfail(reason="待拍板：分号/逗号/全角冒号不在分隔符归一化集合内，扩展需评估误伤", strict=True)
@pytest.mark.parametrize("text", [
    "format;C:",              # 分号分隔
    "format, C:",             # 逗号分隔
    "format：C:",             # 全角冒号（中文输入法常见）
    "del/ f a.txt",           # 斜杠位移（空格挪位）
])
def test_bypass_remaining_separators(text):
    assert guard.evaluate("type_text", {"text": text})[0] == "high"


@pytest.mark.xfail(reason="待拍板：组合键超集（多按的修饰键变体）当前不命中，超集匹配有误伤风险", strict=True)
@pytest.mark.parametrize("keys", [
    ["ctrl", "shift", "w"],   # ctrl+shift+w：浏览器关闭整个窗口
    ["alt", "ctrl", "f4"],    # ctrl+alt+f4：alt+f4 超集
])
def test_bypass_combo_superset(keys):
    assert guard.evaluate("hotkey", {"keys": keys})[0] == "high"


@pytest.mark.xfail(reason="待拍板：非空白字符插入（含标点）需字符级策略，误伤面大", strict=True)
@pytest.mark.parametrize("name", [
    "删x除",                  # 字符插入
    "删、除",                 # 标点插入
])
def test_bypass_char_insertion(name):
    assert guard.evaluate("click_ui_element", {"name": name})[0] == "high"


@pytest.mark.xfail(reason="待拍板：裸关键词无分隔符可归一化，属规则内容调整（加裸词会误伤 reformat 等）", strict=True)
def test_bypass_bare_keyword():
    """裸 "format"（后无任何分隔符）从未命中过——规则 "format " 依赖锚点，
    修复归一化不改变它；需规则内容层面拍板。"""
    assert guard.evaluate("type_text", {"text": "format"})[0] == "high"


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
