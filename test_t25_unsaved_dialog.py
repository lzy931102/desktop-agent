"""T25 close_app 处理「未保存」对话框回归测试。

背景（2026-10-04 用户实测）：记事本输入"你好"后收尾 close_app，WM_CLOSE
弹出「是否保存」对话框，Agent 不认识，反复尝试关闭空转 59 秒。

四块机制，全部离线（不开真窗口、不连模型、mock 全走 monkeypatch 自动还原）：
  1. 对话框识别：按钮文本分类（保存/不保存/取消、带助记符、英文）+
     Win32 顶层属主对话框组合查找 + UIA（Win11 记事本 XAML 内容对话框）
     组合查找 + 两层顺序（Win32 命中不再跑 UIA）
  2. 决策：unsaved=save/discard 点对应按钮后关窗；缺省/不确定 → 点
     「取消」收起提示、窗口保留（交用户决定，不算失败）
  3. 防空转：同一窗口关闭结束时仍活着即计数，2 次未成功 → 硬停止并
     永久放弃；放弃后再调直接拒绝，连 WM_CLOSE 都不再发
  4. System Prompt / TOOLS_SCHEMA 契约：任务书三条规则在案、
     unsaved 参数在案
"""
import pytest

import agent_loop
from core.retry import is_failed_result


HWND = 777


def _notepad_entry(hwnd=HWND):
    return {"type": "app", "name": "notepad", "reason": "临时工具",
            "purpose": "输入你好", "hwnd": hwnd,
            "exe": "notepad.exe", "opened_at": 0.0}


class _FakeBtn:
    """UIA 层假按钮 wrapper：记录 invoke / click_input 是否被调"""

    def __init__(self, text, visible=True, fail_invoke=False):
        self._text = text
        self._visible = visible
        self._fail_invoke = fail_invoke
        self.invoked = False
        self.clicked_input = False

    def window_text(self):
        return self._text

    class _Rect:
        left = top = 0
        right = bottom = 10

        @staticmethod
        def width():
            return 10

        @staticmethod
        def height():
            return 10

    def rectangle(self):
        return self._Rect() if self._visible else type("R", (), {
            "width": staticmethod(lambda: 0),
            "height": staticmethod(lambda: 0)})

    def invoke(self):
        if self._fail_invoke:
            raise RuntimeError("invoke pattern not supported")
        self.invoked = True

    def click_input(self):
        self.clicked_input = True


def _mock_close_env(monkeypatch, alive=lambda h: True,
                    dialog_buttons=None, win32_buttons=None,
                    uia_buttons=None):
    """搭好 _close_app 的离线环境；返回 (closed, clicks) 记录器。

    dialog_buttons：_find_save_dialog_buttons 的替身返回值（None=走两层
    真函数→由 win32_buttons/uia_buttons 替身决定）。
    """
    closed = []

    monkeypatch.setattr(agent_loop, "_window_alive", alive)
    monkeypatch.setattr(agent_loop, "_close_window",
                        lambda h: closed.append(h))
    monkeypatch.setattr(agent_loop, "_window_process_exe",
                        lambda h: "notepad.exe")
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "无标题 - 记事本")
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    if dialog_buttons is not None:
        monkeypatch.setattr(agent_loop, "_find_save_dialog_buttons",
                            lambda owner: dialog_buttons)
    else:
        monkeypatch.setattr(agent_loop, "_owned_dialog_buttons",
                            lambda owner: win32_buttons or {})
        monkeypatch.setattr(agent_loop, "_save_dialog_buttons_uia",
                            lambda owner: uia_buttons or {})
    return closed


# ==================== 1. 对话框识别 ====================

def test_button_text_classification():
    """按钮文本三分类：中英、带助记符、无关文本不误认"""
    f = agent_loop._classify_button_text
    assert f("保存") == "save"
    assert f("保存(S)") == "save"
    assert f("Save") == "save"
    assert f("不保存") == "discard"
    assert f("不保存(N)") == "discard"
    assert f("Don't Save") == "discard"
    assert f("Don't save") == "discard"
    assert f("取消") == "cancel"
    assert f("Cancel") == "cancel"
    assert f("关闭") is None      # 标题栏关闭按钮不得误认
    assert f("重试") is None      # 其他对话框按钮不误认
    assert f("") is None
    assert f(None) is None


