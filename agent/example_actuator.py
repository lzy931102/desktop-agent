"""
执行层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Action, ActionType, create_click_action, create_type_action, create_key_action
from modules.actuator import create_actuator


def example_basic_operations():
    """示例：基本操作"""
    print("示例1：基本操作")
    
    actuator = create_actuator()
    
    # 获取屏幕尺寸
    width, height = actuator.get_screen_size()
    print(f"  屏幕尺寸: {width}x{height}")
    
    # 截屏
    actuator.screenshot("screenshots/example.png")
    print("  截屏完成")
    print()


def example_click_by_coordinates():
    """示例：按坐标点击"""
    print("示例2：按坐标点击")
    
    actuator = create_actuator()
    
    # 直接坐标点击
    action = create_click_action({"x": 100, "y": 100})
    result = actuator.execute(action)
    print(f"  点击结果: {result}")
    print()


def example_type_text():
    """示例：输入文字"""
    print("示例3：输入文字")
    
    actuator = create_actuator()
    
    # 输入文字
    action = create_type_action("Hello, World!")
    result = actuator.execute(action)
    print(f"  输入结果: {result}")
    print()


def example_hotkey():
    """示例：快捷键"""
    print("示例4：快捷键")
    
    actuator = create_actuator()
    
    # Ctrl+C
    action = create_key_action(["ctrl", "c"])
    result = actuator.execute(action)
    print(f"  Ctrl+C结果: {result}")
    
    # Ctrl+V
    action = create_key_action(["ctrl", "v"])
    result = actuator.execute(action)
    print(f"  Ctrl+V结果: {result}")
    print()


def example_element_cache():
    """示例：元素缓存"""
    print("示例5：元素缓存")
    
    actuator = create_actuator()
    
    # 模拟感知层输出的元素
    elements = [
        {"ref": "hwnd:12345", "bbox": [100, 200, 160, 230], "type": "button", "name": "确定"},
        {"ref": "hwnd:12346", "bbox": [300, 400, 360, 430], "type": "button", "name": "取消"}
    ]
    
    # 更新缓存
    actuator.update_element_cache(elements)
    print(f"  缓存元素数: {len(actuator._element_cache)}")
    
    # 通过ref点击（从缓存获取坐标）
    action = create_click_action({"ref": "hwnd:12345"})
    result = actuator.execute(action)
    print(f"  通过ref点击结果: {result}")
    
    # 清空缓存
    actuator.clear_element_cache()
    print(f"  清空后缓存数: {len(actuator._element_cache)}")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例6：完整工作流")
    
    actuator = create_actuator()
    
    # 模拟一个简单的操作流程
    print("  1. 打开记事本 (Win+R -> notepad -> Enter)")
    
    # Win+R打开运行对话框
    action = create_key_action(["win", "r"])
    actuator.execute(action)
    
    # 输入notepad
    import time
    time.sleep(0.5)
    action = create_type_action("notepad")
    actuator.execute(action)
    
    # 按Enter
    action = create_key_action(["enter"])
    actuator.execute(action)
    
    time.sleep(1)
    print("  2. 记事本已打开")
    
    # 输入文字
    action = create_type_action("Hello from Agent!")
    actuator.execute(action)
    print("  3. 已输入文字")
    
    # Ctrl+S保存
    action = create_key_action(["ctrl", "s"])
    actuator.execute(action)
    print("  4. 已发送保存命令")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("执行层使用示例")
    print("=" * 60)
    print()
    
    example_basic_operations()
    example_click_by_coordinates()
    example_type_text()
    example_hotkey()
    example_element_cache()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
