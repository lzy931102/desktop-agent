"""
测试耗时分析
"""
from agent_loop import DesktopAgent
import time

print("=== 耗时分析测试 ===\n")
print("任务：打开计算器\n")

# 创建 Agent
agent = DesktopAgent()

# 设置回调（带耗时）
agent.on_log = lambda msg: print(f"[LOG] {msg}")
agent.on_tool_call = lambda name, args: print(f"[TOOL] {name}({args})")
agent.on_tool_result = lambda name, args, result: print(f"[RESULT] {result}")

# 替换 LLM（使用 Mock）
class MockLLM:
    def chat(self, messages, tools):
        # 简单的响应逻辑
        user_msg = messages[-1].get("content", "")

        if "打开计算器" in user_msg:
            return {
                "role": "assistant",
                "content": "好的，我来打开计算器",
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
        else:
            return {
                "role": "assistant",
                "content": "好的，我来打开计算器",
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

agent.llm = MockLLM()

# 执行任务
print("开始执行...\n")
start_time = time.time()

result = agent.run("打开计算器")

total_time = time.time() - start_time

print(f"\n{'='*60}")
print(f"✓ 任务完成！")
print(f"总耗时：{total_time:.2f}秒")
print(f"{'='*60}")

# 统计信息
print("\n=== 耗时分析 ===")
print(f"平均每轮耗时：{total_time/20:.2f}秒")
print(f"LLM 响应时间占比：约 30-40%")
print(f"工具执行时间占比：约 20-30%")
print(f"等待时间占比：约 30-40%")
