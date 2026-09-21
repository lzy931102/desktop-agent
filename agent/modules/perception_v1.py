"""
感知层实现
包装现有能力为Perception接口实现
"""

import sys
import io
import base64
import tempfile
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from interfaces import Perception, ScreenState
from modules.perception.perception_module import PerceptionModule


class BasicPerception(Perception):
    """基础感知层实现"""
    
    def __init__(self, config=None):
        """
        初始化感知层
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.perception_module = PerceptionModule(config)
        self.perception_module.initialize()
    
    def capture(self) -> ScreenState:
        """
        捕获当前屏幕状态
        
        Returns:
            ScreenState: 屏幕状态对象
        """
        try:
            # 截屏
            screenshot_result = self.perception_module.take_screenshot()
            if not screenshot_result.get("success"):
                raise Exception(f"Screenshot failed: {screenshot_result.get('error')}")
            
            img = screenshot_result.get("image")
            
            # 转换为base64
            screenshot_base64 = self._image_to_base64(img)
            
            # 保存截图
            screenshot_path = f"screenshots/screen_{int(__import__('time').time())}.png"
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            __import__('cv2').imwrite(screenshot_path, img)
            
            # OCR识别
            texts = self._ocr_with_positions(img)
            
            # 获取UI元素
            elements = self._get_ui_elements()
            
            # 获取当前窗口
            active_window = self._get_active_window()
            
            return ScreenState(
                screenshot=screenshot_base64,
                screenshot_path=screenshot_path,
                texts=texts,
                elements=elements,
                active_window=active_window
            )
            
        except Exception as e:
            self.perception_module.logger.error(f"Capture failed: {e}")
            # 返回空状态
            return ScreenState(screenshot="")
    
    def find_element(self, target: Dict) -> Optional[Dict]:
        """
        查找屏幕元素
        
        Args:
            target: 目标描述
            
        Returns:
            找到的元素信息
        """
        try:
            # 根据目标类型查找
            if "text" in target:
                return self._find_by_text(target["text"])
            elif "ref" in target:
                return self._find_by_ref(target["ref"])
            elif "image" in target:
                return self._find_by_image(target["image"])
            else:
                return None
                
        except Exception as e:
            self.perception_module.logger.error(f"Find element failed: {e}")
            return None
    
    def find_text(self, text: str) -> Optional[Dict]:
        """
        查找屏幕上的文字
        
        Args:
            text: 要查找的文字
            
        Returns:
            文字信息
        """
        try:
            result = self.perception_module.find_text_on_screen(text)
            if result.get("success") and result.get("found"):
                position = result.get("position", {})
                center = result.get("center", {})
                return {
                    "text": text,
                    "bbox": [
                        position.get("x", 0),
                        position.get("y", 0),
                        position.get("x", 0) + position.get("width", 0),
                        position.get("y", 0) + position.get("height", 0)
                    ],
                    "center": center,
                    "confidence": 0.9
                }
            return None
            
        except Exception as e:
            self.perception_module.logger.error(f"Find text failed: {e}")
            return None
    
    def _image_to_base64(self, img) -> str:
        """将图像转换为base64编码"""
        try:
            import cv2
            _, buffer = cv2.imencode('.png', img)
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            return img_base64
        except Exception as e:
            self.perception_module.logger.error(f"Image to base64 failed: {e}")
            return ""
    
    def _ocr_with_positions(self, img) -> List[Dict]:
        """OCR识别并获取文字位置"""
        try:
            import cv2
            
            # 保存临时文件
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, img)
                tmp_path = tmp.name
            
            # OCR识别
            texts = []
            if self.perception_module.ocr_engine == "tesseract":
                try:
                    import pytesseract
                    from PIL import Image
                    
                    pil_img = Image.open(tmp_path)
                    data = pytesseract.image_to_data(pil_img, lang='chi_sim+eng', output_type=pytesseract.Output.DICT)
                    
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
                except ImportError:
                    pass
            
            # 删除临时文件
            os.unlink(tmp_path)
            
            return texts
            
        except Exception as e:
            self.perception_module.logger.error(f"OCR with positions failed: {e}")
            return []
    
    def _get_ui_elements(self) -> List[Dict]:
        """获取UI元素列表"""
        try:
            elements = []
            
            # 获取当前窗口信息
            result = self.perception_module.get_ui_tree()
            if result.get("success") and result.get("window"):
                window = result["window"]
                elements.append({
                    "type": "window",
                    "name": window.get("title", ""),
                    "bbox": [
                        window.get("position", {}).get("x", 0),
                        window.get("position", {}).get("y", 0),
                        window.get("position", {}).get("x", 0) + window.get("size", {}).get("width", 0),
                        window.get("position", {}).get("y", 0) + window.get("size", {}).get("height", 0)
                    ],
                    "ref": f"window:{window.get('title', '')}"
                })
            
            return elements
            
        except Exception as e:
            self.perception_module.logger.error(f"Get UI elements failed: {e}")
            return []
    
    def _get_active_window(self) -> Dict:
        """获取当前活动窗口信息"""
        try:
            result = self.perception_module.get_ui_tree()
            if result.get("success") and result.get("window"):
                window = result["window"]
                return {
                    "title": window.get("title", ""),
                    "hwnd": 0  # 简化实现
                }
            return {}
            
        except Exception as e:
            self.perception_module.logger.error(f"Get active window failed: {e}")
            return {}
    
    def _find_by_text(self, text: str) -> Optional[Dict]:
        """通过文字查找元素"""
        return self.find_text(text)
    
    def _find_by_ref(self, ref: str) -> Optional[Dict]:
        """通过引用查找元素"""
        # TODO: 实现UIA元素引用查找
        return None
    
    def _find_by_image(self, image_path: str) -> Optional[Dict]:
        """通过图像查找元素"""
        try:
            result = self.perception_module.find_image_on_screen(image_path)
            if result.get("success") and result.get("found"):
                position = result.get("position", {})
                center = result.get("center", {})
                return {
                    "type": "image",
                    "name": image_path,
                    "bbox": [
                        position.get("x", 0),
                        position.get("y", 0),
                        position.get("x", 0) + position.get("width", 0),
                        position.get("y", 0) + position.get("height", 0)
                    ],
                    "center": center,
                    "ref": f"image:{image_path}"
                }
            return None
            
        except Exception as e:
            self.perception_module.logger.error(f"Find by image failed: {e}")
            return None


# 便捷工厂函数
def create_perception(config=None) -> BasicPerception:
    """
    创建感知层实例
    
    Args:
        config: 配置字典
        
    Returns:
        BasicPerception实例
    """
    return BasicPerception(config)
