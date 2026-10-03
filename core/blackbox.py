"""界面/线程黑匣子（T23）：窗口版 exe 丢弃 stderr，崩溃堆栈无处可寻。

write() 把诊断分节追加到 data_dir/logs/gui-YYYYMMDD.log。
gui 启动时把 stdout/stderr 重定向到这里，Tk 回调异常与
threading.excepthook 也走这里；任务线程生命周期（sessions）同样留痕。
"""
import threading
import time
from pathlib import Path

from core.paths import data_dir

_lock = threading.Lock()


def path() -> Path:
    return data_dir() / "logs" / f"gui-{time.strftime('%Y%m%d')}.log"


def write(title: str, body: str = "") -> None:
    """追加一节诊断记录。写失败必须静默——黑匣子绝不能反过来弄崩应用。"""
    try:
        with _lock:
            p = path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} "
                        f"{title} =====\n")
                if body:
                    f.write(body.rstrip() + "\n")
    except Exception:
        pass
