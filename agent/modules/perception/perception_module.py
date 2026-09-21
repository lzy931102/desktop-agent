"""
感知理解模块
提供OCR、UI元素识别、图像匹配等功能
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_module import BaseModule

try:
    import cv2
    import numpy as np
except ImportError:
    print("请安装opencv: pip install opencv-python")
    sys.exit(1)

try:
    import pyautogui
except ImportError:
    print("请安装pyautogui: pip install pyautogui")
    sys.exit(1)


class PerceptionModule(BaseModule):
    """感知理解模块"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.ocr_engine = None
        self.ui_automation = None
    
    def initialize(self):
        """初始化模块"""
        super().initialize()
        
        # 初始化OCR引擎
        ocr_engine = self.get_config("ocr_engine", "tesseract")
        if ocr_engine == "tesseract":
            self._init_tesseract()
        elif ocr_engine == "easyocr":
            self._init_easyocr()
        
        # 初始化UI自动化
        self._init_ui_automation()
        
        self.logger.info(f"PerceptionModule initialized with OCR: {ocr_engine}")
    
    def _init_tesseract(self):
        """初始化Tesseract OCR"""
        try:
            import pytesseract
            self.ocr_engine = "tesseract"
            self.logger.info("Tesseract OCR initialized")
        except ImportError:
            self.logger.warning("pytesseract not installed, OCR disabled")
    
    def _init_easyocr(self):
        """初始化EasyOCR"""
        try:
            import easyocr
            self.ocr_engine = easyocr.Reader(['ch_sim', 'en'])
            self.logger.info("EasyOCR initialized")
        except ImportError:
            self.logger.warning("easyocr not installed, OCR disabled")
    
    def _init_ui_automation(self):
        """初始化UI自动化"""
        try:
            import comtypes.client
            self.ui_automation = "uiautomation"
            self.logger.info("UIAutomation initialized")
        except ImportError:
            self.logger.warning("UIAutomation not available")
    
    def process(self, input_data: dict) -> dict:
        """
        处理感知请求
        
        Args:
            input_data: 包含action和参数的字典
            
        Returns:
            感知结果
        """
        action = input_data.get("action")
        
        if action == "screenshot":
            return self.take_screenshot()
        
        elif action == "ocr":
            image_path = input_data.get("image_path")
            return self.ocr_image(image_path)
        
        elif action == "ocr_screen":
            return self.ocr_screen()
        
        elif action == "find_text":
            text = input_data.get("text", "")
            return self.find_text_on_screen(text)
        
        elif action == "find_image":
            image_path = input_data.get("image_path")
            confidence = input_data.get("confidence", 0.8)
            return self.find_image_on_screen(image_path, confidence)
        
        elif action == "get_ui_tree":
            return self.get_ui_tree()
        
        elif action == "analyze_screen":
            return self.analyze_screen()
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
    
    def take_screenshot(self) -> dict:
        """
        截屏
        
        Returns:
            截屏结果
        """
        try:
            screenshot = pyautogui.screenshot()
            import io
            img_bytes = io.BytesIO()
            screenshot.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            # 转换为OpenCV格式
            img_array = np.frombuffer(img_bytes.getvalue(), np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            
            return {"success": True, "image": img, "size": screenshot.size}
        except Exception as e:
            self.logger.error(f"Screenshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    def ocr_image(self, image_path: str) -> dict:
        """
        OCR识别图片中的文字
        
        Args:
            image_path: 图片路径
            
        Returns:
            识别结果
        """
        try:
            if self.ocr_engine == "tesseract":
                import pytesseract
                from PIL import Image
                
                img = Image.open(image_path)
                text = pytesseract.image_to_string(img, lang='chi_sim+eng')
                return {"success": True, "text": text.strip()}
            
            elif self.ocr_engine == "easyocr":
                result = self.ocr_engine.readtext(image_path)
                texts = [detection[1] for detection in result]
                return {"success": True, "text": " ".join(texts)}
            
            else:
                return {"success": False, "error": "No OCR engine available"}
        
        except Exception as e:
            self.logger.error(f"OCR failed: {e}")
            return {"success": False, "error": str(e)}
    
    def ocr_screen(self) -> dict:
        """
        OCR识别当前屏幕
        
        Returns:
            识别结果
        """
        try:
            screenshot = pyautogui.screenshot()
            import tempfile
            import os
            
            # 保存临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                screenshot.save(tmp.name)
                tmp_path = tmp.name
            
            # OCR识别
            result = self.ocr_image(tmp_path)
            
            # 删除临时文件
            os.unlink(tmp_path)
            
            return result
        except Exception as e:
            self.logger.error(f"Screen OCR failed: {e}")
            return {"success": False, "error": str(e)}
    
    def find_text_on_screen(self, text: str) -> dict:
        """
        在屏幕上查找文字位置
        
        Args:
            text: 要查找的文字
            
        Returns:
            查找结果
        """
        try:
            # 先截屏
            screenshot = pyautogui.screenshot()
            import tempfile
            import os
            
            # 保存临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                screenshot.save(tmp.name)
                tmp_path = tmp.name
            
            # OCR识别
            if self.ocr_engine == "tesseract":
                import pytesseract
                from PIL import Image
                
                img = Image.open(tmp_path)
                data = pytesseract.image_to_data(img, lang='chi_sim+eng', output_type=pytesseract.Output.DICT)
                
                # 查找文字位置
                for i, word in enumerate(data['text']):
                    if text.lower() in word.lower():
                        x = data['left'][i]
                        y = data['top'][i]
                        w = data['width'][i]
                        h = data['height'][i]
                        
                        # 删除临时文件
                        os.unlink(tmp_path)
                        
                        return {
                            "success": True,
                            "found": True,
                            "position": {"x": x, "y": y, "width": w, "height": h},
                            "center": {"x": x + w//2, "y": y + h//2}
                        }
            
            # 删除临时文件
            os.unlink(tmp_path)
            
            return {"success": True, "found": False}
        
        except Exception as e:
            self.logger.error(f"Find text failed: {e}")
            return {"success": False, "error": str(e)}
    
    def find_image_on_screen(self, image_path: str, confidence: float = 0.8) -> dict:
        """
        在屏幕上查找图像位置
        
        Args:
            image_path: 图像路径
            confidence: 匹配置信度
            
        Returns:
            查找结果
        """
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                return {
                    "success": True,
                    "found": True,
                    "position": {"x": location.left, "y": location.top, 
                                "width": location.width, "height": location.height},
                    "center": {"x": center.x, "y": center.y}
                }
            else:
                return {"success": True, "found": False}
        except Exception as e:
            self.logger.error(f"Find image failed: {e}")
            return {"success": False, "error": str(e)}
    
    def get_ui_tree(self) -> dict:
        """
        获取UI元素树
        
        Returns:
            UI元素树
        """
        try:
            # 这里简化实现，实际需要调用Windows UIAutomation
            # 返回当前窗口信息
            import pygetwindow as gw
            
            active_window = gw.getActiveWindow()
            if active_window:
                return {
                    "success": True,
                    "window": {
                        "title": active_window.title,
                        "position": {"x": active_window.left, "y": active_window.top},
                        "size": {"width": active_window.width, "height": active_window.height}
                    }
                }
            else:
                return {"success": True, "window": None}
        except Exception as e:
            self.logger.error(f"Get UI tree failed: {e}")
            return {"success": False, "error": str(e)}
    
    def analyze_screen(self) -> dict:
        """
        分析屏幕内容
        
        Returns:
            分析结果
        """
        try:
            # 截屏
            screenshot = pyautogui.screenshot()
            
            # 获取基本信息
            import pygetwindow as gw
            active_window = gw.getActiveWindow()
            
            # OCR识别
            ocr_result = self.ocr_screen()
            
            return {
                "success": True,
                "analysis": {
                    "screen_size": screenshot.size,
                    "active_window": {
                        "title": active_window.title if active_window else None,
                        "position": {"x": active_window.left, "y": active_window.top} if active_window else None
                    },
                    "ocr_text": ocr_result.get("text", "") if ocr_result.get("success") else None
                }
            }
        except Exception as e:
            self.logger.error(f"Analyze screen failed: {e}")
            return {"success": False, "error": str(e)}