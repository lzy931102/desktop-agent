"""phone_bridge 接线回归（任务 16）。

覆盖接线前补的三件安全债与接线本身：

- hub.finish 未知状态不再冒充 done（P2-9）：如实落 unknown + 告警事件；
- cloudflared 下载哈希校验（P2-3）：篡改下载源 → 校验失败 → 拒绝落盘；
- GUI 事件回流（PhoneTaskRunner / _phone_forward）：手机任务就是普通
  TaskSession，事件经 hub 让手机端实时可见；
- BridgeServer 本机 HTTP 往返：令牌头鉴权 + no-referrer/no-store 响应头
  + 无令牌引导页（里面引用的「📱 手机连接」面板接线后真实存在）。

本文件不测真隧道（cloudflared 需外网）与真手机，出门链路靠实机验收。
"""
import hashlib
import http.client
import json
import re

import pytest

from phone_bridge import fetcher
from phone_bridge.contract import (EVENT_ERROR, STATE_UNKNOWN,
                                   TERMINAL_STATES)


# ================= hub.finish 未知状态（P2-9） =================

class _Runner:
    """TaskRunner 桩：只记录 submit，便于观察串行调度。"""

    def __init__(self):
        self.submitted = []

    def submit(self, task_id, text):
        self.submitted.append((task_id, text))

    def stop(self, task_id):
        return True


def test_hub_finish_unknown_state_is_not_done():
    """执行方上报认不出的状态 → 落 unknown + 告警事件，绝不冒充 done；
    槽位照常让出、队列里下一条照常拉起。"""
    from phone_bridge.hub import TaskHub

    hub = TaskHub(runner=_Runner())
    t1 = hub.submit("任务一")
    t2 = hub.submit("任务二")                      # 串行：任务二排队
    assert hub.running_task_id == t1.id

    hub.finish(t1.id, "Cancelled")                 # 执行方笔误的状态
    assert t1.state == STATE_UNKNOWN
    assert t1.to_dict()["state_label"] == "状态未知"
    assert any(e.kind == EVENT_ERROR and "已如实标记为未知" in e.text
               for e in t1.events)
    assert hub.running_task_id == t2.id            # 不因状态异常卡死队列


def test_hub_finish_known_states_passthrough():
    """回归：正常终态（done/failed/stopped）行为与修复前完全一致。"""
    from phone_bridge.hub import TaskHub

    assert STATE_UNKNOWN in TERMINAL_STATES
    for state in ("done", "failed", "stopped"):
        hub = TaskHub(runner=_Runner())
        t = hub.submit("任务")
        hub.finish(t.id, state, "结果文本")
        assert t.state == state
        assert t.result == "结果文本"


# ================= cloudflared 下载哈希校验（P2-3） =================

class _FakeResp:
    def __init__(self, data):
        self._data = data
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, data):
        self._data = data

    def open(self, req, timeout=None):
        return _FakeResp(self._data)


def _fake_fetch_env(monkeypatch, tmp_path, data):
    """把下载目标指到 tmp，并把"最小体积"压小，响应体替换为可控字节。"""
    tools = tmp_path / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    dest = tools / "cloudflared.exe"
    monkeypatch.setattr(fetcher, "cloudflared_path", lambda: dest)
    monkeypatch.setattr(fetcher, "CLOUDFLARED_MIN_BYTES", 8)
    monkeypatch.setattr(fetcher, "_opener", lambda: _FakeOpener(data))
    return dest


def test_pinned_constants_shape():
    """锁版本 + 哈希成对维护的底线检查：版本号在 URL 里、哈希是 64 位十六进制。
    升级 cloudflared 时这两个常量必须一起换（取证方式见 fetcher 文件头）。"""
    assert fetcher.CLOUDFLARED_VERSION in fetcher.CLOUDFLARED_URL
    assert "latest" not in fetcher.CLOUDFLARED_URL     # 不用会漂移的 latest 地址
    assert re.fullmatch(r"[0-9a-f]{64}", fetcher.CLOUDFLARED_SHA256)


def test_download_hash_mismatch_rejected(monkeypatch, tmp_path):
    """篡改下载源（内容对不上官方哈希）→ 拒绝落盘、临时文件不残留。"""
    dest = _fake_fetch_env(monkeypatch, tmp_path, b"tampered-bytes-12345678")
    with pytest.raises(fetcher.DownloadError, match="校验不通过"):
        fetcher.download_cloudflared(expected_sha256="0" * 64)
    assert not dest.exists()
    assert list(dest.parent.glob("*.part")) == []


def test_download_hash_match_accepted(monkeypatch, tmp_path):
    """内容与预期哈希一致 → 正常落盘，字节原样。"""
    data = b"legit-cloudflared-bytes-12345678"
    dest = _fake_fetch_env(monkeypatch, tmp_path, data)
    good = hashlib.sha256(data).hexdigest()
    out = fetcher.download_cloudflared(expected_sha256=good)
    assert out == dest
    assert dest.read_bytes() == data


def test_download_undersized_rejected(monkeypatch, tmp_path):
    """明显小于真实组件的响应（错误页/截断）在哈希前就被拒。"""
    tools = tmp_path / "tools2"
    tools.mkdir(parents=True)
    dest = tools / "cloudflared.exe"
    monkeypatch.setattr(fetcher, "cloudflared_path", lambda: dest)
    monkeypatch.setattr(fetcher, "_opener", lambda: _FakeOpener(b"tiny"))
    with pytest.raises(fetcher.DownloadError, match="不完整"):
        fetcher.download_cloudflared(
            expected_sha256=hashlib.sha256(b"tiny").hexdigest())
    assert not dest.exists()