def test_owned_dialog_buttons_combination():
    """Win32 层：属主对话框内的按钮按文本归位，无关按钮被忽略"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(agent_loop, "_owned_dialog_hwnds",
                            lambda owner: [0xD1])
        monkeypatch.setattr(agent_loop, "_child_buttons",
                            lambda dlg: [(0xB1, "保存(S)"), (0xB2, "重试"),
                                         (0xB3, "不保存(N)"), (0xB4, "取消")])
        out = agent_loop._owned_dialog_buttons(HWND)
        assert set(out) == {"save", "discard", "cancel"}
        out["cancel"]()  # 点击器可调用即可（真实现发 BM_CLICK）
    finally:
        monkeypatch.undo()


def test_owned_dialog_requires_save_or_discard():
    """只有「取消」的对话框（查找/字体等）不认定为保存确认，避免误点"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(agent_loop, "_owned_dialog_hwnds",
                            lambda owner: [0xD1])
        monkeypatch.setattr(agent_loop, "_child_buttons",
                            lambda dlg: [(0xB1, "取消"), (0xB2, "帮助")])
        assert agent_loop._owned_dialog_buttons(HWND) == {}
    finally:
        monkeypatch.undo()


def test_uia_dialog_buttons_combination():
    """UIA 层：主窗口树内可见 Button 按文本归位，不可见的不要"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        buttons = [_FakeBtn("保存"), _FakeBtn("关闭"), _FakeBtn("不保存"),
                   _FakeBtn("取消", visible=False)]
        monkeypatch.setattr(agent_loop, "_pywinauto_window_buttons",
                            lambda owner: buttons)
        out = agent_loop._save_dialog_buttons_uia(HWND)
        assert set(out) == {"save", "discard", "cancel"}
        out["save"]()
        assert buttons[0].invoked          # 「保存」被点
        assert not buttons[1].invoked      # 「关闭」没被点
    finally:
        monkeypatch.undo()


def test_uia_invoke_fallback_click_input():
    """UIA invoke 不支持时降级 click_input（动鼠标），点击不落空"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        btn = _FakeBtn("保存", fail_invoke=True)
        monkeypatch.setattr(agent_loop, "_pywinauto_window_buttons",
                            lambda owner: [btn])
        out = agent_loop._save_dialog_buttons_uia(HWND)
        out["save"]()
        assert btn.clicked_input and not btn.invoked
    finally:
        monkeypatch.undo()


def test_find_dialog_win32_hit_skips_uia():
    """识别顺序：Win32 顶层对话框命中即返回，不再跑 UIA（省 1~2 秒）"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(agent_loop, "_owned_dialog_buttons",
                            lambda owner: {"cancel": lambda: None})
        called = []
        monkeypatch.setattr(agent_loop, "_save_dialog_buttons_uia",
                            lambda owner: called.append(owner))
        out = agent_loop._find_save_dialog_buttons(HWND)
        assert set(out) == {"cancel"}
        assert called == []
    finally:
        monkeypatch.undo()


def test_find_dialog_falls_back_to_uia():
    """识别顺序：无 Win32 顶层对话框（Win11 记事本 XAML 场景）→ 走 UIA"""
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(agent_loop, "_owned_dialog_buttons",
                            lambda owner: {})
        monkeypatch.setattr(agent_loop, "_save_dialog_buttons_uia",
                            lambda owner: {"discard": lambda: None})
        assert set(agent_loop._find_save_dialog_buttons(HWND)) == {"discard"}
    finally:
        monkeypatch.undo()


def test_norm_unsaved_defaults_to_cancel():
    """unsaved 非法/缺失一律归一为 cancel（保守：不确定就交用户）"""
    assert agent_loop._norm_unsaved("save") == "save"
    assert agent_loop._norm_unsaved("DISCARD") == "discard"
    assert agent_loop._norm_unsaved(None) == "cancel"
    assert agent_loop._norm_unsaved("") == "cancel"
    assert agent_loop._norm_unsaved("随便什么") == "cancel"


# ==================== 2. 决策：保存 / 不保存 / 取消 ====================

def test_close_app_save_decision_clicks_save_and_closes(monkeypatch):
    """unsaved=save：点「保存」→ 窗口关闭 → 成功文案"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    closed = []
    buttons = {"save": lambda: (calls.__setitem__("save", 1),
                                closed.append(HWND)),
               "discard": lambda: calls.__setitem__("discard", 1),
               "cancel": lambda: calls.__setitem__("cancel", 1)}
    _mock_close_env(monkeypatch, alive=lambda h: h not in closed,
                    dialog_buttons=buttons)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "save",
         "_agent_opened": [_notepad_entry()]})
    assert calls == {"save": 1, "discard": 0, "cancel": 0}
    assert closed == [HWND]
    assert "已点「保存」" in out and "关闭" in out
    assert not is_failed_result(out)


