"""
统一数据结构和模块接口定义
按照开发需求文档第1步定义
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod
from enum import Enum


# ==================== 统一数据结构 ====================

@dataclass
class ScreenState:
    """屏幕状态 - 感知层输出"""
    screenshot: str                          # base64编码截图
    screenshot_path: str = ""                # 截图文件路径
    texts: List[Dict] = field(default_factory=list)      # OCR结果
    elements: List[Dict] = field(default_factory=list)   # UIA/找图元素
    active_window: Dict = field(default_factory=dict)    # 当前窗口信息


@dataclass
class Action:
    """动作指令 - 决策层输出"""
    action: str                              # click/type/select/expand/key/wait/done
    target: Optional[Dict] = None            # 目标描述（文本/元素引用，非坐标）
    text: Optional[str] = None               # 输入文字
    keys: Optional[List[str]] = None         # 快捷键组合
    condition: Optional[Dict] = None         # 等待条件


# 标准动作类型
class ActionType(str, Enum):
    """动作类型枚举"""
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    EXPAND = "expand"
    KEY = "key"
    WAIT = "wait"
    DONE = "done"


ACTIONS = {
    "click":    "点击目标",           # target: {"text": "确定"} 或 {"ref": "hwnd:12345"}
    "type":     "输入文字",           # text: "hello"
    "select":   "选择元素",           # target: {"ref": "hwnd:12345"}
    "expand":   "展开元素",           # target: {...}
    "key":      "按快捷键",           # keys: ["ctrl", "c"]
    "wait":     "等待条件满足",       # condition: {"text": "加载完成"}
    "done":     "任务完成"
}


# ==================== 模块接口 ====================

class Perception(ABC):
    """感知层接口 - 把屏幕变成Agent能理解的结构化信息"""
    
    @abstractmethod
    def capture(self) -> ScreenState:
        """
        捕获当前屏幕状态
        
        Returns:
            ScreenState: 屏幕状态对象
        """
        pass
    
    @abstractmethod
    def find_element(self, target: Dict) -> Optional[Dict]:
        """
        查找屏幕元素
        
        Args:
            target: 目标描述，如 {"text": "确定"} 或 {"ref": "hwnd:12345"}
            
        Returns:
            找到的元素信息，包含bbox和ref
        """
        pass
    
    @abstractmethod
    def find_text(self, text: str) -> Optional[Dict]:
        """
        查找屏幕上的文字
        
        Args:
            text: 要查找的文字
            
        Returns:
            文字信息，包含bbox
        """
        pass


class Brain(ABC):
    """决策层接口 - 根据感知结果和任务目标，输出下一步动作"""
    
    @abstractmethod
    def decide(self, state: ScreenState, goal: str) -> Action:
        """
        根据屏幕状态和目标决定下一步动作
        
        Args:
            state: 当前屏幕状态
            goal: 任务目标描述
            
        Returns:
            Action: 要执行的动作
        """
        pass
    
    @abstractmethod
    def plan(self, goal: str) -> List[Action]:
        """
        规划任务步骤
        
        Args:
            goal: 任务目标描述
            
        Returns:
            动作序列
        """
        pass
    
    @abstractmethod
    def update_state(self, state: ScreenState, action: Action, success: bool):
        """
        根据执行结果更新决策状态
        
        Args:
            state: 执行后的屏幕状态
            action: 执行的动作
            success: 是否成功
        """
        pass


class Actuator(ABC):
    """执行层接口 - 把标准动作指令变成真实操作"""
    
    @abstractmethod
    def execute(self, action: Action) -> bool:
        """
        执行动作
        
        Args:
            action: 要执行的动作
            
        Returns:
            是否成功执行
        """
        pass
    
    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> bool:
        """
        点击指定坐标
        
        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def type_text(self, text: str) -> bool:
        """
        输入文字
        
        Args:
            text: 要输入的文字
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def press_keys(self, keys: List[str]) -> bool:
        """
        按下快捷键组合
        
        Args:
            keys: 按键列表，如 ["ctrl", "c"]
            
        Returns:
            是否成功
        """
        pass


class Verifier(ABC):
    """验证层接口 - 判断动作是否成功"""
    
    @abstractmethod
    def verify(self, before: ScreenState, after: ScreenState, action: Action) -> bool:
        """
        验证动作是否成功
        
        Args:
            before: 执行前的屏幕状态
            after: 执行后的屏幕状态
            action: 执行的动作
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def assert_text(self, text: str, timeout: float = 5.0) -> bool:
        """
        断言屏幕上存在指定文字
        
        Args:
            text: 期望存在的文字
            timeout: 超时时间
            
        Returns:
            是否找到
        """
        pass
    
    @abstractmethod
    def assert_image(self, image_path: str, timeout: float = 5.0) -> bool:
        """
        断言屏幕上存在指定图像
        
        Args:
            image_path: 期望存在的图像路径
            timeout: 超时时间
            
        Returns:
            是否找到
        """
        pass


