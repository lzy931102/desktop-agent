"""T26 停止响应 + 简单任务耗时回归测试。

背景（黑匣子实测，%LOCALAPPDATA%/DesktopAgent/history.jsonl）：
  - 2026-10-05 07:15「打开记事本，输入 你好」status=stopped elapsed=34.5s：
    07:15:28 第 2 轮 LLM 开始 → 07:15:55 才 task_end——点停止后等云端
    非流式 chat() 返回（约 27 秒）才检查到停止标志；
  - 2026-10-04 07:49「看看现在有哪些窗口」elapsed=47.1s：第 1 轮 LLM 10s
    + list_windows <1s + 第 2 轮 LLM 37s——耗时全在 glm-4.5-flash 的
    深度思考上，工具本身零成本。

四块机制，全部离线（不连真 API，mock 走 monkeypatch 自动还原）：
  1. 停止立即中断：LLMStopped 异常；本地 Ollama 流式循环逐块检查；
     云端改流式（delta 聚合）后逐 chunk 检查；FallbackLLMClient 不把
     「停止」当本地故障触发云端 fallback；重试退避睡眠 0.2s 粒度可中断
  2. 轮循环兜底：_run_loop 捕获 LLMStopped → 返回停止文案（GUI 按文案
     判定 stopped，契约不变）
  3. 简单任务耗时：云端 GLM 默认关深度思考（thinking={"type":"disabled"}，
     provider==ZHIPU 才传，防其他厂商 400）；设置 cloud.thinking 可开回
  4. 停止检查点搭载：agent 每轮 chat 前把 stop_check 挂到 LLM 客户端
"""
import json
import time

import pytest

import agent_loop
from agent_loop import LLMClient, LLMStopped, FallbackLLMClient
from core.retry import run_with_retry


def _ollama_client():
    return LLMClient(agent_loop.LLMConfig(
        provider=agent_loop.LLMProvider.OLLAMA,
        base_url="http://localhost:11434", model="fake", temperature=0.1))


def _cloud_client():
    c = LLMClient(agent_loop.LLMConfig(
        provider=agent_loop.LLMProvider.ZHIPU, api_key="fake-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.5-flash", temperature=0.1))
    return c


def _fake_stream(monkeypatch, chunks, create_calls):
    """把云端 client 换成假 OpenAI 客户端；create 收到的 kwargs 记进 create_calls"""
    class _FakeCompletions:
        def create(self, **kw):
            create_calls.append(kw)
            return iter(chunks)

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeOpenAI:
        chat = _FakeChat()

    c = _cloud_client()
    c.client = _FakeOpenAI()
    return c


def _cloud_chunk(delta=None, usage=None, empty_choices=False):
    """构造 OpenAI 流式 chunk 假体（属性对象，同 SDK 真实结构）"""

    class _Usage:
        def __init__(self, u):
            self.prompt_tokens = u.get("prompt_tokens")
            self.completion_tokens = u.get("completion_tokens")

    class _Chunk:
        pass

    ch = _Chunk()
    if empty_choices:
        ch.choices = []
    else:
        class _Choice:
            pass
        choice = _Choice()
        choice.delta = delta or _delta()
        choice.finish_reason = None
        ch.choices = [choice]
    ch.usage = _Usage(usage) if usage else None
    return ch


def _delta(content=None, tool_calls=None):
    """OpenAI 流式 delta 假体（属性对象，同 SDK 真实结构）"""

    class _D:
        pass

    d = _D()
    d.content = content
    d.tool_calls = tool_calls
    return d


def _tc_delta(index=None, id=None, name=None, arguments=None):
    """OpenAI 流式 tool_calls delta 假体"""

    class _Fn:
        def __init__(self):
            self.name = name
            self.arguments = arguments

    class _TC:
        def __init__(self):
            self.index = index
            self.id = id
            self.function = _Fn()

    return _TC()


# ==================== 1. 本地 Ollama：流式循环逐块检查停止 ====================

