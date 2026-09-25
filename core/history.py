"""任务历史：每次任务落一条记录（JSONL），支持回看最近任务。

个人版：本地 %LOCALAPPDATA%/DesktopAgent/history.jsonl
企业版：替换为数据库/服务端实现，接口不变。
"""
import json
import threading
import time
import uuid
from pathlib import Path

from core.paths import data_dir


class TaskHistory:
    def __init__(self, file_path: Path = None):
        self.path = Path(file_path) if file_path else data_dir() / "history.jsonl"
        self._lock = threading.Lock()  # 多任务并行收尾时防止并发改写丢记录

    def start(self, task: str) -> str:
        rec = {"id": uuid.uuid4().hex[:8], "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
               "task": task, "status": "running"}
        self._append(rec)
        return rec["id"]

    def end(self, task_id: str, status: str, result: str = "", turns: int = 0,
            elapsed_s: float = 0.0):
        with self._lock:
            recs = self._read_all()
            for r in reversed(recs):
                if r.get("id") == task_id:
                    r["status"] = status
                    r["result"] = (result or "")[:200]
                    r["turns"] = turns
                    r["elapsed_s"] = round(elapsed_s, 1)
                    r["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    break
            self.path.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                encoding="utf-8")

    def recent(self, limit: int = 50) -> list:
        return list(reversed(self._read_all()))[:limit]

    def _append(self, rec: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _read_all(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
