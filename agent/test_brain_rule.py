"""
决策层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.brain_rule import RuleBasedBrain, create_brain


def test_brain_creation():
    """测试决策层创建"""
    print("测试决策层创建...")
    
    brain = create_brain()
    assert brain is not None
    assert isinstance(brain, RuleBasedBrain)
    
    print("[PASS] 决策层创建测试通过")


def test_decide():
    """测试决策功能"""
    print("测试决策功能...")
    
    brain = create_brain()
    
    # 创建模拟屏幕状态
    state = ScreenState(
        screenshot="base64...",
        texts=[{"text": "确定", "bbox": [100, 200, 160, 230]}],
        elements=[{"type": "button", "name": "确定"}]
    )
    
    # 测试目标解析
    goal = "打开记事本并输入Hello World"
    
    # 第一次决策
    action1 = brain.decide(state, goal)
    assert action1 is not None
    print(f"  第1步动作: {action1.action}")
    
    # 模拟成功执行
    brain.update_state(state, action1, success=True)
    
    # 第二次决策
    action2 = brain.decide(state, goal)
    assert action2 is not None
    print(f"  第2步动作: {action2.action}")
    
    print("[PASS] 决策功能测试通过")


def test_plan():
    """测试任务规划"""
    print("测试任务规划...")
    
    brain = create_brain()
    
    # 规划任务
    goal = "打开记事本并输入Hello World"
    actions = brain.plan(goal)
    
    assert len(actions) > 0
    print(f"  规划了 {len(actions)} 个步骤")
    
    for i, action in enumerate(actions):
        print(f"    步骤{i+1}: {action.action}")
    
    print("[PASS] 任务规划测试通过")


def test_parse_goal():
    """测试目标解析"""
    print("测试目标解析...")
    
    brain = create_brain()
    
    # 测试不同目标
    goals = [
        "打开记事本",
        "输入Hello World",
        "点击确定按钮",
        "按Ctrl+S保存",
        "打开浏览器并搜索"
    ]
    
    for goal in goals:
        steps = brain._parse_goal(goal)
        print(f"  目标: {goal}")
        print(f"    解析为 {len(steps)} 个步骤")
        for step in steps:
            print(f"      - {step.get('type')}: {step}")
    
    print("[PASS] 目标解析测试通过")


def test_update_state():
    """测试状态更新"""
    print("测试状态更新...")
    
    brain = create_brain()
    
    # 初始状态
    state = ScreenState(screenshot="base64...")
    goal = "打开记事本"
    
    # 执行一次决策
    action = brain.decide(state, goal)
    
    # 更新状态（成功）
    brain.update_state(state, action, success=True)
    
    progress = brain.get_progress()
    assert progress["current_step"] == 1
    print(f"  成功后进度: {progress}")
    
    # 更新状态（失败）
    brain.update_state(state, action, success=False)
    print(f"  失败后进度: {brain.get_progress()}")
    
    print("[PASS] 状态更新测试通过")


def test_reset():
    """测试重置功能"""
    print("测试重置功能...")
    
    brain = create_brain()
    
    # 执行一些操作
    state = ScreenState(screenshot="base64...")
    goal = "打开记事本"
    
    brain.decide(state, goal)
    brain.decide(state, goal)
    
    # 重置
    brain.reset()
    
    progress = brain.get_progress()
    assert progress["current_step"] == 0
    assert progress["total_steps"] == 0
    
    print("[PASS] 重置功能测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("决策层测试")
    print("=" * 50)
    
    try:
        test_brain_creation()
        test_decide()
        test_plan()
        test_parse_goal()
        test_update_state()
        test_reset()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
