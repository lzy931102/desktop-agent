# 快速开始

## 安装依赖

```bash
pip install pyautogui opencv-python pillow
```

## 基本使用

### 1. 创建模块

```python
from modules.perception_v1 import create_perception
from modules.brain_rule import create_brain
from modules.actuator import create_actuator
from modules.verifier import create_verifier
from modules.memory_json import create_memory
from modules.security import create_security
from modules.orchestrator import create_orchestrator

# 创建模块
perception = create_perception()
brain = create_brain()
actuator = create_actuator()
verifier = create_verifier()
memory = create_memory()
security = create_security({"auto_approve": True})

# 创建调度层
orchestrator = create_orchestrator()
orchestrator.set_modules(
    perception=perception,
    brain=brain,
    actuator=actuator,
    verifier=verifier,
    memory=memory,
    security=security
)
```

### 2. 执行任务

```python
# 执行任务
success = orchestrator.start("打开记事本并输入Hello World")

# 查看状态
status = orchestrator.get_status()
print(status)
```

### 3. 手动控制

```python
from interfaces import ScreenState, Action, ActionType

# 感知
state = perception.capture()

# 决策
action = brain.decide(state, "打开记事本")

# 执行
success = actuator.execute(action)

# 验证
after = perception.capture()
verified = verifier.verify(state, after, action)

# 记忆
memory.save_state(state, action, verified)
```

## 模块说明

| 模块 | 文件 | 说明 |
|------|------|------|
| 接口 | `interfaces.py` | 统一数据结构和接口定义 |
| 感知层 | `modules/perception_v1.py` | 截屏、OCR、元素识别 |
| 决策层 | `modules/brain_rule.py` | 规则版决策 |
| 执行层 | `modules/actuator.py` | 鼠标键盘操作 |
| 验证层 | `modules/verifier.py` | 动作验证 |
| 记忆层 | `modules/memory_json.py` | JSON存储 |
| 调度层 | `modules/orchestrator.py` | 主循环 |
| 安全层 | `modules/security.py` | 审批门控 |

## 运行测试

```bash
# 运行所有测试
python test_interfaces.py
python test_actuator.py
python test_perception_v1.py
python test_brain_rule.py
python test_verifier.py
python test_memory_json.py
python test_orchestrator.py
python test_security.py

# 运行集成示例
python example_integration.py
```
