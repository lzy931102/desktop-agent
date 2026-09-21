"""
调度层实现
把模块串成主循环
"""

import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import (
    Perception, Brain, Actuator, Verifier, Memory, Security,
    ScreenState, Action, ActionType
)


class TaskStatus(Enum):
    """任务状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Orchestrator:
    """调度层 - 主循环"""
    
    def __init__(self, config=None):
        """
        初始化调度层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 模块引用
        self.perception: Optional[Perception] = None
        self.brain: Optional[Brain] = None
        self.actuator: Optional[Actuator] = None
        self.verifier: Optional[Verifier] = None
        self.memory: Optional[Memory] = None
        self.security: Optional[Security] = None
        
        # 状态
        self.status = TaskStatus.IDLE
        self.current_goal = ""
        self.current_step = 0
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_count = 0
        
        # 回调
        self.on_step_complete = None
        self.on_task_complete = None
        self.on_error = None
    
    def set_modules(
        self,
        perception: Perception = None,
        brain: Brain = None,
        actuator: Actuator = None,
        verifier: Verifier = None,
        memory: Memory = None,
        security: Security = None
    ):
        """
        设置模块
        
        Args:
            perception: 感知层
            brain: 决策层
            actuator: 执行层
            verifier: 验证层
            memory: 记忆层
            security: 安全层
        """
        if perception:
            self.perception = perception
        if brain:
            self.brain = brain
        if actuator:
            self.actuator = actuator
        if verifier:
            self.verifier = verifier
        if memory:
            self.memory = memory
        if security:
            self.security = security
    
    def start(self, goal: str) -> bool:
        """
        开始执行任务
        
        Args:
            goal: 任务目标
            
        Returns:
            是否成功启动
        """
        if self.status == TaskStatus.RUNNING:
            print("Task already running")
            return False
        
        # 验证必要模块
        if not self._validate_modules():
            print("Missing required modules")
            return False
        
        self.current_goal = goal
        self.current_step = 0
        self.retry_count = 0
        self.status = TaskStatus.RUNNING
        
        print(f"Starting task: {goal}")
        
        # 执行主循环
        return self._run_main_loop()
    
    def stop(self):
        """停止当前任务"""
        self.status = TaskStatus.IDLE
        self.current_goal = ""
        print("Task stopped")
    
    def pause(self):
        """暂停任务"""
        if self.status == TaskStatus.RUNNING:
            self.status = TaskStatus.PAUSED
            print("Task paused")
    
    def resume(self):
        """恢复任务"""
        if self.status == TaskStatus.PAUSED:
            self.status = TaskStatus.RUNNING
            print("Task resumed")
            self._run_main_loop()
    
    def _run_main_loop(self) -> bool:
        """
        运行主循环
        
        Returns:
            是否成功完成
        """
        try:
            while self.status == TaskStatus.RUNNING:
                # 1. 感知
                before = self._perceive()
                if before is None:
                    print("Perception failed")
                    self._handle_error("Perception failed")
                    continue
                
                # 2. 决策
                action = self._decide(before)
                if action is None:
                    print("Decision failed")
                    self._handle_error("Decision failed")
                    continue
                
                # 检查是否完成
                if action.action == ActionType.DONE:
                    self._complete_task()
                    return True
                
                # 3. 安全检查
                if not self._security_check(action):
                    print("Security check failed")
                    self._handle_error("Security check failed")
                    continue
                
                # 4. 执行
                success = self._execute(action)
                if not success:
                    print("Execution failed")
                    self._handle_error("Execution failed")
                    continue
                
                # 5. 验证
                after = self._perceive()
                verified = self._verify(before, after, action)
                
                # 6. 记忆
                self._remember(before, action, verified)
                
                # 7. 更新状态
                self._update_state(action, verified)
                
                # 回调
                if self.on_step_complete:
                    self.on_step_complete(self.current_step, action, verified)
                
                self.current_step += 1
                time.sleep(0.1)  # 避免过快循环
            
            return self.status == TaskStatus.COMPLETED
            
        except Exception as e:
            print(f"Main loop error: {e}")
            self._handle_error(str(e))
            return False
    
    def _perceive(self) -> Optional[ScreenState]:
        """感知"""
        try:
            return self.perception.capture()
        except Exception as e:
            print(f"Perception error: {e}")
            return None
    
    def _decide(self, state: ScreenState) -> Optional[Action]:
        """决策"""
        try:
            return self.brain.decide(state, self.current_goal)
        except Exception as e:
            print(f"Brain error: {e}")
            return None
    
    def _security_check(self, action: Action) -> bool:
        """安全检查"""
        if self.security is None:
            return True
        
        try:
            return self.security.check(action)
        except Exception as e:
            print(f"Security error: {e}")
            return False
    
    def _execute(self, action: Action) -> bool:
        """执行"""
        try:
            return self.actuator.execute(action)
        except Exception as e:
            print(f"Actuator error: {e}")
            return False
    
    def _verify(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """验证"""
        if self.verifier is None:
            return True
        
        try:
            return self.verifier.verify(before, after, action)
        except Exception as e:
            print(f"Verifier error: {e}")
            return False
    
    def _remember(self, state: ScreenState, action: Action, success: bool):
        """记忆"""
        if self.memory is None:
            return
        
        try:
            self.memory.save_state(state, action, success)
        except Exception as e:
            print(f"Memory error: {e}")
    
    def _update_state(self, action: Action, success: bool):
        """更新决策层状态"""
        if self.brain is None:
            return
        
        try:
            # 获取当前状态用于更新
            state = self.perception.capture() if self.perception else ScreenState(screenshot="")
            self.brain.update_state(state, action, success)
        except Exception as e:
            print(f"Update state error: {e}")
    
    def _handle_error(self, error_msg: str):
        """处理错误"""
        self.retry_count += 1
        
        if self.on_error:
            self.on_error(error_msg, self.retry_count)
        
        if self.retry_count >= self.max_retries:
            print(f"Max retries reached: {self.max_retries}")
            self.status = TaskStatus.FAILED
        else:
            print(f"Retry {self.retry_count}/{self.max_retries}")
            time.sleep(1)
    
    def _complete_task(self):
        """完成任务"""
        self.status = TaskStatus.COMPLETED
        print(f"Task completed: {self.current_goal}")
        
        if self.on_task_complete:
            self.on_task_complete(self.current_goal, self.current_step)
    
    def _validate_modules(self) -> bool:
        """验证必要模块"""
        required = [self.perception, self.brain, self.actuator]
        return all(module is not None for module in required)
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            "status": self.status.value,
            "goal": self.current_goal,
            "step": self.current_step,
            "retry_count": self.retry_count
        }


# 便捷工厂函数
def create_orchestrator(config=None) -> Orchestrator:
    """
    创建调度层实例
    
    Args:
        config: 配置字典
        
    Returns:
        Orchestrator实例
    """
    return Orchestrator(config)
