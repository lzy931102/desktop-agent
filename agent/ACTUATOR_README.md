# 执行层模块 (Actuator)

## 概述

执行层负责将标准动作指令转换为真实的鼠标键盘操作。基于pyautogui实现，支持7种标准动作类型。

## 文件结构

```
modules/actuator.py        # 执行层实现
test_actuator.py           # 单元测试
example_actuator.py        # 使用示例
```

## 核心类

### PyAutoGUIActuator

基于pyautogui的执行层实现，继承自`Actuator`接口。

```python
from modules.actuator import create_actuator

actuator = create_actuator()
```

## 支持的动作类型

| 动作 | 说明 | 目标格式 |
|------|------|----------|
| CLICK | 点击 | `{"x": 100, "y": 200}` 或 `{"text": "确定"}` 或 `{"ref": "hwnd:12345"}` |
| TYPE | 输入文字 | 通过`text`参数 |
| KEY | 快捷键 | 通过`keys`参数，如`["ctrl", "c"]` |
| SELECT | 选择元素 | 同CLICK |
| EXPAND | 展开元素 | 同CLICK |
| WAIT | 等待 | 通过`condition`参数 |
| DONE | 完成 | 无 |

## 使用方法

### 基本操作

```python
from modules.actuator import create_actuator

actuator = create_actuator()

# 点击坐标
actuator.click(100, 200)

# 输入文字
actuator.type_text("Hello")

# 快捷键
actuator.press_keys(["ctrl", "c"])

# 截屏
actuator.screenshot("screenshot.png")
```

### 执行Action对象

```python
from interfaces import create_click_action, create_type_action, create_key_action

# 点击
action = create_click_action({"x": 100, "y": 200})
actuator.execute(action)

# 输入
action = create_type_action("Hello")
actuator.execute(action)

# 快捷键
action = create_key_action(["ctrl", "c"])
actuator.execute(action)
```

### 元素缓存

```python
# 更新缓存（来自感知层）
elements = [
    {"ref": "hwnd:12345", "bbox": [100, 200, 160, 230]},
    {"ref": "hwnd:12346", "bbox": [300, 400, 360, 430]}
]
actuator.update_element_cache(elements)

# 通过ref点击
action = create_click_action({"ref": "hwnd:12345"})
actuator.execute(action)

# 清空缓存
actuator.clear_element_cache()
```

## 目标解析

执行层支持多种目标格式：

1. **直接坐标**: `{"x": 100, "y": 200}`
2. **元素引用**: `{"ref": "hwnd:12345"}` - 从缓存获取坐标
3. **文字查找**: `{"text": "确定"}` - 需要集成OCR/UIA

## 多层定位Fallback

执行层支持多层定位策略（部分需集成Perception模块）：

```
UIA可访问性树 → OCR文字 → 图像匹配 → VLM定位 → 锚点定位 → 自愈定位
```

## 测试

运行单元测试：

```bash
python test_actuator.py
```

运行使用示例：

```bash
python example_actuator.py
```

## 依赖

- pyautogui: 鼠标键盘操作
- CoreModule: 底层操作封装

## 后续集成

执行层需要与以下模块集成：

1. **Perception**: 提供元素坐标
2. **Brain**: 提供Action对象
3. **Verifier**: 验证执行结果
