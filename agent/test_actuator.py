"""
执行层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Action, ActionType, create_click_action, create_type_action, create_key_action
from modules.actuator import PyAutoGUIActuator, create_actuator


def test_actuator_creation():
    """测试执行层创建"""
    print("测试执行层创建...")
    
    actuator = create_actuator()
    assert actuator is not None
    assert isinstance(actuator, PyAutoGUIActuator)
    
    print("[PASS] 执行层创建测试通过")


def test_actuator_methods():
    """测试执行层方法"""
    print("测试执行层方法...")
    
    actuator = create_actuator()
    
    # 测试点击
    result = actuator.click(100, 100)
    assert isinstance(result, bool)
    
    # 测试输入
    result = actuator.type_text("test")
    assert isinstance(result, bool)
    
    # 测试快捷键
    result = actuator.press_keys(["ctrl", "c"])
    assert isinstance(result, bool)
    
    # 测试屏幕尺寸
    width, height = actuator.get_screen_size()
    assert width > 0
    assert height > 0
    
    print("[PASS] 执行层方法测试通过")


def test_execute_click():
    """测试执行点击动作"""
    print("测试执行点击动作...")
    
    actuator = create_actuator()
    
    # 创建点击动作
    action = create_click_action({"x": 100, "y": 100})
    
    # 执行动作
    result = actuator.execute(action)
    assert isinstance(result, bool)
    
    print("[PASS] 执行点击动作测试通过")


def test_execute_type():
    """测试执行输入动作"""
    print("测试执行输入动作...")
    
    actuator = create_actuator()
    
    # 创建输入动作
    action = create_type_action("hello")
    
    # 执行动作
    result = actuator.execute(action)
    assert isinstance(result, bool)
    
    print("[PASS] 执行输入动作测试通过")


def test_execute_key():
    """测试执行快捷键动作"""
    print("测试执行快捷键动作...")
    
    actuator = create_actuator()
    
    # 创建快捷键动作
    action = create_key_action(["ctrl", "c"])
    
    # 执行动作
    result = actuator.execute(action)
    assert isinstance(result, bool)
    
    print("[PASS] 执行快捷键动作测试通过")


def test_element_cache():
    """测试元素缓存"""
    print("测试元素缓存...")
    
    actuator = create_actuator()
    
    # 更新缓存
    elements = [
        {"ref": "hwnd:12345", "bbox": [100, 200, 160, 230]},
        {"ref": "hwnd:12346", "bbox": [300, 400, 360, 430]}
    ]
    actuator.update_element_cache(elements)
    
    # 验证缓存
    assert "hwnd:12345" in actuator._element_cache
    assert "hwnd:12346" in actuator._element_cache
    
    # 清空缓存
    actuator.clear_element_cache()
    assert len(actuator._element_cache) == 0
    
    print("[PASS] 元素缓存测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("执行层测试")
    print("=" * 50)
    
    try:
        test_actuator_creation()
        test_actuator_methods()
        test_execute_click()
        test_execute_type()
        test_execute_key()
        test_element_cache()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
