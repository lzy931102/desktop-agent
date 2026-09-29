"""phone_bridge 的数据契约：任务、事件的形状与状态机、入参校验。

本模块是纯数据层：不碰网络、不碰 GUI、不 import agent_loop，
因此可以脱离整个程序单独测试。

状态机（线性，不可回退）：

    pending ──▶ running ──▶ done / failed / stopped
                        └─▶ unknown（执行方上报了认不出的结束状态，如实标记）

文案约定：本层抛出的异常信息是**直接给用户看的中文**，
不出现在内部术语（不写 traceback、不写变量名）。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---- 任务状态 ----
STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_STOPPED = "stopped"
STATE_UNKNOWN = "unknown"   # 执行方上报了认不出的结束状态（修复前被冒充成 done）

STATES = (STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_FAILED, STATE_STOPPED,
          STATE_UNKNOWN)
TERMINAL_STATES = (STATE_DONE, STATE_FAILED, STATE_STOPPED, STATE_UNKNOWN)

# 面向手机屏的状态文案（颜色不单独承担信息，配文字）
STATE_LABELS = {
    STATE_PENDING: "排队中",
    STATE_RUNNING: "正在执行",
    STATE_DONE: "已完成",
    STATE_FAILED: "没做成",
    STATE_STOPPED: "已停止",
    STATE_UNKNOWN: "状态未知",
}

# 事件类型（手机端按类型上色/加符号）
EVENT_INFO = "info"
EVENT_TURN = "turn"
EVENT_TOOL = "tool"
EVENT_RESULT = "result"
EVENT_ERROR = "error"

# 容量上限：手机端只回看最近的内容，防止内存与页面无限膨胀
MAX_TEXT_LEN = 2000          # 单条任务指令最长字数
MAX_EVENTS_PER_TASK = 200    # 单个任务保留的事件条数（超出丢最旧）
MAX_TASKS_KEPT = 50          # 保留的历史任务条数
MAX_EVENT_CHARS = 800        # 单条事件文字上限


class TaskInputError(ValueError):
    """任务入参不合法。信息面向用户，可直接展示。"""


def new_task_id() -> str:
    """任务号：12 位十六进制，够短能念、够长不撞。"""
    return uuid.uuid4().hex[:12]


def now_ts() -> float:
    return time.time()


def validate_text(text: Any) -> str:
    """校验并规整手机端提交的任务文字，返回可直接入库的字符串。"""
    if text is None:
        raise TaskInputError("请先写点什么，再让它去做")
    if not isinstance(text, str):
        raise TaskInputError("任务内容只能是文字")
    cleaned = text.strip()
    if not cleaned:
        raise TaskInputError("任务内容还是空的，写一句要它做的事吧")
    if len(cleaned) > MAX_TEXT_LEN:
        raise TaskInputError(f"任务内容太长了，最多 {MAX_TEXT_LEN} 个字")
    return cleaned


def clip_event_text(text: Any) -> str:
    """事件文字裁剪：手机端只显示摘要，超长截断并标注。"""
    s = "" if text is None else str(text)
    if len(s) <= MAX_EVENT_CHARS:
        return s
    return s[:MAX_EVENT_CHARS] + "…（内容较长，已截断）"


@dataclass
class TaskEvent:
    """任务执行过程中的一条进展。seq 在单个任务内自增，供手机端增量拉取。"""

    seq: int
    ts: float
    kind: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"seq": self.seq, "ts": round(self.ts, 3),
                "kind": self.kind, "text": self.text}


@dataclass
class PhoneTask:
    """一条由手机下发（或留档）的任务。"""

    id: str
    text: str
    source: str = "phone"
    state: str = STATE_PENDING
    created_at: float = field(default_factory=now_ts)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    result: str = ""
    events: List[TaskEvent] = field(default_factory=list)

    # ---- 状态流转 ----
    def mark_running(self) -> None:
        if self.state in TERMINAL_STATES:
            return
        self.state = STATE_RUNNING
        self.started_at = self.started_at or now_ts()

    def mark_finished(self, state: str, result: str = "") -> None:
        if state not in TERMINAL_STATES:
            raise ValueError(f"不是终态: {state}")
        if self.state in TERMINAL_STATES:
            return
        self.state = state
        self.result = clip_event_text(result)
        self.ended_at = now_ts()

    @property
    def is_finished(self) -> bool:
        return self.state in TERMINAL_STATES

    # ---- 事件 ----
    def add_event(self, kind: str, text: Any) -> TaskEvent:
        seq = (self.events[-1].seq + 1) if self.events else 1
        ev = TaskEvent(seq=seq, ts=now_ts(), kind=kind,
                       text=clip_event_text(text))
        self.events.append(ev)
        if len(self.events) > MAX_EVENTS_PER_TASK:
            del self.events[0:len(self.events) - MAX_EVENTS_PER_TASK]
        return ev

    def events_since(self, since: int) -> List[TaskEvent]:
        return [e for e in self.events if e.seq > since]

    # ---- 对外序列化 ----
    def to_dict(self, with_events_from: Optional[int] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "state": self.state,
            "state_label": STATE_LABELS.get(self.state, self.state),
            "created_at": round(self.created_at, 3),
            "started_at": round(self.started_at, 3) if self.started_at else None,
            "ended_at": round(self.ended_at, 3) if self.ended_at else None,
            "elapsed_s": self.elapsed_s(),
            "result": self.result,
            "last_seq": self.events[-1].seq if self.events else 0,
        }
        if with_events_from is not None:
            data["events"] = [e.to_dict() for e in self.events_since(with_events_from)]
        return data

    def elapsed_s(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.ended_at or now_ts()
        return round(end - self.started_at, 1)