class Memory(ABC):
    """记忆层接口 - 存任务状态、历史、上下文"""
    
    @abstractmethod
    def save(self, key: str, value: Any) -> None:
        """
        保存数据
        
        Args:
            key: 键
            value: 值
        """
        pass
    
    @abstractmethod
    def load(self, key: str) -> Any:
        """
        加载数据
        
        Args:
            key: 键
            
        Returns:
            保存的值
        """
        pass
    
    @abstractmethod
    def save_state(self, state: ScreenState, action: Action, success: bool) -> None:
        """
        保存执行状态
        
        Args:
            state: 屏幕状态
            action: 执行的动作
            success: 是否成功
        """
        pass
    
    @abstractmethod
    def get_history(self, limit: int = 10) -> List[Dict]:
        """
        获取历史记录
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            历史记录列表
        """
        pass


class Security(ABC):
    """安全层接口 - 防止Agent做危险操作"""
    
    @abstractmethod
    def check(self, action: Action) -> bool:
        """
        检查动作是否安全
        
        Args:
            action: 要检查的动作
            
        Returns:
            是否允许执行
        """
        pass
    
    @abstractmethod
    def require_approval(self, action: Action) -> bool:
        """
        请求用户审批
        
        Args:
            action: 需要审批的动作
            
        Returns:
            是否批准
        """
        pass
    
    @abstractmethod
    def log_action(self, action: Action, success: bool) -> None:
        """
        记录操作日志
        
        Args:
            action: 执行的动作
            success: 是否成功
        """
        pass


class Tools(ABC):
    """工具层接口 - 让Agent能调外部能力"""
    
    @abstractmethod
    def read_file(self, path: str) -> str:
        """
        读取文件
        
        Args:
            path: 文件路径
            
        Returns:
            文件内容
        """
        pass
    
    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """
        写入文件
        
        Args:
            path: 文件路径
            content: 文件内容
        """
        pass
    
    @abstractmethod
    def http_get(self, url: str) -> Dict:
        """
        发送HTTP GET请求
        
        Args:
            url: 请求地址
            
        Returns:
            响应数据
        """
        pass
    
    @abstractmethod
    def clipboard_read(self) -> str:
        """
        读取剪贴板
        
        Returns:
            剪贴板内容
        """
        pass
    
    @abstractmethod
    def clipboard_write(self, text: str) -> None:
        """
        写入剪贴板
        
        Args:
            text: 要写入的内容
        """
        pass


# ==================== 辅助函数 ====================

def create_action(action_type: str, **kwargs) -> Action:
    """
    创建动作对象的辅助函数
    
    Args:
        action_type: 动作类型
        **kwargs: 动作参数
        
    Returns:
        Action对象
    """
    return Action(action=action_type, **kwargs)


def create_click_action(target: Dict) -> Action:
    """创建点击动作"""
    return Action(action=ActionType.CLICK, target=target)


def create_type_action(text: str) -> Action:
    """创建输入动作"""
    return Action(action=ActionType.TYPE, text=text)


def create_key_action(keys: List[str]) -> Action:
    """创建快捷键动作"""
    return Action(action=ActionType.KEY, keys=keys)


def create_wait_action(condition: Dict) -> Action:
    """创建等待动作"""
    return Action(action=ActionType.WAIT, condition=condition)


def create_done_action() -> Action:
    """创建完成动作"""
    return Action(action=ActionType.DONE)
