# 调度层模块 (Orchestrator)

## 概述

调度层负责将所有模块串联成主循环，实现感知→决策→执行→验证的闭环。

## 文件结构

```
modules/orchestrator.py    # 调度层实现
test_orchestrator.py       # 单元测试
example_orchestrator.py    # 使用示例
```

## 核心类

### Orchestrator

调度层实现，负责模块协调和主循环。

```python
from modules.orchestrator import create_orchestrator

orchestrator = create_orchestrator()
```

## 核心功能

### 设置模块

```python
orchestrator.set_modules(
    perception=perception,
    brain=brain,
    actuator=actuator,
    verifier=verifier,
    memory=memory,
    security=security
)
```

### 执行任务

```python
# 开始任务
success = orchestrator.start("打开记事本并输入Hello World")

# 停止任务
orchestrator.stop()

# 暂停/恢复
orchestrator.pause()
orchestrator.resume()
```

### 回调函数

```python
def on_step_complete(step, action, success):
    print(f"步骤{step}完成")

def on_task_complete(goal, total_steps):
    print(f"任务完成")

def on_error(error, retry_count):
    print(f"错误: {error}")

orchestrator.on_step_complete = on_step_complete
orchestrator.on_task_complete = on_task_complete
orchestrator.on_error = on_error
```

## 工作流程

```
while 任务未完成:
    1. before = Perception.capture()          # 感知
    2. action = Brain.decide(before, goal)   # 决策
    3. Security.check(action)                # 安全检查
    4. Actuator.execute(action)              # 执行
    5. after = Perception.capture()          # 再次感知
    6. ok = Verifier.verify(before, after, action)  # 验证
    7. Memory.save(state, action, ok)        # 记忆
    8. Brain.update_state(state, action, ok) # 更新状态
```

## 任务状态

| 状态 | 说明 |
|------|------|
| IDLE | 空闲 |
| RUNNING | 运行中 |
| PAUSED | 已暂停 |
| COMPLETED | 已完成 |
| FAILED | 失败 |

## 使用示例

```python
from modules.orchestrator import create_orchestrator

orchestrator = create_orchestrator()

# 设置模块
orchestrator.set_modules(
    perception=perception,
    brain=brain,
    actuator=actuator
)

# 执行任务
success = orchestrator.start("打开记事本")

# 查看状态
status = orchestrator.get_status()
print(status)
```

## 配置

```python
config = {
    "max_retries": 3  # 最大重试次数
}

orchestrator = create_orchestrator(config)
```

## 测试

运行单元测试：

```bash
python test_orchestrator.py
```

运行使用示例：

```bash
python example_orchestrator.py
```

## 后续增强

1. **任务队列**: 支持多任务调度
2. **定时任务**: 支持定时执行
3. **并行执行**: 支持并行处理多个任务
4. **任务取消**: 支持取消正在执行的任务
