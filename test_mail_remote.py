"""mail_remote 邮件远程模块回归（任务 18）。

覆盖：契约解析矩阵、收件预筛（白名单外的信不碰已读状态）、
首轮校准（旧任务邮件不重放）、uid 去重、任务分发与结果回信。

IMAP/SMTP 会话全部用桩（fake factory 注入），测试不连真实邮箱。
"""
import threading
import time
from email.message import EmailMessage

import pytest

from mail_remote import MailRemote, _SeenStore
from mail_remote.contract import (format_status_reply, new_task_id,
                                  normalize_addr, parse_command,
                                  split_allowed_senders)
from mail_remote.mailbox import derive_hosts, fetch_new, send_reply


# ==================== 契约：解析与白名单 ====================

def test_parse_command_matrix():
    """[da] 主题/正文任务、状态、停止（带/不带号）、无前缀忽略、空内容报用法"""
    c = parse_command("[da] 帮我打开记事本", "", "[da]")
    assert c.kind == "task" and c.task_text == "帮我打开记事本"
    c = parse_command("[da]", "把桌面图片整理到文件夹", "[da]")
    assert c.kind == "task" and c.task_text == "把桌面图片整理到文件夹"
    c = parse_command("[da] 状态", "", "[da]")
    assert c.kind == "status"
    c = parse_command("[da] 停止 ab12cd34ef56", "", "[da]")
    assert c.kind == "stop" and c.stop_task_id == "ab12cd34ef56"
    c = parse_command("[da] 停止", "", "[da]")
    assert c.kind == "stop" and c.stop_task_id == ""     # 空 = 停最近一条
    c = parse_command("普通往来邮件", "正文", "[da]")
    assert c.kind == "ignore"                            # 无前缀：不受理不回信
    c = parse_command("[da]", "   \r\n  ", "[da]")
    assert c.kind == "task" and c.usage_error            # 空任务 → 回用法提示
    c = parse_command("[da] " + "长" * 2001, "", "[da]")
    assert c.kind == "task" and c.usage_error            # 超长 → 回用法提示
    c = parse_command("[通知] 换个前缀", "", "[da]")
    assert c.kind == "ignore"                            # 前缀可配，默认 [da]


def test_addr_normalization():
    assert normalize_addr("张三 <Phone.QQ@qq.com>") == "phone.qq@qq.com"
    assert normalize_addr("no-address-here") == ""
    assert split_allowed_senders("a@QQ.com；b@163.com, c@qq.com a@qq.com") == \
        ["a@qq.com", "b@163.com", "c@qq.com"]            # 去重 + 大小写归一


def test_task_id_shape():
    ids = {new_task_id() for _ in range(50)}
    assert len(ids) == 50 and all(len(i) == 12 for i in ids)


# ==================== 收件层：预筛与已读保护 ====================

class _FakeIMAP:
    """imaplib 会话桩：uid search/fetch/store/select/response"""

    def __init__(self, mails):
        self.mails = mails            # {uid: bytes} 完整信
        self.seen = []
        self.logged = False

    def login(self, user, code):
        self.logged = True
        return ("OK", [b"Logged in"])

    def uid(self, cmd, *args):
        if cmd == "search":
            return ("OK", [b" ".join(self.mails.keys())])
        uid = args[0]
        if cmd == "fetch":
            raw = self.mails[uid]
            marker = ("HEADER.FIELDS" in str(args[1]))
            payload = _header_of(raw) if marker else raw
            return ("OK", [(b"1 (UID " + uid + b")", payload), b")"])
        if cmd == "store":
            self.seen.append(args[0])
            return ("OK", [b""])
        raise AssertionError(cmd)

    def select(self, mailbox, readonly=False):
        return ("OK", [b"[UIDVALIDITY 777] Items"])

    def response(self, name):
        return ("OK", [b"777"]) if name == "UIDVALIDITY" else ("OK", [None])

    def logout(self):
        return ("BYE", [b""])


def _msg_bytes(frm, subject, body):
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m.set_content(body)
    return m.as_bytes()


def _header_of(raw):
    m = EmailMessage()
    m["From"] = "x"
    m["Subject"] = "y"
    full = EmailMessage()
    full["From"] = "placeholder"
    # 从完整信里抽头部：直接用 email 库重拼（测试够用）
    import email as _email
    msg = _email.message_from_bytes(raw)
    head = b"From: " + (msg.get("From") or "").encode() + \
        b"\r\nSubject: " + (msg.get("Subject") or "").encode() + b"\r\n\r\n"
    return head


