# 感知层模块 (Perception v1)

## 概述

感知层负责将屏幕转换为Agent能理解的结构化信息。支持截屏、OCR文字识别、UI元素获取等功能。

## 文件结构

```
modules/perception_v1.py      # 感知层实现
modules/perception/           # 原有感知模块
test_perception_v1.py         # 单元测试
example_perception.py         # 使用示例
```

## 核心类

### BasicPerception

基础感知层实现，继承自`Perception`接口。

```python
from modules.perception_v1 import create_perception

perception = create_perception()
```

## 核心功能

### 截屏

```python
state = perception.capture()

print(f"截图路径: {state.screenshot_path}")
print(f"base64大小: {len(state.screenshot)} 字符")
```

### OCR文字识别

```python
# 自动在capture()中执行
state = perception.capture()

# 查看识别到的文字
for text in state.texts:
    print(f"文字: {text['text']}")
    print(f"位置: {text['bbox']}")
    print(f"置信度: {text['confidence']}")
```

### 查找文字

```python
result = perception.find_text("确定")
if result:
    print(f"位置: {result['bbox']}")
    print(f"中心点: {result['center']}")
```

### 查找元素

```python
# 通过文字查找
result = perception.find_element({"text": "确定"})

# 通过引用查找
result = perception.find_element({"ref": "hwnd:12345"})

# 通过图像查找
result = perception.find_element({"image": "button.png"})
```

## 输出格式

### ScreenState

```python
ScreenState(
    screenshot="base64...",           # base64编码截图
    screenshot_path="screenshots/...", # 截图文件路径
    texts=[                           # OCR识别结果
        {
            "text": "确定",
            "bbox": [100, 200, 160, 230],
            "confidence": 0.98
        }
    ],
    elements=[                        # UI元素
        {
            "type": "button",
            "name": "确定",
            "bbox": [100, 200, 160, 230],
            "ref": "hwnd:12345"
        }
    ],
    active_window={                   # 当前窗口
        "title": "记事本",
        "hwnd": 12345
    }
)
```

## 依赖

- pyautogui: 截屏
- opencv-python: 图像处理
- pytesseract (可选): OCR识别
- easyocr (可选): OCR识别
- uiautomation (可选): UI元素获取

## 安装OCR支持

### Tesseract

```bash
# Windows
# 下载安装: https://github.com/UB-Mannheim/tesseract/wiki
pip install pytesseract

# 添加到系统PATH
```

### EasyOCR

```bash
pip install easyocr
```

## 测试

运行单元测试：

```bash
python test_perception_v1.py
```

运行使用示例：

```bash
python example_perception.py
```

## 后续集成

感知层需要与以下模块集成：

1. **Actuator**: 提供元素坐标给执行层
2. **Brain**: 提供屏幕状态给决策层
3. **Verifier**: 提供验证所需的屏幕状态

## 已知限制

1. OCR需要安装Tesseract或EasyOCR
2. UIA需要安装uiautomation库
3. 某些功能可能需要管理员权限
