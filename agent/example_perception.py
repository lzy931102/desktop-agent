"""
感知层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from modules.perception_v1 import create_perception


def example_capture():
    """示例：截屏并分析"""
    print("示例1：截屏并分析")
    
    perception = create_perception()
    
    # 捕获屏幕状态
    state = perception.capture()
    
    print(f"  截图路径: {state.screenshot_path}")
    print(f"  截图base64大小: {len(state.screenshot)} 字符")
    print(f"  识别文字数: {len(state.texts)}")
    print(f"  识别元素数: {len(state.elements)}")
    print(f"  当前窗口: {state.active_window.get('title', 'N/A')}")
    
    # 显示识别到的文字
    if state.texts:
        print("  识别到的文字:")
        for text in state.texts[:5]:  # 只显示前5个
            print(f"    - {text['text']} (置信度: {text.get('confidence', 0):.2f})")
    
    # 显示识别到的元素
    if state.elements:
        print("  识别到的元素:")
        for elem in state.elements[:5]:
            print(f"    - {elem.get('type', 'unknown')}: {elem.get('name', 'N/A')}")
    print()


def example_find_text():
    """示例：查找文字"""
    print("示例2：查找文字")
    
    perception = create_perception()
    
    # 先截屏
    state = perception.capture()
    
    # 尝试查找文字
    if state.texts:
        first_text = state.texts[0]["text"]
        print(f"  查找文字: {first_text}")
        
        result = perception.find_text(first_text)
        if result:
            print(f"  找到位置: {result.get('bbox')}")
            print(f"  中心点: {result.get('center')}")
        else:
            print("  未找到文字")
    else:
        print("  屏幕上没有识别到文字")
    print()


def example_find_element():
    """示例：查找元素"""
    print("示例3：查找元素")
    
    perception = create_perception()
    
    # 通过文字查找
    print("  通过文字查找 '确定':")
    result = perception.find_element({"text": "确定"})
    if result:
        print(f"    找到: {result}")
    else:
        print("    未找到")
    
    # 通过图像查找（需要准备图像文件）
    print("  通过图像查找:")
    result = perception.find_element({"image": "button.png"})
    if result:
        print(f"    找到: {result}")
    else:
        print("    未找到或图像文件不存在")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例4：感知层工作流")
    
    perception = create_perception()
    
    print("  1. 捕获屏幕状态")
    state = perception.capture()
    
    print("  2. 分析屏幕内容")
    print(f"     - 截图已保存到: {state.screenshot_path}")
    print(f"     - 识别到 {len(state.texts)} 个文字")
    print(f"     - 识别到 {len(state.elements)} 个元素")
    
    print("  3. 查找目标元素")
    # 这里可以集成Brain模块进行决策
    # action = brain.decide(state, "点击确定按钮")
    
    print("  4. 返回结果给调度层")
    # 调度层会使用这个状态进行下一步操作
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("感知层使用示例")
    print("=" * 60)
    print()
    
    example_capture()
    example_find_text()
    example_find_element()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
