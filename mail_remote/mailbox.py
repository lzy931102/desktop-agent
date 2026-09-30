"""mail_remote 的邮箱收发层：IMAP 拉取 + SMTP 回信。

为什么用标准库（imaplib/smtplib/email）而不是第三方库：
本模块随 exe 打包，零额外依赖、零打包风险——与 phone_bridge 的 server.py
用标准库 http.server 是同一条拍板逻辑。

安全约定：
- 只 fetch 信封头做预筛，命中白名单+前缀的信才取正文并标记已读；
  **其它邮件一律不碰已读状态**——这是用户自己的收件箱，不能替人消未读；
- 首次启动只校准不执行（见 __init__.py），防旧任务邮件重放；
- 授权码（不是登录密码）只落本机 settings.json，不进代码仓库。

测试口径：imaplib/smtplib 的会话对象全部经参数注入（fake 可替换），
本文件不自带网络重试——收发失败向上抛 MailboxError，由调用方记日志。
"""
from __future__ import annotations

import email
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from typing import List, Optional, Tuple


class MailboxError(RuntimeError):
    """邮箱收发失败，信息面向用户可直接展示。"""


# 常见邮箱服务商的收发服务器（按邮箱地址域名推导；查不到才要求手填）
KNOWN_HOSTS = {
    "qq.com": ("imap.qq.com", "smtp.qq.com"),
    "foxmail.com": ("imap.qq.com", "smtp.qq.com"),
    "163.com": ("imap.163.com", "smtp.163.com"),
    "126.com": ("imap.126.com", "smtp.126.com"),
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com"),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com"),
    "live.com": ("outlook.office365.com", "smtp.office365.com"),
}


def derive_hosts(addr: str) -> Tuple[Optional[str], Optional[str]]:
    """按邮箱地址域名推导 (imap_host, smtp_host)；未知域名返回 (None, None)"""
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    return KNOWN_HOSTS.get(domain, (None, None))


@dataclass
class MailItem:
    """一封待处理的信（已完成头预筛与正文解析）"""

    uid: bytes
    from_addr: str          # 规范化后的发件人地址
    subject: str            # 解码后的主题
    body: str               # 正文纯文本（无 text/plain 部件时做轻量清洗）


def _decode_header_value(raw) -> str:
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(str(raw))))
    except Exception:
        return str(raw)


def _body_text(msg: email.message.Message) -> str:
    """取正文纯文本：优先 text/plain；只有 html 时做轻量标签清洗"""
    plain = None
    html = None
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if part.get_filename():          # 附件不当作任务文本
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except Exception:
            text = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    if plain is not None:
        return plain
    if html is not None:
        # 轻量清洗：去标签、还常见实体、压空白（任务文本够用，不做完整渲染）
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                      flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">"))
        return text
    return ""


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_CRL_CHECK_LEAF
    except Exception:
        pass
    return ctx


def fetch_new(imap_factory, username: str, auth_code: str,
              imap_host: str, target_pred) -> List[MailItem]:
    """拉取收件箱里"未读 + 命中 target_pred(发件人, 主题)"的信。

    imap_factory(host) → 已连接的 IMAP 会话对象（真实环境给
    lambda h: imaplib.IMAP4_SSL(h, 993)，测试给桩）。流程：
    1. UID SEARCH UNSEEN 拿候选；
    2. 逐个 BODY.PEEK 头部（不置已读），预筛发件人+主题；
    3. 命中的取全信解析，并显式标记 \\Seen——其余邮件不碰已读状态。
    target_pred(from_addr, subject) → bool 由调用方注入（白名单+前缀逻辑
    在 contract 层，本文件只做搬运）。
    """
    try:
        imap = imap_factory(imap_host)
        try:
            typ, _ = imap.login(username, auth_code)
            if typ != "OK":
                raise MailboxError("邮箱登录被拒绝，请检查账号与授权码")
            typ, data = imap.uid("search", None, "UNSEEN")
            if typ != "OK":
                raise MailboxError("收件箱查询失败")
            uids = (data[0] or b"").split()

            out: List[MailItem] = []
            for uid in uids:
                typ, head = imap.uid("fetch", uid,
                                     "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                if typ != "OK" or not head or head[0] is None:
                    continue
                head_bytes = b""
                for chunk in head:
                    if isinstance(chunk, tuple):
                        head_bytes = chunk[1]
                        break
                head_msg = email.message_from_bytes(head_bytes)
                from_addr = parseaddr(_decode_header_value(
                    head_msg.get("From")))[1].lower()
                subject = _decode_header_value(head_msg.get("Subject"))
                if not target_pred(from_addr, subject):
                    continue      # 非目标邮件：不取正文、不标已读
                typ, full = imap.uid("fetch", uid, "(BODY.PEEK[])")
                if typ != "OK" or not full or full[0] is None:
                    continue
                raw = b""
                for chunk in full:
                    if isinstance(chunk, tuple):
                        raw = chunk[1]
                        break
                msg = email.message_from_bytes(raw)
                out.append(MailItem(uid=uid,
                                    from_addr=from_addr,
                                    subject=subject,
                                    body=_body_text(msg)))
                imap.uid("store", uid, "+FLAGS", "(\\Seen)")
            return out
        finally:
            try:
                imap.logout()
            except Exception:
                pass
    except MailboxError:
        raise
    except (imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
        raise MailboxError(
            f"收件箱连接失败：{type(e).__name__}。请检查收件服务器地址、"
            f"账号与授权码") from e


def send_reply(smtp_factory, username: str, auth_code: str,
               smtp_host: str, to_addr: str, subject: str, body: str) -> None:
    """发一封回信。smtp_factory(host) → 已连接 SMTP 会话（测试可注入桩）。"""
    msg = EmailMessage()
    msg["From"] = username
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        smtp = smtp_factory(smtp_host)
        try:
            typ, _ = smtp.login(username, auth_code)
            if typ != "OK":
                raise MailboxError("邮箱登录被拒绝，请检查账号与授权码")
            smtp.send_message(msg)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
    except MailboxError:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise MailboxError(
            f"回信发送失败：{type(e).__name__}。请检查发件服务器地址与授权码") from e
