"""
测试早停机制和真实耗时
"""
from agent_loop import DesktopAgent
import time

print("="*60)
print("测试早停机制")
print("="*60)
print("任务：打开计算器")
print()

# 创建 Agent
agent = DesktopAgent()

# 设置回调（带详细日志）
agent.on_log = lambda msg: print(f"[LOG] {msg}")
agent.on_tool_call = lambda name, args: print(f"[TOOL CALL] {name}({args})")
agent.on_tool_result = lambda name, args, result: print(f"[TOOL RESULT] {result}")

# 模拟真实的 LLM 响应时间
class RealMockLLM:
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
            # 第二次调用，LLM 说完成（没有 tool_calls）
            time.sleep(1.0)
            return {
                "role": "assistant",
                "content": "任务完成，计算器已打开",
                "tool_calls": []  # 注意：这里没有 tool_calls
            }

agent.llm = RealMockLLM()

# 执行任务
print("开始执行...\n")
start_time = time.time()

result = agent.run("打开计算器")

total_time = time.time() - start_time

print(f"\n{'='*60}")
print(f"✓ 任务完成！")
print(f"总耗时：{total_time:.2f}秒")
print(f"{'='*60}")

print("\n=== 早停机制验证 ===")
print(f"如果只跑 2 轮，说明早停生效")
print(f"如果跑满 10 轮，说明早停未生效")

print("\n=== 优化效果对比 ===")
print(f"优化前：60.08秒（20 轮 × 3 秒）")
print(f"优化后：{total_time:.2f}秒（{int(total_time/3)+1} 轮 × 3 秒）")
print(f"提升：{((60.08 - total_time) / 60.08 * 100):.1f}%")
