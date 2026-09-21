"""
测试文件操作
"""

import sys
import os
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from modules.memory import MemoryModule


def test_file_operations():
    """测试文件操作"""
    print("测试文件操作...")
    
    # 创建记忆模块
    config = {"storage_path": "test_storage"}
    memory = MemoryModule(config)
    memory.initialize()
    
    # 测试写入文件
    print("测试写入文件...")
    test_content = "Hello World\n这是一个测试文件。"
    result = memory.write_file("test_file.txt", test_content)
    print(f"写入结果: {result}")
    
    # 检查文件是否存在
    if os.path.exists("test_file.txt"):
        print("文件已创建")
        with open("test_file.txt", "r", encoding="utf-8") as f:
            content = f.read()
        print(f"文件内容: {content}")
    else:
        print("文件未创建")
    
    # 测试读取文件
    print("\n测试读取文件...")
    result = memory.read_file("test_file.txt")
    print(f"读取结果: {result}")
    
    # 测试追加文件
    print("\n测试追加文件...")
    result = memory.append_file("test_file.txt", "\n追加的内容")
    print(f"追加结果: {result}")
    
    # 再次读取
    result = memory.read_file("test_file.txt")
    print(f"最终内容: {result.get('content', '')}")


if __name__ == "__main__":
    test_file_operations()