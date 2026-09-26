"""agent_loop 对 guard 分级的处理路径回归测试（issue #2：medium 落地验证）。

用假 LLM（沿用 test_early_stop.py 的 mock 模式）+ 桩工具注册表驱动
DesktopAgent._run_loop，验证三条分级路径互不等价：

- high  ：走 approval（AutoDenyPolicy 下被拒），工具不执行
- medium：不拦截、工具正常执行，但触发 medium_risk 审计事件
          + "[敏感操作]" 界面提示行
- none  ：静默执行，无 medium_risk 事件、无提示行

修复前行为：agent_loop 只处理 risk == "high"，medium 与 none 完全等价
（无审计事件、无提示，静默执行）。
"""
import json
from pathlib import Path

import pytest

import agent_loop
from agent_loop import DesktopAgent
from core.audit import AuditLogger
from core.approval import AutoDenyPolicy


class _FakeLLM:
    """按序返回预设响应的最小 LLM 桩"""

    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tools):
        return self._responses.pop(0)


class _StubTool:
    """记录调用参数的工具桩"""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return "stub ok"


def _tool_call(call_id, name, args):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(args)}}]}


def _final(text="任务完成"):
    return {"role": "assistant", "content": text, "tool_calls": []}


def _read_audit(log_dir: Path):
    entries = []
    for f in log_dir.glob("audit-*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


@pytest.fixture
def env(tmp_path, monkeypatch):
    """桩工具注册表 + 桩动作后校验（避免读写真实剪贴板/屏幕）"""
    stub = _StubTool()
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"clipboard_write": stub, "press_key": stub})
    monkeypatch.setattr(agent_loop.core_verify, "verify_clipboard",
                        lambda text: (True, "stub"))
    logs = []
    auditor = AuditLogger(log_dir=tmp_path)
    agent = DesktopAgent(llm=None, auditor=auditor, approval=AutoDenyPolicy())
    agent.on_log = logs.append
    return agent, stub, logs, tmp_path


def _run(agent, responses):
    agent.llm = _FakeLLM(responses)
    return agent.run("回归测试任务")


def test_medium_executes_with_audit_and_hint(env):
    """medium 命中：照常执行（不拦截），但必须留下审计事件 + 界面提示。
    修复前：与 none 等价——静默执行，无 medium_risk 事件、无提示行。"""
    agent, stub, logs, tmp_path = env
    result = _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "my password is 123"}),
        _final(),
    ])
    assert len(stub.calls) == 1                       # 不拦截：确实执行了
    assert result == "任务完成"
    assert any("[敏感操作]" in m and "clipboard_write" in m for m in logs)
    entries = _read_audit(tmp_path)
    medium = [e for e in entries if e["type"] == "medium_risk"]
    assert len(medium) == 1
    assert medium[0]["tool"] == "clipboard_write"
    assert "敏感词" in medium[0]["reason"]


def test_none_stays_silent(env):
    """对照组：none（无敏感词）不产生 medium_risk 事件、无提示行。"""
    agent, stub, logs, tmp_path = env
    _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "hello world"}),
        _final(),
    ])
    assert len(stub.calls) == 1
    assert not any("敏感操作" in m for m in logs)
    assert not any(e["type"] == "medium_risk"
                   for e in _read_audit(tmp_path))


def test_high_goes_to_approval_and_denied(env):
    """对照组：high 仍走 approval；AutoDenyPolicy 下被拒，工具不执行。
    medium 分支不得把 high 的行为改掉。"""
    agent, stub, logs, tmp_path = env
    _run(agent, [
        _tool_call("c1", "press_key", {"key": "delete"}),
        _final(),
    ])
    assert stub.calls == []                           # 被拒：未执行
    assert any("[拦截]" in m for m in logs)
    entries = _read_audit(tmp_path)
    approval = [e for e in entries if e["type"] == "approval"]
    assert len(approval) == 1 and approval[0]["allowed"] is False
    assert not any(e["type"] == "medium_risk" for e in entries)


def test_medium_without_auditor_still_executes(env, monkeypatch):
    """无审计注入时 medium 不应报错：降级为仅界面提示，操作照常。"""
    agent, stub, logs, _ = env
    monkeypatch.setattr(agent, "auditor", None)
    result = _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "我的密码"}),
        _final(),
    ])
    assert len(stub.calls) == 1
    assert result == "任务完成"
    assert any("[敏感操作]" in m for m in logs)
