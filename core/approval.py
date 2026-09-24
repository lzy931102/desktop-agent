"""操作确认策略：危险操作（guard 评为 high）必须经过批准才执行。

个人版：GuiApprovalBridge —— agent 工作线程发确认请求，GUI 主线程弹窗，用户点允许/拒绝。
企业版：替换为远程审批流实现（同接口 decide()），主干代码不变。
无界面模式：AutoDenyPolicy —— 危险操作一律拒绝（无人值守安全默认值）。
"""
import queue
import threading


class AutoDenyPolicy:
    """无界面环境的安全默认：所有高危操作直接拒绝"""

    def decide(self, tool_name: str, args: dict, risk: str, reason: str) -> bool:
        return False


class GuiApprovalBridge:
    """工作线程与 GUI 主线程之间的确认桥。

    agent 线程调用 decide() 阻塞等待；
    GUI 主线程轮询 pending() 取请求弹窗，用户选择后 complete() 放行。
    """

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self._requests = queue.Queue()

    def decide(self, tool_name: str, args: dict, risk: str, reason: str) -> bool:
        done = threading.Event()
        box = {"answer": None}
        self._requests.put({
            "tool": tool_name, "args": args, "risk": risk,
            "reason": reason, "event": done, "box": box,
        })
        done.wait(self.timeout)  # 超时未确认视为拒绝（安全默认）
        return bool(box["answer"])

    def pending(self):
        """GUI 主线程取一条待确认请求；无则返回 None"""
        try:
            return self._requests.get_nowait()
        except queue.Empty:
            return None

    @staticmethod
    def complete(request: dict, allowed: bool):
        request["box"]["answer"] = allowed
        request["event"].set()
