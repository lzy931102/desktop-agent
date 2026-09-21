"""
感知层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import ScreenState
from modules.perception_v1 import BasicPerception, create_perception


def test_perception_creation():
    """测试感知层创建"""
    print("测试感知层创建...")
    
    perception = create_perception()
    assert perception is not None
    assert isinstance(perception, BasicPerception)
    
    print("[PASS] 感知层创建测试通过")


def test_capture():
    """测试截屏功能"""
    print("测试截屏功能...")
    
    perception = create_perception()
    
    # 捕获屏幕状态
    state = perception.capture()
    
    assert isinstance(state, ScreenState)
    assert state.screenshot is not None
    assert len(state.screenshot) > 0  # base64编码不为空
    
    print(f"  截图大小: {len(state.screenshot)} 字符")
    print(f"  截图路径: {state.screenshot_path}")
    print(f"  识别文字数: {len(state.texts)}")
    print(f"  识别元素数: {len(state.elements)}")
    
    print("[PASS] 截屏功能测试通过")


def test_find_text():
    """测试文字查找"""
    print("测试文字查找...")
    
    perception = create_perception()
    
    # 先截屏
    state = perception.capture()
    
    # 如果有识别到文字，尝试查找
    if state.texts:
        first_text = state.texts[0]["text"]
        print(f"  尝试查找文字: {first_text}")
        
        result = perception.find_text(first_text)
        if result:
            print(f"  找到文字位置: {result.get('bbox')}")
        else:
            print(f"  未找到文字（可能需要OCR支持）")
    
    print("[PASS] 文字查找测试通过")


def test_find_element():
    """测试元素查找"""
    print("测试元素查找...")
    
    perception = create_perception()
    
    # 通过文字查找
    result = perception.find_element({"text": "test"})
    print(f"  通过文字查找: {result}")
    
    # 通过引用查找
    result = perception.find_element({"ref": "hwnd:12345"})
    print(f"  通过引用查找: {result}")
    
    print("[PASS] 元素查找测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("感知层测试")
    print("=" * 50)
    
    try:
        test_perception_creation()
        test_capture()
        test_find_text()
        test_find_element()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
