"""手机连接（独立模块）：把桌面助手接到手机上，用手机遥控下任务、看结果。

对外只暴露 PhoneBridge。内部四件事各归各的文件：

    contract.py  任务/事件的数据契约与状态机
    auth.py      令牌与失败限速
    hub.py       任务排队、状态跟踪（执行能力由外部注入）
    server.py    手机端 HTTP 服务与页面
    qr.py        局域网地址探测与二维码
    tunnel.py    外网通道（cloudflared）
    fetcher.py   外网通道组件的按需下载

依赖边界（单向，禁止反向）：本包只允许 import 标准库与本包内文件，
**禁止 import agent_loop / gui / core** —— 这保证它可以脱离整个程序单独测试，
也让"换个界面（比如将来企业版的 Web 控制台）"不用动这个模块。

两种连接方式（实测结论，2026-09-28）：
- 在家（同一个 WiFi）：走局域网地址，毫秒级，不依赖外网；
- 出门：走 cloudflared 外网通道，需要电脑联网，地址每次都是新的。
本机实测发现：部分家用路由器对 `*.trycloudflare.com` 返回"N域名不存在"，
所以**同一个 WiFi 下外网地址可能解析不了**——界面必须两个地址都给。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .auth import PairingAuth, mask_token, new_pair_code, new_token
from .contract import (
    STATE_LABELS,
    TERMINAL_STATES,
    PhoneTask,
    TaskInputError,
)
from .hub import TaskHub, TaskRunner
from .qr import all_lan_ips, build_url, describe_network, primary_ip, qr_base64, qr_png
from .server import DEFAULT_PORT, BridgeServer
from .tunnel import (
    ST_FAILED,
    ST_RUNNING,
    ST_STARTING,
    ST_STOPPED,
    CloudflaredTunnel,
    locate_binary,
)

__all__ = ["PhoneBridge", "TaskRunner", "TaskHub", "PairingAuth", "PhoneTask",
           "TaskInputError", "DEFAULT_PORT", "ST_STOPPED", "ST_STARTING",
           "ST_RUNNING", "ST_FAILED"]


class PhoneBridge:
    """手机连接的总开关：HTTP 服务 + 令牌 + 可选外网通道。"""

    def __init__(self, runner: Optional[TaskRunner] = None,
                 port: int = DEFAULT_PORT,
                 on_change: Optional[Callable[[], None]] = None):
        self.auth = PairingAuth()
        self.hub = TaskHub(runner=runner, on_change=on_change)
        self.server = BridgeServer(self.hub, self.auth, port=port)
        self.tunnel: Optional[CloudflaredTunnel] = None
        self._host_ip = ""
        self._on_change = on_change

    # ---- 局域网服务 ----
    def start(self, port: Optional[int] = None) -> Dict[str, Any]:
        """开启手机连接（局域网）。返回可直接喂给界面的状态字典。"""
        if port:
            self.server.port = int(port)
        actual = self.server.start()
        self._host_ip = primary_ip()
        self._fire()
        return self.status()

    def stop(self) -> None:
        """关闭手机连接：外网通道一并收掉（留着白占资源）。"""
        self.disable_external()
        self.server.stop()
        self._fire()

    @property
    def running(self) -> bool:
        return self.server.running

    # ---- 令牌 ----
    def rotate_token(self) -> Dict[str, str]:
        """换一把钥匙：旧手机上打开的页面立刻失效。"""
        token, code = self.auth.rotate()
        self._fire()
        return {"token": token, "pair_code": code,
                "token_masked": mask_token(token)}

    @property
    def token(self) -> str:
        return self.auth.token

    @property
    def pair_code(self) -> str:
        return self.auth.pair_code

    # ---- 外网通道 ----
    def external_ready(self) -> bool:
        """外网通道组件装好了没（没装的话界面要显示"需要下载一次"）。"""
        return locate_binary() is not None

    def enable_external(self) -> Dict[str, Any]:
        """开启外网通道。组件缺失时返回 need_download=True，由界面去问用户。"""
        if not self.external_ready():
            return {"ok": False, "need_download": True,
                    "message": "外网通道需要先下载一个 55 MB 的组件（只下一次）"}
        if not self.server.running:
            return {"ok": False, "need_download": False,
                    "message": "请先打开手机连接，再开外网通道"}
        if self.tunnel is None:
            self.tunnel = CloudflaredTunnel(self.server.port,
                                            on_change=self._fire)
        ok = self.tunnel.start()
        self._fire()
        return {"ok": ok, "need_download": False,
                "message": self.tunnel.message or ("外网通道已开好" if ok else "没开起来")}

    def disable_external(self) -> None:
        if self.tunnel is not None:
            self.tunnel.stop()
        self._fire()

    @property
    def external_url(self) -> str:
        return self.tunnel.url if self.tunnel else ""

    # ---- 地址与二维码 ----
    def lan_url(self) -> str:
        """在家（同一 WiFi）用的地址。"""
        ip = self._host_ip or primary_ip()
        return build_url(ip, self.server.port, self.auth.token)

    def wan_url(self) -> str:
        """出门用的地址。没开外网通道时为空。"""
        return self.external_url

    def url_for(self, where: str = "lan") -> str:
        return self.wan_url() if where == "wan" else self.lan_url()

    def qr_png(self, where: str = "lan", scale: int = 6) -> bytes:
        url = self.url_for(where)
        if not url:
            raise ValueError("这个地址还没准备好")
        return qr_png(url, scale=scale)

    def qr_base64(self, where: str = "lan", scale: int = 6) -> str:
        url = self.url_for(where)
        if not url:
            raise ValueError("这个地址还没准备好")
        return qr_base64(url, scale=scale)

    # ---- 给界面的状态 ----
    def status(self) -> Dict[str, Any]:
        net = describe_network()
        tun = self.tunnel.status() if self.tunnel else {
            "state": ST_STOPPED, "message": "", "url": "",
            "has_binary": self.external_ready()}
        return {
            "running": self.running,
            "port": self.server.port,
            "host_ip": net["ip"],
            "network_hint": net["hint"],
            "alternatives": net["alternatives"],
            "lan_url": self.lan_url() if self.running else "",
            "wan_url": self.wan_url(),
            "token_masked": mask_token(self.auth.token),
            "pair_code": self.auth.pair_code,
            "tunnel": tun,
            "tasks_running": self.hub.running_task_id is not None,
        }

    def _fire(self) -> None:
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass
