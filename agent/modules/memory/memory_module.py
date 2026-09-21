"""
数据持久模块
提供文件读写、任务状态管理、日志记录等功能
"""

import json
import os
import time
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_module import BaseModule


class MemoryModule(BaseModule):
    """数据持久模块"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.storage_path = None
        self.task_states = {}
        self.operation_history = []
    
    def initialize(self):
        """初始化模块"""
        super().initialize()
        
        # 设置存储路径
        self.storage_path = self.get_config("storage_path", "agent_storage")
        os.makedirs(self.storage_path, exist_ok=True)
        
        # 加载已有状态
        self._load_states()
        
        self.logger.info(f"MemoryModule initialized with storage: {self.storage_path}")
    
    def _load_states(self):
        """加载已保存的状态"""
        try:
            states_file = os.path.join(self.storage_path, "task_states.json")
            if os.path.exists(states_file):
                with open(states_file, 'r', encoding='utf-8') as f:
                    self.task_states = json.load(f)
                self.logger.info(f"Loaded {len(self.task_states)} task states")
        except Exception as e:
            self.logger.error(f"Failed to load states: {e}")
            self.task_states = {}
    
    def _save_states(self):
        """保存状态到文件"""
        try:
            states_file = os.path.join(self.storage_path, "task_states.json")
            with open(states_file, 'w', encoding='utf-8') as f:
                json.dump(self.task_states, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save states: {e}")
    
    def process(self, input_data: dict) -> dict:
        """
        处理记忆请求
        
        Args:
            input_data: 包含action和参数的字典
            
        Returns:
            处理结果
        """
        action = input_data.get("action")
        
        if action == "read_file":
            path = input_data.get("path", "")
            return self.read_file(path)
        
        elif action == "write_file":
            path = input_data.get("path", "")
            content = input_data.get("content", "")
            return self.write_file(path, content)
        
        elif action == "append_file":
            path = input_data.get("path", "")
            content = input_data.get("content", "")
            return self.append_file(path, content)
        
        elif action == "save_task_state":
            task_id = input_data.get("task_id", "")
            state = input_data.get("state", {})
            return self.save_task_state(task_id, state)
        
        elif action == "load_task_state":
            task_id = input_data.get("task_id", "")
            return self.load_task_state(task_id)
        
        elif action == "log_operation":
            operation = input_data.get("operation", {})
            return self.log_operation(operation)
        
        elif action == "get_history":
            limit = input_data.get("limit", 100)
            return self.get_history(limit)
        
        elif action == "clear_history":
            return self.clear_history()
        
        elif action == "save_config":
            config = input_data.get("config", {})
            return self.save_config(config)
        
        elif action == "load_config":
            return self.load_config()
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    def read_file(self, path: str) -> dict:
        """
        读取文件
        
        Args:
            path: 文件路径
            
        Returns:
            文件内容
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"success": True, "content": content}
        except Exception as e:
            self.logger.error(f"Read file failed: {e}")
            return {"success": False, "error": str(e)}
    
    def write_file(self, path: str, content: str) -> dict:
        """
        写入文件
        
        Args:
            path: 文件路径
            content: 文件内容
            
        Returns:
            写入结果
        """
        try:
            # 确保目录存在
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return {"success": True, "path": path}
        except Exception as e:
            self.logger.error(f"Write file failed: {e}")
            return {"success": False, "error": str(e)}
    
    def append_file(self, path: str, content: str) -> dict:
        """
        追加内容到文件
        
        Args:
            path: 文件路径
            content: 要追加的内容
            
        Returns:
            追加结果
        """
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            return {"success": True, "path": path}
        except Exception as e:
            self.logger.error(f"Append file failed: {e}")
            return {"success": False, "error": str(e)}
    
    def save_task_state(self, task_id: str, state: dict) -> dict:
        """
        保存任务状态
        
        Args:
            task_id: 任务ID
            state: 任务状态
            
        Returns:
            保存结果
        """
        try:
            self.task_states[task_id] = {
                "state": state,
                "timestamp": datetime.now().isoformat()
            }
            self._save_states()
            return {"success": True, "task_id": task_id}
        except Exception as e:
            self.logger.error(f"Save task state failed: {e}")
            return {"success": False, "error": str(e)}
    
    def load_task_state(self, task_id: str) -> dict:
        """
        加载任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务状态
        """
        try:
            if task_id in self.task_states:
                return {"success": True, "state": self.task_states[task_id]}
            else:
                return {"success": False, "error": f"Task {task_id} not found"}
        except Exception as e:
            self.logger.error(f"Load task state failed: {e}")
            return {"success": False, "error": str(e)}
    
    def log_operation(self, operation: dict) -> dict:
        """
        记录操作日志
        
        Args:
            operation: 操作信息
            
        Returns:
            记录结果
        """
        try:
            log_entry = {
                "operation": operation,
                "timestamp": datetime.now().isoformat()
            }
            self.operation_history.append(log_entry)
            
            # 限制历史记录数量
            max_history = self.get_config("max_history", 1000)
            if len(self.operation_history) > max_history:
                self.operation_history = self.operation_history[-max_history:]
            
            # 保存到文件
            history_file = os.path.join(self.storage_path, "operation_history.json")
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(self.operation_history, f, ensure_ascii=False, indent=2)
            
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Log operation failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_history(self, limit: int = 100) -> dict:
        """
        获取操作历史
        
        Args:
            limit: 返回数量限制
            
        Returns:
            操作历史
        """
        try:
            history = self.operation_history[-limit:]
            return {"success": True, "history": history}
        except Exception as e:
            self.logger.error(f"Get history failed: {e}")
            return {"success": False, "error": str(e)}
    
    def clear_history(self) -> dict:
        """
        清空操作历史
        
        Returns:
            清空结果
        """
        try:
            self.operation_history = []
            history_file = os.path.join(self.storage_path, "operation_history.json")
            if os.path.exists(history_file):
                os.remove(history_file)
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Clear history failed: {e}")
            return {"success": False, "error": str(e)}
    
    def save_config(self, config: dict) -> dict:
        """
        保存配置
        
        Args:
            config: 配置信息
            
        Returns:
            保存结果
        """
        try:
            config_file = os.path.join(self.storage_path, "config.json")
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return {"success": True}
        except Exception as e:
            self.logger.error(f"Save config failed: {e}")
            return {"success": False, "error": str(e)}
    
    def load_config(self) -> dict:
        """
        加载配置
        
        Returns:
            配置信息
        """
        try:
            config_file = os.path.join(self.storage_path, "config.json")
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return {"success": True, "config": config}
            else:
                return {"success": True, "config": {}}
        except Exception as e:
            self.logger.error(f"Load config failed: {e}")
            return {"success": False, "error": str(e)}