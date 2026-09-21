"""
接口使用示例
展示如何使用定义的接口和数据结构
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import (
    ScreenState, Action, ActionType, ACTIONS,
    create_click_action, create_type_action, create_key_action,
    create_wait_action, create_done_action
)


def example_perception_output():
    """示例：感知层输出"""
    print("示例1：感知层输出格式")
    
    # 模拟感知层输出
    screen_state = ScreenState(
        screenshot="base64_encoded_screenshot_data...",
        screenshot_path="screenshots/current.png",
        texts=[
            {"text": "文件", "bbox": [10, 50, 50, 80], "confidence": 0.99},
            {"text": "编辑", "bbox": [60, 50, 100, 80], "confidence": 0.98},
            {"text": "确定", "bbox": [400, 500, 480, 540], "confidence": 0.97},
            {"text": "取消", "bbox": [500, 500, 580, 540], "confidence": 0.96}
        ],
        elements=[
            {"type": "button", "name": "确定", "bbox": [400, 500, 480, 540], "ref": "hwnd:12345"},
            {"type": "button", "name": "取消", "bbox": [500, 500, 580, 540], "ref": "hwnd:12346"},
            {"type": "textbox", "name": "输入框", "bbox": [100, 200, 400, 280], "ref": "hwnd:12347"}
        ],
        active_window={"title": "记事本", "hwnd": 12345}
    )
    
    print(f"  截图路径: {screen_state.screenshot_path}")
    print(f"  识别到 {len(screen_state.texts)} 个文字")
    print(f"  识别到 {len(screen_state.elements)} 个元素")
    print(f"  当前窗口: {screen_state.active_window['title']}")
    print()


def example_brain_output():
    """示例：决策层输出"""
    print("示例2：决策层输出格式")
    
    # 模拟决策层输出的各种动作
    actions = [
        create_click_action({"text": "确定"}),
        create_type_action("Hello, World!"),
        create_key_action(["ctrl", "s"]),
        create_wait_action({"text": "保存成功"}),
        create_done_action()
    ]
    
    for action in actions:
        print(f"  动作: {action.action}", end="")
        if action.target:
            print(f", 目标: {action.target}", end="")
        if action.text:
            print(f", 文本: {action.text}", end="")
        if action.keys:
            print(f", 快捷键: {action.keys}", end="")
        if action.condition:
            print(f", 条件: {action.condition}", end="")
        print()
    print()


def example_action_types():
    """示例：动作类型说明"""
    print("示例3：支持的动作类型")
    
    for action_type, description in ACTIONS.items():
        print(f"  {action_type}: {description}")
    print()


def example_target_formats():
    """示例：目标描述格式"""
    print("示例4：目标描述格式")
    
    # 文本目标
    text_target = {"text": "确定"}
    print(f"  文本目标: {text_target}")
    
    # 元素引用目标
    ref_target = {"ref": "hwnd:12345"}
    print(f"  元素引用: {ref_target}")
    
    # 复合目标
    complex_target = {"text": "确定", "type": "button", "bbox": [400, 500, 480, 540]}
    print(f"  复合目标: {complex_target}")
    print()


def example_orchestrator_flow():
    """示例：调度层工作流程"""
    print("示例5：调度层工作流程")
    
    print("  while 任务未完成:")
    print("      1. before = Perception.capture()          # 感知")
    print("      2. action = Brain.decide(before, goal)   # 决策")
    print("      3. Security.check(action)                # 安全检查")
    print("      4. Actuator.execute(action)              # 执行")
    print("      5. after = Perception.capture()          # 再次感知")
    print("      6. ok = Verifier.verify(before, after, action)  # 验证")
    print("      7. Memory.save(state, action, ok)        # 记忆")
    print("      8. if not ok: 重试 / 换策略 / 报错")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("接口使用示例")
    print("=" * 60)
    print()
    
    example_perception_output()
    example_brain_output()
    example_action_types()
    example_target_formats()
    example_orchestrator_flow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
