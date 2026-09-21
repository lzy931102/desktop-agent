"""
记忆层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.memory_json import JSONMemory, create_memory


def test_memory_creation():
    """测试记忆层创建"""
    print("测试记忆层创建...")
    
    memory = create_memory()
    assert memory is not None
    assert isinstance(memory, JSONMemory)
    
    print("[PASS] 记忆层创建测试通过")


def test_save_load():
    """测试保存和加载"""
    print("测试保存和加载...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 保存数据
    memory.save("test_key", {"value": "hello", "number": 123})
    
    # 加载数据
    data = memory.load("test_key")
    assert data is not None
    assert data["value"] == "hello"
    assert data["number"] == 123
    
    print(f"  保存并加载: {data}")
    
    # 清理
    memory.clear()
    
    print("[PASS] 保存和加载测试通过")


def test_save_state():
    """测试保存执行状态"""
    print("测试保存执行状态...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 创建状态和动作
    state = ScreenState(
        screenshot="base64...",
        texts=[{"text": "确定"}],
        elements=[{"type": "button", "name": "确定"}],
        active_window={"title": "记事本"}
    )
    
    action = Action(action=ActionType.CLICK, target={"text": "确定"})
    
    # 保存状态
    memory.save_state(state, action, success=True)
    
    # 获取历史记录
    history = memory.get_history()
    assert len(history) == 1
    
    print(f"  历史记录数: {len(history)}")
    print(f"  最新记录: {history[0]}")
    
    # 清理
    memory.clear()
    
    print("[PASS] 保存执行状态测试通过")


def test_history():
    """测试历史记录"""
    print("测试历史记录...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 保存多条记录
    for i in range(5):
        state = ScreenState(screenshot=f"screenshot_{i}")
        action = Action(action=ActionType.TYPE, text=f"text_{i}")
        memory.save_state(state, action, success=True)
    
    # 获取历史记录
    history = memory.get_history(limit=3)
    assert len(history) == 3
    
    print(f"  获取最近3条记录: {len(history)}条")
    
    # 清理
    memory.clear()
    
    print("[PASS] 历史记录测试通过")


def test_task():
    """测试任务保存"""
    print("测试任务保存...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 保存任务
    task_data = {
        "goal": "打开记事本",
        "status": "running",
        "steps": 3
    }
    memory.save_task("task_001", task_data)
    
    # 加载任务
    task = memory.load_task("task_001")
    assert task is not None
    assert task["goal"] == "打开记事本"
    
    print(f"  任务数据: {task}")
    
    # 清理
    memory.clear()
    
    print("[PASS] 任务保存测试通过")


def test_context():
    """测试上下文保存"""
    print("测试上下文保存...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 保存上下文
    context_data = {
        "current_step": 2,
        "history": ["step1", "step2"]
    }
    memory.save_context("session_001", context_data)
    
    # 加载上下文
    context = memory.load_context("session_001")
    assert context is not None
    assert context["current_step"] == 2
    
    print(f"  上下文数据: {context}")
    
    # 清理
    memory.clear()
    
    print("[PASS] 上下文保存测试通过")


def test_clear():
    """测试清空功能"""
    print("测试清空功能...")
    
    memory = create_memory({"storage_path": "test_memory"})
    
    # 保存一些数据
    memory.save("key1", "value1")
    memory.save("key2", "value2")
    
    # 清空
    memory.clear()
    
    # 验证已清空
    assert memory.load("key1") is None
    assert memory.load("key2") is None
    
    print("[PASS] 清空功能测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("记忆层测试")
    print("=" * 50)
    
    try:
        test_memory_creation()
        test_save_load()
        test_save_state()
        test_history()
        test_task()
        test_context()
        test_clear()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
