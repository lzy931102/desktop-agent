# -*- coding: utf-8 -*-
"""用真实 Ollama 验证 v2.0.13 的流式改造。

对照版本：v2.0.12 走 stream=False + timeout=120，长提示词下会
`Read timed out. (read timeout=120)`，任务连第一轮都跑不完。

本脚本用「真实系统提示词 + 全部工具定义」发一次请求，用来确认：
  1. 流式解析对真实 Ollama 服务有效；
  2. 报出真实的 prompt token 数 —— 这是判断「120 秒够不够」的关键依据；
  3. 工具调用能被正确解析出来。

用法（宿主机）：
    python verify_stream_live.py [base_url] [model]
"""
import sys
import time

sys.path.insert(0, ".")
from agent_loop import (LLMClient, LLMConfig, LLMProvider,  # noqa: E402
                        SYSTEM_PROMPT, TOOLS_SCHEMA)

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5-coder:7b"

print(f"目标服务: {BASE}")
print(f"模型    : {MODEL}")
print(f"系统提示词长度: {len(SYSTEM_PROMPT)} 字")
print(f"工具数量      : {len(TOOLS_SCHEMA)} 个")
payload_chars = len(SYSTEM_PROMPT) + len(str(TOOLS_SCHEMA))
print(f"提示词+工具定义合计约 {payload_chars} 字符")
print("-" * 60)

cli = LLMClient(LLMConfig(provider=LLMProvider.OLLAMA, base_url=BASE,
                          model=MODEL, temperature=0.1))
_last = {"t": 0.0}


def on_progress(msg):
    now = time.time()
    # 界面每秒最多刷一条，这里也做节流，避免刷屏
    if now - _last["t"] >= 1.0:
        _last["t"] = now
        print(f"  [进度] {msg}", flush=True)


cli.on_progress = on_progress

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": "看看现在有哪些窗口"},
]

print("发起请求（真实长提示词 + 全部工具定义）…")
t0 = time.time()
try:
    resp = cli.chat(messages, TOOLS_SCHEMA)
    elapsed = time.time() - t0
except Exception as e:
    elapsed = time.time() - t0
    print(f"\n[失败] 耗时 {elapsed:.1f} 秒: {type(e).__name__}: {e}")
    sys.exit(1)

usage = resp.get("_usage") or {}
print(f"\n总耗时        : {elapsed:.1f} 秒")
print(f"prompt token  : {usage.get('prompt')}")
print(f"生成 token    : {usage.get('eval')}")
print(f"工具调用      : {resp.get('tool_calls')}")
print(f"文本内容前 200 字: {(resp.get('content') or '')[:200]!r}")

prompt_tokens = usage.get("prompt") or 0
if prompt_tokens:
    print(f"\n[关键结论] 仅 prompt 处理就 {prompt_tokens} token；"
          f"v2.0.12 的 120 秒固定超时在实践中必然不够。")
