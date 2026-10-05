"""T30：type_text 焦点校验 + verify_open_app 差集 回归测试。

实录背景（2026-10-05 早上）：用户自己的记事本（3 个标签、含未保存文件）在前台，
Agent 跑"打开记事本，输入 你好"——open_app 拉起的新窗口没抢到前台
（2026-10-03 已知实测：后台进程 startfile 拉起的应用不抢前台），type_text
盲粘 Ctrl+V，"你好"进了用户自己的文件且任务报成功；audit 全程只有一次
type_text 调用（哈希链完整），证明不是模型连点，是工具层无目标校验。
同一机制也解释了此前"无标题记事本里累积 5 份你好"：多次任务的盲粘
全落进当时前台的同一个残留窗口。

两个修复各对应一组用例：
- type_text 粘贴前焦点校验：前台≠目标 → 拒粘（一次都不许碰剪贴板/键盘）；
  前台=目标 → 正常粘贴；目标窗口已关闭 → 拒粘；无锚定 → 维持原行为但回显
  必须报出接收窗口。
- verify_open_app 差集：调用方传入动作前窗口标题快照后，只有"新出现的"
  命中窗口才算打开成功——用户已开的同名窗口不得再算数（修复前假阳性）。
"""
import sys

import agent_loop
from core import verify as core_verify
# 复用 agent_loop 回归测试的假 LLM 驱动与工具调用构造器（同一套 env 夹具语义）
from test_agent_loop_guard import _final, _run, _tool_call, env  # noqa: F401


class _FakeClip:
    """pyperclip 桩：记录 copy 调用，不碰真实剪贴板"""

    def __init__(self, touched):
        self._touched = touched

    def copy(self, text):
        self._touched.append(("copy", text))


# ==================== type_text：粘贴前焦点校验 ====================

def test_type_text_refuses_when_foreground_is_not_target(monkeypatch):
    """前台不是目标窗口：必须拒粘——剪贴板与键盘一次都不能被碰。

    修复前行为：不看前台直接 Ctrl+V，"你好"进了用户自己的文档（2026-10-05 实录）。
    """
    touched = []
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (False, "用户的记事本"),
                        raising=False)
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "目标窗口")
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey",
                        lambda *a, **k: touched.append(("hotkey", a)))
    monkeypatch.setitem(sys.modules, "pyperclip", _FakeClip(touched))

    result = agent_loop._type_text_with_space("你好", 0.05, target_hwnd=12345)

    assert "错误: 前台是「用户的记事本」" in result
    assert "不是目标「目标窗口」" in result
    assert "已拒绝输入" in result
    assert touched == [], "拒粘时不得触碰剪贴板或键盘"


def test_type_text_pastes_when_foreground_matches_target(monkeypatch):
    """前台确认是目标窗口：正常粘贴，返回空串（工具层照常拼回显）"""
    touched = []
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (True, "无标题 - 记事本"),
                        raising=False)
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey",
                        lambda *a, **k: touched.append(("hotkey", a)))
    monkeypatch.setitem(sys.modules, "pyperclip", _FakeClip(touched))

    result = agent_loop._type_text_with_space("你好", 0.05, target_hwnd=777)

    assert result == ""
    assert ("copy", "你好") in touched and ("hotkey", ("ctrl", "v")) in touched


def test_type_text_refuses_when_target_window_gone(monkeypatch):
    """目标窗口已关闭：拒粘，不碰任何输入设备（防粘进无辜的前台窗口）"""
    touched = []
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: False)
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey",
                        lambda *a, **k: touched.append(("hotkey", a)))

    result = agent_loop._type_text_with_space("hi", 0.05, target_hwnd=999)

    assert "错误" in result and "已拒绝输入" in result
    assert touched == []


