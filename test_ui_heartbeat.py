"""T30 UI 心跳（卡死取证）回归测试。

背景：2026-10-04 任务全部正常收尾后界面无痕冻结，黑匣子/审计链/Windows
事件三处零记录，事后无法定位。立规：主线程 30 秒一拍写独立心跳日志，
冻结即断档，起点可精确到 30 秒内。两条红线：
  1. 心跳写失败必须静默（取证功能绝不能反噬主循环）
  2. after 续链必须无条件执行（泵永不脱链，同 T23 理念）
"""
import time

import pytest

from core import blackbox


class FakeRoot:
    def __init__(self):
        self.after_calls = []

    def after(self, ms, fn):
        self.after_calls.append((ms, fn))


def _hb_file(tmp_path):
    name = f"heartbeat-{time.strftime('%Y%m%d')}.log"
    return tmp_path / "logs" / name


def test_heartbeat_appends_one_line_per_call(tmp_path, monkeypatch):
    """blackbox.heartbeat 独立文件一行一拍；不污染异常黑匣子 gui-*.log"""
    monkeypatch.setattr(blackbox, "data_dir", lambda: tmp_path)
    blackbox.heartbeat()
    blackbox.heartbeat("start pid=1 seq=0")
    lines = _hb_file(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith(time.strftime("%H:%M:%S"))   # 纯时间戳行
    assert "start pid=1 seq=0" in lines[1]
    assert not (tmp_path / "logs" / f"gui-{time.strftime('%Y%m%d')}.log").exists()


def test_heartbeat_write_failure_is_silent(tmp_path, monkeypatch):
    """目标不可写时静默（取证功能不能反噬应用），恢复后照常写"""
    monkeypatch.setattr(blackbox, "data_dir", lambda: tmp_path)
    real_open = open

    def broken_open(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", broken_open)
    blackbox.heartbeat()   # 不应抛
    monkeypatch.setattr("builtins.open", real_open)
    blackbox.heartbeat("recovered")   # 恢复后照常写
    assert "recovered" in _hb_file(tmp_path).read_text(encoding="utf-8")


def test_gui_heartbeat_writes_and_reschedules(tmp_path):
    """gui._ui_heartbeat：首拍带 start 标记，之后 seq 递增；after 续链 30s"""
    import gui
    app = gui.AgentGUI.__new__(gui.AgentGUI)
    app.root = FakeRoot()
    app._hb_seq = 0
    app._ui_heartbeat()
    app._ui_heartbeat()
    text = _hb_file(tmp_path).read_text(encoding="utf-8")
    assert "start pid=" in text and "seq=0" in text and "seq=1" in text
    assert app._hb_seq == 2
    assert app.root.after_calls[-1] == (30_000, app._ui_heartbeat)


def test_gui_heartbeat_survives_blackbox_failure(tmp_path, monkeypatch):
    """blackbox 打爆后主循环续链仍在（红线 2）"""
    import gui
    app = gui.AgentGUI.__new__(gui.AgentGUI)
    app.root = FakeRoot()
    app._hb_seq = 5
    monkeypatch.setattr(blackbox, "heartbeat",
                        lambda note="": (_ for _ in ()).throw(OSError("x")))
    app._ui_heartbeat()   # 不应抛
    assert app.root.after_calls[-1] == (30_000, app._ui_heartbeat)
