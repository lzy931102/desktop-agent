"""T23 界面韧性回归测试（卡死/僵尸会话/黑匣子）。

三个病灶，全部离线（不启动真 GUI、不连模型）：
  1. _pump 泵防崩：单条事件渲染失败只丢这一条，剩余事件照常消费，
     且 root.after(120, _pump) 续链无条件执行（泵永不脱链）
  2. 任务线程任何退出路径都保证 done 终态：正常/异常/ BaseException
     （SystemExit 等 except Exception 接不住的）/ 线程已死后的僵尸 stop
  3. 黑匣子：写失败不反噬（黑匣子绝不能反过来弄崩应用）
"""
import queue
import threading
import time
from pathlib import Path

import pytest

import gui
import ui.sessions as sessions_mod
from core import blackbox
from ui.formatters import _effective_max_turns
from ui.sessions import TaskSession


# ==================== 桩 ====================

class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))


class FakeBar:
    def set(self, v):
        pass


class FakeApproval:
    def pending(self):
        return None


def make_agent_shell(sessions, active=None):
    """跳过 AgentGUI.__init__（不建真 Tk），只铺 _pump 触碰到的属性"""
    app = gui.AgentGUI.__new__(gui.AgentGUI)
    app.sessions = sessions
    app.active = active
    app.root = FakeRoot()
    app.status_bar = FakeBar()
    app.settings = {}
    app._tabs_dirty = False
    app._sidebar_dirty = False
    app._bar_t = 0.0
    app._logbox = None
    return app


def make_session(events, status="done"):
    s = TaskSession(title="测试")
    s.status = status
    s.approval = FakeApproval()
    for ev in events:
        s.ui_queue.put(ev)
    return s


# ==================== 1. 泵防崩 ====================

def test_pump_survives_bad_event_and_reschedules(monkeypatch):
    s = make_session([
        ("log", "第一条"),
        ("boom", None),      # 这条渲染会炸
        ("log", "第三条"),
    ])
    app = make_agent_shell({s.id: s})

    real_apply = gui.AgentGUI._apply

    def flaky_apply(self, s, kind, payload):
        if kind == "boom":
            raise RuntimeError("渲染炸了")
        real_apply(self, s, kind, payload)

    monkeypatch.setattr(gui.AgentGUI, "_apply", flaky_apply)
    app._pump()

    assert s.ui_queue.empty()            # 炸掉的那条没堵住后两条
    assert app.root.after_calls == [(120, app._pump)]  # 续链无条件执行


def test_pump_survives_body_crash_and_reschedules(monkeypatch):
    """_pump 主体任何一段炸掉（如审批段），续链仍在 finally 里执行"""
    s = make_session([], status="running")
    app = make_agent_shell({s.id: s}, active=s)
    monkeypatch.setattr(gui.AgentGUI, "_launch_next_queued",
                        lambda self: (_ for _ in ()).throw(RuntimeError("炸")))
    app._pump()
    assert app.root.after_calls == [(120, app._pump)]


# ==================== 2. 线程终态保证 ====================

