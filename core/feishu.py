"""飞书群机器人：通过自定义机器人 Webhook 把消息发到飞书群（手机电脑同步可见）。

安全约束（在 settings.validate_public_https 公网校验之上）：
- 只允许 https + 飞书官方域名（open.feishu.cn / open.larksuite.com）
- Webhook 地址保存在本机 settings.json，不进代码仓库
"""
from urllib.parse import urlparse

import requests

from core.settings import validate_public_https

ALLOWED_HOSTS = {"open.feishu.cn", "open.larksuite.com"}


def validate_webhook(url: str) -> str:
    """校验 Webhook 地址：合法返回 None，否则返回中文错误原因"""
    url = (url or "").strip()
    if not url:
        return "未配置飞书机器人 Webhook，请到「设置 → 飞书群通知」粘贴"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Webhook 地址必须以 https:// 开头"
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return "Webhook 地址包含异常的账号或端口信息"
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return (f"出于安全考虑只允许飞书官方域名 "
                f"{', '.join(sorted(ALLOWED_HOSTS))}，当前是「{host}」")
    ok, why = validate_public_https(url)
    if not ok:
        return f"Webhook 地址未通过公网校验: {why}"
    return None


def send_feishu_message(text: str, webhook: str = "") -> tuple:
    """发送文本消息到飞书群，返回 (ok, 说明)。

    飞书自定义机器人响应有两种格式：新版 {"code":0,"msg":"success"}，
    旧版 {"StatusCode":0,"StatusMessage":"success"}，两者都认。
    """
    err = validate_webhook(webhook)
    if err:
        return False, err
    try:
        resp = requests.post(
            webhook.strip(),
            json={"msg_type": "text", "content": {"text": str(text)}},
            timeout=10,
            headers={"Content-Type": "application/json"})
    except requests.RequestException as e:
        return False, f"网络请求失败: {e}"
    if resp.status_code != 200:
        return False, f"飞书返回 HTTP {resp.status_code}: {resp.text[:150]}"
    try:
        data = resp.json()
    except ValueError:
        return False, f"飞书返回了非 JSON 内容: {resp.text[:150]}"
    ok = (data.get("code") in (0, "0")) or \
         (data.get("StatusCode") in (0, "0")) or \
         (str(data.get("msg", "")).lower() == "success")
    if ok:
        return True, "已发送到飞书群"
    detail = data.get("msg") or data.get("StatusMessage") or str(data)
    return False, f"飞书拒绝发送: {detail}（若机器人启用了关键词限制，消息需包含关键词）"
