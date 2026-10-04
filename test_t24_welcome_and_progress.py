"""T24 首启引导 + 执行过程可视化回归测试。

六组覆盖（沿用 T23 的离线桩模式，不连模型；渲染组用 withdraw 的真 Tk）：
  1. 首启标志位：welcome_shown 默认 False、置 True 后持久化；
     _maybe_show_welcome 首次弹、二次不弹
  2. 过程事件接线：thought 事件进 events（剥 💭、截 120 字）；
     tool 卡带步骤号；工具结果带人话摘要
  3. result_summary 纯函数各分支（成功动词表 / 未知工具回落 / 失败剥前缀截断）
  4. agent_loop.on_thought：工具轮正文（💭 一句为什么）→ 回调收到；
     空正文不发（不硬凑、不刷屏）
  5. SYSTEM_PROMPT 说话规则在位（💭 格式要求防回归丢失）
  6. 渲染层：thought 卡、tool 卡能建出且文本正确；render_all 重建后
     已完成工具卡的结果行立即带出（修复原先重建后空白）
"""
import json
from types import SimpleNamespace

import pytest

import agent_loop
from agent_loop import DesktopAgent
from core.approval import AutoDenyPolicy
from core.settings import Settings, should_show_onboarding
from ui.formatters import result_summary
from ui.theme import (MSG_INPUT_HINT, PLACEHOLDER, WELCOME_CARD_BUTTON,
                      WELCOME_CARD_HEAD)


# ==================== 桩 ====================

class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))


class FakeChat:
    def __init__(self):
        self.appended = []
        self.refreshed = []

    def append(self, ev):
        self.appended.append(ev)

    def refresh(self, ev):
        self.refreshed.append(ev)


class FakeLogbox:
    def __init__(self):
        self.lines = []

    def configure(self, **kw):
        pass

    def tag_names(self):
        return ()   # T24e：_log_line 走 richtext.insert_rich，先查已配置 tag

    def insert(self, *_a):
        pass

    def see(self, *_a):
        pass


class FakeWelcome:
    """替换真 _show_welcome（不建 Tk 窗口），只记录是否被调"""

    def __init__(self, app):
        self.app = app
        self.calls = 0

    def __call__(self):
        self.calls += 1


def make_shell():
    """跳过 AgentGUI.__init__（不建真 Tk），只铺 _apply 触碰到的属性"""
    import gui
    app = gui.AgentGUI.__new__(gui.AgentGUI)
    app.root = FakeRoot()
    app.settings = {}
    app.logbox = FakeLogbox()
    return app


def fresh_session():
    from ui.sessions import TaskSession
    return TaskSession(title="测试")


# ==================== 1. 首启标志位 ====================

def test_welcome_flag_defaults_false_and_persists(tmp_path):
    """默认没看过引导（False）；点过一次「我知道了」后落盘，永不自动再弹"""
    s = Settings(file_path=tmp_path / "settings.json")
    assert s.get("welcome_shown") is False
    s.set("welcome_shown", True)
    assert Settings(file_path=tmp_path / "settings.json").get(
        "welcome_shown") is True


def test_maybe_show_welcome_first_shows_second_skips(monkeypatch):
    """首启弹一次；welcome_shown=True 后（第二次启动）不再弹"""
    import gui

    def make_app(shown):
        app = gui.AgentGUI.__new__(gui.AgentGUI)
        app.settings = {"welcome_shown": shown}
        stub = FakeWelcome(app)
        monkeypatch.setattr(app, "_show_welcome", stub)
        return app, stub

    app, stub = make_app(False)
    app._maybe_show_welcome()
    assert stub.calls == 1

    app2, stub2 = make_app(True)
    app2._maybe_show_welcome()
    assert stub2.calls == 0


def test_onboarding_choice_still_guards_route_card(monkeypatch):
    """两张卡各管各的标志：欢迎卡标志不影响模型路线卡的状态机判定。
    （环境里若带着云端 Key 会把 should_show_onboarding 判 False，先清掉）"""
    from core.settings import CLOUD_PRESETS
    for p in CLOUD_PRESETS.values():
        monkeypatch.delenv(p["env"], raising=False)
    s = {"onboarding_choice": "dismissed", "cloud": {}}
    assert should_show_onboarding(s, connected=False) is False
    s2 = {"onboarding_choice": "", "cloud": {}}
    assert should_show_onboarding(s2, connected=False) is True


# ==================== 2. 过程事件接线 ====================

