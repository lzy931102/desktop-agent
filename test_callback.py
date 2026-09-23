"""
测试回调机制（使用 MockLLM）
"""
from agent_loop import DesktopAgent
import queue

print("=== 测试回调机制 ===\n")

# 模拟执行（使用模拟的 LLM 响应）
class MockLLM:
    def chat(self, messages, tools):
        return {
            "role": "assistant",
            "content": "我需要打开计算器",
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {
                        "name": "open_app",
                        "arguments": '{"app_name": "calc"}'
                    }
                }
            ]
        }

# 创建 Agent
agent = DesktopAgent()

# 创建队列来接收日志
log_queue = queue.Queue()

# 设置回调
agent.on_log = lambda msg: log_queue.put(msg)
agent.on_tool_call = lambda name, args: log_queue.put(f"🔧 工具调用: {name}({args})")
agent.on_tool_result = lambda name, args, result: log_queue.put(f"✅ 工具结果: {result}")

# 替换 LLM 客户端
agent.llm = MockLLM()

# 执行
print("开始执行...\n")
result = agent.run("打开计算器")

# 输出所有日志
print("\n=== 收到的日志 ===")
logs = []
while not log_queue.empty():
    logs.append(log_queue.get())

for log in logs:
    print(log)

print(f"\n=== 最终结果 ===")
print(result)

# 验证回调是否被调用
print(f"\n=== 验证 ===")
print(f"收到日志条数: {len(logs)}")
print(f"回调是否工作: {'✓' if len(logs) > 0 else '✗'}")
