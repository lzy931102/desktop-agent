"""数据目录：exe 可能被装在只读目录，数据一律放 %LOCALAPPDATA%/DesktopAgent"""
import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "DesktopAgent"
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d
