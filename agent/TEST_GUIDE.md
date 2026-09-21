# 测试指南

## 测试方式

### 方式1：运行单元测试

```bash
# 运行所有测试
python test_interfaces.py      # 接口测试
python test_actuator.py        # 执行层测试
python test_perception_v1.py   # 感知层测试
python test_brain_rule.py      # 决策层测试
python test_verifier.py        # 验证层测试
python test_memory_json.py     # 记忆层测试
python test_orchestrator.py    # 调度层测试
python test_security.py        # 安全层测试
```

### 方式2：运行使用示例

```bash
python example_interfaces.py   # 接口示例
python example_actuator.py     # 执行层示例
python example_perception.py   # 感知层示例
python example_brain.py        # 决策层示例
python example_verifier.py     # 验证层示例
python example_memory.py       # 记忆层示例
python example_orchestrator.py # 调度层示例
python example_security.py     # 安全层示例
python example_integration.py  # 集成示例
```

### 方式3：交互式测试

```python
# 在Python中测试
from modules.perception_v1 import create_perception
from modules.actuator import create_actuator

# 测试感知层
perception = create_perception()
state = perception.capture()
print(f"截图路径: {state.screenshot_path}")

# 测试执行层
actuator = create_actuator()
actuator.click(100, 100)  # 点击屏幕100,100位置
```

## 测试截图

运行后会在 `screenshots/` 目录生成截图文件。
