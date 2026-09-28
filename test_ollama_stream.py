# -*- coding: utf-8 -*-
"""流式 Ollama 调用的单元测试（对应 v2.0.13 的超时修复）

背景：
    v2.0.12 的 LLMClient._chat_ollama 使用 stream=False + timeout=120。
    在纯 CPU 推理场景下，非流式请求必须等整段生成完才返回，而系统提示词 +
    20 多个工具定义合计数千 token，仅 prompt 处理就超过 120 秒（本机实测
    prompt 处理约 34 token/s），导致任务连第一轮都跑不完就报
    `Read timed out. (read timeout=120)`。

本次改为流式逐块解析 + 分块超时。本测试用假响应流验证解析逻辑，
不依赖真实 Ollama 服务。
"""
import json
import unittest
from unittest.mock import patch

import agent_loop
from agent_loop import LLMClient, LLMConfig, LLMProvider


def _line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _chunk(text, done=False, prompt=None, eval_=None):
    d = {"message": {"role": "assistant", "content": text}, "done": done}
    if prompt is not None:
        d["prompt_eval_count"] = prompt
    if eval_ is not None:
        d["eval_count"] = eval_
    return d


class _FakeResponse:
    """模拟 requests 的流式响应（支持 with 上下文管理器）"""

    def __init__(self, lines, status_error=None):
        self._lines = lines
        self._status_error = status_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def iter_lines(self, decode_unicode=False):
        for ln in self._lines:
            yield ln


class _FakeSession:
    def __init__(self, lines, status_error=None):
        self._lines = lines
        self._status_error = status_error
        self.trust_env = True
        self.post_kwargs = None

    def post(self, url, **kwargs):
        self.post_kwargs = kwargs
        return _FakeResponse(self._lines, self._status_error)


def _client(**cfg):
    """构造 LLMClient 但跳过 __init__ 中的真实 SDK 初始化"""
    c = LLMClient.__new__(LLMClient)
    c.config = LLMConfig(provider=LLMProvider.OLLAMA,
                         base_url="http://localhost:11434",
                         model="qwen2.5-coder:7b", **cfg)
    c.client = None
    c.on_progress = None
    return c


class TestOllamaStreaming(unittest.TestCase):

    def test_content_assembled_in_order(self):
        """多块内容按顺序拼接，空行被忽略"""
        lines = [
            _line(_chunk("你好")),
            b"",
            _line(_chunk("，世界")),
            _line(_chunk("", done=True, prompt=1234, eval_=56)),
        ]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            resp = _client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp["content"], "你好，世界")
        self.assertEqual(resp["tool_calls"], [])

    def test_usage_extracted_from_final_chunk(self):
        lines = [
            _line(_chunk("ok")),
            _line(_chunk("", done=True, prompt=3000, eval_=120)),
        ]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            resp = _client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp["_usage"], {"prompt": 3000, "eval": 120})

    def test_request_is_streaming_with_long_read_timeout(self):
        """回归保护：必须走流式，且读超时不能退回 120 秒"""
        lines = [_line(_chunk("x", done=True))]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            _client().chat([{"role": "user", "content": "hi"}])
        body = sess.post_kwargs["json"]
        self.assertTrue(body["stream"], "必须使用流式，否则长提示词必然读超时")
        self.assertEqual(body["keep_alive"], "30m")
        self.assertIn("num_ctx", body["options"])
        # timeout=(连接, 分块间隔)，且间隔必须远大于 120 秒
        connect_to, read_to = sess.post_kwargs["timeout"]
        self.assertEqual(connect_to, 15)
        self.assertGreater(read_to, 120)

    def test_num_ctx_default_amplified(self):
        lines = [_line(_chunk("x", done=True))]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            _client().chat([{"role": "user", "content": "hi"}])
        self.assertGreaterEqual(sess.post_kwargs["json"]["options"]["num_ctx"], 8192)

    def test_structured_tool_calls_collected(self):
        tc = {"function": {"name": "list_windows", "arguments": "{}"}}
        lines = [
            _line({"message": {"role": "assistant", "content": "", "tool_calls": [tc]},
                   "done": False}),
            _line(_chunk("", done=True, prompt=10, eval_=5)),
        ]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            resp = _client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(len(resp["tool_calls"]), 1)
        self.assertEqual(resp["tool_calls"][0]["function"]["name"], "list_windows")

    def test_text_tool_call_fallback_still_works(self):
        """兼容层：GGUF 模型把工具调用输出为文本时仍能提取"""
        payload = '```json\n{"name": "list_windows", "arguments": {}}\n```'
        lines = [_line(_chunk(payload, done=True, prompt=10, eval_=5))]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            resp = _client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(len(resp["tool_calls"]), 1)
        self.assertEqual(resp["tool_calls"][0]["function"]["name"], "list_windows")
        self.assertEqual(resp["content"], "")

    def test_progress_callback_invoked(self):
        """进度回调应被触发（界面靠它判断「在动」而不是卡死）"""
        notes = []
        lines = [
            _line(_chunk("一")),
            _line(_chunk("二")),
            _line(_chunk("", done=True, prompt=10, eval_=2)),
        ]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            cli = _client()
            cli.on_progress = notes.append
            cli.chat([{"role": "user", "content": "hi"}])
        self.assertTrue(notes, "必须至少上报一次进度")
        self.assertTrue(any("首字" in n for n in notes),
                        "首个字到达时应上报首字耗时")

    def test_broken_json_line_skipped(self):
        """流中若混入非 JSON 行（心跳/半包）应跳过而不是崩溃"""
        lines = [
            _line(_chunk("好")),
            b"not-json",
            _line(_chunk("", done=True, prompt=1, eval_=1)),
        ]
        sess = _FakeSession(lines)
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            resp = _client().chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp["content"], "好")

    def test_http_error_propagates(self):
        """服务端报错时必须抛出，而不是静默返回空内容"""
        lines = [_line(_chunk("x", done=True))]
        sess = _FakeSession(lines, status_error=RuntimeError("500 Server Error"))
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            with self.assertRaises(RuntimeError):
                _client().chat([{"role": "user", "content": "hi"}])

    def test_tools_payload_shape(self):
        """工具定义按 Ollama 要求包装成 {"type":"function","function":{...}}"""
        lines = [_line(_chunk("x", done=True))]
        sess = _FakeSession(lines)
        tools = [{"function": {"name": "open_app", "description": "d", "parameters": {}}}]
        with patch.object(agent_loop.requests, "Session", return_value=sess):
            _client().chat([{"role": "user", "content": "hi"}], tools=tools)
        sent = sess.post_kwargs["json"]["tools"]
        self.assertEqual(sent[0]["type"], "function")
        self.assertEqual(sent[0]["function"]["name"], "open_app")


class TestFallbackProgressPassthrough(unittest.TestCase):

    def test_on_progress_setter_reaches_both_clients(self):
        """FallbackLLMClient 的进度回调应同时转发给本地与云端客户端"""
        local = _client()
        cloud = _client()
        fb = agent_loop.FallbackLLMClient(local, cloud, on_fallback=None)
        seen = []

        def cb(msg):
            seen.append(msg)

        fb.on_progress = cb
        self.assertIs(local.on_progress, cb)
        self.assertIs(cloud.on_progress, cb)
        self.assertIs(fb.on_progress, cb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