# ================= GUI 接线：事件回流 + 执行方适配 =================

class _HubSpy:
    def __init__(self):
        self.published = []
        self.finished = []

    def publish(self, tid, kind, text):
        self.published.append((tid, kind, text))

    def finish(self, tid, state, result=""):
        self.finished.append((tid, state, result))


class _BridgeSpy:
    def __init__(self):
        self.hub = _HubSpy()


def _bare_gui():
    """AgentGUI.__new__ 绕过 __init__：不建 Tk 窗口，只测状态/回流逻辑。"""
    from gui import AgentGUI

    app = AgentGUI.__new__(AgentGUI)
    app.phone_bridge = _BridgeSpy()
    app._phone_tasks = {}
    return app


def test_gui_phone_forward_maps_events():
    """手机任务的事件按契约回流 hub：日志分类映射、工具事件、终态三形。"""
    from gui import AgentGUI, TaskSession

    app = _bare_gui()
    s = TaskSession("手机回流回归")
    s.phone_task_id = "ph1"
    app._phone_tasks["ph1"] = s
    hub = app.phone_bridge.hub

    AgentGUI._phone_forward(app, s, "log", "── 第 2/10 轮 ──")
    AgentGUI._phone_forward(app, s, "log", "思考用时 1.0 秒（提示 1 token）")
    AgentGUI._phone_forward(app, s, "log", "[拦截] open_app: 测试")
    AgentGUI._phone_forward(app, s, "tool_call", ("open_app", {"app_name": "calc"}))
    AgentGUI._phone_forward(app, s, "tool_result", ("open_app", {}, "opened calc"))
    AgentGUI._phone_forward(app, s, "done", (True, "搞定了", False))

    kinds = [k for _, k, _ in hub.published]
    assert kinds == ["turn", "tool", "tool"]   # 噪声与拦截行不上屏；1 次调用 + 1 个结果
    assert hub.finished == [("ph1", "done", "搞定了")]
    assert "ph1" not in app._phone_tasks               # 终态后解除对照

    # 失败 / 停止 两种终态同样映射到位
    app2 = _bare_gui()
    hub2 = app2.phone_bridge.hub
    s2 = TaskSession("手机回流回归2")
    s2.phone_task_id = "ph2"
    AgentGUI._phone_forward(app2, s2, "done", (False, "出错了", False))
    AgentGUI._phone_forward(app2, s2, "done", (None, "", True))
    assert [(t, st) for t, st, _ in hub2.finished] == [("ph2", "failed"),
                                                       ("ph2", "stopped")]


def test_gui_phone_queued_cancel_reaches_hub():
    """电脑侧取消排队中的手机任务：hub 落 stopped，不会永远挂在执行中。"""
    from gui import AgentGUI, TaskSession

    app = _bare_gui()
    s = TaskSession("手机取消回归")
    s.phone_task_id = "ph9"
    app._phone_tasks["ph9"] = s
    AgentGUI._phone_task_cancelled(app, s)
    assert app.phone_bridge.hub.finished == [("ph9", "stopped", "已在电脑上取消")]


def test_phone_runner_stop_before_start_cancels():
    """hub 派发后、主线程会话落地前收到停止：不建会话，按已取消收场。"""

    class _Root:
        def __init__(self):
            self.pending = []

        def after(self, delay, fn):
            self.pending.append(fn)      # 真主循环稍后执行；测试手动驱动

    class _App:
        def __init__(self):
            self.root = _Root()
            self.phone_bridge = _BridgeSpy()
            self._phone_tasks = {}

    from gui import PhoneTaskRunner

    app = _App()
    runner = PhoneTaskRunner(app)
    runner.stop("p1")                    # 停止请求先登记并排队回调
    assert runner._stop_before_start == {"p1"}
    runner._create_session("p1", "打开记事本")   # 先排队的创建回调先执行
    assert app.phone_bridge.hub.finished == [("p1", "stopped", "还没开始就被叫停了")]
    assert app._phone_tasks == {}        # 没有会话被创建
    runner._stop_session("p1")           # 迟到的停止回调安全落空
    assert app.root.pending              # 两个 after 投递都发生过


# ================= BridgeServer 本机 HTTP 往返 =================

def test_bridge_server_roundtrip_auth_and_headers():
    """真实 HTTP 链路（本机）：令牌头鉴权、安全响应头、无令牌引导页。"""
    from phone_bridge.auth import PairingAuth
    from phone_bridge.hub import TaskHub
    from phone_bridge.server import BridgeServer

    srv = BridgeServer(TaskHub(), PairingAuth(), host="127.0.0.1", port=0)
    port = srv.start()
    try:
        auth = srv.auth

        def _get(path, token=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            headers = {"X-Phone-Token": token} if token is not None else {}
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            return resp, body

        resp, body = _get("/api/ping", auth.token)
        assert resp.status == 200 and json.loads(body)["ok"] is True
        # P2-3 补的安全响应头（令牌防经 Referer/缓存外泄的纵深防御）
        assert resp.getheader("Referrer-Policy") == "no-referrer"
        assert "no-store" in (resp.getheader("Cache-Control") or "")

        resp, _ = _get("/api/ping", "wrong-token")
        assert resp.status == 401        # 错令牌拒绝（限速由 auth 层计数）

        resp, body = _get("/", auth.token)
        assert resp.status == 200        # 带令牌返回手机端页面
        assert "桌面助手".encode("utf-8") in body

        resp, body = _get("/", None)
        assert resp.status == 200        # 无令牌不给 401 裸页，给引导页
        assert "手机连接".encode("utf-8") in body
    finally:
        srv.stop()
