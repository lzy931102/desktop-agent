"""P0 三连修复的回归测试（2026-09-30 晚实跑日志暴露的问题，见 docs/任务修改列表）。

- T7 轮次上限：默认 30、DesktopAgent 可注入、最后 2 轮注入收束提示
- T6 open_url + 确定性失败不重试：白名单/校验类拒绝立即返回，不再白烧 3 次退避
- T8 空回复假成功：模型空回复时 history 状态不得记为 success（0f38d020 实录）

用假 LLM（沿用 test_agent_loop_guard.py 的 mock 模式）驱动 DesktopAgent._run_loop，
不碰真实屏幕/浏览器；open_url 的公网校验用桩 getaddrinfo 保证离线确定性。
"""
import json
from pathlib import Path

import pytest

import agent_loop
from agent_loop import DesktopAgent, _open_url
from core.audit import AuditLogger
from core.history import TaskHistory
from core.retry import run_with_retry
from core.guard import evaluate as guard_evaluate
from core.settings import DEFAULTS, MAX_TURNS, validate_public_url


class _FakeLLM:
    """按序返回预设响应的最小 LLM 桩"""

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
def stub_tools(monkeypatch):
    stub = _StubTool()
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"clipboard_write": stub, "press_key": stub})
    return stub


@pytest.fixture
def no_sleep(monkeypatch):
    """退避重试测试不等真实 1+2+4 秒"""
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    import core.retry as retry_mod
    monkeypatch.setattr(retry_mod.time, "sleep", lambda s: None)


# ---- T7：轮次上限 ----

def test_max_turns_default_is_30():
    assert MAX_TURNS == 30
    assert DEFAULTS["max_turns"] == 30


def test_agent_honors_max_turns_param():
    assert DesktopAgent().max_turns == MAX_TURNS
    assert DesktopAgent(max_turns=5).max_turns == 5
    # 非法值回落默认，不出 0/负数
    assert DesktopAgent(max_turns=0).max_turns == MAX_TURNS


def test_low_turns_hint_injected_before_last_turns(stub_tools):
    """max_turns=3 的任务应收到"还剩 2 轮/1 轮/最后一轮"三轮提示，
    且提示在 LLM 调用前进入对话（模型下一轮就能看见）"""
    agent = DesktopAgent(llm=None, max_turns=3)
    agent.llm = _FakeLLM([
        _tool_call("t1", "clipboard_write", {"text": "a"}),
        _tool_call("t2", "clipboard_write", {"text": "b"}),
        _tool_call("t3", "clipboard_write", {"text": "c"}),
    ])
    result = agent.run("回归：轮次提示")
    assert "最大轮次" in result
    hints = [m for m in agent.messages
             if m.get("role") == "user" and "【系统提示】" in m.get("content", "")]
    assert len(hints) == 3
    assert "还剩 2 轮" in hints[0]["content"]
    assert "还剩 1 轮" in hints[1]["content"]
    assert "最后一轮" in hints[2]["content"]


def test_no_hint_when_turns_are_plentiful(stub_tools):
    """轮次富余（默认 30）时不该提前打扰"""
    agent = DesktopAgent(llm=None)
    agent.llm = _FakeLLM([_tool_call("t1", "clipboard_write", {"text": "a"}),
                          _final()])
    agent.run("回归：无提示")
    hints = [m for m in agent.messages
             if m.get("role") == "user" and "【系统提示】" in m.get("content", "")]
    assert hints == []


# ---- T6：open_url 与确定性失败不重试 ----

@pytest.fixture
def fake_dns(monkeypatch):
    """域名解析桩（服务端请求路径 validate_public_https 的 check_dns=True 用）：
    baidu → 公网；internal.test → 内网；localhost → 环回"""
    import socket as socket_mod

    def fake_getaddrinfo(host, *a, **kw):
        table = {"internal.test": ["10.0.0.5"],
                 "localhost": ["127.0.0.1"],
                 "metadata.google.internal": ["169.254.169.254"]}
        ip = table.get(host, ["93.184.216.34"])[0]
        return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("core.settings.socket.getaddrinfo", fake_getaddrinfo)