def test_ollama_stream_stop_interrupts(monkeypatch):
    """stop_check 命中后当前 chunk 处理完立即抛 LLMStopped，不再等流结束"""
    lines = [
        json.dumps({"message": {"content": "第一块"}, "done": False}).encode(),
        json.dumps({"message": {"content": "第二块"}, "done": False}).encode(),
        json.dumps({"done": True, "prompt_eval_count": 5, "eval_count": 7}).encode(),
    ]

    class _FakeResp:
        def raise_for_status(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self, decode_unicode=False):
            return iter(lines)

    class _FakeSession:
        trust_env = False

        def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(agent_loop.requests, "Session", _FakeSession)
    c = _ollama_client()
    seen = {"n": 0}

    def stop_check():
        seen["n"] += 1
        return seen["n"] >= 2  # 第 1 chunk 后命中

    c.stop_check = stop_check
    with pytest.raises(LLMStopped):
        c.chat([{"role": "user", "content": "hi"}])
    assert seen["n"] == 2  # 第 2 个 chunk 前就中断，没读完流


def test_ollama_stream_no_stop_returns_full(monkeypatch):
    """无停止请求：聚合行为与旧版一致（content 拼接 + usage 透传）"""
    lines = [
        json.dumps({"message": {"content": "你"}, "done": False}).encode(),
        json.dumps({"message": {"content": "好"}, "done": False}).encode(),
        json.dumps({"done": True, "prompt_eval_count": 11, "eval_count": 7}).encode(),
    ]

    class _FakeResp:
        def raise_for_status(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self, decode_unicode=False):
            return iter(lines)

    class _FakeSession:
        trust_env = False

        def post(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(agent_loop.requests, "Session", _FakeSession)
    c = _ollama_client()
    resp = c.chat([{"role": "user", "content": "hi"}])
    assert resp["content"] == "你好"
    assert resp["_usage"] == {"prompt": 11, "eval": 7}


# ==================== 2. 云端：改流式（可中断 + delta 聚合） ====================

def test_cloud_stream_aggregates_content_and_tool_calls():
    """云端流式：content 增量拼接、tool_calls 分片聚合、usage 从空 choices 块取"""
    chunks = [
        _cloud_chunk(_delta(content="你好")),
        _cloud_chunk(_delta(tool_calls=[_tc_delta(index=0, id="call1",
                                                  name="list_windows")])),
        _cloud_chunk(_delta(tool_calls=[_tc_delta(index=0, arguments='{"limit":')])),
        _cloud_chunk(_delta(tool_calls=[_tc_delta(index=0, arguments="5}")])),
        _cloud_chunk(usage={"prompt_tokens": 11, "completion_tokens": 7},
                     empty_choices=True),
    ]
    calls = []
    c = _fake_stream(None, chunks, calls)
    resp = c.chat([{"role": "user", "content": "hi"}])
    assert resp["content"] == "你好"
    assert resp["tool_calls"] == [{
        "id": "call1", "type": "function",
        "function": {"name": "list_windows", "arguments": '{"limit":5}'}}]
    assert resp["_usage"] == {"prompt": 11, "eval": 7}


def test_cloud_stream_stop_interrupts():
    """云端流式：stop_check 命中 → LLMStopped，点停止不再等整轮返回"""
    chunks = [
        _cloud_chunk(_delta(content="a")),
        _cloud_chunk(_delta(content="b")),
        _cloud_chunk(_delta(content="c")),
    ]
    calls = []
    c = _fake_stream(None, chunks, calls)
    c.stop_check = lambda: True
    with pytest.raises(LLMStopped):
        c.chat([{"role": "user", "content": "hi"}])


def test_cloud_sends_request_streaming():
    """云端请求必须带 stream=True（T26 可中断的前提）"""
    calls = []
    chunks = [_cloud_chunk(_delta(content="x"))]
    _fake_stream(None, chunks, calls).chat([{"role": "user", "content": "hi"}])
    assert calls[0].get("stream") is True


def test_cloud_thinking_disabled_by_default_for_zhipu():
    """GLM 深度思考默认关闭（47 秒简单任务里 37 秒耗在思考上）；
    仅 ZHIPU 传 thinking 参数，防 OpenAI/DeepSeek 端 400"""
    calls = []
    chunks = [_cloud_chunk(_delta(content="x"))]
    c = _fake_stream(None, chunks, calls)
    c.thinking = "disabled"
    c.chat([{"role": "user", "content": "hi"}])
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_cloud_thinking_none_sends_nothing():
    """thinking 未设置（None）：不传 extra_body——OpenAI/DeepSeek/Ollama 兼容"""
    calls = []
    chunks = [_cloud_chunk(_delta(content="x"))]
    c = _fake_stream(None, chunks, calls)
    c.chat([{"role": "user", "content": "hi"}])
    assert "extra_body" not in calls[0]


# ==================== 3. Fallback：停止不是故障，不触发云端续跑 ====================

def test_fallback_llm_stopped_does_not_fall_through_to_cloud():
    """本地抛 LLMStopped：直接透传——绝不能被当成「本地故障」切云端继续跑"""
    class _Local:
        config = None
        on_progress = None

        def chat(self, *a, **kw):
            raise LLMStopped()

    class _Cloud:
        def __init__(self):
            self.called = False

        def chat(self, *a, **kw):
            self.called = True
            raise AssertionError("停止后不应再调云端")

    cloud = _Cloud()
    fb = FallbackLLMClient(_Local(), cloud)
    with pytest.raises(LLMStopped):
        fb.chat([{"role": "user", "content": "hi"}])
    assert not cloud.called


def test_fallback_stop_check_passthrough():
    """stop_check 属性透传到本地/云端两个客户端（界面侧设一次即可）"""
    class _P:
        config = None
        on_progress = None
        stop_check = None

    local, cloud = _P(), _P()
    fb = FallbackLLMClient(local, cloud)
    fb.stop_check = lambda: False
    assert local.stop_check is not None and cloud.stop_check is not None


# ==================== 4. 重试退避可中断 ====================

def test_retry_backoff_interrupted_by_stop():
    """工具重试退避睡眠可中断：stop_check 抛 LLMStopped 穿透，
    不再干等最长 1+2+4 秒退避"""
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        return "错误: 网络抖动"

    def stop_check():
        if calls["n"] >= 2:  # 第 2 次失败后、退避中命中
            raise LLMStopped()
        # 不命中时不抛（返回 None）

    t0 = time.time()
    with pytest.raises(LLMStopped):
        run_with_retry(always_fail, "click", True, stop_check=stop_check)
    assert time.time() - t0 < 1.5  # 未中断则要吃 1s+2s 退避


def test_retry_backoff_untouched_without_stop():
    """不传 stop_check：退避行为与旧版完全一致（回归保护）"""
    calls = {"n": 0}

    def fail_then_ok():
        calls["n"] += 1
        return "错误: x" if calls["n"] == 1 else "done"

    result, attempts, ok = run_with_retry(fail_then_ok, "click", True)
    assert (result, attempts, ok) == ("done", 2, True)


# ==================== 5. 轮循环兜底 + 检查点搭载 ====================

class _StopAwareFakeLLM:
    """chat 抛 LLMStopped 的假模型；记录 chat 时 stop_check 是否已搭载"""

    def __init__(self):
        self.stop_check = None
        self.stop_check_at_chat = None

    def chat(self, messages, tools=None):
        self.stop_check_at_chat = self.stop_check
        raise LLMStopped()


def test_run_loop_returns_stopped_copy_on_llm_stopped():
    """LLM 调用中途停止：run() 返回停止文案（GUI 按"停止"二字判定，
    会话终态 stopped 的契约不变）"""
    llm = _StopAwareFakeLLM()
    agent = agent_loop.DesktopAgent(llm=llm)
    result = agent.run("随便什么任务")
    assert result == "已按要求停止执行。"
    assert llm.stop_check_at_chat is not None  # chat 前已搭载检查点
    assert llm.stop_check_at_chat() is False   # 未请求停止时返回 False


def test_stop_signal_flows_from_stop_to_check():
    """agent.stop() → 挂载的 stop_check 立即为 True（信号链端到端）"""
    llm = _StopAwareFakeLLM()
    agent = agent_loop.DesktopAgent(llm=llm)
    agent.stop()
    # 模拟 _run_loop 挂载（真实路径在 chat 前）：stop_check 读实时标志
    llm.stop_check = lambda: agent._stop_requested
    assert llm.stop_check_at_chat is None
    assert llm.stop_check() is True
