"""
测试AGENT各模块功能
"""

import sys
import json
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import AgentScheduler


def test_core_module():
    """测试核心模块"""
    print("\n=== 测试核心模块 ===")
    
    config = {
        "core": {},
        "perception": {"ocr_engine": "tesseract"},
        "cognition": {
            "provider": "zhipu",
            "api_key": "YOUR_API_KEY_HERE",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4-flash"
        },
        "memory": {"storage_path": "test_storage"}
    }
    
    scheduler = AgentScheduler(config)
    scheduler.initialize()
    
    # 测试截屏
    print("测试截屏...")
    result = scheduler.core.screenshot("test_screenshot.png")
    print(f"截屏结果: {result}")
    
    # 测试鼠标移动
    print("测试鼠标移动...")
    result = scheduler.core.move_to(100, 100)
    print(f"移动结果: {result}")
    
    return scheduler


def test_perception_module(scheduler):
    """测试感知模块"""
    print("\n=== 测试感知模块 ===")
    
    # 测试截屏分析
    print("测试截屏分析...")
    result = scheduler.perception.take_screenshot()
    print(f"截屏结果: {result.get('success')}")
    
    # 测试OCR
    print("测试OCR...")
    result = scheduler.perception.ocr_screen()
    print(f"OCR结果: {result.get('success')}")
    if result.get('success'):
        print(f"识别文字: {result.get('text', '')[:100]}...")
    
    return result


def test_memory_module(scheduler):
    """测试记忆模块"""
    print("\n=== 测试记忆模块 ===")
    
    # 测试文件写入
    print("测试文件写入...")
    result = scheduler.memory.write_file("test_file.txt", "Hello World")
    print(f"写入结果: {result}")
    
    # 测试文件读取
    print("测试文件读取...")
    result = scheduler.memory.read_file("test_file.txt")
    print(f"读取结果: {result}")
    
    # 测试任务状态保存
    print("测试任务状态保存...")
    result = scheduler.memory.save_task_state("test_task", {"status": "running"})
    print(f"保存结果: {result}")
    
    # 测试任务状态加载
    print("测试任务状态加载...")
    result = scheduler.memory.load_task_state("test_task")
    print(f"加载结果: {result}")
    
    return result


def main():
    """主测试函数"""
    print("开始测试电脑操作AGENT...")
    
    try:
        # 测试核心模块
        scheduler = test_core_module()
        
        # 测试感知模块
        test_perception_module(scheduler)
        
        # 测试记忆模块
        test_memory_module(scheduler)
        
        print("\n=== 所有测试完成 ===")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()