def test_validate_public_url_allows_http_rejects_private(fake_dns):
    ok, why = validate_public_url("https://www.baidu.com/", require_https=False)
    assert ok, why
    ok, _ = validate_public_url("http://example.com/page", require_https=False)
    assert ok
    # http 允许、ftp 不允许
    ok, why = validate_public_url("ftp://example.com", require_https=False)
    assert not ok and "http" in why
    # IP 字面量：内网/环回直接拒绝，无需解析
    for bad in ("http://192.168.1.5/", "http://127.0.0.1:8080/",
                "http://169.254.169.254/latest/meta-data/"):
        ok, _ = validate_public_url(bad, require_https=False)
        assert not ok, bad
    # 本地主机名模式直接拒绝（无 DNS 模式下的兜底）
    for bad in ("http://localhost:8080/", "http://router.local/",
                "http://nas.internal/"):
        ok, _ = validate_public_url(bad, require_https=False, check_dns=False)
        assert not ok, bad


def test_browser_open_skips_dns_check_server_path_keeps_it(fake_dns):
    """2026-10-01 实测：系统 DNS 把 github.com 指向 127.0.0.1（拦截策略）而
    浏览器经 DoH/代理可达——浏览器路径不做 DNS 预校验（避免误杀），
    服务端请求路径（云端 API/飞书 webhook）保留 DNS 级校验"""
    # 浏览器路径（check_dns=False）：域名不做本进程解析判定
    ok, why = validate_public_url("http://github.com/trending",
                                  require_https=False, check_dns=False)
    assert ok, why
    # 同一域名走服务端语义（check_dns=True）：解析到内网仍然拒绝
    ok, _ = validate_public_url("http://internal.test/",
                                require_https=False, check_dns=True)
    assert not ok


def test_open_url_rejects_then_opens_public(monkeypatch, fake_dns):
    opened = []
    monkeypatch.setattr(agent_loop.os, "startfile", lambda u: opened.append(u))
    # 字面量内网/环回/本地主机名拒绝且不触发浏览器
    for bad in ("http://192.168.1.5/", "http://localhost:8080/",
                "http://router.local/", "file:///C:/Windows/System32/", ""):
        result = _open_url({"url": bad})
        assert result.startswith("错误"), bad
    assert opened == []
    # 公网域名放行并交给默认浏览器（域名不做本进程 DNS 判定）
    result = _open_url({"url": "https://www.baidu.com/s?wd=weather"})
    assert result.startswith("opened in default browser")
    assert opened == ["https://www.baidu.com/s?wd=weather"]


def test_open_url_risk_is_medium():
    """出网动作按 medium 记录（不拦截不确认），与发飞书同级"""
    risk, reason = guard_evaluate("open_url", {"url": "https://www.baidu.com"})
    assert risk == "medium"
    assert reason


def test_permanent_failure_skips_backoff(no_sleep):
    """白名单拒绝等确定性失败：重试清单内的工具也只执行 1 次"""
    attempts = {"n": 0}

    def always_whitelist_miss():
        attempts["n"] += 1
        return agent_loop._open_app("chrome")

    result, used, ok = run_with_retry(always_whitelist_miss, "open_app",
                                      retryable=True, max_retries=3)
    assert attempts["n"] == 1, "确定性拒绝不该重试"
    assert not ok
    assert "仅支持" in result


def test_transient_failure_still_retries(no_sleep):
    """瞬时失败仍走满退避重试——确认收紧没有误伤重试机制"""
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        return "错误: 窗口未出现"

    _, used, ok = run_with_retry(flaky, "open_app", retryable=True, max_retries=3)
    assert attempts["n"] == 4, "1 次首发 + 3 次重试"
    assert not ok


