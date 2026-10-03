"""T22 任务收尾智能关闭回归测试。

三块机制，全部离线（不开真窗口、不连模型、mock 全部走 monkeypatch 自动还原）：
  1. open_app / open_url 打开成功时把 (type, name, reason, purpose, hwnd,
     opened_at) 记进本任务记录；reason 缺省/含糊归一为 unknown / 临时工具 /
     结果载体；不注入记录表时行为与旧版完全一致（向后兼容）
  2. close_app 白名单 + 记录双重校验：白名单外拒绝；不是本任务打开的窗口
     拒绝（用户自己开的窗口天然保留）；窗口已不在返回非失败文案（不触发重试）
  3. DesktopAgent.run 每任务复位记录；_execute_tool 全管道注入记录表
"""
import pytest

import agent_loop
from agent_loop import DesktopAgent
from core.retry import is_failed_result, is_permanent_failure


class _LLM:
    """假模型：直接给最终答复，让 run() 走完生命周期"""

    def chat(self, messages, tools=None):
        return {"role": "assistant", "content": "好的",
                "tool_calls": [], "_usage": {}}


def _fake_startfile(monkeypatch):
    """拦截 os.startfile（全局 os 模块属性，monkeypatch 自动还原）并抹掉真实 sleep"""
    launched = []

    def fake_startfile(what):
        launched.append(str(what))

    monkeypatch.setattr(agent_loop.os, "startfile", fake_startfile)
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    return launched


# ==================== 1. 打开记录 ====================

def test_open_app_records_entry(monkeypatch):
    launched = _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 4321)
    record = []
    args = {"app_name": "calc", "reason": "临时工具",
            "purpose": "计算 345×12", "_agent_opened": record}
    out = agent_loop.TOOL_FUNCTIONS["open_app"](args)
    assert out == "opened calc"
    assert launched == ["calc.exe"]
    assert "_agent_opened" not in args  # 搭载键在工具入口被取走，不外泄
    assert len(record) == 1
    entry = record[0]
    assert entry["type"] == "app"
    assert entry["name"] == "calc"
    assert entry["reason"] == "临时工具"
    assert entry["purpose"] == "计算 345×12"
    assert entry["hwnd"] == 4321
    assert entry["exe"] == "calc.exe"
    assert isinstance(entry["opened_at"], float)


def test_open_app_without_record_unchanged(monkeypatch):
    """不注入记录表（旧式直调）：行为与 T22 之前完全一致，且不报错"""
    launched = _fake_startfile(monkeypatch)
    out = agent_loop.TOOL_FUNCTIONS["open_app"]({"app_name": "calc"})
    assert out == "opened calc"
    assert launched == ["calc.exe"]


def test_open_app_reject_outside_whitelist_still_works(monkeypatch):
    """白名单拒绝文案不变（T6 既有契约），且不产生记录"""
    out = agent_loop.TOOL_FUNCTIONS["open_app"](
        {"app_name": "chrome", "_agent_opened": []})
    assert "仅支持" in out
    assert is_permanent_failure(out)


def test_open_url_records_entry(monkeypatch):
    _fake_startfile(monkeypatch)
    record = []
    out = agent_loop.TOOL_FUNCTIONS["open_url"](
        {"url": "https://www.baidu.com/s?wd=天气", "reason": "结果载体",
         "purpose": "给用户看天气", "_agent_opened": record})
    assert "opened in default browser" in out
    assert len(record) == 1
    entry = record[0]
    assert entry["type"] == "url"
    assert entry["name"] == "https://www.baidu.com/s?wd=天气"
    assert entry["reason"] == "结果载体"
    assert entry["hwnd"] == 0  # 网页在既有浏览器窗口开新 tab，无法归属 hwnd


def test_reason_defaults_and_normalization(monkeypatch):
    _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 0)
    record = []
    agent_loop.TOOL_FUNCTIONS["open_app"]({"app_name": "calc",
                                           "_agent_opened": record})
    assert record[0]["reason"] == "unknown"  # 忘记录 reason → 保守保留
    record2 = []
    agent_loop.TOOL_FUNCTIONS["open_app"]({"app_name": "calc",
                                           "reason": "临时用一下",
                                           "_agent_opened": record2})
    assert record2[0]["reason"] == "临时工具"
    record3 = []
    agent_loop.TOOL_FUNCTIONS["open_url"]({"url": "https://www.baidu.com",
                                           "reason": "给用户看的结果",
                                           "_agent_opened": record3})
    assert record3[0]["reason"] == "结果载体"
    record4 = []
    agent_loop.TOOL_FUNCTIONS["open_url"]({"url": "https://www.baidu.com",
                                           "reason": "模型自由发挥的话",
                                           "_agent_opened": record4})
    assert record4[0]["reason"] == "unknown"


# ==================== 2. close_app 校验与关闭 ====================

