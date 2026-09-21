"""
调度层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.orchestrator import create_orchestrator, TaskStatus


def example_basic_usage():
    """示例：基本用法"""
    print("示例1：基本用法")
    
    orchestrator = create_orchestrator()
    
    # 查看状态
    status = orchestrator.get_status()
    print(f"  初始状态: {status['status']}")
    
    # 注意：实际运行需要设置模块
    print("  需要设置模块才能运行任务")
    print()


def example_set_modules():
    """示例：设置模块"""
    print("示例2：设置模块")
    
    orchestrator = create_orchestrator()
    
    # 创建模拟模块
    class MockPerception:
        def capture(self):
            return ScreenState(screenshot="")
    
    class MockBrain:
        def decide(self, state, goal):
            return Action(action=ActionType.DONE)
        def update_state(self, state, action, success):
            pass
    
    class MockActuator:
        def execute(self, action):
            return True
    
    class MockVerifier:
        def verify(self, before, after, action):
            return True
    
    class MockMemory:
        def save_state(self, state, action, success):
            pass
    
    # 设置模块
    orchestrator.set_modules(
        perception=MockPerception(),
        brain=MockBrain(),
        actuator=MockActuator(),
        verifier=MockVerifier(),
        memory=MockMemory()
    )
    
    print("  模块设置完成")
    print(f"  模块验证: {orchestrator._validate_modules()}")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例3：完整工作流")
    
    # 这个示例展示调度层的工作流程
    print("  调度层工作流程:")
    print("    1. 感知: Perception.capture()")
    print("    2. 决策: Brain.decide(state, goal)")
    print("    3. 安全: Security.check(action)")
    print("    4. 执行: Actuator.execute(action)")
    print("    5. 验证: Verifier.verify(before, after, action)")
    print("    6. 记忆: Memory.save_state(state, action, success)")
    print("    7. 更新: Brain.update_state(state, action, success)")
    print()


def example_callbacks():
    """示例：回调函数"""
    print("示例4：回调函数")
    
    orchestrator = create_orchestrator()
    
    # 定义回调函数
    def on_step_complete(step, action, success):
        print(f"    步骤{step}完成: {action.action.value}, 成功: {success}")
    
    def on_task_complete(goal, total_steps):
        print(f"    任务完成: {goal}, 总步骤: {total_steps}")
    
    def on_error(error, retry_count):
        print(f"    错误: {error}, 重试次数: {retry_count}")
    
    # 设置回调
    orchestrator.on_step_complete = on_step_complete
    orchestrator.on_task_complete = on_task_complete
    orchestrator.on_error = on_error
    
    print("  回调函数设置完成")
    print()


def example_status_management():
    """示例：状态管理"""
    print("示例5：状态管理")
    
    orchestrator = create_orchestrator()
    
    # 模拟状态变化
    print(f"  初始状态: {orchestrator.status.value}")
    
    orchestrator.status = TaskStatus.RUNNING
    print(f"  运行状态: {orchestrator.status.value}")
    
    orchestrator.status = TaskStatus.PAUSED
    print(f"  暂停状态: {orchestrator.status.value}")
    
    orchestrator.status = TaskStatus.COMPLETED
    print(f"  完成状态: {orchestrator.status.value}")
    
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("调度层使用示例")
    print("=" * 60)
    print()
    
    example_basic_usage()
    example_set_modules()
    example_workflow()
    example_callbacks()
    example_status_management()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
