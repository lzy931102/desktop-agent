"""
安全层使用示例
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Action, ActionType
from modules.security import create_security


def example_basic_usage():
    """示例：基本用法"""
    print("示例1：基本用法")
    
    security = create_security({"auto_approve": True})
    
    # 检查安全动作
    action = Action(action=ActionType.CLICK, target={"text": "确定"})
    result = security.check(action)
    print(f"  安全动作检查: {result}")
    
    # 检查危险动作
    action = Action(action=ActionType.KEY, keys=["alt", "f4"])
    result = security.check(action)
    print(f"  危险动作检查: {result}")
    print()


def example_auto_approve():
    """示例：自动审批"""
    print("示例2：自动审批")
    
    # 自动审批模式
    security = create_security({"auto_approve": True})
    
    action = Action(action=ActionType.KEY, keys=["alt", "f4"])
    result = security.check(action)
    print(f"  自动审批模式: {result}")
    
    # 手动审批模式
    security.set_auto_approve(False)
    print("  手动审批模式: 需要用户输入")
    print()


def example_logging():
    """示例：操作日志"""
    print("示例3：操作日志")
    
    security = create_security({"log_dir": "example_security_logs"})
    
    # 记录多个操作
    actions = [
        Action(action=ActionType.CLICK, target={"text": "确定"}),
        Action(action=ActionType.TYPE, text="Hello"),
        Action(action=ActionType.KEY, keys=["ctrl", "s"])
    ]
    
    for action in actions:
        security.log_action(action, success=True)
        print(f"  记录: {action.action.value}")
    
    # 获取日志
    logs = security.get_logs()
    print(f"  总日志数: {len(logs)}")
    
    # 清理
    import shutil
    import os
    if os.path.exists("example_security_logs"):
        shutil.rmtree("example_security_logs")
    print()


def example_approval_config():
    """示例：审批配置"""
    print("示例4：审批配置")
    
    security = create_security()
    
    # 添加需要审批的动作
    security.add_approval_required(ActionType.CLICK)
    print(f"  需要审批的动作: {[a.value for a in security.approval_required]}")
    
    # 移除
    security.remove_approval_required(ActionType.CLICK)
    print(f"  移除后: {[a.value for a in security.approval_required]}")
    print()


def example_workflow():
    """示例：完整工作流"""
    print("示例5：安全层工作流")
    
    security = create_security({"auto_approve": True})
    
    # 模拟一个操作序列
    actions = [
        ("打开记事本", Action(action=ActionType.KEY, keys=["win", "r"])),
        ("输入notepad", Action(action=ActionType.TYPE, text="notepad")),
        ("按Enter", Action(action=ActionType.KEY, keys=["enter"])),
        ("输入文字", Action(action=ActionType.TYPE, text="Hello")),
        ("保存", Action(action=ActionType.KEY, keys=["ctrl", "s"])),
    ]
    
    for desc, action in actions:
        result = security.check(action)
        print(f"  {desc}: {'允许' if result else '拒绝'}")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("安全层使用示例")
    print("=" * 60)
    print()
    
    example_basic_usage()
    example_auto_approve()
    example_logging()
    example_approval_config()
    example_workflow()
    
    print("=" * 60)
    print("示例结束")
    print("=" * 60)