def _calc_entry(hwnd=777):
    return {"type": "app", "name": "calc", "reason": "临时工具",
            "purpose": "计算 345×12", "hwnd": hwnd,
            "exe": "calc.exe", "opened_at": 0.0}


def test_close_app_rejects_non_whitelist():
    """白名单外的应用（浏览器等结果载体）拒绝关闭，且为确定性失败"""
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "chrome", "_agent_opened": [_calc_entry()]})
    assert "不支持" in out
    assert is_permanent_failure(out)


def test_close_app_never_touches_windows_agent_did_not_open(monkeypatch):
    """记录为空：即使指定 calc 也绝不按进程名全局扫窗关闭（用户窗口天然保留）"""
    closed = []
    monkeypatch.setattr(agent_loop, "_close_window", lambda h: closed.append(h))
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "calc", "_agent_opened": []})
    assert closed == []
    assert "找不到窗口" in out
    assert is_permanent_failure(out)


def test_close_app_closes_recorded_window(monkeypatch):
    """按记录关窗：UWP 宿主进程（applicationframehost）经标题词校验放行"""
    closed = []
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: h not in closed)
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "applicationframehost.exe")
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "计算器")
    monkeypatch.setattr(agent_loop, "_close_window", lambda h: closed.append(h))
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "calc", "_agent_opened": [_calc_entry()]})
    assert closed == [777]
    assert "已关闭" in out


def test_close_app_hwnd_priority_and_record_guard(monkeypatch):
    """hwnd 优先走精确关窗；hwnd 不在记录里一律拒绝（不误关用户窗口）"""
    closed = []
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "calc.exe")
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "计算器")
    monkeypatch.setattr(agent_loop, "_close_window", lambda h: closed.append(h))
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"hwnd": 777, "_agent_opened": [_calc_entry()]})
    assert closed == [777]
    closed.clear()
    out2 = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"hwnd": 12345, "_agent_opened": [_calc_entry()]})
    assert closed == []
    assert "不支持" in out2


def test_close_app_reports_already_gone(monkeypatch):
    """Agent 开的窗已被关掉：如实回报，不算失败（不触发模型重试）"""
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: False)
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "calc", "_agent_opened": [_calc_entry()]})
    assert "无需处理" in out
    assert not is_failed_result(out)


def test_close_app_rejects_when_window_identity_changed(monkeypatch):
    """hwnd 被系统复用给别的窗口（标题/进程都对不上）：拒绝关闭"""
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "explorer.exe")
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "文件资源管理器")
    closed = []
    monkeypatch.setattr(agent_loop, "_close_window", lambda h: closed.append(h))
    out = agent_loop.TOOL_FUNCTIONS["close_app"](
        {"app_name": "calc", "_agent_opened": [_calc_entry()]})
    assert closed == []
    assert "找不到窗口" in out


def test_close_app_requires_param():
    out = agent_loop.TOOL_FUNCTIONS["close_app"]({"_agent_opened": []})
    assert "不支持" in out


# ==================== 3. 任务生命周期与管道 ====================

def test_run_resets_record_per_task():
    agent = DesktopAgent(llm=_LLM())
    agent._agent_opened.append(_calc_entry())
    result = agent.run("测试收尾")
    assert result == "好的"
    assert agent._agent_opened == []  # 逐任务复位（CLI 复用实例场景）


def test_execute_tool_pipeline_open_then_close(monkeypatch):
    """管道级：_execute_tool 注入记录 → open_app 记下 hwnd → close_app 用它关"""
    _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 888)
    monkeypatch.setattr(agent_loop.core_verify, "verify_open_app",
                        lambda name, **kw: (True, "窗口已出现"))
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: h not in closed)
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "calc.exe")
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "计算器")
    closed = []
    monkeypatch.setattr(agent_loop, "_close_window", lambda h: closed.append(h))
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    agent = DesktopAgent(llm=_LLM())
    r1 = agent._execute_tool("open_app", {"app_name": "calc",
                                          "reason": "临时工具",
                                          "purpose": "算数"}, "none")
    assert r1.startswith("opened")
    assert len(agent._agent_opened) == 1
    r2 = agent._execute_tool("close_app", {"app_name": "calc"}, "none")
    assert closed == [888]
    assert "已关闭" in r2


def test_system_prompt_documents_cleanup_rules():
    assert "打开软件时的记录规则" in agent_loop.SYSTEM_PROMPT
    assert "任务收尾规则" in agent_loop.SYSTEM_PROMPT
    assert "临时工具" in agent_loop.SYSTEM_PROMPT
    assert "结果载体" in agent_loop.SYSTEM_PROMPT
    names = {t["function"]["name"] for t in agent_loop.TOOLS_SCHEMA}
    assert "close_app" in names
    open_app_schema = next(t for t in agent_loop.TOOLS_SCHEMA
                           if t["function"]["name"] == "open_app")
    props = open_app_schema["function"]["parameters"]["properties"]
    assert "reason" in props and "purpose" in props
