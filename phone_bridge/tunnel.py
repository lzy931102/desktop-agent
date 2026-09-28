"""外网通道：用 cloudflared 快速隧道，把本机的手机页面暴露到公网。

为什么要外网通道：用户的要求是"在哪里都可以连接他"。
局域网地址只在同一个 WiFi 下有效；出门用手机流量就打不开了。
cloudflared 快速隧道是**本机主动往外连**，不需要公网 IP、不用改路由器端口映射，
代价是：① 每次开启地址都是新的（所以必须扫码，不能存书签）；
② 免费隧道没有可用性承诺。

一个已实测的坑（2026-09-28 取证）：
部分家用路由器（本机实测中国移动宽带的路由器）对 `*.trycloudflare.com`
返回"N域名不存在"，导致**同一 WiFi 下**手机解析不到外网地址。
所以界面必须同时给"在家用"和"出门用"两个地址，不能只给一个。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .fetcher import cloudflared_path

# 状态
ST_STOPPED = "stopped"
ST_STARTING = "starting"
ST_RUNNING = "running"
ST_FAILED = "failed"

START_TIMEOUT_S = 60.0        # 超过这个时间还没拿到地址就算失败
STOP_WAIT_S = 6.0             # 退出等待上限

_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_CREATE_NO_WINDOW = 0x08000000      # 别弹黑框


def locate_binary() -> Optional[Path]:
    """找 cloudflared：环境变量 → 数据目录 → 程序旁边 → PATH。"""
    env = os.environ.get("DESKTOPAGENT_CLOUDFLARED", "").strip()
    if env and Path(env).is_file():
        return Path(env)
    cached = cloudflared_path()
    if cached.is_file():
        return cached
    beside = Path(os.path.abspath(sys.executable)).parent / "cloudflared.exe"
    if beside.is_file():
        return beside
    found = shutil.which("cloudflared")
    return Path(found) if found else None


class CloudflaredTunnel:
    """把 http://127.0.0.1:<port> 通过 cloudflared 暴露成一个公网地址。"""

    def __init__(self, local_port: int,
                 on_change: Optional[Callable[[], None]] = None,
                 binary: Optional[Path] = None):
        self.local_port = int(local_port)
        self._on_change = on_change
        self._binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._state = ST_STOPPED
        self._message = ""
        self.url = ""
        self._want_running = False

    # ---- 状态 ----
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def running(self) -> bool:
        return self.state == ST_RUNNING and bool(self.url)

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "message": self._message,
                    "url": self.url, "has_binary": bool(self._binary or locate_binary())}

    def _set(self, state: str, message: str = "") -> None:
        with self._lock:
            self._state = state
            self._message = message
        self._notify()

    def _notify(self) -> None:
        cb = self._on_change
        if cb:
            try:
                cb()
            except Exception:
                pass

    # ---- 开关 ----
    def start(self) -> bool:
        """启动隧道。返回 False 表示没能起来，原因见 status()["message"]。"""
        with self._lock:
            if self._proc is not None:
                return self._state == ST_RUNNING
            binary = self._binary or locate_binary()
            if binary is None:
                self._binary = None
                self._set(ST_FAILED, "还没装外网通道组件，需要先下载一次")
                return False
            self._binary = binary
            self._want_running = True
            self.url = ""
            self._set(ST_STARTING, "正在开一条通往外网的路…")
            try:
                self._proc = subprocess.Popen(
                    [str(binary), "tunnel", "--url",
                     f"http://127.0.0.1:{self.local_port}", "--no-autoupdate"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=_CREATE_NO_WINDOW)
            except OSError as e:
                self._proc = None
                self._set(ST_FAILED, f"外网通道没启动起来（{e}）")
                return False
            self._reader = threading.Thread(target=self._read_loop,
                                            name="phone-bridge-tunnel", daemon=True)
            self._reader.start()
            threading.Thread(target=self._watchdog, name="phone-bridge-tunnel-wd",
                             daemon=True).start()
            return True

    def _watchdog(self) -> None:
        """超时兜底：cloudflared 卡住不出地址时，别让界面一直转圈。"""
        time.sleep(START_TIMEOUT_S)
        with self._lock:
            stuck = self._state == ST_STARTING and self._proc is not None
        if stuck:
            self._set(ST_FAILED, "等了 1 分钟还没拿到外网地址，请检查电脑网络后重试")
            self.stop()

    def stop(self) -> None:
        with self._lock:
            self._want_running = False
            proc, self._proc = self._proc, None
            self.url = ""
            if proc is None:
                self._set(ST_STOPPED, "")
                return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass
        self._set(ST_STOPPED, "")

    # ---- 输出解析 ----
    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        got_url = False
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if not got_url:
                    m = _URL_RE.search(line)
                    if m:
                        got_url = True
                        self.url = m.group(0)
                        self._set(ST_RUNNING, "外网通道已开好")
            # 进程结束
            code = proc.wait()
            with self._lock:
                self._proc = None
                want = self._want_running
            if want:
                self._set(ST_FAILED,
                          f"外网通道意外断开了，可以再点一次开启（退出码 {code}）")
            else:
                self._set(ST_STOPPED, "")
        except Exception as e:                     # 读流异常不能让程序崩
            with self._lock:
                self._proc = None
            self._set(ST_FAILED, f"外网通道读取出错：{e}")
        finally:
            if not got_url and self.state == ST_STARTING:
                self._set(ST_FAILED, "等了 1 分钟还没拿到外网地址，请检查电脑网络后重试")
                self.stop()
