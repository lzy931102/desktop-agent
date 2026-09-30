"""mail_remote 的数据契约：命令解析、白名单、文案。

设计（2026-09-30，用户拍板：手机远程操作=发任务/查状态/停止，通道用邮件，
不走飞书、不用扫码隧道；独立模块，只准 import 标准库）：

手机给自己的邮箱发一封信（主题带前缀），电脑上的助手轮询收件：

    [da] 帮我打开记事本        → 下任务（主题即任务文本）
    [da]                       → 下任务（任务文本在正文）
    [da] 状态                  → 回信当前任务状态
    [da] 停止                  → 停止最近一条任务
    [da] 停止 ab12cd34ef56     → 停止指定任务

安全边界：
- 只有**白名单发件人**的信会被受理（白名单由用户在设置面板配置）；
- 主题必须带前缀（默认 [da]），防止把正常往来邮件误当任务执行；
- 首次启动只校准（记录现有未读信的 uid，不执行），防旧任务邮件重放；
- 执行仍走 GUI 的 TaskSession 通道 + core/guard 审批——本模块不碰鼠标键盘。

文案约定：本层抛出的异常信息是**直接给用户看的中文**。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Optional

DEFAULT_SUBJECT_PREFIX = "[da]"
MAX_TASK_LEN = 2000
MAX_RESULT_LEN = 1500

CMD_STATUS = "状态"
CMD_STOP = "停止"

# 命令种类
KIND_TASK = "task"
KIND_STATUS = "status"
KIND_STOP = "stop"
KIND_IGNORE = "ignore"      # 非目标邮件（无前缀/白名单外），不处理也不回信


class MailTaskError(ValueError):
    """邮件任务不合法。信息面向用户，可直接回信展示。"""


def new_task_id() -> str:
    """任务号：12 位十六进制（与 phone_bridge 同规格，够短能念）"""
    return uuid.uuid4().hex[:12]


def normalize_addr(addr: str) -> str:
    """提取并小写化邮箱地址（From 头可能是 '名字 <a@b.c>' 形态）"""
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", addr or "")
    return m.group(0).lower() if m else ""


def split_allowed_senders(raw: str) -> list:
    """设置里的白名单字符串（逗号/分号/换行分隔）→ 规范化地址列表"""
    if not raw:
        return []
    parts = re.split(r"[,;，；\s]+", str(raw))
    seen = []
    for p in parts:
        a = normalize_addr(p)
        if a and a not in seen:
            seen.append(a)
    return seen


@dataclass
class MailCommand:
    """一封白名单来信的解析结果"""

    kind: str                       # KIND_TASK / KIND_STATUS / KIND_STOP / KIND_IGNORE
    task_text: str = ""             # KIND_TASK 时的任务文本
    stop_task_id: str = ""          # KIND_STOP 时的任务号（空 = 最近一条）
    usage_error: str = ""           # KIND_TASK 但内容不合法时的回信提示


def parse_command(subject: str, body: str,
                  prefix: str = DEFAULT_SUBJECT_PREFIX) -> MailCommand:
    """按契约解析一封来信。主题不带前缀 → KIND_IGNORE（不受理、不回信）。

    解析优先级（前缀后的部分）：
    1. 恰为「状态」              → 查状态
    2. 以「停止」开头            → 停止（可带任务号）
    3. 有剩余文本                → 主题即任务
    4. 主题只剩前缀              → 正文即任务
    """
    subject = (subject or "").strip()
    body = (body or "").strip()
    prefix = (prefix or DEFAULT_SUBJECT_PREFIX).strip()
    if not subject.startswith(prefix):
        return MailCommand(kind=KIND_IGNORE)
    rest = subject[len(prefix):].strip()

    if rest == CMD_STATUS:
        return MailCommand(kind=KIND_STATUS)
    if rest.startswith(CMD_STOP):
        return MailCommand(kind=KIND_STOP,
                           stop_task_id=rest[len(CMD_STOP):].strip())

    task = rest or body
    if not task:
        return MailCommand(kind=KIND_TASK, usage_error=(
            f"没读到任务内容：主题请写成「{prefix} 任务描述」，"
            f"或主题只写「{prefix}」、把任务写在正文里"))
    if len(task) > MAX_TASK_LEN:
        return MailCommand(kind=KIND_TASK, usage_error=(
            f"任务太长了（{len(task)} 字），最多 {MAX_TASK_LEN} 字"))

    # 控制字符清洗（邮件正文常见 \r 与连续空行，压成单行更耐读）
    task = re.sub(r"\r", "", task).strip()
    return MailCommand(kind=KIND_TASK, task_text=task)


def clip_result(text) -> str:
    """结果回信裁剪：邮件不宜超长，超长截断并标注"""
    s = "" if text is None else str(text)
    if len(s) <= MAX_RESULT_LEN:
        return s
    return s[:MAX_RESULT_LEN] + "…（结果较长，已截断）"


def format_status_reply(status: dict) -> str:
    """把状态快照格式化成回信正文。status 结构由调用方（GUI）提供：
    {"running": [{title, action, turn}], "queued": n, "bridge_note": str}
    """
    lines = []
    running = status.get("running") or []
    if running:
        lines.append("正在执行的：")
        for t in running:
            lines.append(f"· {t.get('title', '')}（{t.get('action', '')}）")
    else:
        lines.append("当前没有在执行的任务。")
    queued = status.get("queued")
    if queued:
        lines.append(f"排队等待：{queued} 条")
    note = status.get("bridge_note")
    if note:
        lines.append(note)
    lines.append("（回信 [da] 状态 可再次查询；[da] 停止 停最近一条）")
    return "\n".join(lines)
