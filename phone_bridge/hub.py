"""任务中枢：手机下发的任务在这里排队、跟踪状态、收集过程，供手机端查询。

与执行方解耦（关键设计）：
hub 不知道任务是怎么被执行的——它只认 TaskRunner 这个协议。
GUI 把「跑一条任务」的能力注入进来（复用现有 TaskSession 通道），
hub 只负责排队、状态机、留档。这样 phone_bridge 可以脱离整个程序单独测试。

为什么串行执行：DesktopAgent 用的是同一个鼠标键盘，
两条任务同时跑会互相抢焦点（抢不到就点错地方）。所以中枢只允许一条在跑，其余排队。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Protocol

from .contract import (
    EVENT_ERROR,
    EVENT_INFO,
    MAX_TASKS_KEPT,
    STATE_FAILED,
    STATE_PENDING,
    STATE_STOPPED,
    PhoneTask,
    TaskInputError,
    new_task_id,
    validate_text,
)


class TaskRunner(Protocol):
    """执行方契约。实现者负责真正把任务跑起来（GUI 侧用 TaskSession）。"""

    def submit(self, task_id: str, text: str) -> None:
        """接手一条任务。实现必须**立即返回**（不要阻塞 HTTP 请求线程）。"""

    def stop(self, task_id: str) -> bool:
        """请求停止。返回 True 表示确实找到并已请求停止。"""


class TaskHub:
    """任务排队 + 状态跟踪。所有公开方法线程安全。"""

    def __init__(self, runner: Optional[TaskRunner] = None,
                 on_change: Optional[Callable[[], None]] = None,
                 max_keep: int = MAX_TASKS_KEPT):
        self._lock = threading.RLock()
        self._tasks: "OrderedDict[str, PhoneTask]" = OrderedDict()
        self._runner = runner
        self._on_change = on_change
        self._max_keep = max_keep
        self._current_id: Optional[str] = None   # 正在执行的任务
        self._queue: List[str] = []              # 等待执行的 task_id（先进先出）

    # ---- 装配 ----
    def attach_runner(self, runner: TaskRunner) -> None:
        with self._lock:
            self._runner = runner

    def attach_on_change(self, cb: Optional[Callable[[], None]]) -> None:
        with self._lock:
            self._on_change = cb

    # ---- 手机端入口 ----
    def submit(self, text: Any, source: str = "phone") -> PhoneTask:
        """接收一条新任务：校验 → 入队 → 有空就立即开工。"""
        cleaned = validate_text(text)
        with self._lock:
            task = PhoneTask(id=new_task_id(), text=cleaned, source=source)
            self._tasks[task.id] = task
            self._queue.append(task.id)
            self._trim_locked()
            task.add_event(EVENT_INFO, "已收到，正在排队")
            self._dispatch_locked()
        self._notify()
        return task

    def stop(self, task_id: str) -> Dict[str, Any]:
        """停止一条任务：在跑的中断执行，排队的直接出队。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return {"ok": False, "message": "没找到这条任务，可能已经被清理了"}
            if task.is_finished:
                return {"ok": False, "message": "这条任务已经结束了"}
            if task_id in self._queue:
                self._queue.remove(task_id)
                task.add_event(EVENT_INFO, "已在你这边取消")
                task.mark_finished(STATE_STOPPED, "已取消")
                result = {"ok": True, "message": "已取消"}
            else:
                runner = self._runner
                if runner is not None:
                    try:
                        runner.stop(task_id)
                    except Exception as e:          # 执行方异常不影响中枢
                        task.add_event(EVENT_ERROR, f"停止请求没能送达：{e}")
                task.add_event(EVENT_INFO, "已发送停止指令，等它停稳")
                result = {"ok": True, "message": "已请求停止"}
        self._notify()
        return result

    # ---- 执行方回调 ----
    def publish(self, task_id: str, kind: str, text: Any) -> None:
        """执行方上报一条进展。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.is_finished:
                return
            task.add_event(kind, text)
        self._notify()

    def finish(self, task_id: str, state: str, result: str = "") -> None:
        """执行方宣布任务结束：落终态 → 让出位置 → 拉起下一条。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if state not in (STATE_FAILED, STATE_STOPPED):
                task.mark_finished("done", result)
            else:
                task.mark_finished(state, result)
            if self._current_id == task_id:
                self._current_id = None
            if task_id in self._queue:
                self._queue.remove(task_id)
            self._dispatch_locked()
        self._notify()

    # ---- 内部：调度 ----
    def _dispatch_locked(self) -> None:
        """有空位就开工。调用方必须已持锁。"""
        if self._current_id is not None or not self._queue:
            return
        while self._queue:
            task_id = self._queue.pop(0)
            task = self._tasks.get(task_id)
            if task is None or task.is_finished:
                continue
            self._current_id = task_id
            task.mark_running()
            task.add_event(EVENT_INFO, "开始做了")
            runner = self._runner
            if runner is None:
                task.add_event(EVENT_ERROR, "这台电脑的助手没接上，任务没法执行")
                task.mark_finished(STATE_FAILED, "助手没接上")
                self._current_id = None
                continue
            try:
                runner.submit(task_id, task.text)
            except Exception as e:
                task.add_event(EVENT_ERROR, f"任务没能交出去：{e}")
                task.mark_finished(STATE_FAILED, "交接失败")
                self._current_id = None
                continue
            return

    def _trim_locked(self) -> None:
        """只保留最近的 N 条任务（不删正在跑的和排队的）。"""
        if len(self._tasks) <= self._max_keep:
            return
        protected = set(self._queue)
        if self._current_id:
            protected.add(self._current_id)
        for tid in list(self._tasks.keys()):
            if len(self._tasks) <= self._max_keep:
                break
            if tid not in protected:
                self._tasks.pop(tid, None)

    def _notify(self) -> None:
        cb = self._on_change
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass          # 界面刷新失败不能反过来影响任务

    # ---- 查询（只读快照）----
    def snapshot(self, events_from: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            current = self._tasks.get(self._current_id) if self._current_id else None
            tasks = list(reversed(self._tasks.values()))
            return {
                "server_time": round(time.time(), 3),
                "current": (current.to_dict(with_events_from=events_from or 0)
                            if current else None),
                "tasks": [t.to_dict() for t in tasks],
                "queue_len": len(self._queue),
                "running": bool(current),
            }

    def get(self, task_id: str,
            events_from: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return task.to_dict(with_events_from=events_from)

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = list(reversed(self._tasks.values()))[:max(1, int(limit))]
            return [t.to_dict() for t in tasks]

    @property
    def running_task_id(self) -> Optional[str]:
        with self._lock:
            return self._current_id

    def idle(self) -> bool:
        with self._lock:
            return self._current_id is None and not self._queue


class QueueFullError(RuntimeError):
    """保留错误类型：将来要做队列长度上限时使用。"""
