# 手机/邮件任务运行器。
# T4 Phase 1 从 gui.py 原样抽出（PhoneTaskRunner + MailTaskRunner）。
import time

from ui.formatters import short_title
from ui.sessions import TaskSession
from ui.theme import DEFAULT_MAX_CONCURRENT, MSG_ON_IT, MSG_QUEUED

try:
    from phone_bridge.contract import STATE_STOPPED
except ImportError:
    STATE_STOPPED = None  # 手机连接组件未装齐时有 phone_bridge 守卫，引用不可达

class PhoneTaskRunner:
    """phone_bridge.hub 的执行方适配器（TaskRunner 协议，任务 16 接线）。

    手机任务落回现有 TaskSession 通道：HTTP 线程只做投递，会话的创建/
    启动/停止一律经 root.after 回主线程（踩坑.md 条目 4），与本地任务
    走同一条"并发上限 + 排队"的路，不另开执行路径。submit 必须立即
    返回（hub 契约：不能阻塞 HTTP 请求线程）。
    """

    def __init__(self, app):
        self.app = app
        # hub 派发后、主线程会话还没建好之前收到的停止请求（见 _create_session）
        self._stop_before_start = set()

    def submit(self, task_id: str, text: str) -> None:
        self.app.root.after(0, lambda: self._create_session(task_id, text))

    def stop(self, task_id: str) -> bool:
        # hub.stop 在持锁状态下调用本方法：只登记 + 投递，绝不在锁内回调 hub
        self._stop_before_start.add(task_id)
        self.app.root.after(0, lambda: self._stop_session(task_id))
        return True

    def _create_session(self, task_id: str, text: str):
        if task_id in self._stop_before_start:
            # 停止请求赶在会话落地前：不建会话，直接按已取消收场
            self._stop_before_start.discard(task_id)
            if self.app.phone_bridge:
                try:
                    self.app.phone_bridge.hub.finish(
                        task_id, STATE_STOPPED, "还没开始就被叫停了")
                except Exception:
                    pass
            return
        s = TaskSession(title="📱 " + short_title(text))
        s.phone_task_id = task_id
        self.app.sessions[s.id] = s
        self.app._phone_tasks[task_id] = s
        s.task_text = text
        s.add("system", text="📱 这条任务来自手机连接", tone="info")
        s.add("user", text=text)
        # 与 _start_or_stop / _run_scheduled 同一条排队规则
        max_c = max(1, min(5, int(self.app.settings.get(
            "max_concurrent", DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.app.sessions.values()
                      if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self.app)
        self.app._select(s)
        self.app._sidebar_dirty = self.app._tabs_dirty = True

    def _stop_session(self, task_id: str):
        s = self.app._phone_tasks.get(task_id)
        if s is None:
            return    # 会话未落地（随 _create_session 的取消路径收场）或已结束
        if s.status == "queued":
            s.status = "draft"
            s.add("system", text="📱 手机端取消了这条任务", tone="info")
            self.app._phone_task_cancelled(s)
            self.app._remove_session(s)
        elif s.status == "running":
            s.stop_requested_at = time.time()
            s.stop()   # 与界面上点「停止」等效，done 事件经 _apply 回流 hub
            s.add("system", text="📱 手机端请求停止：当前这步执行完就停",
                  tone="faint")


class MailTaskRunner:
    """mail_remote 的执行方适配器：与 PhoneTaskRunner 同形（轮询线程只投递，
    会话创建/启停一律经 root.after 回主线程），任务落同一条 TaskSession 通道。

    与手机路径的差异：邮件通道带宽低，事件不做逐条回流——受理确认/查状态/
    停止由 mail_remote 直接回信，任务收尾由 _apply 的一次 done 事件回信结果。
    """

    def __init__(self, app):
        self.app = app

    def submit(self, task_id: str, text: str) -> None:
        self.app.root.after(0, lambda: self._create_session(task_id, text))

    def stop(self, task_id: str) -> bool:
        self.app.root.after(0, lambda: self._stop_session(task_id))
        return True

    def _create_session(self, task_id: str, text: str):
        s = TaskSession(title="✉️ " + short_title(text))
        s.mail_task_id = task_id
        self.app.sessions[s.id] = s
        self.app._mail_tasks[task_id] = s
        s.task_text = text
        s.add("system", text="✉️ 这条任务来自邮件远程", tone="info")
        s.add("user", text=text)
        # 与 _start_or_stop / _run_scheduled 同一条排队规则
        max_c = max(1, min(5, int(self.app.settings.get(
            "max_concurrent", DEFAULT_MAX_CONCURRENT))))
        running = sum(1 for x in self.app.sessions.values()
                      if x.status == "running")
        if running >= max_c:
            s.status = "queued"
            s.add("system", text=MSG_QUEUED.format(n=running), tone="info")
        else:
            s.status = "running"
            s.add("system", text=MSG_ON_IT, tone="faint")
            s.launch(self.app)
        self.app._select(s)
        self.app._sidebar_dirty = self.app._tabs_dirty = True

    def _stop_session(self, task_id: str):
        s = self.app._mail_tasks.get(task_id)
        if s is None:
            return
        if s.status == "queued":
            s.status = "draft"
            s.add("system", text="✉️ 邮件端取消了这条任务", tone="info")
            if self.app.mail_remote:
                try:
                    self.app.mail_remote.report(task_id, "已停止",
                                                "已在开始前取消")
                except Exception:
                    pass
            self.app._remove_session(s)
        elif s.status == "running":
            s.stop_requested_at = time.time()
            s.stop()
            s.add("system", text="✉️ 邮件端请求停止：当前这步执行完就停",
                  tone="faint")
