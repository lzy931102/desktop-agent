# conftest.py — 全量测试统一数据隔离（T28）。
# 泵防崩等用例故意注入的渲染异常会经 blackbox.write 落盘；不重定向时，
# 故障注入堆栈会写进用户真实的 %LOCALAPPDATA%\DesktopAgent 黑匣子日志
# （2026-10-04 07:09/07:10/07:18 三段噪音实录）。这里 autouse 一次解决
# 所有用例：黑匣子目录指到 pytest 每条用例独立的临时目录。
import pytest

from core import blackbox


@pytest.fixture(autouse=True)
def _isolate_blackbox(tmp_path, monkeypatch):
    monkeypatch.setattr(blackbox, "data_dir", lambda: tmp_path)