def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def test_normal_run_delivers_done_exactly_once(monkeypatch):
    class FakeLLM:
        pass

    class FakeAgent:
        total_tokens = 0

        def run(self, text):
            return "做完了"

    monkeypatch.setattr(sessions_mod, "build_llm_client", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(sessions_mod, "DesktopAgent", lambda *a, **k: FakeAgent())

    s = TaskSession(title="正常")
    s.task_text = "测试"
    s._run(_FakeApp())
    dones = [ev for ev in _drain(s.ui_queue) if ev[0] == "done"]
    assert len(dones) == 1
    assert dones[0][1][0] is True        # ok
    assert dones[0][1][1] == "做完了"


def test_base_exception_still_delivers_done(monkeypatch):
    """SystemExit 等 except Exception 接不住的异常：finally 必须兜底落终态"""

    class FakeLLM:
        pass

    class FakeAgent:
        total_tokens = 0

        def run(self, text):
            raise SystemExit("引擎线程被带走")

    monkeypatch.setattr(sessions_mod, "build_llm_client", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(sessions_mod, "DesktopAgent", lambda *a, **k: FakeAgent())

    s = TaskSession(title="僵尸")
    s.task_text = "测试"
    # SystemExit 设计上继续向上传（threading.excepthook 会把它写进黑匣子），
    # 但 done 终态必须先由 finally 兜底发出
    with pytest.raises(SystemExit):
        s._run(_FakeApp())
    dones = [ev for ev in _drain(s.ui_queue) if ev[0] == "done"]
    assert len(dones) == 1
    assert dones[0][1][0] is False
    assert "意外退出" in dones[0][1][1]


class _FakeApp:
    """TaskSession._run 需要的最小 app 形状（build_llm_client 已被替换）"""
    settings = {}
    audit = None
    history = None


def test_zombie_stop_emits_done():
    """线程已死、done 丢失的僵尸会话：stop() 直接给界面终态，停止不再空等"""
    s = TaskSession(title="僵尸会话")
    s.status = "running"
    monkey_thread = threading.Thread(target=lambda: None)
    monkey_thread.start()
    monkey_thread.join()
    s._thread = monkey_thread            # 线程已结束
    s.agent = None                       # 引擎都没建起来就死了
    s.stop()
    dones = [ev for ev in _drain(s.ui_queue) if ev[0] == "done"]
    assert len(dones) == 1
    assert dones[0][1][0] is False


def test_stop_with_live_agent_does_not_emit_done():
    """对照：线程活着、agent 在跑时，stop 只设标志，不发假终态"""
    s = TaskSession(title="在跑")
    s.status = "running"
    gate = threading.Event()
    s._thread = threading.Thread(target=gate.wait, daemon=True)
    s._thread.start()
    s.agent = type("A", (), {"stop": lambda self: None})()
    try:
        s.stop()
        assert _drain(s.ui_queue) == []
    finally:
        gate.set()


# ==================== 3. 黑匣子 ====================

def test_blackbox_write_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(blackbox, "data_dir", lambda: tmp_path)
    blackbox.write("标题A", "内容行")
    blackbox.write("标题B")
    log = (tmp_path / "logs" / blackbox.path().name).read_text(encoding="utf-8")
    assert "标题A" in log and "内容行" in log and "标题B" in log


def test_blackbox_write_failure_is_silent(tmp_path, monkeypatch):
    """黑匣子写失败（磁盘满/权限）绝不能反过来弄崩应用"""
    monkeypatch.setattr(blackbox, "data_dir",
                        lambda: (_ for _ in ()).throw(OSError("盘满")))
    blackbox.write("不该抛")  # 不抛即通过


def test_task_stage_logged_to_blackbox(tmp_path, monkeypatch):
    """任务线程生命周期进黑匣子：run-enter / run-exit 可查"""
    monkeypatch.setattr(blackbox, "data_dir", lambda: tmp_path)

    class FakeLLM:
        pass

    class FakeAgent:
        total_tokens = 0

        def run(self, text):
            return "好"

    monkeypatch.setattr(sessions_mod, "build_llm_client", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(sessions_mod, "DesktopAgent", lambda *a, **k: FakeAgent())
    s = TaskSession(title="留痕")
    s.task_text = "测试"
    s._run(_FakeApp())
    time.sleep(0.05)
    log = (tmp_path / "logs" / blackbox.path().name).read_text(encoding="utf-8")
    assert "run-enter" in log and "run-exit" in log


# ==================== 4. 拆分包名称完整性 ====================

def test_no_undefined_names_in_ui_modules():
    """T4 拆分包漏导入回归：ERR 缺失让每条系统气泡渲染必崩（T23 黑匣子
    2026-10-03 捕获）。pyflakes 的 undefined name（F821）在 ui/ 与 gui.py
    必须为零——pyflakes 能正确处理函数内局部导入，不误报。"""
    import io

    from pyflakes.api import check
    from pyflakes.reporter import Reporter

    root = Path(sessions_mod.__file__).parent.parent
    files = sorted(p for p in (root / "ui").rglob("*.py")
                   if "__init__" not in p.name) + [root / "gui.py"]
    out = io.StringIO()
    for p in files:
        # 自己按 utf-8 读源码再喂给 pyflakes：api.check 的第一参数是源码
        # 字符串（不是文件列表），且显式读入可绕开它的编码探测歧义
        check(p.read_text(encoding="utf-8"), str(p), Reporter(out, out))
    bad = [line for line in out.getvalue().splitlines()
           if "undefined name" in line]
    assert bad == [], "存在未定义名引用（拆分漏导入）:\n" + "\n".join(bad)


# ==================== 5. _apply_log 轮次渲染（T4 拆分残留回归） ====================

class _FakeLogbox:
    """记录 _log_line 写入的行，模拟滚动日志区"""

    def __init__(self):
        self.lines = []

    def configure(self, **kw):
        pass

    def insert(self, pos, text):
        self.lines.append(text)

    def see(self, pos):
        pass


class _FakeChat:
    def append(self, ev):
        pass

    def refresh(self, ev):
        pass

    def render_all(self, s):
        pass


def test_t23_apply_log_no_app_attribute():
    """T4 拆分残留回归：_apply_log 的 turn 分支曾引用不存在的 self.app
    （gui.py:610 写成 self.app.settings），每条"第 N 轮"日志事件必抛
    AttributeError；被事件泵兜住不崩，但日志区画不出"—— 第 N 轮 ——"、
    状态条/侧栏轮次停更（黑匣子 gui-20261004.log 2026-10-04 06:09 捕获）。
    修复为 self.settings 后，本用例锁定三处可见状态：
    不再抛异常、轮次计数/状态条文案更新、日志行真实写入。"""
    s = make_session([], status="running")
    app = make_agent_shell({s.id: s}, active=s)
    app.logbox = _FakeLogbox()
    app.chat = _FakeChat()

    # 原始格式与 agent_loop.py:1631 上报一致（parse_log strip 后命中 "── 第"）
    app._apply_log(s, "\n── 第 3/30 轮 ──")   # 旧代码在此抛 AttributeError

    assert s.turn == 3
    assert s.current_action == \
        f"🧠 第 3/{_effective_max_turns(app.settings)} 轮思考中…"
    assert "—— 第 3 轮 ——" in "".join(app.logbox.lines)   # 日志区画出来了
    assert s.log_lines and "—— 第 3 轮 ——" in s.log_lines[-1]
