# 决策层模块 (Brain - 规则版)

## 概述

决策层负责根据屏幕状态和任务目标，输出下一步动作。本模块是基于规则的简单实现，先跑通闭环。

## 文件结构

```
modules/brain_rule.py    # 决策层实现
test_brain_rule.py       # 单元测试
example_brain.py         # 使用示例
```

## 核心类

### RuleBasedBrain

基于规则的决策层实现，继承自`Brain`接口。

```python
from modules.brain_rule import create_brain

brain = create_brain()
```

## 核心功能

### 决策

```python
state = ScreenState(...)  # 感知层输出
goal = "打开记事本并输入Hello World"

action = brain.decide(state, goal)
print(f"动作: {action.action}")
```

### 任务规划

```python
actions = brain.plan(goal)
for action in actions:
    print(f"步骤: {action.action}")
```

### 状态更新

```python
# 执行后更新状态
brain.update_state(state, action, success=True)

# 查看进度
progress = brain.get_progress()
print(f"进度: {progress['progress']:.2%}")
```

## 支持的目标类型

| 目标 | 解析结果 |
|------|----------|
| 打开记事本 | open_app: notepad |
| 输入Hello World | type_text: Hello World |
| 点击确定按钮 | click: {"text": "确定"} |
| 按Ctrl+S保存 | hotkey: ["ctrl", "s"] |
| 打开浏览器 | open_app: chrome |

## 工作流程

```
1. 解析目标 -> 生成步骤列表
2. 根据当前步骤 -> 生成动作
3. 执行动作 -> 更新状态
4. 重复直到完成
```

## 使用示例

```python
from modules.brain_rule import create_brain
from interfaces import ScreenState

brain = create_brain()

# 创建屏幕状态
state = ScreenState(
    screenshot="base64...",
    texts=[{"text": "确定", "bbox": [100, 200, 160, 230]}],
    elements=[],
    active_window={"title": "记事本"}
)

# 决策
goal = "打开记事本并输入Hello World"
action = brain.decide(state, goal)

# 执行后更新
brain.update_state(state, action, success=True)
```

## 测试

运行单元测试：

```bash
python test_brain_rule.py
```

运行使用示例：

```bash
python example_brain.py
```

## 后续升级

规则版决策层的局限性：

1. 只能处理简单、固定流程的任务
2. 无法理解复杂的自然语言目标
3. 缺乏错误恢复能力

后续版本将集成AI推理：

1. 接入GPT-4V/Qwen-VL等多模态模型
2. 实现自然语言理解
3. 支持动态任务规划
4. 具备错误恢复能力

## 集成说明

决策层需要与以下模块集成：

1. **Perception**: 获取屏幕状态
2. **Actuator**: 执行动作
3. **Verifier**: 验证执行结果
4. **Memory**: 保存执行历史
