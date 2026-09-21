"""
电脑操作AGENT主入口
"""

import sys
import json
import logging
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from scheduler import AgentScheduler


def setup_logging(level="INFO"):
    """设置日志"""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('agent.log', encoding='utf-8')
        ]
    )


def load_config(config_file="agent_config.json"):
    """加载配置"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Config file {config_file} not found, using default config")
        return {
            "core": {},
            "perception": {"ocr_engine": "tesseract"},
            "cognition": {
                "provider": "zhipu",
                "api_key": "your_api_key_here",
                "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4-flash"
            },
            "memory": {"storage_path": "agent_storage"}
        }


def main():
    """主函数"""
    # 设置日志
    setup_logging()
    
    # 加载配置
    config = load_config()
    
    # 创建调度器
    scheduler = AgentScheduler(config)
    scheduler.initialize()
    
    print("电脑操作AGENT已启动")
    print("命令：")
    print("  start <任务描述> - 开始执行任务")
    print("  stop - 停止当前任务")
    print("  status - 查看状态")
    print("  once - 执行一次循环")
    print("  quit - 退出程序")
    
    # 交互循环
    while True:
        try:
            user_input = input("\n> ").strip()
            
            if not user_input:
                continue
            
            parts = user_input.split(maxsplit=1)
            command = parts[0].lower()
            
            if command == "quit" or command == "exit":
                print("退出程序")
                break
            
            elif command == "start":
                if len(parts) < 2:
                    print("请提供任务描述")
                    continue
                task = parts[1]
                result = scheduler.start_task(task)
                print(f"结果: {result}")
                
                # 开始执行循环
                print("开始执行任务...")
                scheduler.run()
            
            elif command == "stop":
                result = scheduler.stop_task()
                print(f"结果: {result}")
            
            elif command == "status":
                result = scheduler.get_status()
                print(f"状态: {result}")
            
            elif command == "once":
                result = scheduler.execute_once()
                print(f"结果: {result}")
            
            else:
                print(f"未知命令: {command}")
        
        except KeyboardInterrupt:
            print("\n程序被中断")
            break
        except Exception as e:
            print(f"错误: {e}")


if __name__ == "__main__":
    main()