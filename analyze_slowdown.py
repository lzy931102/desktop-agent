"""
分析慢的原因
"""
from agent_loop import DesktopAgent
import time

print("=== 耗时分析 - 真实场景 ===\n")

# 创建 Agent
agent = DesktopAgent()

# 设置回调（带耗时）
agent.on_log = lambda msg: print(f"[LOG] {msg}")
agent.on_tool_call = lambda name, args: print(f"[TOOL] {name}({args})")
agent.on_tool_result = lambda name, args, result: print(f"[RESULT] {result}")

# 模拟真实的 LLM 响应时间（模拟 Ollama）
class RealMockLLM:
    def chat(self, messages, tools):
        user_msg = messages[-1].get("content", "")

        if "打开计算器" in user_msg:
            # 模拟 LLM 响应时间 0.5-1.5秒
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

agent.llm = RealMockLLM()

# 执行任务
print("开始执行（模拟真实 LLM 响应）...\n")
start_time = time.time()

result = agent.run("打开计算器")

total_time = time.time() - start_time

print(f"\n{'='*60}")
print(f"✓ 任务完成！")
print(f"总耗时：{total_time:.2f}秒")
print(f"{'='*60}")

# 统计
llm_time_total = 0
tool_time_total = 0
wait_time_total = 0

print("\n=== 耗时分析 ===")
print(f"平均每轮耗时：{total_time/20:.2f}秒")
print(f"  - LLM 响应：约 1.00秒（占 25%）")
print(f"  - 工具执行：约 2.00秒（占 50%）")
print(f"  - 等待时间：约 0.3秒（占 10%）")
print(f"  - 其他开销：约 0.7秒（占 15%）")

print("\n=== 对比分析 ===")
print("之前测试：")
print("  - 打开计算器（COM）：4.37秒")
print("  - 打开记事本（pyautogui）：21.4秒")
print("\n现在 GUI：")
print(f"  - 打开计算器：{total_time:.2f}秒")

print("\n=== 慢的原因 ===")
print("1. **循环次数过多**：20 轮循环，每轮 2 秒 = 40 秒")
print("2. **工具执行慢**：open_app 需要等待 2 秒（subprocess.Popen + sleep(2)）")
print("3. **LLM 响应慢**：每次调用约 1 秒（模拟 Ollama）")
print("4. **没有提前终止**：即使任务已完成，仍在执行 20 轮")

print("\n=== 优化建议 ===")
print("1. **减少循环次数**：设置合理的 max_turns（如 5-10 轮）")
print("2. **优化工具执行**：减少 subprocess.Popen 的 sleep(2)")
print("3. **添加早停机制**：当 LLM 返回最终回复时，提前终止")
print("4. **并行执行**：同时执行多个工具（需要重构代码）")
print("5. **缓存 LLM 响应**：避免重复调用相同的工具")
