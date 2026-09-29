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
import hashlib
import json
import time
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


# ================= wait 工具：上限钳位 + 分段停止（UX-P1-4） =================

def test_wait_clamps_seconds_to_60(monkeypatch):
    """seconds=100000 不许真睡：钳到 WAIT_MAX_SECONDS。

    生产上限是 60 秒（真等 60 秒套件受不了），这里把上限压小验证
    "大输入被钳到上限、而不是按输入睡"这一行为本身。
    """
    monkeypatch.setattr(agent_loop, "WAIT_MAX_SECONDS", 0.05)
    start = time.monotonic()
    result = agent_loop._wait_tool({"seconds": 100000})
    assert time.monotonic() - start < 5
    assert result == "waited 0.05s"


def test_wait_garbage_and_negative_seconds():
    """非法/负数输入不抛异常：非法按 1 秒，负数按 0 秒（立即返回）。"""
    assert agent_loop._wait_tool({"seconds": "abc"}) == "waited 1s"
    assert agent_loop._wait_tool({"seconds": None}) == "waited 1s"
    assert agent_loop._wait_tool({"seconds": -5}) == "waited 0s"


def test_wait_stop_flag_breaks_sleep_quickly():
    """sleep 期间停止标志已置位 → 秒级返回，不等睡满。"""
    start = time.monotonic()
    result = agent_loop._wait_tool({"seconds": 60}, stop_requested=lambda: True)
    assert time.monotonic() - start < 2
    assert "停止" in result


def test_wait_checks_stop_each_segment_not_zero_times():
    """停止标志在第 2 秒才翻转 → 应睡满约 2 秒后返回，证明分段检查真的在跑。"""
    start = time.monotonic()
    flip_at = start + 2.0

    result = agent_loop._wait_tool(
        {"seconds": 60},
        stop_requested=lambda: time.monotonic() >= flip_at)
    elapsed = time.monotonic() - start
    assert elapsed >= 1.9
    assert "停止" in result


def test_execute_tool_wait_honors_agent_stop_flag():
    """接线回归：_execute_tool 必须把 self 的停止标志传给 wait（防止特判被删）。"""
    agent = DesktopAgent()
    agent._stop_requested = True
    start = time.monotonic()
    result = agent._execute_tool("wait", {"seconds": 100000}, "none")
    assert time.monotonic() - start < 2
    assert "停止" in result


# ============ 审计哈希链续链 + 界面失败判定收敛（REL-P1-1 / REL-P1-2） ============

def _chain_verified(entries):
    """全链校验：seq 递增无重复、prev 逐条相接、每条哈希可复算。"""
    prev = ""
    seqs = []
    for e in entries:
        assert e["prev"] == prev
        check = {k: v for k, v in e.items() if k != "hash"}
        digest = hashlib.sha256(json.dumps(
            check, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        assert digest == e["hash"]
        prev = e["hash"]
        seqs.append(e["seq"])
    assert seqs == sorted(set(seqs))   # 递增且无重复
    return seqs


def test_audit_chain_resumes_after_same_day_restart(tmp_path):
    """同日重启续链（REL-P1-1）：写两条 → 重建实例 → 再写一条，全文件
    哈希链校验通过、seq 递增无重复；文件尾损坏时照常续链，但新条目带
    chain_repaired 标记（不静默）。
    修复前：重建实例从 seq=0/prev="" 起链——同日重启后 seq 重复、链断裂，
    防篡改无法区分"重启"与"篡改"。"""
    a = AuditLogger(log_dir=tmp_path)
    a.emit("task_start", task="任务A")
    a.emit("tool_call", tool="click")
    a.close()

    b = AuditLogger(log_dir=tmp_path)   # 重建实例，模拟同日重启
    b.emit("tool_result", tool="click", result="ok")
    b.close()

    entries = _read_audit(tmp_path)
    assert len(entries) == 3
    assert _chain_verified(entries) == [0, 1, 2]      # 修复前：0,1,0

    # 文件尾损坏（篡改行，不带换行尾——即崩溃半行的形态）：原样留在文件，
    # 从最后一条可验证记录续链，下一条如实标记 chain_repaired
    day_file = tmp_path / f"audit-{time.strftime('%Y%m%d')}.jsonl"
    with open(day_file, "a", encoding="utf-8") as f:
        f.write('{"ts": "tampered", "type": "tool_call", "seq": 99}')
    c = AuditLogger(log_dir=tmp_path)
    c.emit("approval", tool="del")
    c.close()

    good = [json.loads(l) for l in day_file.read_text(
        encoding="utf-8").splitlines() if l.strip() and "hash" in json.loads(l)]
    assert len(good) == 4
    assert _chain_verified(good) == [0, 1, 2, 3]      # 损坏行不占用 seq
    assert all("chain_repaired" not in e for e in good[:3])
    assert good[-1]["chain_repaired"] is True


def test_gui_tool_result_judgement_uses_is_failed_result():
    """界面侧失败判定与重试层同源（REL-P1-2）："failed to connect" 不带
    "错误" 前缀，修复前 startswith("错误") 判定漏放——界面打 ✓、重试层
    （is_failed_result）判失败，两套语义；收敛后界面必须同样判负。"""
    from gui import AgentGUI, TaskSession

    app = AgentGUI.__new__(AgentGUI)   # 绕过 __init__：不建 Tk 窗口，只测状态逻辑
    app.active = None                  # 非当前 Tab → 不触碰 chat 控件
    app._log_line = lambda *a, **k: None

    def _apply(result):
        s = TaskSession("判定回归")
        ev = s.add("tool", name="open_app", args={}, state="run",
                   result="", note="", img=None)
        AgentGUI._apply_tool_result(app, s, "open_app", {}, result)
        return ev

    # 文档点名的形态：不带"错误"前缀的失败（修复前在这里打 ✓）
    assert _apply("无法连接模型服务: failed to connect to Ollama")["state"] == "err"
    assert _apply("错误: 未知工具 foo")["state"] == "err"   # 传统前缀形态仍判负
    assert _apply("已打开 记事本")["state"] == "ok"          # 正常结果不误伤
