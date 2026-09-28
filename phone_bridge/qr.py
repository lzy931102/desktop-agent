"""把"手机该访问哪个地址"这件事算出来，并生成二维码。

为什么需要这一层：
用户不该去查自己的局域网 IP。这里自动挑一个"手机能访问到"的地址，
配上令牌拼成链接，再画成二维码给用户扫。

依赖：segno（纯 Python 二维码，无二进制依赖，打包友好）。
"""
from __future__ import annotations

import base64
import io
import ipaddress
import socket
from typing import Dict, List, Optional

import segno

QR_SCALE = 6          # 二维码放大倍数（越大图越大、越好扫）
QR_BORDER = 2         # 静区（二维码四周留白，太小会扫不出来）

# 只用于 UDP "连一下"探测出口网卡，不真的发包
_PROBE_TARGET = ("223.5.5.5", 53)


def primary_ip() -> str:
    """取本机走外网/局域网那张网卡的 IPv4。

    做法：创建一个 UDP socket 连一下公共地址——只要内核选了出口网卡就拿到地址，
    不会真的发数据。拿不到时退回 127.0.0.1（此时手机肯定连不上，界面需提示）。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(_PROBE_TARGET)
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def all_lan_ips() -> List[str]:
    """列出本机所有可能被手机访问的 IPv4（去重、去掉回环/链路本地）。

    用于"这个地址不通？换一个试试"——多网卡（有线+无线+虚拟网卡）时会有多个。
    """
    found: List[str] = []

    def _add(ip: str) -> None:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return
        if addr.version != 4 or addr.is_loopback or addr.is_link_local:
            return
        if ip not in found:
            found.append(ip)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(info[4][0])
    except OSError:
        pass
    _add(primary_ip())

    # 出口网卡排第一（最可能通）
    first = primary_ip()
    if first in found:
        found.remove(first)
    found.insert(0, first)
    return found


def build_url(ip: str, port: int, token: str, scheme: str = "http") -> str:
    """拼出手机该打开的链接。令牌编在链接里，扫一次就带上了。"""
    return f"{scheme}://{ip}:{port}/?t={token}"


def qr_png(data: str, scale: int = QR_SCALE) -> bytes:
    """把文字画成 PNG 二维码字节。"""
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=QR_BORDER)
    return buf.getvalue()


def qr_base64(data: str, scale: int = QR_SCALE) -> str:
    """二维码的 base64（供 tkinter PhotoImage 直接吃，不用落盘）。"""
    return base64.b64encode(qr_png(data, scale)).decode("ascii")


def reachable_for_phone(ip: str) -> bool:
    """粗判这个地址是不是"手机能访问到"的类型（回环/无地址就是不行）。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_loopback or addr.is_unspecified)


def describe_network() -> Dict[str, object]:
    """给界面用的一行网络说明，避免用户面对一堆 IP 发懵。"""
    ip = primary_ip()
    ok = reachable_for_phone(ip)
    return {
        "ip": ip,
        "ok": ok,
        "hint": ("手机和电脑连同一个 WiFi 就能扫" if ok else
                 "没检测到可用的局域网地址，请先连上 WiFi 或网线"),
        "alternatives": all_lan_ips(),
    }