def test_latest_app_hwnd_picks_last_alive_entry():
    """锚定 hwnd 取 T22 开窗记录里最近一个成功抓到窗口的 app 条目"""
    record = [{"type": "app", "hwnd": 111}, {"type": "url"},
              {"type": "app", "hwnd": 0}, {"type": "app", "hwnd": 222}]
    assert agent_loop._latest_app_hwnd(record) == 222
    assert agent_loop._latest_app_hwnd([]) == 0
    assert agent_loop._latest_app_hwnd(None) == 0
    assert agent_loop._latest_app_hwnd([{"type": "app", "hwnd": 0}]) == 0


# ==================== type_text：工具入口与回显 ====================

def test_type_text_tool_echo_names_receiving_window(monkeypatch):
    """成功回显必须带上接收窗口标题——模型据此能发现粘错目标（发现 G 教训：
    错误信息要给模型可行动的细节，而不是一句"失败了"）"""
    monkeypatch.setattr(agent_loop, "_latest_app_hwnd", lambda record: 777,
                        raising=False)
    monkeypatch.setattr(agent_loop, "_type_text_with_space",
                        lambda text, interval, target_hwnd=0: "")
    monkeypatch.setattr(agent_loop, "_foreground_title",
                        lambda: "无标题 - 记事本", raising=False)

    out = agent_loop.TOOL_FUNCTIONS["type_text"]({"text": "hi"})

    assert "typed: hi" in out and "已完整输入" in out
    assert "已输入到「无标题 - 记事本」" in out


def test_type_text_tool_refusal_short_circuits_echo(monkeypatch):
    """拒粘时错误信息直接作为工具结果，不得再拼"已完整输入"回显（防误导）"""
    monkeypatch.setattr(agent_loop, "_latest_app_hwnd", lambda record: 777,
                        raising=False)
    monkeypatch.setattr(agent_loop, "_type_text_with_space",
                        lambda text, interval, target_hwnd=0:
                            "错误: 前台是「A」，不是目标「B」，已拒绝输入（不盲粘）")

    out = agent_loop.TOOL_FUNCTIONS["type_text"]({"text": "hi"})

    assert out.startswith("错误:")
    assert "typed:" not in out and "已完整输入" not in out


def test_type_text_without_target_keeps_legacy_echo(monkeypatch):
    """无锚定（本任务没成功 open_app 过，如开始菜单敲字流程）：维持原行为
    可输入，但回显同样报出接收窗口——输入去向始终可见"""
    monkeypatch.setattr(agent_loop, "_type_text_with_space",
                        lambda text, interval, target_hwnd=0: "")
    monkeypatch.setattr(agent_loop, "_foreground_title",
                        lambda: "开始菜单", raising=False)

    out = agent_loop.TOOL_FUNCTIONS["type_text"]({"text": "345"})

    assert "typed: 345" in out and "已完整输入" in out
    assert "已输入到「开始菜单」" in out


def test_dispatch_carries_open_record_for_type_text(env, monkeypatch):
    """dispatch 必须把 T22 开窗记录搭载给 type_text（同 open_app/close_app），
    否则工具层拿不到锚定 hwnd"""
    agent, _stub, _logs, _tmp_path = env
    seen = {}
    monkeypatch.setitem(agent_loop.TOOL_FUNCTIONS, "type_text",
                        lambda args: seen.update(args) or "ok")
    agent._agent_opened = [{"type": "app", "hwnd": 42}]
    _run(agent, [
        _tool_call("t1", "type_text", {"text": "hi"}),
        _final(),
    ])
    assert seen.get("_agent_opened") is agent._agent_opened


# ==================== verify_open_app：差集校验 ====================

def test_verify_open_app_diff_ignores_preexisting_window(monkeypatch):
    """用户已开的记事本不能让校验假阳性：没有新窗口出现 → 判失败。

    修复前行为：只查"屏幕上有没有记事本"——用户已开的窗口直接让校验通过
    （2026-10-05 实录：新窗口根本没出现，校验照样报"窗口已出现"）。
    """
    monkeypatch.setattr(core_verify, "_enum_visible_windows",
                        lambda: [(111, "*你好 - 记事本"),
                                 (222, "免费部署网站 - 记事本")])

    ok, detail = core_verify.verify_open_app(
        "notepad", pre_windows=[(111, "*你好 - 记事本"),
                                (222, "免费部署网站 - 记事本")])

    assert ok is False
    assert "新窗口" in detail


