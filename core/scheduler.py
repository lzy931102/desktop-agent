"""定时触发：任务按 每天/每周/间隔 三种规则到点执行。

持久化到 scheduled_tasks.json，记录 last_run 时间戳，程序重启后不会重复触发
（这也是不采用 schedule 库的原因：它没有持久化，重启即丢"今天已跑"状态）。
到点回调 on_due(task_dict) 由 GUI 决定如何执行。
"""
import json
import threading
import time
import uuid
from pathlib import Path

from core.paths import data_dir

CHECK_INTERVAL = 15  # 秒


class Scheduler:
    def __init__(self, on_due, file_path: Path = None):
        self.on_due = on_due
        self.path = Path(file_path) if file_path else data_dir() / "scheduled_tasks.json"
        self._stop = threading.Event()
        self._thread = None
        self._fired_this_minute = set()  # (task_id, YYYYMMDDHHMM) 防同分钟重复

    # ---------- 任务管理 ----------
    def load(self) -> list:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []

    def save(self, tasks: list):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def add(self, task: str, stype: str, time_str: str = "",
            weekday: str = "", interval_minutes: int = 0) -> dict:
        rec = {"id": uuid.uuid4().hex[:8], "task": task, "type": stype,
               "time": time_str, "weekday": weekday,
               "interval_minutes": interval_minutes,
               "enabled": True, "last_run": 0, "last_status": ""}
        tasks = self.load()
        tasks.append(rec)
        self.save(tasks)
        return rec

    def remove(self, task_id: str):
        self.save([t for t in self.load() if t["id"] != task_id])

    def set_enabled(self, task_id: str, enabled: bool):
        tasks = self.load()
        for t in tasks:
            if t["id"] == task_id:
                t["enabled"] = enabled
        self.save(tasks)

    def set_last_status(self, task_id: str, status: str):
        tasks = self.load()
        for t in tasks:
            if t["id"] == task_id:
                t["last_status"] = status
                t["last_run"] = time.time()
        self.save(tasks)

    # ---------- 调度 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(CHECK_INTERVAL):
            try:
                self.check_due()
            except Exception:
                continue

    def check_due(self, now=None) -> list:
        """返回本轮到点触发的任务列表"""
        now = now or time.time()
        lt = time.localtime(now)
        stamp = time.strftime("%Y%m%d%H%M", lt)
        weekday = ["monday", "tuesday", "wednesday", "thursday", "friday",
                   "saturday", "sunday"][(lt.tm_wday + 1) % 7]  # tm_wday 周一=0
        hhmm = time.strftime("%H:%M", lt)
        due = []
        tasks = self.load()
        dirty = False
        for t in tasks:
            if not t.get("enabled") or not t.get("task"):
                continue
            if (t["id"], stamp) in self._fired_this_minute:
                continue
            if self._is_due(t, now, hhmm, weekday, stamp):
                self._fired_this_minute.add((t["id"], stamp))
                t["last_run"] = now
                t["last_status"] = "triggered"
                dirty = True
                due.append(t)
        if dirty:
            self.save(tasks)
        for t in due:
            try:
                self.on_due(t)
            except Exception:
                pass
        return due

    @staticmethod
    def _is_due(t: dict, now: float, hhmm: str, weekday: str, stamp: str) -> bool:
        stype = t.get("type")
        if stype == "interval":
            minutes = int(t.get("interval_minutes") or 0)
            return minutes > 0 and now - float(t.get("last_run") or 0) >= minutes * 60
        if t.get("time") != hhmm:
            return False
        if stype == "daily":
            return stamp[:8] != time.strftime("%Y%m%d", time.localtime(float(t.get("last_run") or 0)))
        if stype == "weekly":
            return t.get("weekday", "").lower() == weekday and \
                stamp[:8] != time.strftime("%Y%m%d", time.localtime(float(t.get("last_run") or 0)))
        return False

    @staticmethod
    def describe(t: dict) -> str:
        stype = t.get("type")
        if stype == "daily":
            return f"每天 {t.get('time')}"
        if stype == "weekly":
            names = {"monday": "一", "tuesday": "二", "wednesday": "三", "thursday": "四",
                     "friday": "五", "saturday": "六", "sunday": "日"}
            w = names.get(t.get("weekday", ""), t.get("weekday", ""))
            return f"每周{w} {t.get('time')}"
        if stype == "interval":
            return f"每 {t.get('interval_minutes')} 分钟"
        return stype or ""
