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


# ---- Tk 渲染测试共享唯一解释器（T30 补） ----
# 同一进程反复创建/销毁 Tk 解释器不稳定（2026-10-04 实测：全量跑时第二个
# 解释器建到一半 init.tcl source 失败 "Can't find a usable init.tcl"，
# 单文件跑又正常——纯 flaky）。session 级单例：一次创建、会话末销毁、
# 销毁失败静默（teardown 噪音不影响断言）。
@pytest.fixture(scope="session")
def ctk_root():
    ctk = pytest.importorskip("customtkinter")
    root = ctk.CTk()
    root.withdraw()
    yield ctk, root
    try:
        root.destroy()
    except Exception:
        pass
