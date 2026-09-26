"""core/guard + core/approval 安全层回归测试（pytest）。

替代 v1 T10 的场景覆盖思路（拦截 / 放行 / 绕过尝试），
断言目标是现行 API，不依赖 v1 的 SecurityModule 接口。

被测契约：
- guard.evaluate(tool_name, args) -> (risk, reason)，risk ∈ none/medium/high
- guard.is_retryable(tool_name) -> bool
- GuiApprovalBridge：工作线程 decide() 阻塞，主线程 pending()/complete() 放行，
  超时视为拒绝
- AutoDenyPolicy：无界面环境默认全拒

已知缺口（用测试固化当前行为，修复需另行拍板，见 issue #2）：
- hotkey 组合键乱序（["f4","alt"]）不命中关键词 → 绕过
- type_text "format C:" 不命中（规则关键词 "format " 依赖尾随空格）→ 绕过
- click_ui_element 名称插空格（"删 除"）不命中 → 绕过
- evaluate 传入非 dict args 会 AttributeError（未入套件，仅在 issue 报告）
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
    """medium 只分级提示，不得升级为 high 拦截（当前 agent_loop 对 medium 无专门处理）。"""
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


# ==================== 绕过尝试：固化当前行为，暴露已知缺口（修复需拍板） ====================

def test_bypass_reorder_hotkey_not_blocked():
    """已知缺口：组合键乱序 ["f4","alt"] 连接成 "f4+alt"，不命中 "alt+f4"。"""
    assert guard.evaluate("hotkey", {"keys": ["f4", "alt"]}) == ("none", "")


def test_bypass_format_separator_variant():
    """已知缺口：关键词 "format " 依赖空格分隔，制表符/冒号变体不命中（首轮预测 "format C:" 会
    绕过是错的——它 format 后本就有空格，实测正常拦截）。"""
    assert guard.evaluate("type_text", {"text": "format\tC:"}) == ("none", "")
    assert guard.evaluate("type_text", {"text": "format:C:"}) == ("none", "")


def test_bypass_space_injected_button_name():
    """已知缺口：按钮名插空格 "删 除" 不含连续子串 "删除"。"""
    assert guard.evaluate("click_ui_element", {"name": "删 除"}) == ("none", "")


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
