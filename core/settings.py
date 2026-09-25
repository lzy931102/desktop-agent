"""应用设置：模型选择、托盘行为等，持久化到 settings.json。"""
import json
from pathlib import Path

from core.paths import data_dir

DEFAULTS = {
    "model": "qwen2.5-coder:7b",
    "minimize_to_tray": True,
}


class Settings:
    def __init__(self, file_path: Path = None):
        self.path = Path(file_path) if file_path else data_dir() / "settings.json"
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self._data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value):
        self._data[key] = value
        self.save()