def test_verify_open_app_diff_accepts_new_window(monkeypatch):
    """快照之外新出现的命中窗口 → 判成功"""
    monkeypatch.setattr(core_verify, "_enum_visible_windows",
                        lambda: [(111, "*你好 - 记事本"),
                                 (333, "无标题 - 记事本")])

    ok, detail = core_verify.verify_open_app(
        "notepad", pre_windows=[(111, "*你好 - 记事本")])

    assert ok is True
    assert detail == "新窗口已出现"


def test_verify_open_app_diff_counts_same_title_new_hwnd(monkeypatch):
    """同名标题的新 hwnd（记事本都叫"无标题 - 记事本"）必须认出是新窗口"""
    monkeypatch.setattr(core_verify, "_enum_visible_windows",
                        lambda: [(111, "无标题 - 记事本"),
                                 (222, "无标题 - 记事本")])

    ok, _ = core_verify.verify_open_app(
        "notepad", pre_windows=[(111, "无标题 - 记事本")])

    assert ok is True


def test_verify_open_app_diff_ignores_title_mutation_of_old_window(monkeypatch):
    """已有窗口的标题变化（记事本 * 未保存标记是异步刷新的）不得被当成
    新窗口——2026-10-05 手动验证实测：按标题差集会假阳性，必须按 hwnd 差集"""
    monkeypatch.setattr(core_verify, "_enum_visible_windows",
                        lambda: [(111, "无标题 - 记事本"),
                                 (111, "*无标题 - 记事本")])  # 同 hwnd 标题变了

    ok, detail = core_verify.verify_open_app(
        "notepad", pre_windows=[(111, "无标题 - 记事本")])

    assert ok is False
    assert "新窗口" in detail


def test_verify_open_app_no_snapshot_keeps_legacy_behavior(monkeypatch):
    """对照组：不传快照（旧调用方/直调）保持原存在性检查，老测试不受影响"""
    monkeypatch.setattr(core_verify, "_window_titles",
                        lambda: ["*你好 - 记事本"])

    ok, detail = core_verify.verify_open_app("notepad")

    assert ok is True
    assert detail == "窗口已出现"


def test_verify_open_app_diff_polls_until_new_window(monkeypatch):
    """差集路径同样要轮询等待（发现 G②：冷启动窗口晚到不假阴性）"""
    seq = [[], [], [(333, "无标题 - 记事本")]]
    monkeypatch.setattr(core_verify, "_enum_visible_windows",
                        lambda: seq.pop(0) if len(seq) > 1 else seq[0])
    monkeypatch.setattr(core_verify.time, "sleep", lambda s: None)

    ok, _ = core_verify.verify_open_app("notepad", pre_windows=[])

    assert ok is True


def test_open_app_verify_receives_pre_snapshot(env, monkeypatch):
    """dispatch 侧：open_app 执行前必须取窗口快照，并传给动作后校验"""
    agent, _stub, _logs, _tmp_path = env
    seen = {}
    monkeypatch.setitem(agent_loop.TOOL_FUNCTIONS, "open_app",
                        lambda args: "opened notepad")
    monkeypatch.setattr(agent_loop.core_verify, "snapshot_windows",
                        lambda: [(111, "打开前的窗口")], raising=False)
    monkeypatch.setattr(agent_loop.core_verify, "verify_open_app",
                        lambda app_name, attempts=4, interval=1.0, pre_windows=None:
                        seen.update(app=app_name, pre=pre_windows) or (True, "ok"))

    _run(agent, [
        _tool_call("o1", "open_app",
                   {"app_name": "notepad", "reason": "结果载体",
                    "purpose": "测试"}),
        _final(),
    ])

    assert seen["pre"] == [(111, "打开前的窗口")]
    assert seen["app"] == "notepad"