def test_window_not_found_is_permanent(no_sleep):
    """UIA 助手的"找不到窗口/控件"是确定性失败（2026-10-01 重放实录：
    页面跳转后旧窗口名连续 4 次 UIA 超时、每次约 2 分钟，共烧 8 分钟）"""
    attempts = {"n": 0}

    def stale_window():
        attempts["n"] += 1
        return "错误: 找不到窗口「百度一下，你就知道」。可见窗口有: 今天天气_百度搜索"

    result, used, ok = run_with_retry(stale_window, "list_ui_elements",
                                      retryable=True, max_retries=3)
    assert attempts["n"] == 1
    assert not ok
    assert "找不到窗口" in result


def test_open_app_whitelist_miss_never_retries_end_to_end(tmp_path, no_sleep):
    """端到端：open_app("chrome") 在完整 agent 循环里只产生一次工具调用，
    审计里没有 retry 事件（2026-09-30 晚 12 次无用 retry 的回归保护）"""
    agent = DesktopAgent(llm=None, auditor=AuditLogger(log_dir=tmp_path))
    agent.llm = _FakeLLM([
        _tool_call("t1", "open_app", {"app_name": "chrome"}),
        _final("浏览器打不开，已用其他方式说明"),
    ])
    agent.run("回归：open_app 确定性拒绝")
    entries = _read_audit(tmp_path)
    assert sum(1 for e in entries if e.get("type") == "tool_call") == 1
    assert not [e for e in entries if e.get("type") == "retry"]


def test_system_prompt_forbids_uia_on_browsers():
    """T11 缓解（2026-10-01 重放实录：Chrome 上单次 UIA 调用 121 秒）——
    提示词必须引导模型在浏览器场景绕开 UIA、走视觉路线"""
    prompt = agent_loop.SYSTEM_PROMPT
    assert "浏览器例外" in prompt
    assert "Chrome" in prompt
    assert "禁止" in prompt and "list_ui_elements" in prompt


def test_browser_uia_block():
    """T11 结构性约束：浏览器窗口类直接拒绝 UIA 控件操作。2026-10-01 重放实测
    glm-4-flash 两度无视提示词与工具描述（150 秒/次 × 5），软引导不够——
    在 agent_vision 助手层硬拦，把 150 秒浪费变成一条即时错误"""
    from agent_vision import _browser_uia_block

    class _W:
        def __init__(self, cls):
            self._cls = cls

        def class_name(self):
            return self._cls

    for browser_cls in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
        msg = _browser_uia_block(_W(browser_cls))
        assert "不支持" in msg, browser_cls
    assert _browser_uia_block(_W("Notepad")) == ""


# ---- T8：空回复不得记为 success ----

def test_empty_reply_recorded_as_empty_reply(tmp_path, stub_tools):
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([{"role": "assistant", "content": "", "tool_calls": []}])
    result = agent.run("回归：空回复")
    assert "模型未返回有效内容" in result
    rec = agent.history.recent(1)[0]
    assert rec["status"] == "empty_reply", "空回复不该落 success（0f38d020 形态）"
    assert rec["status"] not in ("success",)


def test_normal_reply_still_success(tmp_path, stub_tools):
    """防收紧误伤：正常答复仍记 success"""
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([_final("已把结果整理好放在桌面")])
    agent.run("回归：正常收尾")
    assert agent.history.recent(1)[0]["status"] == "success"


def test_empty_reply_flag_resets_between_tasks(tmp_path, stub_tools):
    """逐任务复位：上一任务空回复不污染下一任务定态"""
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([{"role": "assistant", "content": "", "tool_calls": []}])
    agent.run("回归：第一条空")
    assert agent.history.recent(1)[0]["status"] == "empty_reply"
    agent.llm = _FakeLLM([_final("这次正常完成")])
    agent.run("回归：第二条正常")
    assert agent.history.recent(1)[0]["status"] == "success"
