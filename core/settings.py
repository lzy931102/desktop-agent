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
    # 看屏幕（视觉理解）走哪个模型。
    # auto = 配了云端 Key 就用云端，否则回退本机 Ollama 的 qwen-vl。
    # width：送模型前把截图缩到这个宽度。实测 1600 比 1024 准得多
    # （1024 会把界面认成别的软件），且云端耗时仍只有 1~5 秒。
    "vision": {
        "mode": "auto",  # auto | cloud | local
        "cloud_model": "glm-4v-flash",
        "width": 1600,
        "timeout": 45,
    },
    "minimize_to_tray": True,
    "feishu_webhook": "",  # 飞书群自定义机器人 Webhook（电脑↔手机消息通道）
    "plugins": {"disabled": []},  # 停用的插件文件名（不含 .py）；停用的插件不加载不执行
    # 首启引导（UX-P1-6）：""=未引导；"cloud"/"local"=已选路线，不再自动弹；
    # "later"=下次启动仍未连上时再提醒一次；"dismissed"=不再自动弹（徽章仍可唤出）
    "onboarding_choice": "",
    # 邮件远程（mail_remote，任务 18）：手机发邮件遥控电脑。授权码只落本机
    # settings.json（不在代码仓库）；开关不持久化——每次启动手动开启
    "mail_remote": {
        "username": "",
        "auth_code": "",
        "imap_host": "",       # 留空按邮箱域名自动识别（qq/163/gmail/outlook…）
        "smtp_host": "",
        "allowed_senders": "",  # 白名单发件人（逗号/分号分隔），空 = 不受理任何来信
        "poll_seconds": 60,
        "subject_prefix": "[da]",
    },
}

# Agent 单次任务的最大思考-行动轮数上限（REL-P1-3 单一来源：gui 界面展示与
# agent_loop 循环都引用这里，改一处即全局生效）
MAX_TURNS = 10

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

# 各家可用的「看屏幕」视觉模型（DeepSeek 目前没有视觉模型，故不在此表）
VISION_MODEL_PRESETS = {
    "zhipu": "glm-4v-flash",       # 免费、实测 1~5 秒一张屏
    "openai": "gpt-4o-mini",
    "tongyi": "qwen-vl-plus",
}
# 需要「看得更细」时可换的更慢更强的模型（供设置界面选项用）
VISION_MODEL_OPTIONS = ["glm-4v-flash", "glm-4.6v-flash", "glm-4v", "glm-4v-plus"]


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


# ---- 首启引导判定（UX-P1-6）：纯逻辑放 core，脱离 GUI 可回归 ----
ONBOARDING_AUTO_STATES = ("", "later")  # 仅这两种状态允许自动弹出


def cloud_ready(settings) -> bool:
    """云端路径是否已配置好（settings 里存了 Key，或对应环境变量有值）"""
    try:
        key, _ = resolve_api_key(dict(settings.get("cloud", {}) or {}))
    except Exception:
        return False
    return bool(str(key or "").strip())


def should_show_onboarding(settings, connected: bool) -> bool:
    """是否自动弹首启引导卡：没连上 + 云端路径没配好 + 处于可自动弹状态。

    已配好任一模型路径的老用户（云端 Key 就绪）不弹；本地用户 Ollama 正常
    运行时 connected=True 不弹；"later" 只再提醒一次——GUI 弹出前会把状态
    推进为 "dismissed"，这次再关掉就不会有下一次。
    """
    if connected or cloud_ready(settings):
        return False
    return str(settings.get("onboarding_choice", "") or "") in ONBOARDING_AUTO_STATES


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
