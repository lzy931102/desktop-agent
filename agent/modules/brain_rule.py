"""
决策层实现 - 规则版
基于规则的简单决策，先跑通闭环
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Brain, ScreenState, Action, ActionType
from interfaces import create_click_action, create_type_action, create_key_action, create_wait_action, create_done_action


class RuleBasedBrain(Brain):
    """基于规则的决策层"""
    
    def __init__(self, config=None):
        """
        初始化决策层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.current_step = 0
        self.task_steps = []
        self.history = []
    
    def decide(self, state: ScreenState, goal: str) -> Action:
        """
        根据屏幕状态和目标决定下一步动作
        
        Args:
            state: 当前屏幕状态
            goal: 任务目标描述
            
        Returns:
            Action: 要执行的动作
        """
        # 如果没有任务步骤，先解析目标
        if not self.task_steps:
            self.task_steps = self._parse_goal(goal)
            self.current_step = 0
        
        # 如果任务完成
        if self.current_step >= len(self.task_steps):
            return create_done_action()
        
        # 获取当前步骤
        step = self.task_steps[self.current_step]
        
        # 根据规则生成动作
        action = self._execute_rule(step, state)
        
        # 记录历史
        self.history.append({
            "step": self.current_step,
            "rule": step,
            "action": action,
            "state_summary": {
                "texts_count": len(state.texts),
                "elements_count": len(state.elements)
            }
        })
        
        return action
    
    def plan(self, goal: str) -> List[Action]:
        """
        规划任务步骤
        
        Args:
            goal: 任务目标描述
            
        Returns:
            动作序列
        """
        steps = self._parse_goal(goal)
        actions = []
        
        for step in steps:
            action = self._step_to_action(step)
            actions.append(action)
        
        return actions
    
    def update_state(self, state: ScreenState, action: Action, success: bool):
        """
        根据执行结果更新决策状态
        
        Args:
            state: 执行后的屏幕状态
            action: 执行的动作
            success: 是否成功
        """
        if success:
            self.current_step += 1
        else:
            # 失败时可以重试或调整策略
            pass
        
        # 记录执行结果
        if self.history:
            self.history[-1]["success"] = success
    
    def _parse_goal(self, goal: str) -> List[Dict]:
        """
        解析目标为步骤列表
        
        Args:
            goal: 目标描述
            
        Returns:
            步骤列表
        """
        steps = []
        
        # 简单的规则解析
        goal_lower = goal.lower()
        
        # 打开应用
        if "打开" in goal or "open" in goal_lower:
            app_name = self._extract_app_name(goal)
            steps.append({"type": "open_app", "app": app_name})
        
        # 输入文字
        if "输入" in goal or "type" in goal_lower or "input" in goal_lower:
            text = self._extract_input_text(goal)
            steps.append({"type": "type_text", "text": text})
        
        # 点击
        if "点击" in goal or "click" in goal_lower:
            target = self._extract_click_target(goal)
            steps.append({"type": "click", "target": target})
        
        # 保存
        if "保存" in goal or "save" in goal_lower:
            steps.append({"type": "hotkey", "keys": ["ctrl", "s"]})
        
        # 如果没有识别到具体步骤，返回默认步骤
        if not steps:
            steps.append({"type": "wait", "seconds": 1})
        
        return steps
    
    def _extract_app_name(self, goal: str) -> str:
        """从目标中提取应用名"""
        # 简单的关键词匹配
        app_keywords = {
            "记事本": "notepad",
            "notepad": "notepad",
            "浏览器": "chrome",
            "chrome": "chrome",
            "edge": "msedge",
            "word": "winword",
            "excel": "excel",
            "ppt": "powerpnt"
        }
        
        for key, value in app_keywords.items():
            if key in goal.lower():
                return value
        
        return "notepad"  # 默认
    
    def _extract_input_text(self, goal: str) -> str:
        """从目标中提取输入文字"""
        # 尝试提取引号中的文字
        import re
        patterns = [
            r'["""]([^"""]+)["""]',  # 中英文引号
            r"'([^']+)'",
            r'"([^"]+)"'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, goal)
            if match:
                return match.group(1)
        
        # 如果没有找到，返回默认文字
        return "Hello from Agent"
    
    def _extract_click_target(self, goal: str) -> Dict:
        """从目标中提取点击目标"""
        # 尝试提取按钮名称
        button_keywords = ["确定", "取消", "保存", "打开", "关闭", "ok", "cancel", "save"]
        
        for keyword in button_keywords:
            if keyword in goal.lower():
                return {"text": keyword}
        
        # 默认点击第一个识别到的文字
        return {"text": "确定"}
    
    def _execute_rule(self, step: Dict, state: ScreenState) -> Action:
        """根据规则执行动作"""
        step_type = step.get("type")
        
        if step_type == "open_app":
            # 打开应用：Win+R -> 输入应用名 -> Enter
            app = step.get("app", "notepad")
            # 这里简化为直接输入应用名
            return create_type_action(app)
        
        elif step_type == "type_text":
            # 输入文字
            text = step.get("text", "")
            return create_type_action(text)
        
        elif step_type == "click":
            # 点击
            target = step.get("target", {"text": "确定"})
            return create_click_action(target)
        
        elif step_type == "hotkey":
            # 快捷键
            keys = step.get("keys", [])
            return create_key_action(keys)
        
        elif step_type == "wait":
            # 等待
            seconds = step.get("seconds", 1)
            return create_wait_action({"timeout": seconds})
        
        else:
            # 未知类型，等待
            return create_wait_action({"timeout": 1})
    
    def _step_to_action(self, step: Dict) -> Action:
        """将步骤转换为动作（用于plan方法）"""
        step_type = step.get("type")
        
        if step_type == "open_app":
            app = step.get("app", "notepad")
            return create_key_action(["win", "r"])
        
        elif step_type == "type_text":
            text = step.get("text", "")
            return create_type_action(text)
        
        elif step_type == "click":
            target = step.get("target", {"text": "确定"})
            return create_click_action(target)
        
        elif step_type == "hotkey":
            keys = step.get("keys", [])
            return create_key_action(keys)
        
        elif step_type == "wait":
            seconds = step.get("seconds", 1)
            return create_wait_action({"timeout": seconds})
        
        else:
            return create_wait_action({"timeout": 1})
    
    def reset(self):
        """重置决策层状态"""
        self.current_step = 0
        self.task_steps = []
        self.history = []
    
    def get_progress(self) -> Dict:
        """获取任务进度"""
        return {
            "current_step": self.current_step,
            "total_steps": len(self.task_steps),
            "progress": self.current_step / len(self.task_steps) if self.task_steps else 0,
            "history_length": len(self.history)
        }


# 便捷工厂函数
def create_brain(config=None) -> RuleBasedBrain:
    """
    创建决策层实例
    
    Args:
        config: 配置字典
        
    Returns:
        RuleBasedBrain实例
    """
    return RuleBasedBrain(config)
