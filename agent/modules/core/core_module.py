"""
核心执行模块
提供鼠标、键盘、截屏等基础操作
"""

import time
import sys
from pathlib import Path
from typing import Optional, Tuple, List

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_module import BaseModule

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
except ImportError:
    print("请安装pyautogui: pip install pyautogui")
    sys.exit(1)


class CoreModule(BaseModule):
    """核心执行模块"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.screen_width, self.screen_height = pyautogui.size()
    
    def initialize(self):
        """初始化模块"""
        super().initialize()
        self.logger.info(f"CoreModule initialized. Screen size: {self.screen_width}x{self.screen_height}")
    
    def process(self, input_data: dict) -> dict:
        """
        处理执行命令
        
        Args:
            input_data: 包含action和参数的字典
            
        Returns:
            执行结果
        """
        action = input_data.get("action")
        
        if action == "click":
            x = input_data.get("x", 0)
            y = input_data.get("y", 0)
            button = input_data.get("button", "left")
            clicks = input_data.get("clicks", 1)
            return self.click(x, y, button, clicks)
        
        elif action == "type":
            text = input_data.get("text", "")
            interval = input_data.get("interval", 0.05)
            return self.type_text(text, interval)
        
        elif action == "hotkey":
            keys = input_data.get("keys", [])
            return self.hotkey(*keys)
        
        elif action == "screenshot":
            path = input_data.get("path", "screenshot.png")
            return self.screenshot(path)
        
        elif action == "move_to":
            x = input_data.get("x", 0)
            y = input_data.get("y", 0)
            duration = input_data.get("duration", 0.5)
            return self.move_to(x, y, duration)
        
        elif action == "scroll":
            clicks = input_data.get("clicks", 0)
            return self.scroll(clicks)
        
        elif action == "wait":
            seconds = input_data.get("seconds", 1)
            return self.wait(seconds)
        
        elif action == "press":
            key = input_data.get("key", "")
            presses = input_data.get("presses", 1)
            return self.press_key(key, presses)
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
        """
        点击指定坐标
        
        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮 ('left', 'right', 'middle')
            clicks: 点击次数
            
        Returns:
            执行结果
        """
        try:
            pyautogui.click(x, y, button=button, clicks=clicks)
            self.logger.info(f"Clicked at ({x}, {y}) with {button} button")
            return {"success": True, "action": "click", "x": x, "y": y}
        except Exception as e:
            self.logger.error(f"Click failed: {e}")
            return {"success": False, "error": str(e)}
    
    def type_text(self, text: str, interval: float = 0.05) -> dict:
        """
        输入文字
        
        Args:
            text: 要输入的文字
            interval: 字符间隔时间
            
        Returns:
            执行结果
        """
        try:
            pyautogui.write(text, interval=interval)
            self.logger.info(f"Typed text: {text[:20]}..." if len(text) > 20 else f"Typed text: {text}")
            return {"success": True, "action": "type", "text": text}
        except Exception as e:
            self.logger.error(f"Type failed: {e}")
            return {"success": False, "error": str(e)}
    
    def press_key(self, key: str, presses: int = 1) -> dict:
        """
        按下按键
        
        Args:
            key: 按键名称
            presses: 按下次数
            
        Returns:
            执行结果
        """
        try:
            pyautogui.press(key, presses=presses)
            self.logger.info(f"Pressed key: {key}")
            return {"success": True, "action": "press", "key": key}
        except Exception as e:
            self.logger.error(f"Press key failed: {e}")
            return {"success": False, "error": str(e)}
    
    def hotkey(self, *keys) -> dict:
        """
        执行快捷键组合
        
        Args:
            keys: 按键序列
            
        Returns:
            执行结果
        """
        try:
            pyautogui.hotkey(*keys)
            key_str = "+".join(keys)
            self.logger.info(f"Hotkey: {key_str}")
            return {"success": True, "action": "hotkey", "keys": list(keys)}
        except Exception as e:
            self.logger.error(f"Hotkey failed: {e}")
            return {"success": False, "error": str(e)}
    
    def move_to(self, x: int, y: int, duration: float = 0.5) -> dict:
        """
        移动鼠标到指定位置
        
        Args:
            x: X坐标
            y: Y坐标
            duration: 移动时间
            
        Returns:
            执行结果
        """
        try:
            pyautogui.moveTo(x, y, duration=duration)
            self.logger.info(f"Moved to ({x}, {y})")
            return {"success": True, "action": "move_to", "x": x, "y": y}
        except Exception as e:
            self.logger.error(f"Move failed: {e}")
            return {"success": False, "error": str(e)}
    
    def scroll(self, clicks: int) -> dict:
        """
        滚动鼠标
        
        Args:
            clicks: 滚动量（正数向上，负数向下）
            
        Returns:
            执行结果
        """
        try:
            pyautogui.scroll(clicks)
            self.logger.info(f"Scrolled: {clicks}")
            return {"success": True, "action": "scroll", "clicks": clicks}
        except Exception as e:
            self.logger.error(f"Scroll failed: {e}")
            return {"success": False, "error": str(e)}
    
    def screenshot(self, path: str = "screenshot.png") -> dict:
        """
        截屏并保存
        
        Args:
            path: 保存路径
            
        Returns:
            执行结果
        """
        try:
            img = pyautogui.screenshot()
            img.save(path)
            self.logger.info(f"Screenshot saved to {path}")
            return {"success": True, "action": "screenshot", "path": path}
        except Exception as e:
            self.logger.error(f"Screenshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    def wait(self, seconds: float) -> dict:
        """
        等待指定时间
        
        Args:
            seconds: 等待秒数
            
        Returns:
            执行结果
        """
        try:
            time.sleep(seconds)
            self.logger.info(f"Waited {seconds} seconds")
            return {"success": True, "action": "wait", "seconds": seconds}
        except Exception as e:
            self.logger.error(f"Wait failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """
        获取当前鼠标位置
        
        Returns:
            (x, y) 坐标
        """
        return pyautogui.position()
    
    def get_screen_size(self) -> Tuple[int, int]:
        """
        获取屏幕尺寸
        
        Returns:
            (width, height)
        """
        return self.screen_width, self.screen_height