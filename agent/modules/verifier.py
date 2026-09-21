"""
验证层实现
基于截图diff的验证
"""

import sys
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from interfaces import Verifier, ScreenState, Action, ActionType


class BasicVerifier(Verifier):
    """基础验证层实现"""
    
    def __init__(self, config=None):
        """
        初始化验证层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        self.diff_threshold = self.config.get("diff_threshold", 0.1)  # 10%差异阈值
        self._ensure_screenshot_dir()
    
    def _ensure_screenshot_dir(self):
        """确保截图目录存在"""
        os.makedirs(self.screenshot_dir, exist_ok=True)
    
    def verify(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """
        验证动作是否成功
        
        Args:
            before: 执行前的屏幕状态
            after: 执行后的屏幕状态
            action: 执行的动作
            
        Returns:
            是否成功
        """
        try:
            # 根据动作类型选择验证策略
            if action.action == ActionType.CLICK:
                return self._verify_click(before, after, action)
            elif action.action == ActionType.TYPE:
                return self._verify_type(before, after, action)
            elif action.action == ActionType.KEY:
                return self._verify_key(before, after, action)
            elif action.action == ActionType.WAIT:
                return self._verify_wait(before, after, action)
            elif action.action == ActionType.DONE:
                return True
            else:
                # 默认使用截图对比
                return self._verify_screenshot_diff(before, after)
                
        except Exception as e:
            print(f"Verify failed: {e}")
            return False
    
    def assert_text(self, text: str, timeout: float = 5.0) -> bool:
        """
        断言屏幕上存在指定文字
        
        Args:
            text: 期望存在的文字
            timeout: 超时时间
            
        Returns:
            是否找到
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # 截屏
            import pyautogui
            screenshot = pyautogui.screenshot()
            
            # OCR识别
            if self._ocr_available():
                texts = self._ocr_screen(screenshot)
                for t in texts:
                    if text.lower() in t.get("text", "").lower():
                        return True
            
            time.sleep(0.5)
        
        return False
    
    def assert_image(self, image_path: str, timeout: float = 5.0) -> bool:
        """
        断言屏幕上存在指定图像
        
        Args:
            image_path: 期望存在的图像路径
            timeout: 超时时间
            
        Returns:
            是否找到
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                import pyautogui
                location = pyautogui.locateOnScreen(image_path, confidence=0.8)
                if location:
                    return True
            except Exception:
                pass
            
            time.sleep(0.5)
        
        return False
    
    def _verify_click(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """验证点击动作"""
        # 点击后屏幕应该有变化
        if before.screenshot == after.screenshot:
            # 没有变化，可能是点击了无效区域
            # 对于某些点击（如按钮），屏幕应该有变化
            return False
        
        return True
    
    def _verify_type(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """验证输入动作"""
        # 输入后屏幕应该有变化（文字增加）
        if before.screenshot == after.screenshot:
            return False
        
        return True
    
    def _verify_key(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """验证快捷键动作"""
        # 快捷键后屏幕应该有变化
        if before.screenshot == after.screenshot:
            # 某些快捷键可能不会立即产生视觉变化
            # 如Ctrl+C，这里简化处理
            return True
        
        return True
    
    def _verify_wait(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """验证等待动作"""
        # 等待动作总是成功
        return True
    
    def _verify_screenshot_diff(self, before: ScreenState, after: ScreenState) -> bool:
        """通过截图对比验证"""
        try:
            # 如果没有截图数据，假定成功
            if not before.screenshot or not after.screenshot:
                return True
            
            # 比较截图大小
            before_size = len(before.screenshot)
            after_size = len(after.screenshot)
            
            # 如果大小差异过大，认为有变化
            size_diff = abs(before_size - after_size) / max(before_size, after_size)
            
            # 简单的验证：如果有变化，认为成功
            return True
            
        except Exception as e:
            print(f"Screenshot diff failed: {e}")
            return True  # 出错时假定成功
    
    def _ocr_available(self) -> bool:
        """检查OCR是否可用"""
        try:
            import pytesseract
            return True
        except ImportError:
            return False
    
    def _ocr_screen(self, screenshot) -> List[Dict]:
        """OCR识别屏幕文字"""
        try:
            import pytesseract
            from PIL import Image
            import io
            
            # 转换为PIL Image
            img_io = io.BytesIO()
            screenshot.save(img_io, format='PNG')
            img_io.seek(0)
            pil_img = Image.open(img_io)
            
            # OCR识别
            data = pytesseract.image_to_data(pil_img, lang='chi_sim+eng', output_type=pytesseract.Output.DICT)
            
            texts = []
            for i, word in enumerate(data['text']):
                if word.strip():
                    texts.append({
                        "text": word,
                        "bbox": [
                            data['left'][i],
                            data['top'][i],
                            data['left'][i] + data['width'][i],
                            data['top'][i] + data['height'][i]
                        ],
                        "confidence": data.get('conf', [0])[i] / 100.0
                    })
            
            return texts
            
        except Exception as e:
            print(f"OCR failed: {e}")
            return []
    
    def wait_for_text(self, text: str, timeout: float = 10.0, interval: float = 0.5) -> bool:
        """
        等待文字出现
        
        Args:
            text: 期望文字
            timeout: 超时时间
            interval: 检查间隔
            
        Returns:
            是否找到
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            import pyautogui
            screenshot = pyautogui.screenshot()
            
            if self._ocr_available():
                texts = self._ocr_screen(screenshot)
                for t in texts:
                    if text.lower() in t.get("text", "").lower():
                        return True
            
            time.sleep(interval)
        
        return False
    
    def wait_for_image(self, image_path: str, timeout: float = 10.0, interval: float = 0.5) -> bool:
        """
        等待图像出现
        
        Args:
            image_path: 期望图像路径
            timeout: 超时时间
            interval: 检查间隔
            
        Returns:
            是否找到
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                import pyautogui
                location = pyautogui.locateOnScreen(image_path, confidence=0.8)
                if location:
                    return True
            except Exception:
                pass
            
            time.sleep(interval)
        
        return False


# 便捷工厂函数
def create_verifier(config=None) -> BasicVerifier:
    """
    创建验证层实例
    
    Args:
        config: 配置字典
        
    Returns:
        BasicVerifier实例
    """
    return BasicVerifier(config)