def test_close_app_discard_decision_clicks_discard(monkeypatch):
    """unsaved=discard（任务没要求保存，如「输入你好」）：点「不保存」"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    closed = []
    buttons = {"save": lambda: calls.__setitem__("save", 1),
               "discard": lambda: (calls.__setitem__("discard", 1),
                                   closed.append(HWND)),
               "cancel": lambda: calls.__setitem__("cancel", 1)}
    _mock_close_env(monkeypatch, alive=lambda h: h not in closed,
                    dialog_buttons=buttons)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "discard",
         "_agent_opened": [_notepad_entry()]})
    assert calls == {"save": 0, "discard": 1, "cancel": 0}
    assert closed == [HWND]
    assert "已点「不保存」" in out and "关闭" in out


def test_close_app_unspecified_keeps_window_and_not_failure(monkeypatch):
    """缺省 unsaved：点「取消」收起提示，窗口保留——交用户决定，不算失败"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    buttons = {"save": lambda: calls.__setitem__("save", 1),
               "discard": lambda: calls.__setitem__("discard", 1),
               "cancel": lambda: calls.__setitem__("cancel", 1)}
    _mock_close_env(monkeypatch, alive=lambda h: True,
                    dialog_buttons=buttons)
    record = [_notepad_entry()]
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})
    assert calls == {"save": 0, "discard": 0, "cancel": 1}
    assert "窗口保留" in out and "手动" in out
    assert not is_failed_result(out)
    assert agent_loop._window_alive(HWND)  # 窗口没被关


def test_close_app_invalid_unsaved_defaults_to_cancel(monkeypatch):
    """unsaved 传了不认识的值：按 cancel 处理（保守），不点保存/不保存"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    buttons = {"save": lambda: calls.__setitem__("save", 1),
               "discard": lambda: calls.__setitem__("discard", 1),
               "cancel": lambda: calls.__setitem__("cancel", 1)}
    _mock_close_env(monkeypatch, alive=lambda h: True,
                    dialog_buttons=buttons)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "我也不知道",
         "_agent_opened": [_notepad_entry()]})
    assert calls == {"save": 0, "discard": 0, "cancel": 1}
    assert "窗口保留" in out


def test_close_app_save_ineffective_counts_failure(monkeypatch):
    """点了「保存」窗口仍未关（如无标题文件弹另存为）：计 1 次失败并说明"""
    calls = {"save": 0}
    buttons = {"save": lambda: calls.__setitem__("save", 1),
               "discard": lambda: None, "cancel": lambda: None}
    _mock_close_env(monkeypatch, alive=lambda h: True,
                    dialog_buttons=buttons)
    record = [_notepad_entry()]
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "save", "_agent_opened": record})
    assert record[0]["close_fails"] == 1
    assert "仍未关闭" in out
    assert "另存为" in out          # 指出可能弹了另存为，别只会重试
    assert is_failed_result(out)


# ==================== 3. 防空转：2 次上限 + 永久放弃 ====================

def test_close_app_no_dialog_failure_counts_and_warns(monkeypatch):
    """无对话框、窗口仍活（旧行为场景）：保留原文案 + 计 1 次失败"""
    _mock_close_env(monkeypatch, alive=lambda h: True, win32_buttons={})
    record = [_notepad_entry()]
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})
    assert record[0]["close_fails"] == 1
    assert "窗口仍在" in out
    assert is_failed_result(out)


def test_close_app_hard_stop_after_two_failures(monkeypatch):
    """同一窗口 2 次未关掉：硬停止——如实报告、要求模型停止尝试"""
    _mock_close_env(monkeypatch, alive=lambda h: True, win32_buttons={})
    record = [_notepad_entry()]
    r1 = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})
    assert "2 次" not in r1                      # 第 1 次还只提醒
    r2 = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})
    assert "错误" in r2
    assert "2 次" in r2
    assert "停止" in r2
    assert "手动" in r2
    assert record[0]["close_fails"] == 2


def test_close_app_gave_up_never_sends_wm_close_again(monkeypatch):
    """放弃后再调：直接拒绝，连 WM_CLOSE 都不再发（物理封死空转）"""
    closed = _mock_close_env(monkeypatch, alive=lambda h: True,
                             win32_buttons={})
    record = [_notepad_entry()]
    for _ in range(2):
        agent_loop.TOOL_FUNCTIONS["close_app"](
            {"app_name": "notepad", "_agent_opened": record})
    closed.clear()
    r3 = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})
    assert closed == []                          # 第三次连 WM_CLOSE 都不发
    assert "错误" in r3
    assert "不要再" in r3 or "停止" in r3


def test_close_app_mixed_failures_also_reach_limit(monkeypatch):
    """失败路径混合（先无对话框失败、再 cancel 保留）同样计入 2 次上限"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    buttons = {"save": lambda: calls.__setitem__("save", 1),
               "discard": lambda: calls.__setitem__("discard", 1),
               "cancel": lambda: calls.__setitem__("cancel", 1)}
    _mock_close_env(monkeypatch, alive=lambda h: True,
                    dialog_buttons=buttons)
    record = [_notepad_entry()]
    agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "save", "_agent_opened": record})
    r2 = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "_agent_opened": record})  # 第二次不传 → cancel
    assert calls["cancel"] == 1                  # cancel 按钮仍点了（收提示）
    assert "2 次" in r2 and "错误" in r2
    assert record[0]["close_fails"] == 2


