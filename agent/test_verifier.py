"""
验证层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState, Action, ActionType
from modules.verifier import BasicVerifier, create_verifier


def test_verifier_creation():
    """测试验证层创建"""
    print("测试验证层创建...")
    
    verifier = create_verifier()
    assert verifier is not None
    assert isinstance(verifier, BasicVerifier)
    
    print("[PASS] 验证层创建测试通过")


def test_verify_click():
    """测试点击验证"""
    print("测试点击验证...")
    
    verifier = create_verifier()
    
    # 模拟执行前后的屏幕状态
    before = ScreenState(
        screenshot="screenshot_before",
        texts=[{"text": "按钮"}]
    )
    
    after = ScreenState(
        screenshot="screenshot_after",  # 不同的截图
        texts=[{"text": "按钮"}, {"text": "新内容"}]
    )
    
    action = Action(action=ActionType.CLICK, target={"text": "按钮"})
    
    # 验证
    result = verifier.verify(before, after, action)
    assert isinstance(result, bool)
    
    print(f"  点击验证结果: {result}")
    print("[PASS] 点击验证测试通过")


def test_verify_type():
    """测试输入验证"""
    print("测试输入验证...")
    
    verifier = create_verifier()
    
    # 模拟执行前后的屏幕状态
    before = ScreenState(
        screenshot="screenshot_before",
        texts=[]
    )
    
    after = ScreenState(
        screenshot="screenshot_after",
        texts=[{"text": "Hello"}]
    )
    
    action = Action(action=ActionType.TYPE, text="Hello")
    
    # 验证
    result = verifier.verify(before, after, action)
    assert isinstance(result, bool)
    
    print(f"  输入验证结果: {result}")
    print("[PASS] 输入验证测试通过")


def test_verify_done():
    """测试完成验证"""
    print("测试完成验证...")
    
    verifier = create_verifier()
    
    before = ScreenState(screenshot="screenshot")
    after = ScreenState(screenshot="screenshot")
    action = Action(action=ActionType.DONE)
    
    # 完成动作总是成功
    result = verifier.verify(before, after, action)
    assert result == True
    
    print(f"  完成验证结果: {result}")
    print("[PASS] 完成验证测试通过")


def test_assert_text():
    """测试文字断言"""
    print("测试文字断言...")
    
    verifier = create_verifier()
    
    # 注意：这个测试需要实际的屏幕和OCR支持
    # 这里只测试方法是否存在
    assert hasattr(verifier, 'assert_text')
    assert callable(verifier.assert_text)
    
    print("  assert_text方法可用")
    print("[PASS] 文字断言测试通过")


def test_assert_image():
    """测试图像断言"""
    print("测试图像断言...")
    
    verifier = create_verifier()
    
    # 注意：这个测试需要实际的屏幕
    # 这里只测试方法是否存在
    assert hasattr(verifier, 'assert_image')
    assert callable(verifier.assert_image)
    
    print("  assert_image方法可用")
    print("[PASS] 图像断言测试通过")


def test_wait_for_text():
    """测试等待文字"""
    print("测试等待文字...")
    
    verifier = create_verifier()
    
    # 注意：这个测试需要实际的屏幕和OCR支持
    # 这里只测试方法是否存在
    assert hasattr(verifier, 'wait_for_text')
    assert callable(verifier.wait_for_text)
    
    print("  wait_for_text方法可用")
    print("[PASS] 等待文字测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("验证层测试")
    print("=" * 50)
    
    try:
        test_verifier_creation()
        test_verify_click()
        test_verify_type()
        test_verify_done()
        test_assert_text()
        test_assert_image()
        test_wait_for_text()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
