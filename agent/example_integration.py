"""
完整集成示例
展示如何使用所有模块
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.perception_v1 import create_perception
from modules.brain_rule import create_brain
from modules.actuator import create_actuator
from modules.verifier import create_verifier
from modules.memory_json import create_memory
from modules.security import create_security
from modules.orchestrator import create_orchestrator


def example_simple_task():
    """示例：简单任务"""
    print("示例1：简单任务 - 打开记事本")
    
    # 创建所有模块
    perception = create_perception()
    brain = create_brain()
    actuator = create_actuator()
    verifier = create_verifier()
    memory = create_memory({"storage_path": "example_memory"})
    security = create_security({"auto_approve": True})
    
    # 创建调度层
    orchestrator = create_orchestrator({"max_retries": 3})
    
    # 设置模块
    orchestrator.set_modules(
        perception=perception,
        brain=brain,
        actuator=actuator,
        verifier=verifier,
        memory=memory,
        security=security
    )
    
    # 定义回调
    def on_step_complete(step, action, success):
        print(f"    步骤{step}: {action.action.value} - {'成功' if success else '失败'}")
    
    def on_task_complete(goal, total_steps):
        print(f"    任务完成: {goal}")
    
    def on_error(error, retry_count):
        print(f"    错误: {error} (重试 {retry_count}/3)")
    
    orchestrator.on_step_complete = on_step_complete
    orchestrator.on_task_complete = on_task_complete
    orchestrator.on_error = on_error
    
    # 执行任务
    print("  开始执行任务...")
    # 注意：实际执行需要图形界面环境
    # success = orchestrator.start("打开记事本")
    
    # 清理
    memory.clear()
    
    print("  示例完成")
    print()


def example_manual_workflow():
    """示例：手动工作流"""
    print("示例2：手动工作流")
    
    # 创建模块
    perception = create_perception()
    brain = create_brain()
    actuator = create_actuator()
    verifier = create_verifier()
    memory = create_memory({"storage_path": "example_memory"})
    
    goal = "打开记事本并输入Hello World"
    
    print(f"  目标: {goal}")
    print("  手动执行流程:")
    
    # 1. 感知
    print("\n  1. 感知阶段")
    state = perception.capture()
    print(f"     截图路径: {state.screenshot_path}")
    print(f"     识别文字: {len(state.texts)}个")
    
    # 2. 决策
    print("\n  2. 决策阶段")
    action = brain.decide(state, goal)
    print(f"     决策动作: {action.action.value}")
    if action.text:
        print(f"     输入文字: {action.text}")
    if action.keys:
        print(f"     快捷键: {action.keys}")
    
    # 3. 执行
    print("\n  3. 执行阶段")
    success = actuator.execute(action)
    print(f"     执行结果: {'成功' if success else '失败'}")
    
    # 4. 验证
    print("\n  4. 验证阶段")
    after = perception.capture()
    verified = verifier.verify(state, after, action)
    print(f"     验证结果: {'通过' if verified else '失败'}")
    
    # 5. 记忆
    print("\n  5. 记忆阶段")
    memory.save_state(state, action, verified)
    print(f"     已保存执行记录")
    
    # 清理
    memory.clear()
    
    print("\n  手动工作流完成")
    print()


def example_module_interaction():
    """示例：模块交互"""
    print("示例3：模块交互")
    
    # 创建模块
    perception = create_perception()
    brain = create_brain()
    actuator = create_actuator()
    
    print("  模块交互流程:")
    print("    Brain -> 需要屏幕状态 -> Perception")
    print("    Brain -> 生成动作 -> Actuator")
    print("    Actuator -> 执行动作 -> 真实操作")
    print("    Perception -> 捕获结果 -> Verifier")
    
    # 模拟交互
    state = perception.capture()
    action = brain.decide(state, "测试任务")
    
    print(f"\n  交互结果:")
    print(f"    感知到: {len(state.texts)}个文字")
    print(f"    决策: {action.action.value}")
    
    print()


def example_configuration():
    """示例：配置管理"""
    print("示例4：配置管理")
    
    # 各模块配置
    configs = {
        "perception": {
            "ocr_engine": "tesseract"
        },
        "brain": {},
        "actuator": {},
        "verifier": {
            "screenshot_dir": "screenshots",
            "diff_threshold": 0.1
        },
        "memory": {
            "storage_path": "memory",
            "max_history": 100
        },
        "security": {
            "log_dir": "security_logs",
            "auto_approve": True
        },
        "orchestrator": {
            "max_retries": 3
        }
    }
    
    print("  模块配置:")
    for module, config in configs.items():
        print(f"    {module}: {config}")
    
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("完整集成示例")
    print("=" * 60)
    print()
    
    example_simple_task()
    example_manual_workflow()
    example_module_interaction()
    example_configuration()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
