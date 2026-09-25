"""审计日志：每条记录带序号与哈希链（防篡改），按天分片存储为 JSONL。

个人版：写入 %LOCALAPPDATA%/DesktopAgent/logs/audit-YYYYMMDD.jsonl
企业版：只需替换本类的 emit 实现（如批量上报集中审计服务），接口不变。
"""
import hashlib
import json
import threading
import time
from pathlib import Path

from core.paths import data_dir


class AuditLogger:
    def __init__(self, log_dir: Path = None):
        self.log_dir = Path(log_dir) if log_dir else data_dir() / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._prev_hash = ""
        self._day = None
        self._fh = None
        self._lock = threading.Lock()  # 多任务并行时哈希链必须串行写入

    def emit(self, etype: str, **payload):
        """记录一条审计事件。etype 如 task_start / tool_call / approval_denied"""
        with self._lock:
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": etype}
            entry.update(payload)
            entry["seq"] = self._seq
            entry["prev"] = self._prev_hash
            entry["hash"] = hashlib.sha256(
                json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16]
            try:
                self._write(entry)
            except OSError:
                return  # 审计写失败不阻断任务执行
            self._seq += 1
            self._prev_hash = entry["hash"]

    def _write(self, entry: dict):
        day = time.strftime("%Y%m%d")
        if self._fh is None or day != self._day:
            if self._fh:
                self._fh.close()
            self._day = day
            self._fh = open(self.log_dir / f"audit-{day}.jsonl", "a", encoding="utf-8")
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None