def test_apply_thought_strips_prefix_and_truncates():
    """thought 事件：剥 💭 前缀、超长截到 120 字、进对话流"""
    app = make_shell()
    s = fresh_session()
    app.active = s
    app.chat = FakeChat()

    app._apply(s, "thought", "💭 任务需要记事本，先打开它")
    assert len(s.events) == 1
    ev = s.events[0]
    assert ev["kind"] == "thought"
    assert ev["text"] == "任务需要记事本，先打开它"
    assert s.current_action.startswith("💭 ")
    assert app.chat.appended == [ev]

    app._apply(s, "thought", "长" * 300)
    assert len(s.events[1]["text"]) == 120


def test_apply_thought_empty_after_strip_is_dropped():
    """只有 💭 没有正文的摘要不落卡（不刷空卡片）"""
    app = make_shell()
    s = fresh_session()
    app.active = s
    app.chat = FakeChat()
    app._apply(s, "thought", "💭")
    app._apply(s, "thought", "   ")
    assert s.events == []
    assert app.chat.appended == []


def test_tool_card_has_step_number_and_result_summary():
    """工具卡：第 1 步/第 2 步递增；结果落卡时带人话摘要"""
    app = make_shell()
    s = fresh_session()
    app.active = s
    app.chat = FakeChat()

    app._apply(s, "tool_call", ("open_app", {"app_name": "notepad"}))
    app._apply(s, "tool_call", ("type_text", {"text": "你好"}))
    steps = [e["step"] for e in s.events if e["kind"] == "tool"]
    assert steps == [1, 2]

    app._apply(s, "tool_result", ("open_app", {"app_name": "notepad"},
                                  "已打开 记事本"))
    tool_ev = s.events[0]
    assert tool_ev["state"] == "ok"
    assert tool_ev["summary"] == "已打开"
    assert app.chat.refreshed == [tool_ev]


# ==================== 3. result_summary ====================

def test_result_summary_known_tools_map_to_plain_verbs():
    assert result_summary("open_app", "ok", True) == "已打开"
    assert result_summary("open_url", "ok", True) == "已打开"
    assert result_summary("close_app", "ok", True) == "已关闭"
    assert result_summary("screenshot", "已保存", True) == "已截图保存"


def test_result_summary_unknown_tool_falls_back():
    assert result_summary("some_plugin_tool", "ok", True) == "已完成"


def test_result_summary_failure_keeps_reason():
    """失败带原因（引擎报错本就说人话），剥「错误: 」前缀、截 80 字"""
    assert result_summary("focus_window", "错误: 未找到标题包含 a 的窗口",
                          False) == "没成功：未找到标题包含 a 的窗口"
    long = "错误: " + "x" * 200
    out = result_summary("click", long, False)
    assert out.startswith("没成功：")
    assert len(out) <= len("没成功：") + 80


# ==================== 4. agent_loop.on_thought ====================

class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tools):
        return self._responses.pop(0)


class _StubTool:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return "stub ok"


def _tool_call_with_content(content, name, args):
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(args)}}]}


def _final(text="任务完成"):
    return {"role": "assistant", "content": text, "tool_calls": []}


@pytest.fixture
def loop_env(tmp_path, monkeypatch):
    stub = _StubTool()
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS", {"press_key": stub})
    agent = DesktopAgent(llm=None, auditor=None, approval=AutoDenyPolicy())
    thoughts = []
    agent.on_thought = thoughts.append
    agent.on_log = lambda m: None
    return agent, stub, thoughts


def test_on_thought_fires_once_per_tool_turn(loop_env):
    """工具轮正文（💭 一句为什么）→ on_thought 收到；多工具同轮只发一次"""
    agent, stub, thoughts = loop_env
    agent.llm = _FakeLLM([
        _tool_call_with_content("💭 任务需要记事本，先打开它", "press_key",
                                {"key": "enter"}),
        _final(),
    ])
    result = agent.run("回归测试任务")
    assert result == "任务完成"
    assert len(stub.calls) == 1
    assert thoughts == ["💭 任务需要记事本，先打开它"]


def test_on_thought_silent_when_content_empty(loop_env):
    """模型没写摘要（空正文）就不发——不硬凑、不刷屏，工具卡兜底"""
    agent, stub, thoughts = loop_env
    agent.llm = _FakeLLM([
        _tool_call_with_content("", "press_key", {"key": "enter"}),
        _final(),
    ])
    agent.run("回归测试任务")
    assert thoughts == []


