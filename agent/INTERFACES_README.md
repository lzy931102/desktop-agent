# 接口定义模块

## 概述

本模块定义了电脑操作AGENT的统一数据结构和模块接口，是整个系统的基础。

## 文件结构

```
interfaces.py          # 统一数据结构和模块接口定义
test_interfaces.py     # 接口测试
example_interfaces.py  # 使用示例
```

## 核心数据结构

### ScreenState

屏幕状态数据类，感知层输出。

```python
@dataclass
class ScreenState:
    screenshot: str                          # base64编码截图
    screenshot_path: str = ""                # 截图文件路径
    texts: List[Dict] = field(default_factory=list)      # OCR结果
    elements: List[Dict] = field(default_factory=list)   # UIA/找图元素
    active_window: Dict = field(default_factory=dict)    # 当前窗口信息
```

### Action

动作指令数据类，决策层输出。

```python
@dataclass
class Action:
    action: str                              # 动作类型
    target: Optional[Dict] = None            # 目标描述
    text: Optional[str] = None               # 输入文字
    keys: Optional[List[str]] = None         # 快捷键组合
    condition: Optional[Dict] = None         # 等待条件
```

### ActionType

动作类型枚举：

| 类型 | 说明 | 参数 |
|------|------|------|
| CLICK | 点击目标 | target: {"text": "确定"} 或 {"ref": "hwnd:12345"} |
| TYPE | 输入文字 | text: "hello" |
| SELECT | 选择元素 | target: {"ref": "hwnd:12345"} |
| EXPAND | 展开元素 | target: {...} |
| KEY | 按快捷键 | keys: ["ctrl", "c"] |
| WAIT | 等待条件满足 | condition: {"text": "加载完成"} |
| DONE | 任务完成 | 无 |

## 模块接口

### Perception (感知层)

```python
class Perception(ABC):
    def capture(self) -> ScreenState: ...
    def find_element(self, target: Dict) -> Optional[Dict]: ...
    def find_text(self, text: str) -> Optional[Dict]: ...
```

### Brain (决策层)

```python
class Brain(ABC):
    def decide(self, state: ScreenState, goal: str) -> Action: ...
    def plan(self, goal: str) -> List[Action]: ...
    def update_state(self, state: ScreenState, action: Action, success: bool): ...
```

### Actuator (执行层)

```python
class Actuator(ABC):
    def execute(self, action: Action) -> bool: ...
    def click(self, x: int, y: int, button: str = "left") -> bool: ...
    def type_text(self, text: str) -> bool: ...
    def press_keys(self, keys: List[str]) -> bool: ...
```

### Verifier (验证层)

```python
class Verifier(ABC):
    def verify(self, before: ScreenState, after: ScreenState, action: Action) -> bool: ...
    def assert_text(self, text: str, timeout: float = 5.0) -> bool: ...
    def assert_image(self, image_path: str, timeout: float = 5.0) -> bool: ...
```

### Memory (记忆层)

```python
class Memory(ABC):
    def save(self, key: str, value: Any) -> None: ...
    def load(self, key: str) -> Any: ...
    def save_state(self, state: ScreenState, action: Action, success: bool) -> None: ...
    def get_history(self, limit: int = 10) -> List[Dict]: ...
```

### Security (安全层)

```python
class Security(ABC):
    def check(self, action: Action) -> bool: ...
    def require_approval(self, action: Action) -> bool: ...
    def log_action(self, action: Action, success: bool) -> None: ...
```

### Tools (工具层)

```python
class Tools(ABC):
    def read_file(self, path: str) -> str: ...
    def write_file(self, path: str, content: str) -> None: ...
    def http_get(self, url: str) -> Dict: ...
    def clipboard_read(self) -> str: ...
    def clipboard_write(self, text: str) -> None: ...
```

## 辅助函数

```python
# 创建动作对象
create_action(action_type: str, **kwargs) -> Action
create_click_action(target: Dict) -> Action
create_type_action(text: str) -> Action
create_key_action(keys: List[str]) -> Action
create_wait_action(condition: Dict) -> Action
create_done_action() -> Action
```

## 设计原则

1. **接口先行**：先定义数据结构，再实现模块
2. **动作结构化**：模型输出"目标描述"，不输出坐标
3. **模型无关**：决策层不绑定特定AI
4. **积木可替换**：换实现不改调用方

## 使用示例

```python
from interfaces import ScreenState, Action, create_click_action

# 感知层输出
state = ScreenState(
    screenshot="base64...",
    texts=[{"text": "确定", "bbox": [100, 200, 160, 230]}],
    elements=[{"type": "button", "name": "确定", "ref": "hwnd:12345"}]
)

# 决策层输出
action = create_click_action({"text": "确定"})

# 执行层使用
actuator.execute(action)
```

## 测试

运行测试验证接口定义：

```bash
python test_interfaces.py
```

运行示例查看使用方式：

```bash
python example_interfaces.py
```
