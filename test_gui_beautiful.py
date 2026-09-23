"""
自动化测试脚本 - 验证 GUI 美化功能
"""
from agent_loop import DesktopAgent
import time

# 测试任务列表
test_tasks = [
    "打开计算器",
    "打开记事本，输入 Hello",
    "打开浏览器，搜索 Python"
]

# 模拟 LLM 响应（简化版）
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
        elif "记事本" in user_msg and "输入" in user_msg:
            return {
                "role": "assistant",
                "content": "好的，我来打开记事本并输入文字",
                "tool_calls": [
                    {
                        "id": "2",
                        "type": "function",
                        "function": {
                            "name": "open_app",
                            "arguments": '{"app_name": "notepad"}'
                        }
                    },
                    {
                        "id": "3",
                        "type": "function",
                        "function": {
                            "name": "type_text",
                            "arguments": '{"text": "Hello"}'
                        }
                    }
                ]
            }
        else:
            return {
                "role": "assistant",
                "content": "好的，我来打开浏览器搜索",
                "tool_calls": [
                    {
                        "id": "4",
                        "type": "function",
                        "function": {
                            "name": "open_app",
                            "arguments": '{"app_name": "chrome"}'
                        }
                    }
                ]
            }


def test_gui():
    """测试 GUI 功能"""
    print("=== GUI 美化测试 ===\n")

    # 创建 Agent
    agent = DesktopAgent()

    # 设置回调（带人性化）
    agent.on_log = lambda msg: print(f"[LOG] {msg}")
    agent.on_tool_call = lambda name, args: print(f"[TOOL] {name}({args})")
    agent.on_tool_result = lambda name, args, result: print(f"[RESULT] {result}")

    # 替换 LLM
    agent.llm = MockLLM()

    # 测试每个任务
    for i, task in enumerate(test_tasks, 1):
        print(f"\n{'='*60}")
        print(f"测试任务 {i}/{len(test_tasks)}: {task}")
        print(f"{'='*60}\n")

        # 记录开始时间
        start_time = time.time()

        # 模拟执行
        result = agent.run(task)

        # 计算耗时
        elapsed_time = time.time() - start_time

        # 显示结果
        print(f"\n{'='*60}")
        print(f"✓ 任务完成！")
        print(f"耗时：{elapsed_time:.1f}秒")
        print(f"{'='*60}")

        # 等待一下
        time.sleep(1)

    print(f"\n{'='*60}")
    print("✓ 所有测试完成！")
    print(f"{'='*60}")


if __name__ == "__main__":
    test_gui()
