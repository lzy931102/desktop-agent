"""
验证层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.verifier import create_verifier


def example_basic_verification():
    """示例：基本验证"""
    print("示例1：基本验证")
    
    verifier = create_verifier()
    
    # 模拟执行前后的屏幕状态
    before = ScreenState(
        screenshot="screenshot_before_base64...",
        texts=[{"text": "按钮", "bbox": [100, 200, 160, 230]}],
        elements=[{"type": "button", "name": "按钮"}]
    )
    
    after = ScreenState(
        screenshot="screenshot_after_base64...",
        texts=[{"text": "按钮", "bbox": [100, 200, 160, 230]}, {"text": "新内容"}],
        elements=[{"type": "button", "name": "按钮"}, {"type": "text", "name": "新内容"}]
    )
    
    # 点击动作
    action = Action(action=ActionType.CLICK, target={"text": "按钮"})
    
    # 验证
    result = verifier.verify(before, after, action)
    
    print(f"  动作: {action.action.value}")
    print(f"  验证结果: {'成功' if result else '失败'}")
    print()


def example_type_verification():
    """示例：输入验证"""
    print("示例2：输入验证")
    
    verifier = create_verifier()
    
    before = ScreenState(
        screenshot="screenshot_before...",
        texts=[]
    )
    
    after = ScreenState(
        screenshot="screenshot_after...",
        texts=[{"text": "Hello World"}]
    )
    
    action = Action(action=ActionType.TYPE, text="Hello World")
    
    result = verifier.verify(before, after, action)
    
    print(f"  输入文字: {action.text}")
    print(f"  验证结果: {'成功' if result else '失败'}")
    print()


def example_assertions():
    """示例：断言功能"""
    print("示例3：断言功能")
    
    verifier = create_verifier()
    
    # 注意：这些断言需要实际的屏幕和OCR支持
    # 这里只展示API用法
    
    print("  断言API:")
    print("    - assert_text(text, timeout): 断言屏幕存在指定文字")
    print("    - assert_image(image_path, timeout): 断言屏幕存在指定图像")
    print("    - wait_for_text(text, timeout): 等待文字出现")
    print("    - wait_for_image(image_path, timeout): 等待图像出现")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例4：验证层工作流")
    
    verifier = create_verifier()
    
    # 模拟一个完整的验证流程
    print("  1. 执行前截屏")
    before = ScreenState(
        screenshot="screenshot_before...",
        texts=[{"text": "确定"}]
    )
    
    print("  2. 执行动作")
    action = Action(action=ActionType.CLICK, target={"text": "确定"})
    
    print("  3. 执行后截屏")
    after = ScreenState(
        screenshot="screenshot_after...",
        texts=[{"text": "确定"}, {"text": "操作成功"}]
    )
    
    print("  4. 验证结果")
    result = verifier.verify(before, after, action)
    
    print(f"  验证结果: {'成功' if result else '失败'}")
    
    if not result:
        print("  5. 验证失败，可能需要重试或报错")
    else:
        print("  5. 验证成功，继续下一步")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("验证层使用示例")
    print("=" * 60)
    print()
    
    example_basic_verification()
    example_type_verification()
    example_assertions()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
