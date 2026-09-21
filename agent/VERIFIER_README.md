# 验证层模块 (Verifier)

## 概述

验证层负责判断动作是否成功。通过对比执行前后的屏幕状态，验证动作是否达到预期效果。

## 文件结构

```
modules/verifier.py     # 验证层实现
test_verifier.py        # 单元测试
example_verifier.py     # 使用示例
```

## 核心类

### BasicVerifier

基础验证层实现，继承自`Verifier`接口。

```python
from modules.verifier import create_verifier

verifier = create_verifier()
```

## 核心功能

### 动作验证

```python
# 执行前后的屏幕状态
before = ScreenState(...)
after = ScreenState(...)

# 动作
action = Action(action=ActionType.CLICK, target={"text": "确定"})

# 验证
result = verifier.verify(before, after, action)
print(f"验证结果: {result}")
```

### 文字断言

```python
# 断言屏幕存在指定文字
found = verifier.assert_text("确定", timeout=5.0)

# 等待文字出现
found = verifier.wait_for_text("加载完成", timeout=10.0)
```

### 图像断言

```python
# 断言屏幕存在指定图像
found = verifier.assert_image("button.png", timeout=5.0)

# 等待图像出现
found = verifier.wait_for_image("loading.gif", timeout=10.0)
```

## 验证策略

### 点击验证

- 检查屏幕是否发生变化
- 如果点击后无变化，可能是无效点击

### 输入验证

- 检查屏幕是否出现新文字
- 验证输入是否成功

### 快捷键验证

- 检查屏幕变化
- 某些快捷键可能不会立即产生视觉变化

### 截图对比

- 对比执行前后的截图
- 计算差异比例

## 使用示例

```python
from modules.verifier import create_verifier
from interfaces import ScreenState, Action, ActionType

verifier = create_verifier()

# 模拟状态
before = ScreenState(screenshot="before...")
after = ScreenState(screenshot="after...")

# 验证点击
action = Action(action=ActionType.CLICK, target={"text": "确定"})
result = verifier.verify(before, after, action)

# 等待文字出现
verifier.wait_for_text("操作成功", timeout=10.0)
```

## 配置

```python
config = {
    "screenshot_dir": "screenshots",  # 截图保存目录
    "diff_threshold": 0.1             # 差异阈值 (10%)
}

verifier = create_verifier(config)
```

## 测试

运行单元测试：

```bash
python test_verifier.py
```

运行使用示例：

```bash
python example_verifier.py
```

## 后续增强

1. **图像相似度对比**: 使用OpenCV进行像素级对比
2. **OCR验证**: 通过OCR识别验证文字内容
3. **UI元素验证**: 验证UI元素状态变化
4. **容差自愈**: 允许一定偏差并自动重试