def test_on_thought_strips_think_tags(loop_env):
    """思考模型把 <think> 草稿漏进工具轮正文时，摘要只取正文（T28 同源规则）"""
    agent, stub, thoughts = loop_env
    agent.llm = _FakeLLM([
        _tool_call_with_content("<think>内部草稿</think>💭 打开记事本写结果",
                                "press_key", {"key": "enter"}),
        _final(),
    ])
    agent.run("回归测试任务")
    assert thoughts == ["💭 打开记事本写结果"]


# ==================== 5. SYSTEM_PROMPT 说话规则 ====================

def test_system_prompt_has_thought_rule():
    """💭 说话规则在 SYSTEM_PROMPT 里：有格式、有示例、禁术语"""
    p = agent_loop.SYSTEM_PROMPT
    assert "💭" in p
    assert "为什么这么做" in p
    assert "💭 任务需要记事本，先打开它" in p
    assert "不出现工具名" in p


def test_placeholder_and_hint_copy_in_place():
    """输入框提示文案与小字（T24 任务 3）不回归丢失"""
    assert "打开记事本" in PLACEHOLDER
    assert "我能帮你操作电脑" in MSG_INPUT_HINT
    assert WELCOME_CARD_HEAD.startswith("👋")
    assert "我知道了" in WELCOME_CARD_BUTTON


# ==================== 6. 渲染层（真 Tk，withdraw 不弹窗） ====================

@pytest.fixture(scope="module")
def tk_env(ctk_root):
    """会话级共享 CTk 实例（conftest.ctk_root）：同进程反复建/销毁 Tk
    解释器不稳定（init.tcl source 偶发失败），全测试会话只建一次。"""
    return ctk_root


def _all_text(container):
    """递归收集容器里所有带 text 选项控件的文本（不依赖 CTk 内部类名）；
    T24e 扩展起工具卡结果行是 tk.Text（无 text 选项），改读其内容区"""
    import tkinter as tkbase
    texts = []
    for w in container.winfo_children():
        if isinstance(w, tkbase.Text):
            texts.append(w.get("1.0", "end").rstrip("\n"))
        else:
            try:
                texts.append(str(w.cget("text")))
            except Exception:
                pass   # frame 类控件没有 text，跳过继续下钻
        texts.extend(_all_text(w))
    return texts


def test_thought_card_renders_plain_text(tk_env):
    from ui.chat_stream import ChatStream
    ctk, root = tk_env
    app = SimpleNamespace(root=None, settings={})
    cs = ChatStream(root, app)
    cs.append({"kind": "thought", "text": "任务需要记事本，先打开它"},
              scroll=False)
    joined = "\n".join(_all_text(cs.frame))
    assert "💭 任务需要记事本，先打开它" in joined


def test_tool_card_renders_step_head_and_summary_after_refresh(tk_env):
    from ui.chat_stream import ChatStream
    ctk, root = tk_env
    app = SimpleNamespace(root=None, settings={})
    cs = ChatStream(root, app)
    ev = {"kind": "tool", "name": "open_app", "args": {"app_name": "notepad"},
          "state": "run", "result": "", "note": "", "img": None, "step": 2}
    cs.append(ev, scroll=False)
    assert "第 2 步" in "\n".join(_all_text(cs.frame))       # 步骤号在头上
    assert "参数：" not in "\n".join(_all_text(cs.frame))     # 技术参数不再上卡

    ev.update(state="ok", result="已打开 记事本", summary="已打开")
    cs.refresh(ev)
    assert "✓ 已打开" in "\n".join(_all_text(cs.frame))      # 人话摘要上卡
    assert "已打开 记事本" not in "\n".join(_all_text(cs.frame))  # 原文不直出


def test_render_all_rebuild_keeps_finished_result_visible(tk_env):
    """切 Tab 回来重建卡片：已完成工具卡的结果行立即带出（原先空白）"""
    from ui.chat_stream import ChatStream
    ctk, root = tk_env
    app = SimpleNamespace(root=None, settings={})
    s = fresh_session()
    s.events.append({"kind": "tool", "name": "open_app",
                     "args": {"app_name": "notepad"}, "state": "ok",
                     "result": "已打开 记事本", "summary": "已打开",
                     "note": "", "img": None, "step": 1})
    cs = ChatStream(root, app)
    cs.render_all(s)
    assert "✓ 已打开" in "\n".join(_all_text(cs.frame))
