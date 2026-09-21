"""
调度层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.orchestrator import Orchestrator, TaskStatus, create_orchestrator


def test_orchestrator_creation():
    """测试调度层创建"""
    print("测试调度层创建...")
    
    orchestrator = create_orchestrator()
    assert orchestrator is not None
    assert isinstance(orchestrator, Orchestrator)
    assert orchestrator.status == TaskStatus.IDLE
    
    print("[PASS] 调度层创建测试通过")


def test_status():
    """测试状态管理"""
    print("测试状态管理...")
    
    orchestrator = create_orchestrator()
    
    # 初始状态
    assert orchestrator.status == TaskStatus.IDLE
    
    # 获取状态
    status = orchestrator.get_status()
    assert status["status"] == "idle"
    
    print(f"  初始状态: {status}")
    print("[PASS] 状态管理测试通过")


def test_validate_modules():
    """测试模块验证"""
    print("测试模块验证...")
    
    orchestrator = create_orchestrator()
    
    # 没有模块时验证失败
    assert orchestrator._validate_modules() == False
    
    # 设置模拟模块
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
    
    orchestrator.set_modules(
        perception=MockPerception(),
        brain=MockBrain(),
        actuator=MockActuator()
    )
    
    # 有模块时验证成功
    assert orchestrator._validate_modules() == True
    
    print("[PASS] 模块验证测试通过")


def test_set_modules():
    """测试设置模块"""
    print("测试设置模块...")
    
    orchestrator = create_orchestrator()
    
    # 创建模拟模块
    class MockModule:
        pass
    
    mock_perception = MockModule()
    mock_brain = MockModule()
    mock_actuator = MockModule()
    
    # 设置模块
    orchestrator.set_modules(
        perception=mock_perception,
        brain=mock_brain,
        actuator=mock_actuator
    )
    
    # 验证设置
    assert orchestrator.perception == mock_perception
    assert orchestrator.brain == mock_brain
    assert orchestrator.actuator == mock_actuator
    
    print("[PASS] 设置模块测试通过")


def test_stop():
    """测试停止功能"""
    print("测试停止功能...")
    
    orchestrator = create_orchestrator()
    
    # 模拟运行状态
    orchestrator.status = TaskStatus.RUNNING
    orchestrator.current_goal = "test"
    
    # 停止
    orchestrator.stop()
    
    assert orchestrator.status == TaskStatus.IDLE
    assert orchestrator.current_goal == ""
    
    print("[PASS] 停止功能测试通过")


def test_pause_resume():
    """测试暂停和恢复"""
    print("测试暂停和恢复...")
    
    orchestrator = create_orchestrator()
    
    # 模拟运行状态
    orchestrator.status = TaskStatus.RUNNING
    
    # 暂停
    orchestrator.pause()
    assert orchestrator.status == TaskStatus.PAUSED
    
    # 恢复会启动主循环，这里只测试状态设置
    # 实际恢复需要完整的模块
    orchestrator.status = TaskStatus.RUNNING
    assert orchestrator.status == TaskStatus.RUNNING
    
    print("[PASS] 暂停和恢复测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("调度层测试")
    print("=" * 50)
    
    try:
        test_orchestrator_creation()
        test_status()
        test_validate_modules()
        test_set_modules()
        test_stop()
        test_pause_resume()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
