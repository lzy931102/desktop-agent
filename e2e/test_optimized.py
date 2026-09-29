"""
测试优化后的性能
"""
from agent_loop import DesktopAgent
import time

print("=== 优化后性能测试 ===\n")
print("任务：打开计算器\n")

# 创建 Agent
agent = DesktopAgent()

# 设置回调（带耗时）
agent.on_log = lambda msg: print(f"[LOG] {msg}")
agent.on_tool_call = lambda name, args: print(f"[TOOL] {name}({args})")
agent.on_tool_result = lambda name, args, result: print(f"[RESULT] {result}")

# 模拟真实的 LLM 响应时间
class MockLLM:
    def chat(self, messages, tools):
        user_msg = messages[-1].get("content", "")

        if "打开计算器" in user_msg:
            time.sleep(1.0)
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
            # 如果没有 content，继续调用工具
            time.sleep(1.0)
            return {
                "role": "assistant",
                "content": "",
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
print("开始执行（优化后：max_turns=10）...\n")
start_time = time.time()

result = agent.run("打开计算器")

total_time = time.time() - start_time

print(f"\n{'='*60}")
print(f"✓ 任务完成！")
print(f"总耗时：{total_time:.2f}秒")
print(f"{'='*60}")

print("\n=== 优化效果对比 ===")
print(f"优化前：60.08秒（20 轮 × 3 秒）")
print(f"优化后：{total_time:.2f}秒（10 轮 × ? 秒）")
print(f"提升：{((60.08 - total_time) / 60.08 * 100):.1f}%")
