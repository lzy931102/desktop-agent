"""
调度层 / 主循环
负责感知 → 决策 → 执行 → 验证的循环
"""

import json
import time
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from base_module import BaseModule
from modules.core import CoreModule
from modules.perception import PerceptionModule
from modules.cognition import CognitionModule
from modules.memory import MemoryModule


class AgentScheduler(BaseModule):
    """AGENT调度器"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.core = None
        self.perception = None
        self.cognition = None
        self.memory = None
        
        self.current_task = None
        self.task_state = {}
        self.is_running = False
        self.max_retries = 3
        self.retry_count = 0
    
    def initialize(self):
        """初始化调度器"""
        super().initialize()
        
        # 初始化各个模块
        self.core = CoreModule(self.get_config("core", {}))
        self.perception = PerceptionModule(self.get_config("perception", {}))
        self.cognition = CognitionModule(self.get_config("cognition", {}))
        self.memory = MemoryModule(self.get_config("memory", {}))
        
        # 初始化模块
        self.core.initialize()
        self.perception.initialize()
        self.cognition.initialize()
        self.memory.initialize()
        
        self.logger.info("AgentScheduler initialized")
    
    def process(self, input_data: dict) -> dict:
        """
        处理调度请求
        
        Args:
            input_data: 包含action和参数的字典
            
        Returns:
            处理结果
        """
        action = input_data.get("action")
        
        if action == "start":
            task = input_data.get("task", "")
            return self.start_task(task)
        
        elif action == "stop":
            return self.stop_task()
        
        elif action == "status":
            return self.get_status()
        
        elif action == "execute_once":
            return self.execute_once()
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    def start_task(self, task: str) -> dict:
        """
        开始执行任务
        
        Args:
            task: 任务描述
            
        Returns:
            启动结果
        """
        try:
            self.current_task = task
            self.task_state = {
                "task": task,
                "status": "running",
                "start_time": time.time(),
                "steps": []
            }
            self.is_running = True
            self.retry_count = 0
            
            # 保存任务状态
            self.memory.save_task_state("current", self.task_state)
            
            self.logger.info(f"Task started: {task}")
            return {"success": True, "message": f"Task started: {task}"}
        
        except Exception as e:
            self.logger.error(f"Start task failed: {e}")
            return {"success": False, "error": str(e)}
    
    def stop_task(self) -> dict:
        """
        停止当前任务
        
        Returns:
            停止结果
        """
        try:
            self.is_running = False
            self.task_state["status"] = "stopped"
            self.task_state["end_time"] = time.time()
            
            # 保存任务状态
            self.memory.save_task_state("current", self.task_state)
            
            self.logger.info("Task stopped")
            return {"success": True, "message": "Task stopped"}
        
        except Exception as e:
            self.logger.error(f"Stop task failed: {e}")
            return {"success": False, "error": str(e)}
    
    def execute_once(self) -> dict:
        """
        执行一次循环
        
        Returns:
            执行结果
        """
        try:
            if not self.is_running:
                return {"success": False, "error": "No task running"}
            
            # 1. 感知
            self.logger.info("Step 1: Perceiving...")
            perception_result = self.perception.process({
                "action": "analyze_screen"
            })
            
            if not perception_result.get("success"):
                return {"success": False, "error": f"Perception failed: {perception_result.get('error')}"}
            
            # 2. 决策
            self.logger.info("Step 2: Deciding...")
            decision_result = self.cognition.process({
                "action": "plan_next_action",
                "state": {
                    "task": self.current_task,
                    "perception": perception_result.get("analysis"),
                    "history": self.task_state.get("steps", [])[-5:]  # 最近5步
                }
            })
            
            if not decision_result.get("success"):
                return {"success": False, "error": f"Decision failed: {decision_result.get('error')}"}
            
            plan = decision_result.get("plan", {})
            
            # 检查是否完成
            if plan.get("action") == "done":
                self.task_state["status"] = "completed"
                self.task_state["end_time"] = time.time()
                self.memory.save_task_state("current", self.task_state)
                return {"success": True, "message": "Task completed", "completed": True}
            
            # 3. 执行
            self.logger.info("Step 3: Acting...")
            action_result = self._execute_action(plan)
            
            # 记录步骤
            step = {
                "perception": perception_result.get("analysis"),
                "decision": plan,
                "action_result": action_result,
                "timestamp": time.time()
            }
            self.task_state["steps"].append(step)
            
            # 4. 验证
            self.logger.info("Step 4: Verifying...")
            verification_result = self._verify_action(action_result)
            
            # 处理验证失败
            if not verification_result.get("success"):
                self.retry_count += 1
                if self.retry_count >= self.max_retries:
                    self.task_state["status"] = "failed"
                    self.task_state["error"] = "Max retries exceeded"
                    self.memory.save_task_state("current", self.task_state)
                    return {"success": False, "error": "Max retries exceeded"}
            
            # 保存状态
            self.memory.save_task_state("current", self.task_state)
            
            return {
                "success": True,
                "step": len(self.task_state["steps"]),
                "action": plan,
                "result": action_result
            }
        
        except Exception as e:
            self.logger.error(f"Execute once failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _execute_action(self, plan: dict) -> dict:
        """
        执行具体操作
        
        Args:
            plan: 执行计划
            
        Returns:
            执行结果
        """
        action_type = plan.get("action")
        parameters = plan.get("parameters", {})
        
        if action_type == "click":
            return self.core.process({
                "action": "click",
                "x": parameters.get("x", 0),
                "y": parameters.get("y", 0)
            })
        
        elif action_type == "type":
            return self.core.process({
                "action": "type",
                "text": parameters.get("text", "")
            })
        
        elif action_type == "hotkey":
            return self.core.process({
                "action": "hotkey",
                "keys": parameters.get("keys", [])
            })
        
        elif action_type == "wait":
            return self.core.process({
                "action": "wait",
                "seconds": parameters.get("seconds", 1)
            })
        
        elif action_type == "screenshot":
            return self.core.process({
                "action": "screenshot",
                "path": parameters.get("path", "screenshot.png")
            })
        
        else:
            return {"success": False, "error": f"Unknown action type: {action_type}"}
    
    def _verify_action(self, action_result: dict) -> dict:
        """
        验证操作结果
        
        Args:
            action_result: 操作结果
            
        Returns:
            验证结果
        """
        # 简单验证：检查操作是否成功
        if action_result.get("success"):
            return {"success": True, "verified": True}
        else:
            return {"success": True, "verified": False, "error": action_result.get("error")}
    
    def get_status(self) -> dict:
        """
        获取当前状态
        
        Returns:
            状态信息
        """
        return {
            "success": True,
            "status": {
                "is_running": self.is_running,
                "current_task": self.current_task,
                "task_state": self.task_state,
                "retry_count": self.retry_count
            }
        }
    
    def run(self):
        """运行主循环"""
        self.logger.info("Starting main loop...")
        
        while self.is_running:
            result = self.execute_once()
            
            if result.get("completed"):
                self.logger.info("Task completed")
                break
            
            if not result.get("success"):
                self.logger.error(f"Execution failed: {result.get('error')}")
                # 等待一会再重试
                time.sleep(1)
            else:
                # 短暂等待
                time.sleep(0.5)
        
        self.logger.info("Main loop ended")