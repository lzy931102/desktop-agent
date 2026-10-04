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


def heartbeat_path() -> Path:
    return data_dir() / "logs" / f"heartbeat-{time.strftime('%Y%m%d')}.log"


def heartbeat(note: str = "") -> None:
    """UI 心跳（卡死取证）：主线程定期一拍，独立日志一行一条。

    2026-10-04 一次无痕冻结（任务全部正常收尾后 UI 卡死，黑匣子/审计/
    Windows 事件三处零记录）立项：主线程冻结时 after 调度即停，心跳断档，
    起点可精确到 30 秒内。与 write() 分文件——心跳高频（30 秒一拍），
    不灌进异常黑匣子。写失败必须静默，绝不能反噬主循环。
    """
    try:
        with _lock:
            p = heartbeat_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y-%m-%d %H:%M:%S')
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{stamp} {note}\n" if note else f"{stamp}\n")
    except Exception:
        pass


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