def test_fetch_new_filters_and_marks_seen():
    """预筛：白名单+前缀命中才取正文并标记已读；陌生来信不碰已读状态"""
    mails = {
        b"1": _msg_bytes("phone@qq.com", "[da]", "打开记事本"),
        b"2": _msg_bytes("stranger@qq.com", "[da] 冒充", ""),
        b"3": _msg_bytes("phone@qq.com", "没有前缀的家常邮件", "别动它"),
    }
    fake = _FakeIMAP(mails)
    pred = lambda addr, subject: (addr == "phone@qq.com"
                                  and subject.startswith("[da]"))
    items = fetch_new(lambda h: fake, "pc@qq.com", "code", "imap.qq.com", pred)
    assert [i.uid for i in items] == [b"1"]     # 只有目标信被取出
    assert items[0].from_addr == "phone@qq.com"
    assert items[0].body.strip() == "打开记事本"   # 主题只有前缀 → 任务在正文
    assert fake.seen == [b"1"]                  # 只标记目标信


# ==================== MailRemote：校准 / 去重 / 分发 / 回信 ====================

class _FakeRunner:
    def __init__(self):
        self.submitted = []
        self.stopped = []

    def submit(self, task_id, text):
        self.submitted.append((task_id, text))

    def stop(self, task_id):
        self.stopped.append(task_id)
        return task_id in dict(self.submitted) or True


class _FakeSMTP:
    sent = []                    # (to, subject, body)

    def login(self, u, p):
        return ("OK", [b"ok"])

    def send_message(self, msg):
        _FakeSMTP.sent.append((msg["To"], msg["Subject"], msg.get_content()))

    def quit(self):
        return ("BYE", [b""])


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    from mail_remote import state_path
    monkeypatch.setattr("mail_remote.state_path", lambda: tmp_path / "st.json")
    _FakeSMTP.sent.clear()
    return tmp_path / "st.json"


def _make_remote(mails_holder, runner, status_provider=None):
    fake_imap = _FakeIMAP(mails_holder["mails"])
    remote = MailRemote(runner, status_provider=status_provider,
                        on_log=lambda m: None)
    return remote, lambda h: fake_imap, fake_imap


