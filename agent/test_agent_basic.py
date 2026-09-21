"""
测试AGENT基本功能
"""

import sys
import json
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import AgentScheduler


def main():
    """主测试函数"""
    print("测试电脑操作AGENT基本功能...")
    
    # 配置
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
    
    # 创建调度器
    print("1. 创建调度器...")
    scheduler = AgentScheduler(config)
    scheduler.initialize()
    print("调度器创建成功")
    
    # 测试核心模块
    print("\n2. 测试核心模块...")
    
    # 截屏
    print("   测试截屏...")
    result = scheduler.core.screenshot("test_screenshot.png")
    print(f"   截屏结果: {result.get('success')}")
    
    # 移动鼠标
    print("   测试移动鼠标...")
    result = scheduler.core.move_to(100, 100)
    print(f"   移动结果: {result.get('success')}")
    
    # 获取屏幕尺寸
    print("   获取屏幕尺寸...")
    width, height = scheduler.core.get_screen_size()
    print(f"   屏幕尺寸: {width}x{height}")
    
    # 测试感知模块
    print("\n3. 测试感知模块...")
    
    # 截屏分析
    print("   测试截屏分析...")
    result = scheduler.perception.take_screenshot()
    print(f"   截屏分析结果: {result.get('success')}")
    
    # 测试记忆模块
    print("\n4. 测试记忆模块...")
    
    # 保存任务状态
    print("   测试保存任务状态...")
    result = scheduler.memory.save_task_state("test_task", {
        "status": "running",
        "progress": 0.5
    })
    print(f"   保存结果: {result.get('success')}")
    
    # 加载任务状态
    print("   测试加载任务状态...")
    result = scheduler.memory.load_task_state("test_task")
    print(f"   加载结果: {result.get('success')}")
    if result.get('success'):
        state = result.get('state', {})
        print(f"   任务状态: {state.get('state', {}).get('status')}")
    
    # 测试调度器
    print("\n5. 测试调度器...")
    
    # 获取状态
    print("   测试获取状态...")
    result = scheduler.get_status()
    print(f"   状态结果: {result.get('success')}")
    
    print("\n=== 所有测试完成 ===")
    print("AGENT基本功能正常！")


if __name__ == "__main__":
    main()