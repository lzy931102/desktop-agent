"""T21 单实例锁回归测试。

测 gui.ensure_single_instance 的锁语义：
  1. 首次调用返回 True（允许启动）
  2. 同名第二次调用返回 False（判定已有实例，拒绝启动；传不存在的窗口标题，
     保证测试绝不碰用户在跑的真实窗口——docs/踩坑.md #3 环境干扰）
  3. 非 Windows 平台恒放行
  4. Mutex 完全不可用时降级为放行启动（锁绝不阻塞启动）
锁名按进程号取独立值，避免与真实 DesktopAgent 实例或其他测试进程互撞。
"""
import ctypes
import os

import gui


def test_second_call_is_rejected():
    name = f"DesktopAgent_T21Test_{os.getpid()}"
    assert gui.ensure_single_instance(app_name=name,
                                      window_title="T21测试-不存在的窗口") is True
    assert gui.ensure_single_instance(app_name=name,
                                      window_title="T21测试-不存在的窗口") is False


def test_non_windows_platform_allows_start(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert gui.ensure_single_instance(app_name="DesktopAgent_T21Test_posix") is True


def test_mutex_unavailable_degrades_to_start(monkeypatch):
    class _Denied:
        def __init__(self, *a, **k):
            pass

        @staticmethod
        def CreateMutexW(*a, **k):
            ctypes.set_last_error(5)  # ERROR_ACCESS_DENIED
            return None

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: _Denied())
    assert gui.ensure_single_instance(app_name="DesktopAgent_T21Test_denied") is True
