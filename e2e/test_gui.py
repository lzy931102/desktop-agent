"""
测试脚本：验证 GUI 和 Agent 的回调机制
"""
from agent_loop import DesktopAgent
import queue

# 测试回调机制
print("=== 测试回调机制 ===\n")

# 创建 Agent
agent = DesktopAgent(None)

# 创建队列来接收日志
log_queue = queue.Queue()
result_queue = queue.Queue()

# 设置回调
agent.on_log = lambda msg: log_queue.put(msg)
agent.on_tool_call = lambda name, args: log_queue.put(f"[工具调用] {name}({args})")
agent.on_tool_result = lambda name, args, result: log_queue.put(f"[工具结果] {result}")

# 模拟执行
print("开始执行...\n")
result = agent.run("测试任务")

# 输出所有日志
print("\n=== 收到的日志 ===")
while not log_queue.empty():
    print(log_queue.get())

print(f"\n=== 最终结果 ===")
print(result)
