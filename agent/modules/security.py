"""
安全层实现
审批门控和操作日志
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Security, Action, ActionType


class BasicSecurity(Security):
    """基础安全层实现"""
    
    def __init__(self, config=None):
        """
        初始化安全层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.log_dir = self.config.get("log_dir", "security_logs")
        self.auto_approve = self.config.get("auto_approve", False)
        self.approval_required = self._get_approval_required_actions()
        self._ensure_log_dir()
    
    def _ensure_log_dir(self):
        """确保日志目录存在"""
        os.makedirs(self.log_dir, exist_ok=True)
    
    def check(self, action: Action) -> bool:
        """
        检查动作是否安全
        
        Args:
            action: 要检查的动作
            
        Returns:
            是否允许执行
        """
        try:
            # 记录操作
            self.log_action(action, None)
            
            # 检查是否需要审批
            if self._needs_approval(action):
                if self.auto_approve:
                    return True
                return self.require_approval(action)
            
            return True
            
        except Exception as e:
            print(f"Security check failed: {e}")
            return False
    
    def require_approval(self, action: Action) -> bool:
        """
        请求用户审批
        
        Args:
            action: 需要审批的动作
            
        Returns:
            是否批准
        """
        try:
            # 打印审批信息
            print("\n" + "=" * 50)
            print("安全审批请求")
            print("=" * 50)
            print(f"动作类型: {action.action.value}")
            
            if action.target:
                print(f"目标: {action.target}")
            if action.text:
                print(f"文字: {action.text}")
            if action.keys:
                print(f"快捷键: {action.keys}")
            
            print("-" * 50)
            
            # 等待用户输入
            response = input("是否批准? (y/n): ").strip().lower()
            
            approved = response in ['y', 'yes', '是', '批准']
            
            print(f"审批结果: {'批准' if approved else '拒绝'}")
            print("=" * 50 + "\n")
            
            return approved
            
        except Exception as e:
            print(f"Approval request failed: {e}")
            return False
    
    def log_action(self, action: Action, success: Optional[bool]) -> None:
        """
        记录操作日志
        
        Args:
            action: 执行的动作
            success: 是否成功
        """
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "action": action.action.value,
                "target": action.target,
                "text": action.text,
                "keys": action.keys,
                "success": success
            }
            
            # 写入日志文件
            log_file = os.path.join(self.log_dir, f"security_{datetime.now().strftime('%Y%m%d')}.json")
            
            logs = []
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            
            logs.append(log_entry)
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"Log action failed: {e}")
    
    def _needs_approval(self, action: Action) -> bool:
        """检查动作是否需要审批"""
        # 危险动作列表
        dangerous_actions = [
            ActionType.KEY,  # 快捷键可能执行危险操作
        ]
        
        # 检查是否是危险动作
        if action.action in dangerous_actions:
            # 检查是否是特定快捷键
            if action.keys:
                dangerous_keys = [
                    ["alt", "f4"],  # 关闭程序
                    ["ctrl", "w"],  # 关闭标签
                    ["ctrl", "q"],  # 退出
                    ["delete"],     # 删除
                ]
                
                for dangerous in dangerous_keys:
                    if set(dangerous).issubset(set(action.keys)):
                        return True
        
        return False
    
    def _get_approval_required_actions(self) -> List[ActionType]:
        """获取需要审批的动作类型"""
        return self.config.get("approval_required", [
            ActionType.KEY,
        ])
    
    def get_logs(self, date: Optional[str] = None) -> List[Dict]:
        """
        获取日志
        
        Args:
            date: 日期 (YYYY-MM-DD格式)
            
        Returns:
            日志列表
        """
        try:
            if date is None:
                date = datetime.now().strftime('%Y%m%d')
            else:
                date = date.replace('-', '')
            
            log_file = os.path.join(self.log_dir, f"security_{date}.json")
            
            if not os.path.exists(log_file):
                return []
            
            with open(log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except Exception as e:
            print(f"Get logs failed: {e}")
            return []
    
    def set_auto_approve(self, auto_approve: bool):
        """
        设置自动审批
        
        Args:
            auto_approve: 是否自动审批
        """
        self.auto_approve = auto_approve
    
    def add_approval_required(self, action_type: ActionType):
        """
        添加需要审批的动作类型
        
        Args:
            action_type: 动作类型
        """
        if action_type not in self.approval_required:
            self.approval_required.append(action_type)
    
    def remove_approval_required(self, action_type: ActionType):
        """
        移除需要审批的动作类型
        
        Args:
            action_type: 动作类型
        """
        if action_type in self.approval_required:
            self.approval_required.remove(action_type)


# 便捷工厂函数
def create_security(config=None) -> BasicSecurity:
    """
    创建安全层实例
    
    Args:
        config: 配置字典
        
    Returns:
        BasicSecurity实例
    """
    return BasicSecurity(config)
