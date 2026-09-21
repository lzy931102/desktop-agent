"""
决策层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState
from modules.brain_rule import create_brain


def example_basic_decision():
    """示例：基本决策"""
    print("示例1：基本决策")
    
    brain = create_brain()
    
    # 模拟屏幕状态
    state = ScreenState(
        screenshot="base64...",
        texts=[
            {"text": "文件", "bbox": [10, 50, 50, 80]},
            {"text": "编辑", "bbox": [60, 50, 100, 80]},
            {"text": "确定", "bbox": [400, 500, 480, 540]}
        ],
        elements=[
            {"type": "button", "name": "确定", "bbox": [400, 500, 480, 540]}
        ],
        active_window={"title": "记事本"}
    )
    
    # 决策
    goal = "打开记事本并输入Hello World"
    action = brain.decide(state, goal)
    
    print(f"  目标: {goal}")
    print(f"  决策动作: {action.action}")
    if action.text:
        print(f"  输入文字: {action.text}")
    if action.target:
        print(f"  点击目标: {action.target}")
    print()


def example_task_planning():
    """示例：任务规划"""
    print("示例2：任务规划")
    
    brain = create_brain()
    
    # 规划任务
    goal = "打开记事本并输入Hello World"
    actions = brain.plan(goal)
    
    print(f"  目标: {goal}")
    print(f"  规划步骤:")
    for i, action in enumerate(actions):
        print(f"    {i+1}. {action.action}")
        if action.text:
            print(f"       文字: {action.text}")
        if action.keys:
            print(f"       快捷键: {action.keys}")
    print()


def example_goal_parsing():
    """示例：目标解析"""
    print("示例3：目标解析")
    
    brain = create_brain()
    
    # 不同类型的目标
    goals = [
        "打开记事本",
        "输入Hello World",
        "点击确定按钮",
        "按Ctrl+S保存",
        "打开浏览器"
    ]
    
    for goal in goals:
        steps = brain._parse_goal(goal)
        print(f"  目标: {goal}")
        print(f"    解析为: {[s['type'] for s in steps]}")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例4：完整工作流")
    
    brain = create_brain()
    
    # 模拟屏幕状态
    state = ScreenState(
        screenshot="base64...",
        texts=[{"text": "记事本", "bbox": [100, 100, 200, 130]}],
        elements=[],
        active_window={"title": "桌面"}
    )
    
    goal = "打开记事本并输入Hello World"
    
    print(f"  目标: {goal}")
    print("  开始执行:")
    
    # 模拟执行循环
    for step in range(10):  # 最多10步
        action = brain.decide(state, goal)
        
        if action.action.value == "done":
            print(f"    第{step+1}步: 任务完成!")
            break
        
        print(f"    第{step+1}步: {action.action.value}")
        
        # 模拟成功执行
        brain.update_state(state, action, success=True)
        
        # 更新模拟状态
        state = ScreenState(
            screenshot="base64...",
            texts=[{"text": "Hello World", "bbox": [100, 100, 200, 130]}],
            elements=[],
            active_window={"title": "记事本"}
        )
    
    # 查看进度
    progress = brain.get_progress()
    print(f"  最终进度: {progress}")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("决策层使用示例")
    print("=" * 60)
    print()
    
    example_basic_decision()
    example_task_planning()
    example_goal_parsing()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
