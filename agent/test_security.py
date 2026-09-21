"""
安全层测试
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Action, ActionType
from modules.security import BasicSecurity, create_security


def test_security_creation():
    """测试安全层创建"""
    print("测试安全层创建...")
    
    security = create_security()
    assert security is not None
    assert isinstance(security, BasicSecurity)
    
    print("[PASS] 安全层创建测试通过")


def test_check_safe_action():
    """测试安全动作检查"""
    print("测试安全动作检查...")
    
    security = create_security({"auto_approve": True})
    
    # 安全动作
    action = Action(action=ActionType.CLICK, target={"text": "确定"})
    
    # 检查
    result = security.check(action)
    assert result == True
    
    print(f"  安全动作检查: {result}")
    print("[PASS] 安全动作检查测试通过")


def test_check_dangerous_action():
    """测试危险动作检查"""
    print("测试危险动作检查...")
    
    security = create_security({"auto_approve": True})
    
    # 危险动作 (Alt+F4)
    action = Action(action=ActionType.KEY, keys=["alt", "f4"])
    
    # 检查
    result = security.check(action)
    assert result == True  # 自动审批模式
    
    print(f"  危险动作检查: {result}")
    print("[PASS] 危险动作检查测试通过")


def test_log_action():
    """测试操作日志"""
    print("测试操作日志...")
    
    security = create_security({"log_dir": "test_security_logs"})
    
    # 记录操作
    action = Action(action=ActionType.CLICK, target={"text": "确定"})
    security.log_action(action, success=True)
    
    # 获取日志
    logs = security.get_logs()
    assert len(logs) > 0
    
    print(f"  日志条数: {len(logs)}")
    print(f"  最新日志: {logs[-1]}")
    
    # 清理
    import os
    import shutil
    if os.path.exists("test_security_logs"):
        shutil.rmtree("test_security_logs")
    
    print("[PASS] 操作日志测试通过")


def test_auto_approve():
    """测试自动审批"""
    print("测试自动审批...")
    
    security = create_security({"auto_approve": True})
    
    # 设置自动审批
    security.set_auto_approve(True)
    assert security.auto_approve == True
    
    # 禁用自动审批
    security.set_auto_approve(False)
    assert security.auto_approve == False
    
    print("[PASS] 自动审批测试通过")


def test_approval_required():
    """测试审批要求"""
    print("测试审批要求...")
    
    security = create_security()
    
    # 添加需要审批的动作
    security.add_approval_required(ActionType.CLICK)
    assert ActionType.CLICK in security.approval_required
    
    # 移除需要审批的动作
    security.remove_approval_required(ActionType.CLICK)
    assert ActionType.CLICK not in security.approval_required
    
    print("[PASS] 审批要求测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("安全层测试")
    print("=" * 50)
    
    try:
        test_security_creation()
        test_check_safe_action()
        test_check_dangerous_action()
        test_log_action()
        test_auto_approve()
        test_approval_required()
        
        print("=" * 50)
        print("所有测试通过!")
        print("=" * 50)
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
