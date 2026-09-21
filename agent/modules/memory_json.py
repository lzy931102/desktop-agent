"""
记忆层实现
基于JSON文件的存储
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

from interfaces import Memory, ScreenState, Action


class JSONMemory(Memory):
    """基于JSON的记忆层实现"""
    
    def __init__(self, config=None):
        """
        初始化记忆层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.storage_path = self.config.get("storage_path", "memory")
        self.max_history = self.config.get("max_history", 100)
        self._ensure_storage_dir()
        self._cache = {}
    
    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        os.makedirs(self.storage_path, exist_ok=True)
    
    def save(self, key: str, value: Any) -> None:
        """
        保存数据
        
        Args:
            key: 键
            value: 值
        """
        try:
            file_path = self._get_file_path(key)
            
            # 转换为可序列化的格式
            data = self._serialize(value)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 更新缓存
            self._cache[key] = data
            
        except Exception as e:
            print(f"Save failed: {e}")
    
    def load(self, key: str) -> Any:
        """
        加载数据
        
        Args:
            key: 键
            
        Returns:
            保存的值
        """
        try:
            # 检查缓存
            if key in self._cache:
                return self._deserialize(self._cache[key])
            
            file_path = self._get_file_path(key)
            
            if not os.path.exists(file_path):
                return None
            
            # 读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 更新缓存
            self._cache[key] = data
            
            return self._deserialize(data)
            
        except Exception as e:
            print(f"Load failed: {e}")
            return None
    
    def save_state(self, state: ScreenState, action: Action, success: bool) -> None:
        """
        保存执行状态
        
        Args:
            state: 屏幕状态
            action: 执行的动作
            success: 是否成功
        """
        try:
            # 创建状态记录
            record = {
                "timestamp": datetime.now().isoformat(),
                "action": {
                    "type": action.action.value,
                    "target": action.target,
                    "text": action.text,
                    "keys": action.keys
                },
                "success": success,
                "screen": {
                    "texts_count": len(state.texts),
                    "elements_count": len(state.elements),
                    "active_window": state.active_window
                }
            }
            
            # 加载历史记录
            history = self.load("execution_history") or []
            
            # 添加新记录
            history.append(record)
            
            # 限制历史记录数量
            if len(history) > self.max_history:
                history = history[-self.max_history:]
            
            # 保存历史记录
            self.save("execution_history", history)
            
        except Exception as e:
            print(f"Save state failed: {e}")
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        """
        获取历史记录
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            历史记录列表
        """
        try:
            history = self.load("execution_history") or []
            return history[-limit:]
        except Exception as e:
            print(f"Get history failed: {e}")
            return []
    
    def save_task(self, task_id: str, task_data: Dict) -> None:
        """
        保存任务数据
        
        Args:
            task_id: 任务ID
            task_data: 任务数据
        """
        key = f"task_{task_id}"
        self.save(key, task_data)
    
    def load_task(self, task_id: str) -> Optional[Dict]:
        """
        加载任务数据
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务数据
        """
        key = f"task_{task_id}"
        return self.load(key)
    
    def save_context(self, context_id: str, context_data: Dict) -> None:
        """
        保存上下文数据
        
        Args:
            context_id: 上下文ID
            context_data: 上下文数据
        """
        key = f"context_{context_id}"
        self.save(key, context_data)
    
    def load_context(self, context_id: str) -> Optional[Dict]:
        """
        加载上下文数据
        
        Args:
            context_id: 上下文ID
            
        Returns:
            上下文数据
        """
        key = f"context_{context_id}"
        return self.load(key)
    
    def clear(self) -> None:
        """清空所有数据"""
        try:
            # 清空缓存
            self._cache.clear()
            
            # 删除存储目录中的所有文件
            for filename in os.listdir(self.storage_path):
                file_path = os.path.join(self.storage_path, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    
        except Exception as e:
            print(f"Clear failed: {e}")
    
    def _get_file_path(self, key: str) -> str:
        """获取文件路径"""
        # 将key转换为安全的文件名
        safe_key = key.replace("/", "_").replace("\\", "_").replace(":", "_")
        return os.path.join(self.storage_path, f"{safe_key}.json")
    
    def _serialize(self, value: Any) -> Any:
        """序列化数据"""
        if isinstance(value, ScreenState):
            return {
                "_type": "ScreenState",
                "screenshot": value.screenshot,
                "screenshot_path": value.screenshot_path,
                "texts": value.texts,
                "elements": value.elements,
                "active_window": value.active_window
            }
        elif isinstance(value, Action):
            return {
                "_type": "Action",
                "action": value.action.value,
                "target": value.target,
                "text": value.text,
                "keys": value.keys,
                "condition": value.condition
            }
        elif isinstance(value, dict):
            return {k: self._serialize(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._serialize(item) for item in value]
        else:
            return value
    
    def _deserialize(self, data: Any) -> Any:
        """反序列化数据"""
        if isinstance(data, dict):
            if "_type" in data:
                if data["_type"] == "ScreenState":
                    return ScreenState(
                        screenshot=data.get("screenshot", ""),
                        screenshot_path=data.get("screenshot_path", ""),
                        texts=data.get("texts", []),
                        elements=data.get("elements", []),
                        active_window=data.get("active_window", {})
                    )
                elif data["_type"] == "Action":
                    from interfaces import ActionType
                    return Action(
                        action=ActionType(data.get("action", "done")),
                        target=data.get("target"),
                        text=data.get("text"),
                        keys=data.get("keys"),
                        condition=data.get("condition")
                    )
            return {k: self._deserialize(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._deserialize(item) for item in data]
        else:
            return data


# 便捷工厂函数
def create_memory(config=None) -> JSONMemory:
    """
    创建记忆层实例
    
    Args:
        config: 配置字典
        
    Returns:
        JSONMemory实例
    """
    return JSONMemory(config)
