"""审计日志：每条记录带序号与哈希链（防篡改），按天分片存储为 JSONL。

个人版：写入 %LOCALAPPDATA%/DesktopAgent/logs/audit-YYYYMMDD.jsonl
企业版：只需替换本类的 emit 实现（如批量上报集中审计服务），接口不变。
"""
import hashlib
import json
import os
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
        # 尾部损坏被跳过时置位：下一条新条目带 chain_repaired 标记，不静默
        self._pending_repair = False
        self._resume_chain()
        self._day = None
        self._fh = None
        self._lock = threading.Lock()  # 多任务并行时哈希链必须串行写入

    def _resume_chain(self):
        """同日重启续链：读当天文件逐条验哈希，从最后一条可验证记录接着
        编 seq / 接哈希。否则重启后 seq 重复、链断裂，防篡改就无法区分
        "重启"与"篡改"。

        尾部损坏（解析失败 / 缺字段 / 哈希对不上 / 与前条哈希链脱节）：
        从最后一条可验证记录照常续链，但让下一条新条目带 chain_repaired
        标记——损坏行原样留在文件里，事后审计看得出这里断过。
        """
        path = self.log_dir / f"audit-{time.strftime('%Y%m%d')}.jsonl"
        try:
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            return
        prev_checked = None  # 当天首条的 prev 可能接的是昨日链尾，无法在此验证
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                self._pending_repair = True
                break
            if not isinstance(entry, dict) or "seq" not in entry \
                    or "prev" not in entry or "hash" not in entry \
                    or (prev_checked is not None and entry["prev"] != prev_checked):
                self._pending_repair = True
                break
            check = {k: v for k, v in entry.items() if k != "hash"}
            digest = hashlib.sha256(json.dumps(
                check, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16]
            if digest != entry["hash"]:
                self._pending_repair = True
                break
            prev_checked = entry["hash"]
            self._seq = entry["seq"] + 1
            self._prev_hash = entry["hash"]

    def emit(self, etype: str, **payload):
        """记录一条审计事件。etype 如 task_start / tool_call / approval_denied"""
        with self._lock:
            entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": etype}
            entry.update(payload)
            if self._pending_repair:
                entry["chain_repaired"] = True
                self._pending_repair = False
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
            path = self.log_dir / f"audit-{day}.jsonl"
            self._seal_broken_tail(path)
            self._fh = open(path, "a", encoding="utf-8")
        self._fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fh.flush()

    @staticmethod
    def _seal_broken_tail(path: Path):
        """崩溃可能留下没有换行尾的半行：追加前补一个换行，防止新旧 JSON 粘成一行"""
        try:
            if path.exists() and path.stat().st_size > 0:
                with open(path, "rb") as bf:
                    bf.seek(-1, os.SEEK_END)
                    if bf.read(1) != b"\n":
                        with open(path, "a", encoding="utf-8") as seal:
                            seal.write("\n")
        except OSError:
            pass

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None
