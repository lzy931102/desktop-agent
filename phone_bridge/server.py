"""手机端 HTTP 服务：只服务一台手机、几条请求，所以用标准库而不是框架。

为什么不用 Flask/aiohttp：本模块要随 exe 一起打包，
标准库 http.server 零额外依赖、零打包风险，够用。

安全边界（重要）：
- 服务绑在局域网网卡上，**同一 WiFi 的人能连到端口**，所以每个请求都要带令牌；
- 令牌错会按来源限速（auth.py），防止有人暴力猜；
- 本服务不做任何电脑操作，只把任务交给 hub；真正的危险操作仍走
  core/guard.py + GUI 确认弹窗，这一层没有被绕过。
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .auth import PairingAuth
from .contract import TaskInputError
from .hub import TaskHub

MAX_BODY_BYTES = 64 * 1024      # 请求体上限：任务文字最长 2000 字，64KB 足够
DEFAULT_PORT = 8765

# 手机没带令牌时看到的页面（不是干巴巴的 401，得告诉用户怎么办）
NO_TOKEN_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需要先扫码</title><style>
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
margin:0;padding:36px 22px;background:#0f1115;color:#e6e8eb;line-height:1.75}
.card{max-width:420px;margin:0 auto;background:#171a21;border:1px solid #262b36;
border-radius:14px;padding:24px}
h1{font-size:19px;margin:0 0 12px}
p{margin:0 0 10px;color:#a8b0bd;font-size:15px}
b{color:#e6e8eb}
</style></head><body><div class="card">
<h1>这条链接不完整</h1>
<p>请回到电脑上，打开桌面助手的 <b>📱 手机连接</b>，重新扫一次二维码。</p>
<p>手动输入地址的话，别漏掉链接最后 <b>?t=</b> 后面那一串字符。</p>
</div></body></html>"""


