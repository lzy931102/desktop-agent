"""
基础模块接口
所有模块都必须继承这个基类，实现标准接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json
import logging


class BaseModule(ABC):
    """所有模块的基类"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化模块
        
        Args:
            config: 模块配置字典
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._initialized = False
    
    def initialize(self):
        """
        初始化模块资源
        子类可以重写这个方法进行特定初始化
        """
        self._initialized = True
        self.logger.info(f"{self.__class__.__name__} initialized")
    
    @abstractmethod
    def process(self, input_data: Any) -> Any:
        """
        处理输入数据，返回输出
        
        Args:
            input_data: 输入数据
            
        Returns:
            处理结果
        """
        pass
    
    def validate_input(self, input_data: Any) -> bool:
        """
        验证输入数据
        
        Args:
            input_data: 输入数据
            
        Returns:
            是否有效
        """
        return True
    
    def validate_output(self, output_data: Any) -> bool:
        """
        验证输出数据
        
        Args:
            output_data: 输出数据
            
        Returns:
            是否有效
        """
        return True
    
    def cleanup(self):
        """
        清理资源
        子类可以重写这个方法进行特定清理
        """
        self._initialized = False
        self.logger.info(f"{self.__class__.__name__} cleaned up")
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            配置值
        """
        return self.config.get(key, default)
    
    def set_config(self, key: str, value: Any):
        """
        设置配置项
        
        Args:
            key: 配置键
            value: 配置值
        """
        self.config[key] = value
    
    def to_dict(self) -> Dict:
        """
        将模块状态转换为字典
        
        Returns:
            模块状态字典
        """
        return {
            "class": self.__class__.__name__,
            "config": self.config,
            "initialized": self._initialized
        }
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(config={self.config})"