# ==================== 4. System Prompt / Schema 契约 ====================

def test_system_prompt_documents_unsaved_rules():
    """任务书三条规则在案：按上下文选保存/不保存/取消、2 次上限、完成标准"""
    prompt = agent_loop.SYSTEM_PROMPT
    assert "是否保存" in prompt
    assert "unsaved" in prompt
    assert "2 次" in prompt
    assert "用户要求的事做到了" in prompt


def test_schema_has_unsaved_param():
    """close_app schema 暴露 unsaved 三值参数，默认语义写进描述"""
    schema = next(t for t in agent_loop.TOOLS_SCHEMA
                  if t["function"]["name"] == "close_app")
    props = schema["function"]["parameters"]["properties"]
    assert "unsaved" in props
    assert set(props["unsaved"]["enum"]) == {"save", "discard", "cancel"}


# ==================== 5. T33 数据安全闸：带 * 的记事本不自动关闭 ====================
# 背景（2026-10-05 audit 铁证）：18:48:28/50 两次 close_app discard 显式点
# 「不保存」，把载着用户会话恢复文档的整个窗口销毁。带 * 标题 = 窗口里有
# 未保存内容（可能是用户的旧文档），任何自动关闭都不做，交用户手动处理。

def test_close_app_refuses_star_notepad_no_wm_close(monkeypatch):
    """带 * 的记事本：拒绝自动关闭，连 WM_CLOSE 都不发，不算失败结果"""
    closed = _mock_close_env(monkeypatch, alive=lambda h: True, win32_buttons={})
    monkeypatch.setattr(agent_loop, "_window_title",
                        lambda h: "*你好 - Notepad")
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "discard",
         "_agent_opened": [_notepad_entry()]})
    assert closed == []                          # WM_CLOSE 一次都没发
    assert "不自动关闭" in out and "手动处理" in out
    assert not is_failed_result(out)             # 引导模型上报，不进失败重试
    assert agent_loop._window_alive(HWND)        # 窗口保留


def test_close_app_refuses_restored_flag_even_clean_title(monkeypatch):
    """标题干净但 open 时检出会话恢复（恢复文档在后台标签的盲区）：同样拒绝"""
    closed = _mock_close_env(monkeypatch, alive=lambda h: True, win32_buttons={})
    entry = _notepad_entry()
    entry["restored_session"] = True             # T32 guard 打的标记
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "discard",
         "_agent_opened": [entry]})
    assert closed == []
    assert "不自动关闭" in out


def test_close_app_star_notepad_refuses_save_too(monkeypatch):
    """unsaved=save 同样拒绝：对未保存旧文档点「保存」会弹另存为，也是动用户数据"""
    calls = {"save": 0, "discard": 0, "cancel": 0}
    buttons = {k: (lambda k=k: calls.__setitem__(k, 1)) for k in calls}
    closed = _mock_close_env(monkeypatch, alive=lambda h: True,
                             dialog_buttons=buttons)
    monkeypatch.setattr(agent_loop, "_window_title",
                        lambda h: "*你好 - Notepad")
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "notepad", "unsaved": "save",
         "_agent_opened": [_notepad_entry()]})
    assert closed == [] and calls == {"save": 0, "discard": 0, "cancel": 0}
    assert "不自动关闭" in out


def test_close_app_star_mspaint_still_closes(monkeypatch):
    """范围对照：带 * 的非记事本（画图）不受此闸约束，照常走关闭流程"""
    closed = _mock_close_env(monkeypatch, alive=lambda h: h not in closed,
                             win32_buttons={})
    monkeypatch.setattr(agent_loop, "_window_title",
                        lambda h: "*未命名 - 画图")
    entry = {"type": "app", "name": "mspaint", "reason": "临时工具",
             "purpose": "画图", "hwnd": HWND,
             "exe": "mspaint.exe", "opened_at": 0.0}
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "mspaint", "unsaved": "discard",
         "_agent_opened": [entry]})
    assert closed == [HWND]                      # WM_CLOSE 正常发出
    assert "已关闭" in out                       # 常规关闭路径不受闸影响