def _wait_sent(n, timeout=3):
    """回信走后台线程：轮询等待发送记录达到 n 封"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(_FakeSMTP.sent) >= n:
            return True
        time.sleep(0.05)
    return False


def test_first_run_calibrates_then_executes(fresh_state, monkeypatch):
    """首跑只登记不执行（防旧任务邮件重放）；第二跑新信才受理分发"""
    holder = {"mails": {b"1": _msg_bytes("phone@qq.com", "[da] 旧任务", "")}}
    remote, imap_f, fake_imap = _make_remote(holder, _FakeRunner())
    remote.start({"username": "pc@qq.com", "auth_code": "code",
                  "allowed_senders": "phone@qq.com", "subject_prefix": "[da]",
                  "poll_seconds": 60}, imap_factory=imap_f)
    assert remote._poll_once() == 0       # 校准：不执行
    holder["mails"][b"2"] = _msg_bytes("phone@qq.com", "[da] 新任务", "")
    assert remote._poll_once() == 1       # 新信：受理
    tid, text = remote._runner.submitted[0]
    assert text == "新任务"
    # 同一封信第三跑（模拟 Seen 标记丢失）→ uid 去重，不重复执行
    assert remote._poll_once() == 0
    assert len(remote._runner.submitted) == 1
    remote.stop()


def test_status_and_stop_commands(fresh_state, monkeypatch):
    holder = {"mails": {b"1": _msg_bytes("phone@qq.com", "[da] 状态", "")}}
    remote, imap_f, _ = _make_remote(
        holder, _FakeRunner(), status_provider=lambda: {
            "running": [{"title": "✉️ 任务", "action": "第 2 轮"}],
            "queued": 1})
    smtp_f = lambda h: _FakeSMTP()
    remote.start({"username": "pc@qq.com", "auth_code": "code",
                  "allowed_senders": "phone@qq.com", "poll_seconds": 60},
                 imap_factory=imap_f, smtp_factory=smtp_f)
    remote._poll_once()                                            # 校准
    holder["mails"][b"2"] = _msg_bytes("phone@qq.com", "[da] 状态", "")
    holder["mails"][b"3"] = _msg_bytes("phone@qq.com", "[da] 停止", "")
    assert remote._poll_once() == 2
    assert _wait_sent(2), "两条命令的回信都应发出"
    status_body = next(b for t, s, b in _FakeSMTP.sent if "状态" in s)
    stop_body = next(b for t, s, b in _FakeSMTP.sent if "停止" in s)
    assert "✉️ 任务" in status_body and "排队等待：1 条" in status_body
    assert "没找到" in stop_body          # 还没受理过任务：无号可停
    remote.stop()


def test_stop_latest_and_report_reply(fresh_state, monkeypatch):
    """先受理一条任务，[da] 停止 → 停最近任务号；report() 回信终态结果"""
    holder = {"mails": {}}
    remote, imap_f, _ = _make_remote(holder, _FakeRunner())
    smtp_f = lambda h: _FakeSMTP()
    remote.start({"username": "pc@qq.com", "auth_code": "code",
                  "allowed_senders": "phone@qq.com", "poll_seconds": 60},
                 imap_factory=imap_f, smtp_factory=smtp_f)
    remote._poll_once()                                            # 校准空箱
    holder["mails"][b"1"] = _msg_bytes("phone@qq.com", "[da] 整理桌面", "")
    remote._poll_once()
    assert _wait_sent(1)                     # 受理确认信
    tid = remote._runner.submitted[0][0]

    holder["mails"][b"2"] = _msg_bytes("phone@qq.com", "[da] 停止", "")
    remote._poll_once()
    assert remote._runner.stopped == [tid]
    assert _wait_sent(2), "停止回信未发出"
    stop_body = _FakeSMTP.sent[-1][2]
    assert "已发送停止指令" in stop_body and tid in stop_body

    remote.report(tid, "已完成", "桌面整理好了，共归档 5 个文件")
    assert _wait_sent(3), "结果回信未发出"
    to, subject, body = _FakeSMTP.sent[-1]
    assert to == "phone@qq.com" and "整理桌面" in subject
    assert "【已完成】" in body and "归档 5 个文件" in body
    remote.stop()


def test_seen_store_uidvalidity_reset(tmp_path):
    """uid 命名空间（UIDVALIDITY）变化 → 历史记录作废重新校准"""
    st = _SeenStore(tmp_path / "s.json")
    st.mark("V1", b"1")
    assert st.already("V1", b"1")
    assert not st.already("V2", b"1")          # 换了 uid 空间：不认旧记录
    st.mark("V2", b"1")
    assert st.already("V2", b"1")
    # 落盘重载后仍生效
    st2 = _SeenStore(tmp_path / "s.json")
    assert st2.already("V2", b"1") and not st2.already("V1", b"1")


def test_config_validation_errors():
    r = MailRemote(_FakeRunner())
    with pytest.raises(Exception, match="邮箱账号"):
        r.start({"auth_code": "x", "allowed_senders": "a@b.c"})
    with pytest.raises(Exception, match="授权码"):
        r.start({"username": "a@qq.com", "allowed_senders": "a@b.c"})
    with pytest.raises(Exception, match="白名单"):
        r.start({"username": "a@qq.com", "auth_code": "x"})


def test_derive_hosts_known_domains():
    assert derive_hosts("a@qq.com") == ("imap.qq.com", "smtp.qq.com")
    assert derive_hosts("a@gmail.com") == ("imap.gmail.com", "smtp.gmail.com")
    assert derive_hosts("a@unknown.tld") == (None, None)


def test_send_reply_builds_message():
    captured = []

    class _S:
        def login(self, u, p):
            return ("OK", [b"ok"])

        def send_message(self, msg):
            captured.append(msg)

        def quit(self):
            return ("BYE", [b""])

    send_reply(lambda h: _S(), "pc@qq.com", "code", "smtp.qq.com",
               "phone@qq.com", "Re: [da] 状态", "当前没有在执行的任务。")
    assert captured[0]["To"] == "phone@qq.com"
    assert "状态" in captured[0]["Subject"]


def test_format_status_reply_readable():
    text = format_status_reply({
        "running": [{"title": "✉️ 整理桌面", "action": "第 2/10 轮"}],
        "queued": 2})
    assert "整理桌面" in text and "排队等待：2 条" in text
