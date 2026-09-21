# 电脑操作AGENT

基于模块化架构的智能电脑操作代理，支持感知→决策→执行→验证的闭环循环。

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    调度层 Orchestrator                        │
│        感知 → 决策 → 安全检查 → 执行 → 验证 → 记忆            │
└───────┬─────────┬─────────┬─────────┬─────────┬─────────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │ 感知层 │ │ 决策层 │ │ 执行层 │ │ 验证层 │ │ 记忆层  │
   │Percept.│ │ Brain  │ │Actuator│ │Verifier│ │ Memory  │
   └────┬───┘ └───┬────┘ └──┬─────┘ └─┬──────┘ └┬────────┘
        │         │         │         │         │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐ ┌─▼──────┐ ┌▼────────┐
   │截屏/OCR│ │规则版  │ │鼠标键盘│ │截图diff│ │JSON存储 │
   │找图    │ │决策    │ │pyautogui│ │断言   │ │         │
   └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘
                                 │
                           ┌─────▼─────┐
                           │  安全层   │
                           │ Security  │
                           └───────────┘
```

## 安装

1. 安装Python 3.8+
2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 安装Tesseract OCR（可选）：
   - Windows: 下载安装 https://github.com/UB-Mannheim/tesseract/wiki
   - 添加到系统PATH

## 配置

编辑 `agent_config.json` 文件：

```json
{
  "core": {},
  "perception": {
    "ocr_engine": "tesseract"
  },
  "cognition": {
    "provider": "zhipu",
    "api_key": "your_api_key_here",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4-flash"
  },
  "memory": {
    "storage_path": "agent_storage"
  }
}
```

## 使用方法

### 启动AGENT

```bash
python main.py
```

### 交互命令

- `start <任务描述>` - 开始执行任务
- `stop` - 停止当前任务
- `status` - 查看状态
- `once` - 执行一次循环
- `quit` - 退出程序

### 示例

```
> start 打开记事本并输入"Hello World"
开始执行任务...
[INFO] Step 1: Perceiving...
[INFO] Step 2: Deciding...
[INFO] Step 3: Acting...
[INFO] Step 4: Verifying...
...
任务完成
```

## 模块说明

### interfaces.py（接口定义）
- `ScreenState`: 屏幕状态数据结构
- `Action`: 动作指令数据结构
- `ActionType`: 动作类型枚举
- 7个模块接口: Perception, Brain, Actuator, Verifier, Memory, Security, Tools

### modules/actuator.py（执行层）
- `PyAutoGUIActuator`: 基于pyautogui的执行层实现
- 支持7种标准动作类型
- 元素缓存机制

### modules/perception_v1.py（感知层）
- `BasicPerception`: 基础感知层实现
- 截屏、OCR文字识别、UI元素获取
- 文字查找、图像查找

### modules/brain_rule.py（决策层）
- `RuleBasedBrain`: 基于规则的决策层
- 目标解析、任务规划
- 状态更新、进度跟踪

### modules/verifier.py（验证层）
- `BasicVerifier`: 基础验证层实现
- 动作验证、文字断言、图像断言
- 等待功能

### modules/memory_json.py（记忆层）
- `JSONMemory`: 基于JSON的记忆层
- 数据保存/加载、执行状态记录
- 任务管理、上下文管理

### modules/orchestrator.py（调度层）
- `Orchestrator`: 调度层实现
- 主循环、模块协调
- 状态管理、回调函数

### modules/security.py（安全层）
- `BasicSecurity`: 基础安全层实现
- 审批门控、操作日志
- 危险动作检测

### CoreModule（核心执行模块）
- 点击、输入、快捷键、截屏等基础操作

### PerceptionModule（感知理解模块）
- OCR识别屏幕文字
- 查找文字/图像位置
- 获取UI元素树

### CognitionModule（决策推理模块）
- AI分析截图
- 规划下一步操作
- 生成执行命令

### MemoryModule（数据持久模块）
- 文件读写
- 任务状态管理
- 操作历史记录

## 快速开始

```python
from modules.perception_v1 import create_perception
from modules.brain_rule import create_brain
from modules.actuator import create_actuator
from modules.orchestrator import create_orchestrator

# 创建模块
perception = create_perception()
brain = create_brain()
actuator = create_actuator()

# 创建调度层
orchestrator = create_orchestrator()
orchestrator.set_modules(
    perception=perception,
    brain=brain,
    actuator=actuator
)

# 执行任务
success = orchestrator.start("打开记事本并输入Hello World")
```

详细说明请参考 `QUICKSTART.md`。

## 扩展开发

### 添加新模块

1. 在 `modules/` 目录下创建新文件
2. 继承对应的接口类（如 `Actuator`、`Perception` 等）
3. 实现接口方法
4. 在调度层中集成

### 自定义配置

修改模块配置：

```python
config = {
    "storage_path": "memory",
    "auto_approve": True,
    "max_retries": 3
}
memory = create_memory(config)
```

## 测试

运行所有测试：

```bash
python test_interfaces.py
python test_actuator.py
python test_perception_v1.py
python test_brain_rule.py
python test_verifier.py
python test_memory_json.py
python test_orchestrator.py
python test_security.py
```

## 注意事项

1. 首次使用需要安装依赖：`pip install pyautogui opencv-python pillow`
2. OCR功能需要安装Tesseract或EasyOCR
3. 某些操作可能需要管理员权限
4. 建议在虚拟环境中运行