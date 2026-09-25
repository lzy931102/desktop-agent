"""应用设置：模型模式（本地/云端/自动）、本地与云端配置、托盘行为等。

凭据策略：API Key 优先从环境变量读取（ZHIPU_API_KEY 等），
GUI 填写的值才落盘到本机 settings.json（%LOCALAPPDATA%，不在代码仓库内）。
"""
import copy
import ipaddress
import json
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from core.paths import data_dir

DEFAULTS = {
    "model_mode": "local",  # "local" | "cloud" | "auto"
    "local": {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5-coder:7b",
    },
    "cloud": {
        "provider": "zhipu",  # zhipu | deepseek | openai | tongyi
        "api_key": "",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "minimize_to_tray": True,
}

# 云端服务商预设与对应的环境变量名
CLOUD_PRESETS = {
    "智谱": {"provider": "zhipu", "base_url": "https://open.bigmodel.cn/api/paas/v4",
             "model": "glm-4-flash", "env": "ZHIPU_API_KEY"},
    "DeepSeek": {"provider": "deepseek", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat", "env": "DEEPSEEK_API_KEY"},
    "OpenAI": {"provider": "openai", "base_url": "https://api.openai.com/v1",
               "model": "gpt-4o-mini", "env": "OPENAI_API_KEY"},
    "通义": {"provider": "tongyi", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "model": "qwen-plus", "env": "DASHSCOPE_API_KEY"},
}

# provider 字符串 → LLMProvider 枚举值（tongyi 走 OpenAI 兼容接口）
PROVIDER_ENUM = {"zhipu": "zhipu", "deepseek": "deepseek", "openai": "openai",
                 "tongyi": "other"}


def resolve_api_key(cloud_cfg: dict) -> tuple:
    """解析云端 API Key，返回 (key, source)。

    优先级：settings.json 里显式保存的值（用户最近配置）> 环境变量（兜底）。
    """
    env_name = next((p["env"] for p in CLOUD_PRESETS.values()
                     if p["provider"] == cloud_cfg.get("provider")), None)
    saved = str(cloud_cfg.get("api_key", "") or "").strip()
    if saved:
        return saved, "settings"
    if env_name and os.environ.get(env_name):
        return os.environ[env_name], "env"
    return "", ""


def validate_public_https(url: str) -> tuple:
    """云端服务地址必须为 https 且解析后不指向内网/环回/保留地址"""
    try:
        p = urlparse(url)
    except ValueError:
        return False, "URL 无效"
    if p.scheme != "https":
        return False, "云端地址必须使用 https"
    host = p.hostname or ""
    if not host:
        return False, "缺少主机名"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # 是域名，继续解析
    else:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            return False, "不允许使用非公网 IP"
        return True, ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False, "无法解析主机名"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_reserved
                or ip.is_link_local or ip.is_multicast or ip.is_unspecified):
            return False, "云端地址解析到了内网/保留地址，已拒绝"
    return True, ""


class Settings:
    def __init__(self, file_path: Path = None):
        self.path = Path(file_path) if file_path else data_dir() / "settings.json"
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                merged = copy.deepcopy(DEFAULTS)
                for k, v in stored.items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k].update(v)
                    else:
                        merged[k] = v
                self._data = merged
            except (ValueError, OSError):
                pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def get(self, key: str, default=None):
        return self._data.get(key, copy.deepcopy(DEFAULTS.get(key, default)))

    def set(self, key: str, value):
        self._data[key] = value
        self.save()
