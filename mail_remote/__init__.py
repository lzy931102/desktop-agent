"""邮件远程控制（独立模块）：手机发邮件遥控这台电脑——下任务、查状态、停止。

与 phone_bridge 的关系（2026-09-30 用户拍板）：
- phone_bridge（扫码 + 局域网/隧道）**保留但暂停推进**，出门链路不再作为
  验收项；本模块接手"出门也能用"的场景——邮件服务器天然中转，无需隧道、
  无需第三方推送平台、无需飞书。
- 依赖边界与 phone_bridge 同一条纪律：本包只准 import 标准库，
  **禁止 import agent_loop / gui / core / phone_bridge**，可脱离主程序单测。

工作方式：
1. 用户在设置面板开启「邮件远程」，填邮箱账号 + 授权码 + 白名单发件人；
2. 模块每 N 秒 IMAP 轮询收件箱（默认 60 秒，只看未读信）；
3. 白名单发件人来信且主题带前缀（默认 [da]）→ 按契约执行：
   下任务 / 查状态 / 停止；执行走调用方注入的 TaskRunner（GUI 的
   TaskSession 通道，guard 审批一条不少）；
4. 受理即回信确认（带任务号）；任务收尾由调用方回调 report() → 回信结果；
5. 「状态」命令随时回信当前在跑什么。

安全边界（缺一不可）：
- 白名单发件人：只有名单内的地址能下达指令（设置面板配置）；
- 主题前缀：不带前缀的信一律无视，且**不改变其已读状态**——这是用户
  自己的收件箱；
- 首次启动只校准：把当前未读信的 uid 记为已见但**不执行**，防旧任务邮件
  在重启后重放（配合 uid + UIDVALIDITY 去重，状态落 %LOCALAPPDATA%）；
- 邮箱授权码只落本机 settings.json，不进代码仓库。

状态文件：%LOCALAPPDATA%/DesktopAgent/mail_remote_state.json
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .contract import (
    DEFAULT_SUBJECT_PREFIX,
    KIND_IGNORE,
    KIND_STATUS,
    KIND_STOP,
    KIND_TASK,
    MailCommand,
    clip_result,
    format_status_reply,
    new_task_id,
    normalize_addr,
    parse_command,
    split_allowed_senders,
)
from .mailbox import MailboxError, derive_hosts, fetch_new, send_reply

POLL_MIN_SECONDS = 30          # 轮询下限：太频繁会被服务商限速
MAX_TRACKED_TASKS = 200        # 任务号 → 回信地址 的留存量上限
STATE_UID_CAP = 500            # 已见 uid 留存量上限（超出丢最旧）


class MailConfigError(ValueError):
    """配置不完整/不合法。信息面向用户，可直接展示。"""


def state_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "DesktopAgent" / "mail_remote_state.json"


def _default_imap_factory(host: str):
    import imaplib
    return imaplib.IMAP4_SSL(host, 993)


def _default_smtp_factory(host: str):
    import smtplib
    return smtplib.SMTP_SSL(host, 465)


class _SeenStore:
    """已见 uid 的落盘去重（含 UIDVALIDITY：邮箱重建/换库后 uid 会重排）"""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._validity = ""
        self._seen: List[str] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._validity = str(data.get("uidvalidity", ""))
            self._seen = [str(u) for u in data.get("seen", [])][-STATE_UID_CAP:]
        except (OSError, ValueError):
            pass

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"uidvalidity": self._validity, "seen": self._seen[-STATE_UID_CAP:]},
            ensure_ascii=False), encoding="utf-8")

    def already(self, validity: str, uid: bytes) -> bool:
        with self._lock:
            if validity != self._validity:
                return False               # uid 命名空间换了：历史记录作废
            return uid.decode() in self._seen

    def ensure_validity(self, validity: str):
        """显式落 uid 命名空间（首跑校准必须调用——即使本轮一封信都没有，
        否则空收件箱会让"首跑"永远成立，任务永远不执行）"""
        with self._lock:
            if self._validity != validity:
                self._validity = validity
                self._seen = []
                self._save()

    def mark(self, validity: str, uid: bytes):
        with self._lock:
            if validity != self._validity:
                self._validity = validity
                self._seen = []
            u = uid.decode()
            if u not in self._seen:
                self._seen.append(u)
                self._seen = self._seen[-STATE_UID_CAP:]
            self._save()


class MailRemote:
    """邮件远程的总开关：轮询线程 + 命令分发 + 结果回信。

    调用方（GUI）注入：
    - runner: submit(task_id, text) / stop(task_id) —— 与 phone_bridge 的
      TaskRunner 同形协议（GUI 侧同一个执行适配器都能喂）；
    - status_provider() → dict（format_status_reply 认的结构）；
    - on_log(msg) → 界面日志回调（可 None）。
    """

    def __init__(self, runner, status_provider: Optional[Callable] = None,
                 on_log: Optional[Callable[[str], None]] = None):
        self._runner = runner
        self._status_provider = status_provider
        self._on_log = on_log or (lambda m: print(m))
        self._store = _SeenStore(state_path())
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._config: Dict = {}
        self._running = False
        self._imap_factory = _default_imap_factory    # 测试可在 start 时注入
        self._smtp_factory = _default_smtp_factory
        # 任务号/回信键 → (回信地址, 原主题)；留最近 N 条
        self._reply_to: Dict[str, tuple] = {}
        self._task_order: List[str] = []   # 受理的邮件任务号（"停止"不带号时取尾）
        self.last_error = ""

    # ---- 生命周期 ----
    def start(self, config: Dict, imap_factory=None, smtp_factory=None) -> None:
        """校验配置并启动轮询线程。config 字段见 contract / 设置面板；
        imap/smtp 会话工厂可注入（测试用桩，生产用默认 SSL 连接）。"""
        cfg = self._validate(config)
        with self._lock:
            if self._running:
                return
            self._config = cfg
            self._imap_factory = imap_factory or self._imap_factory
            self._smtp_factory = smtp_factory or self._smtp_factory
            self._stop_event.clear()
            self._running = True
            self._thread = threading.Thread(
                target=self._poll_loop, name="mail-remote-poll", daemon=True)
            self._thread.start()
        self._log(f"✉️ 邮件远程已开启：{cfg['username']}"
                  f"（每 {cfg['poll_seconds']} 秒查一次收件箱，"
                  f"白名单 {len(cfg['allowed_senders'])} 人）")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        self._log("✉️ 邮件远程已关闭")

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def username(self) -> str:
        with self._lock:
            return self._config.get("username", "")

    @staticmethod
    def _validate(config: Dict) -> Dict:
        username = normalize_addr(str(config.get("username", "")))
        if not username:
            raise MailConfigError("请先填写邮箱账号")
        auth_code = str(config.get("auth_code", "")).strip()
        if not auth_code:
            raise MailConfigError(
                "请先填写授权码（在邮箱设置里开启 IMAP/SMTP 后生成，不是登录密码）")
        imap_host = str(config.get("imap_host", "")).strip()
        smtp_host = str(config.get("smtp_host", "")).strip()
        d_imap, d_smtp = derive_hosts(username)
        imap_host = imap_host or d_imap or ""
        smtp_host = smtp_host or d_smtp or ""
        if not imap_host or not smtp_host:
            raise MailConfigError(
                "识别不了这个邮箱的收发服务器，请在设置里手动填写")
        senders = split_allowed_senders(str(config.get("allowed_senders", "")))
        if not senders:
            raise MailConfigError(
                "请先配置白名单发件人（手机邮箱地址），否则任何来信都不会被受理")
        try:
            poll_seconds = max(POLL_MIN_SECONDS,
                               int(config.get("poll_seconds", 60) or 60))
        except (TypeError, ValueError):
            poll_seconds = 60
        prefix = (str(config.get("subject_prefix", "")).strip()
                  or DEFAULT_SUBJECT_PREFIX)
        return {"username": username, "auth_code": auth_code,
                "imap_host": imap_host, "smtp_host": smtp_host,
                "poll_seconds": poll_seconds, "allowed_senders": senders,
                "subject_prefix": prefix}

    # ---- 轮询 ----
    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._poll_once()
                self.last_error = ""
            except MailboxError as e:
                self.last_error = str(e)
                self._log(f"✉️ 邮箱检查失败：{e}")
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self._log(f"✉️ 邮件远程轮询异常：{self.last_error}")
            self._stop_event.wait(self._config.get("poll_seconds", 60))

    def _poll_once(self) -> int:
        """执行一轮拉取与分发，返回受理的命令数（测试直接调它）。

        首次运行（状态文件没有当前邮箱的 uidvalidity 记录）只做校准：
        把现有未读信的 uid 记为已见但不执行——防止重启后旧任务邮件重放。
        """
        cfg = self._config
        senders = set(cfg["allowed_senders"])
        prefix = cfg["subject_prefix"]

        def target_pred(from_addr: str, subject: str) -> bool:
            return from_addr in senders and subject.strip().startswith(prefix)

        validity = self._fetch_uidvalidity() or f"@{cfg['username']}"
        first_run = self._store._validity != validity
        self._store.ensure_validity(validity)

        items = fetch_new(self._imap_factory,
                          cfg["username"], cfg["auth_code"],
                          cfg["imap_host"], target_pred)

        handled = 0
        for item in items:
            if self._store.already(validity, item.uid):
                continue
            self._store.mark(validity, item.uid)
            if first_run:
                self._log("✉️ 首次校准：历史来信只登记不执行")
                continue
            cmd = parse_command(item.subject, item.body, prefix)
            if cmd.kind == KIND_IGNORE:
                continue          # 白名单内但不带前缀：登记不处理
            reply_key = f"mail:{item.uid.decode()}"
            self._remember_reply(reply_key, item.from_addr, item.subject)
            self._dispatch(cmd, item.from_addr, item.subject, reply_key)
            handled += 1
        return handled

    def _fetch_uidvalidity(self) -> str:
        """读当前邮箱的 UIDVALIDITY（uid 去重命名空间）。读不到返回空串，
        调用方退化为按账号名合成命名空间（Seen 标记仍是主防线）。"""
        try:
            imap = self._imap_factory(self._config["imap_host"])
            try:
                imap.login(self._config["username"], self._config["auth_code"])
                typ, _data = imap.select("INBOX", readonly=True)
                if typ != "OK":
                    return ""
                _code, val = imap.response("UIDVALIDITY")
                if not val:
                    return ""
                v = val[0]
                if isinstance(v, bytes):
                    return v.decode()
                return str(v)
            finally:
                try:
                    imap.logout()
                except Exception:
                    pass
        except Exception:
            return ""

    def _remember_reply(self, key: str, addr: str, subject: str):
        with self._lock:
            self._reply_to[key] = (addr, subject)
            if len(self._reply_to) > MAX_TRACKED_TASKS:
                for k in list(self._reply_to.keys())[:-MAX_TRACKED_TASKS]:
                    self._reply_to.pop(k, None)

    # ---- 分发与回信 ----
    def _dispatch(self, cmd: MailCommand, from_addr: str, subject: str,
                  reply_key: str):
        if cmd.kind == KIND_STATUS:
            status = (self._status_provider() if self._status_provider
                      else {"running": [], "queued": 0})
            self._send_reply_bg(from_addr, f"Re: {subject}",
                                format_status_reply(status))
            return
        if cmd.kind == KIND_STOP:
            with self._lock:
                tid = cmd.stop_task_id or (self._task_order[-1]
                                           if self._task_order else "")
            ok = False
            if tid:
                try:
                    ok = bool(self._runner.stop(tid))
                except Exception as e:
                    self._log(f"✉️ 停止请求失败：{e}")
                if ok:
                    with self._lock:
                        if tid in self._task_order:
                            self._task_order.remove(tid)
            self._send_reply_bg(
                from_addr, f"Re: {subject}",
                (f"已发送停止指令（任务 {tid or '未知'}），"
                 "当前这步执行完才真停" if ok else
                 "没找到这条任务，可能已经结束了"))
            return
        if cmd.usage_error:
            self._send_reply_bg(from_addr, f"Re: {subject}",
                                cmd.usage_error)
            return
        # KIND_TASK
        task_id = new_task_id()
        self._remember_reply(task_id, from_addr, subject)
        try:
            self._runner.submit(task_id, cmd.task_text)
        except Exception as e:
            self._log(f"✉️ 任务没能交出去：{e}")
            self._send_reply_bg(from_addr, f"Re: {subject}",
                                "这台电脑的助手暂时没接上，任务没有执行")
            return
        with self._lock:
            self._task_order.append(task_id)
            self._task_order = self._task_order[-MAX_TRACKED_TASKS:]
        self._log(f"✉️ 收到邮件任务 {task_id}：{cmd.task_text[:50]}")
        self._send_reply_bg(
            from_addr, f"Re: {subject}",
            f"已收到，任务号 {task_id}，交给电脑上的助手了。\n"
            f"做完会回信结果；中途回「[da] 状态」可查进度，"
            f"「[da] 停止 {task_id}」可停止。")

    def report(self, task_id: str, state_label: str, result: str):
        """任务收尾回调（GUI 在 done 事件里调）：回信结果给当初的发件人"""
        with self._lock:
            entry = self._reply_to.get(task_id)
        if not entry:
            return
        addr, subject = entry
        self._send_reply_bg(addr, f"Re: {subject}",
                            f"【{state_label}】\n{clip_result(result)}")

    def _send_reply_bg(self, to_addr: str, subject: str, body: str):
        def work():
            try:
                cfg = self._config
                send_reply(self._smtp_factory,
                           cfg["username"], cfg["auth_code"],
                           cfg["smtp_host"], to_addr, subject, body)
            except MailboxError as e:
                self._log(f"✉️ 回信失败：{e}")
            except Exception as e:
                self._log(f"✉️ 回信异常：{type(e).__name__}: {e}")
        threading.Thread(target=work, name="mail-remote-reply",
                         daemon=True).start()

    def _log(self, msg: str):
        try:
            self._on_log(msg)
        except Exception:
            pass
