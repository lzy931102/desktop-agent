"""
记忆层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.memory_json import create_memory


def example_basic_save_load():
    """示例：基本保存和加载"""
    print("示例1：基本保存和加载")
    
    memory = create_memory({"storage_path": "example_memory"})
    
    # 保存数据
    memory.save("user_config", {
        "theme": "dark",
        "language": "zh-CN",
        "font_size": 14
    })
    
    # 加载数据
    config = memory.load("user_config")
    print(f"  加载配置: {config}")
    
    # 清理
    memory.clear()
    print()


def example_execution_state():
    """示例：保存执行状态"""
    print("示例2：保存执行状态")
    
    memory = create_memory({"storage_path": "example_memory"})
    
    # 模拟执行过程
    for i in range(3):
        state = ScreenState(
            screenshot=f"screenshot_{i}",
            texts=[{"text": f"步骤{i+1}"}],
            elements=[],
            active_window={"title": "记事本"}
        )
        
        action = Action(
            action=ActionType.CLICK if i % 2 == 0 else ActionType.TYPE,
            target={"text": f"按钮{i+1}"} if i % 2 == 0 else None,
            text=f"输入内容{i+1}" if i % 2 == 1 else None
        )
        
        memory.save_state(state, action, success=True)
        print(f"  保存步骤{i+1}")
    
    # 获取历史记录
    history = memory.get_history()
    print(f"  历史记录数: {len(history)}")
    
    # 清理
    memory.clear()
    print()


def example_task_management():
    """示例：任务管理"""
    print("示例3：任务管理")
    
    memory = create_memory({"storage_path": "example_memory"})
    
    # 保存任务
    task = {
        "task_id": "task_001",
        "goal": "打开记事本并输入Hello World",
        "status": "running",
        "current_step": 1,
        "total_steps": 4,
        "created_at": "2024-01-01T10:00:00"
    }
    memory.save_task("task_001", task)
    
    # 加载任务
    loaded_task = memory.load_task("task_001")
    print(f"  任务状态: {loaded_task['status']}")
    print(f"  当前步骤: {loaded_task['current_step']}/{loaded_task['total_steps']}")
    
    # 更新任务
    loaded_task["status"] = "completed"
    loaded_task["current_step"] = 4
    memory.save_task("task_001", loaded_task)
    
    # 清理
    memory.clear()
    print()


def example_context():
    """示例：上下文管理"""
    print("示例4：上下文管理")
    
    memory = create_memory({"storage_path": "example_memory"})
    
    # 保存会话上下文
    context = {
        "session_id": "session_001",
        "user": "admin",
        "current_task": "task_001",
        "history": [
            {"action": "click", "target": "确定"},
            {"action": "type", "text": "Hello"},
            {"action": "hotkey", "keys": ["ctrl", "s"]}
        ]
    }
    memory.save_context("session_001", context)
    
    # 加载上下文
    loaded_context = memory.load_context("session_001")
    print(f"  会话用户: {loaded_context['user']}")
    print(f"  历史操作数: {len(loaded_context['history'])}")
    
    # 清理
    memory.clear()
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例5：记忆层工作流")
    
    memory = create_memory({"storage_path": "example_memory"})
    
    print("  1. 初始化任务")
    task = {
        "goal": "打开记事本",
        "status": "running",
        "steps": []
    }
    memory.save_task("workflow_task", task)
    
    print("  2. 执行步骤1")
    state1 = ScreenState(screenshot="screenshot1", texts=[{"text": "Win+R"}])
    action1 = Action(action=ActionType.KEY, keys=["win", "r"])
    memory.save_state(state1, action1, success=True)
    
    print("  3. 执行步骤2")
    state2 = ScreenState(screenshot="screenshot2", texts=[{"text": "notepad"}])
    action2 = Action(action=ActionType.TYPE, text="notepad")
    memory.save_state(state2, action2, success=True)
    
    print("  4. 获取执行历史")
    history = memory.get_history()
    print(f"     历史记录: {len(history)}条")
    
    print("  5. 完成任务")
    task["status"] = "completed"
    memory.save_task("workflow_task", task)
    
    # 清理
    memory.clear()
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("记忆层使用示例")
    print("=" * 60)
    print()
    
    example_basic_save_load()
    example_execution_state()
    example_task_management()
    example_context()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