def web_dir() -> Path:
    """网页目录：兼容"源码运行"和"打包成 exe"两种形态。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for cand in (base / "phone_bridge" / "web", base / "web"):
            if cand.is_dir():
                return cand
        return base / "web"
    return Path(__file__).resolve().parent / "web"


class _Handler(BaseHTTPRequestHandler):
    """路由 + 鉴权。业务逻辑一律下沉到 hub，这里只做搬运。"""

    server_version = "DesktopAgentPhoneBridge"
    protocol_version = "HTTP/1.1"

    # ---- 让日志不刷屏（HTTP 请求逐条打印会淹没运行日志）----
    def log_message(self, fmt, *args):    # noqa: A003 - 覆写父类接口
        pass

    # ---- 工具 ----
    @property
    def _hub(self) -> TaskHub:
        return self.server.hub          # type: ignore[attr-defined]

    @property
    def _auth(self) -> PairingAuth:
        return self.server.auth         # type: ignore[attr-defined]

    def _client_key(self) -> str:
        return self.client_address[0]

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass          # 手机提前关页面，属正常现象

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _html(self, code: int, text: str) -> None:
        self._send(code, text.encode("utf-8"), "text/html; charset=utf-8")

    def _denied(self, message: str) -> None:
        left = self._auth.blocked_seconds_left(self._client_key())
        if left:
            message = f"尝试次数太多，请等 {left} 秒后再试"
        self._json(401, {"ok": False, "message": message})

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise TaskInputError("提交的内容太大了")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise TaskInputError("提交的内容格式不对")
        return data if isinstance(data, dict) else {}

    def _token_from_request(self, query: dict) -> str:
        header = self.headers.get("X-Phone-Token")
        if header:
            return header.strip()
        vals = query.get("t") or []
        return vals[0].strip() if vals else ""

    # ---- GET ----
    def do_GET(self):                       # noqa: N802 - 父类命名
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        token = self._token_from_request(query)

        if parsed.path in ("/", "/index.html"):
            if not self._auth.check(token, self._client_key()):
                self._html(200, NO_TOKEN_HTML)
                return
            page = web_dir() / "index.html"
            try:
                self._html(200, page.read_text(encoding="utf-8"))
            except OSError:
                self._json(500, {"ok": False, "message": "手机页面文件读不到，请重装这个版本"})
            return

        if not self._auth.check(token, self._client_key()):
            self._denied("链接里的钥匙不对，请在电脑上重新扫码")
            return

        if parsed.path == "/api/state":
            events_from = self._int(query, "events_from", 0)
            self._json(200, {"ok": True, **self._hub.snapshot(events_from)})
            return

        if parsed.path == "/api/ping":
            self._json(200, {"ok": True, "message": "已连上电脑上的助手"})
            return

        if parsed.path.startswith("/api/task/"):
            task_id = parsed.path[len("/api/task/"):]
            events_from = self._int(query, "events_from", 0)
            data = self._hub.get(task_id, events_from)
            if data is None:
                self._json(404, {"ok": False, "message": "这条任务找不到了"})
            else:
                self._json(200, {"ok": True, "task": data})
            return

        self._json(404, {"ok": False, "message": "没有这个地址"})

    # ---- POST ----
    def do_POST(self):                      # noqa: N802 - 父类命名
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        token = self._token_from_request(query)
        if not self._auth.check(token, self._client_key()):
            self._denied("链接里的钥匙不对，请在电脑上重新扫码")
            return
        try:
            data = self._read_json()
        except TaskInputError as e:
            self._json(400, {"ok": False, "message": str(e)})
            return

        if parsed.path == "/api/task":
            try:
                task = self._hub.submit(data.get("text"), source="phone")
            except TaskInputError as e:
                self._json(400, {"ok": False, "message": str(e)})
                return
            self._json(200, {"ok": True, "task": task.to_dict(),
                             "message": "已经交给电脑上的助手了"})
            return

        if parsed.path == "/api/stop":
            task_id = str(data.get("task_id") or "").strip()
            if not task_id:
                self._json(400, {"ok": False, "message": "没指名要停哪一条任务"})
                return
            self._json(200, {"ok": True, **self._hub.stop(task_id)})
            return

        self._json(404, {"ok": False, "message": "没有这个地址"})

    @staticmethod
    def _int(query: dict, key: str, default: int) -> int:
        vals = query.get(key) or []
        try:
            return int(vals[0]) if vals else default
        except (ValueError, TypeError):
            return default


class _BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BridgeServer:
    """把 hub + auth 挂到一个后台 HTTP 服务上，可反复开关。"""

    def __init__(self, hub: TaskHub, auth: PairingAuth,
                 host: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self.hub = hub
        self.auth = auth
        self.host = host
        self.port = int(port)
        self._httpd: Optional[_BridgeHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ---- 生命周期 ----
    def start(self) -> int:
        """启动服务，返回实际监听端口（端口被占时自动顺延）。"""
        with self._lock:
            if self._httpd is not None:
                return self.port
            last_err: Optional[Exception] = None
            for candidate in range(self.port, self.port + 20):
                try:
                    httpd = _BridgeHTTPServer((self.host, candidate), _Handler)
                except OSError as e:      # 端口被占：换一个再试
                    last_err = e
                    continue
                httpd.hub = self.hub          # type: ignore[attr-defined]
                httpd.auth = self.auth        # type: ignore[attr-defined]
                self._httpd = httpd
                # 传 0 时由系统分配端口，实际端口以 socket 上的为准
                self.port = httpd.server_address[1]
                self._thread = threading.Thread(
                    target=httpd.serve_forever, name="phone-bridge-http",
                    kwargs={"poll_interval": 0.3}, daemon=True)
                self._thread.start()
                return self.port
            raise OSError(f"端口 {self.port} 附近都被占用了，换个端口再试") from last_err

    def stop(self) -> None:
        with self._lock:
            if self._httpd is None:
                return
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._thread = None

    @property
    def running(self) -> bool:
        return self._httpd is not None
