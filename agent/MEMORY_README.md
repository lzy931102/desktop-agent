# 记忆层模块 (Memory - JSON版)

## 概述

记忆层负责存储任务状态、历史记录和上下文信息。本模块基于JSON文件实现，简单易用。

## 文件结构

```
modules/memory_json.py   # 记忆层实现
test_memory_json.py      # 单元测试
example_memory.py        # 使用示例
```

## 核心类

### JSONMemory

基于JSON的记忆层实现，继承自`Memory`接口。

```python
from modules.memory_json import create_memory

memory = create_memory()
```

## 核心功能

### 基本保存和加载

```python
# 保存数据
memory.save("user_config", {"theme": "dark"})

# 加载数据
config = memory.load("user_config")
print(config)  # {'theme': 'dark'}
```

### 保存执行状态

```python
from interfaces import ScreenState, Action, ActionType

state = ScreenState(screenshot="...", texts=[...])
action = Action(action=ActionType.CLICK, target={"text": "确定"})

# 保存状态
memory.save_state(state, action, success=True)

# 获取历史记录
history = memory.get_history(limit=10)
```

### 任务管理

```python
# 保存任务
task = {"goal": "打开记事本", "status": "running"}
memory.save_task("task_001", task)

# 加载任务
task = memory.load_task("task_001")
```

### 上下文管理

```python
# 保存上下文
context = {"user": "admin", "session": "001"}
memory.save_context("session_001", context)

# 加载上下文
context = memory.load_context("session_001")
```

## 存储结构

```
memory/
├── user_config.json           # 用户配置
├── execution_history.json     # 执行历史
├── task_task_001.json         # 任务数据
├── context_session_001.json   # 上下文数据
└── ...
```

## 配置

```python
config = {
    "storage_path": "memory",    # 存储目录
    "max_history": 100           # 最大历史记录数
}

memory = create_memory(config)
```

## 使用示例

```python
from modules.memory_json import create_memory
from interfaces import ScreenState, Action, ActionType

memory = create_memory()

# 保存状态
state = ScreenState(screenshot="...")
action = Action(action=ActionType.CLICK, target={"text": "确定"})
memory.save_state(state, action, success=True)

# 获取历史
history = memory.get_history()
```

## 测试

运行单元测试：

```bash
python test_memory_json.py
```

运行使用示例：

```bash
python example_memory.py
```

## 后续升级

1. **SQLite存储**: 数据量大时升级到SQLite
2. **项目记忆**: 绑定到特定项目/文件夹
3. **上下文管理**: 更复杂的上下文管理
4. **数据压缩**: 压缩存储的截图数据
