"""
执行层实现
包装现有能力为Actuator接口实现
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from interfaces import Actuator, Action, ActionType
from modules.core.core_module import CoreModule


class PyAutoGUIActuator(Actuator):
    """基于pyautogui的执行层实现"""
    
    def __init__(self, config=None):
        """
        初始化执行层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.core = CoreModule(config)
        self.core.initialize()
        self._element_cache = {}  # 元素引用缓存
    
    def execute(self, action: Action) -> bool:
        """
        执行动作
        
        Args:
            action: 要执行的动作
            
        Returns:
            是否成功执行
        """
        try:
            if action.action == ActionType.CLICK:
                return self._execute_click(action)
            elif action.action == ActionType.TYPE:
                return self._execute_type(action)
            elif action.action == ActionType.KEY:
                return self._execute_key(action)
            elif action.action == ActionType.SELECT:
                return self._execute_select(action)
            elif action.action == ActionType.EXPAND:
                return self._execute_expand(action)
            elif action.action == ActionType.WAIT:
                return self._execute_wait(action)
            elif action.action == ActionType.DONE:
                return True
            else:
                self.core.logger.error(f"Unknown action type: {action.action}")
                return False
        except Exception as e:
            self.core.logger.error(f"Execute failed: {e}")
            return False
    
    def _execute_click(self, action: Action) -> bool:
        """执行点击动作"""
        if not action.target:
            self.core.logger.error("Click action missing target")
            return False
        
        # 从目标描述获取坐标
        x, y = self._resolve_target(action.target)
        if x is None or y is None:
            self.core.logger.error(f"Cannot resolve target: {action.target}")
            return False
        
        result = self.core.click(x, y)
        return result.get("success", False)
    
    def _execute_type(self, action: Action) -> bool:
        """执行输入动作"""
        if not action.text:
            self.core.logger.error("Type action missing text")
            return False
        
        result = self.core.type_text(action.text)
        return result.get("success", False)
    
    def _execute_key(self, action: Action) -> bool:
        """执行快捷键动作"""
        if not action.keys:
            self.core.logger.error("Key action missing keys")
            return False
        
        result = self.core.hotkey(*action.keys)
        return result.get("success", False)
    
    def _execute_select(self, action: Action) -> bool:
        """执行选择动作"""
        if not action.target:
            self.core.logger.error("Select action missing target")
            return False
        
        # 选择等同于点击
        x, y = self._resolve_target(action.target)
        if x is None or y is None:
            return False
        
        result = self.core.click(x, y)
        return result.get("success", False)
    
    def _execute_expand(self, action: Action) -> bool:
        """执行展开动作"""
        if not action.target:
            self.core.logger.error("Expand action missing target")
            return False
        
        # 展开通常需要点击下拉箭头或加号
        x, y = self._resolve_target(action.target)
        if x is None or y is None:
            return False
        
        result = self.core.click(x, y)
        return result.get("success", False)
    
    def _execute_wait(self, action: Action) -> bool:
        """执行等待动作"""
        if action.condition:
            # 如果有等待条件，等待指定时间（简化实现）
            seconds = action.condition.get("timeout", 5.0)
        else:
            seconds = 1.0
        
        result = self.core.wait(seconds)
        return result.get("success", False)
    
    def _resolve_target(self, target: Dict) -> tuple:
        """
        解析目标描述，返回坐标
        
        支持的目标格式：
        - {"text": "确定"} - 通过文字查找坐标
        - {"ref": "hwnd:12345"} - 通过元素引用获取坐标
        - {"x": 100, "y": 200} - 直接坐标
        
        Returns:
            (x, y) 坐标，如果无法解析返回 (None, None)
        """
        # 直接坐标
        if "x" in target and "y" in target:
            return target["x"], target["y"]
        
        # 元素引用
        if "ref" in target:
            ref = target["ref"]
            if ref in self._element_cache:
                cached = self._element_cache[ref]
                return cached.get("x"), cached.get("y")
            # TODO: 通过UIA或其他方式解析ref
            self.core.logger.warning(f"Element ref not cached: {ref}")
            return None, None
        
        # 文字查找
        if "text" in target:
            # TODO: 集成OCR或UIA查找文字坐标
            # 暂时返回None，等待Perception模块实现
            self.core.logger.warning(f"Text lookup not implemented: {target['text']}")
            return None, None
        
        return None, None
    
    def click(self, x: int, y: int, button: str = "left") -> bool:
        """
        点击指定坐标
        
        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮
            
        Returns:
            是否成功
        """
        result = self.core.click(x, y, button)
        return result.get("success", False)
    
    def type_text(self, text: str) -> bool:
        """
        输入文字
        
        Args:
            text: 要输入的文字
            
        Returns:
            是否成功
        """
        result = self.core.type_text(text)
        return result.get("success", False)
    
    def press_keys(self, keys: List[str]) -> bool:
        """
        按下快捷键组合
        
        Args:
            keys: 按键列表，如 ["ctrl", "c"]
            
        Returns:
            是否成功
        """
        result = self.core.hotkey(*keys)
        return result.get("success", False)
    
    def update_element_cache(self, elements: List[Dict]):
        """
        更新元素缓存
        
        Args:
            elements: 元素列表，每个元素包含ref和坐标
        """
        for elem in elements:
            ref = elem.get("ref")
            if ref:
                self._element_cache[ref] = {
                    "x": elem.get("bbox", [0, 0, 0, 0])[0] + (elem.get("bbox", [0, 0, 0, 0])[2] - elem.get("bbox", [0, 0, 0, 0])[0]) // 2,
                    "y": elem.get("bbox", [0, 0, 0, 0])[1] + (elem.get("bbox", [0, 0, 0, 0])[3] - elem.get("bbox", [0, 0, 0, 0])[1]) // 2
                }
    
    def clear_element_cache(self):
        """清空元素缓存"""
        self._element_cache.clear()
    
    def get_screen_size(self) -> tuple:
        """
        获取屏幕尺寸
        
        Returns:
            (width, height)
        """
        return self.core.get_screen_size()
    
    def screenshot(self, path: str = "screenshot.png") -> bool:
        """
        截屏
        
        Args:
            path: 保存路径
            
        Returns:
            是否成功
        """
        result = self.core.screenshot(path)
        return result.get("success", False)


# 便捷工厂函数
def create_actuator(config=None) -> PyAutoGUIActuator:
    """
    创建执行层实例
    
    Args:
        config: 配置字典
        
    Returns:
        PyAutoGUIActuator实例
    """
    return PyAutoGUIActuator(config)
