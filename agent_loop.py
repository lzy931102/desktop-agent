import os
import json
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

import requests

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # 仅使用 OpenAI 兼容云端服务时需要；本地 Ollama 模式不需要

import pyautogui
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

import agent_vision
from agent_vision import (
    analyze_screen,
    list_visible_windows as _list_windows_impl,
    focus_window as _focus_window_impl,
    list_ui_elements as _list_ui_elements_impl,
    click_ui_element as _click_ui_element_impl,
    clipboard_read as _clipboard_read_impl,
    clipboard_write as _clipboard_write_impl,
)
from core import guard
from core import verify as core_verify
from core.approval import AutoDenyPolicy
from core.audit import AuditLogger
from core.feishu import send_feishu_message as _feishu_send
from core.history import TaskHistory
from core.retry import run_with_retry
from core.settings import PROVIDER_ENUM, Settings, resolve_api_key, validate_public_https
from core.verify import check_message_sent


def _send_feishu_impl(text: str) -> str:
    """发飞书群消息的 Agent 工具实现：webhook 取自本机设置"""
    ok, detail = _feishu_send(text, Settings().get("feishu_webhook", ""))
    return f"已发送到飞书群（{detail}）：{text}" if ok else f"错误: {detail}"


class LLMProvider(Enum):
    OPENAI = "openai"
    ZHIPU = "zhipu"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    OTHER = "other"


@dataclass
class LLMConfig:
    provider: LLMProvider
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.1


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = self._create_client()

    def _create_client(self):
        if self.config.provider == LLMProvider.OLLAMA:
            return None
        if OpenAI is None:
            raise RuntimeError("未安装 openai 库，无法使用云端模型；请改用本地 Ollama 模式")
        return OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url or self._default_base_url()
        )

    def _default_base_url(self) -> str:
        urls = {
            LLMProvider.OPENAI: "https://api.openai.com/v1",
            LLMProvider.ZHIPU: "https://open.bigmodel.cn/api/paas/v4",
            LLMProvider.DEEPSEEK: "https://api.deepseek.com/v1",
        }
        return urls.get(self.config.provider, "https://api.openai.com/v1")

    def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        if self.config.provider == LLMProvider.OLLAMA:
            return self._chat_ollama(messages, tools)
        return self._chat_openai_compatible(messages, tools)

    def _chat_openai_compatible(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        return {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in (msg.tool_calls or [])
            ]
        }

    def list_models(self) -> list:
        """列出 Ollama 上可用的模型名（仅 OLLAMA provider）"""
        if self.config.provider != LLMProvider.OLLAMA:
            return []
        base = self.config.base_url or "http://localhost:11434"
        if not base.startswith(("http://", "https://")):
            return []
        try:
            session = requests.Session()
            session.trust_env = False
            r = session.get(f"{base}/api/tags", timeout=5)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
        except Exception:
            return []

    def ping(self) -> tuple:
        """云端连通性测试：发一次最小对话请求，返回 (ok, 描述)"""
        if self.config.provider == LLMProvider.OLLAMA:
            return self.check_connection()
        if not self.config.api_key:
            return False, "未配置 API Key"
        ok, why = validate_public_https(self.config.base_url)
        if not ok:
            return False, why
        try:
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=4,
            )
            return True, f"已连通（模型 {resp.model or self.config.model}）"
        except Exception as e:
            return False, str(e)[:150]

    def list_models(self) -> list:
        """列出 Ollama 上可用的模型名（仅 OLLAMA provider）"""
        if self.config.provider != LLMProvider.OLLAMA:
            return []
        base = self.config.base_url or "http://localhost:11434"
        if not base.startswith(("http://", "https://")):
            return []
        try:
            session = requests.Session()
            session.trust_env = False
            r = session.get(f"{base}/api/tags", timeout=5)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
        except Exception:
            return []

    def check_connection(self) -> tuple:
        """检查 LLM 服务是否可用，返回 (ok, 描述信息)。Ollama 查 /api/tags，
        OpenAI 兼容服务查 /models。仅允许 http/https。"""
        base = self.config.base_url or self._default_base_url()
        if not base.startswith(("http://", "https://")):
            return False, "地址必须是 http/https"
        try:
            if self.config.provider == LLMProvider.OLLAMA:
                session = requests.Session()
                session.trust_env = False
                r = session.get(f"{base}/api/tags", timeout=4)
                r.raise_for_status()
                models = [m.get("name", "") for m in r.json().get("models", [])]
                model = self.config.model
                if model and not any(m == model or m.split(":")[0] == model for m in models):
                    return False, f"已连接，但找不到模型 {model}"
                return True, "已连接"
            r = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {self.config.api_key}"}, timeout=6)
            r.raise_for_status()
            return True, "已连接"
        except Exception as e:
            return False, str(e)[:120]

    def _normalize_messages_for_ollama(self, messages: List[Dict]) -> List[Dict]:
        """Ollama 的 peg-native 引擎用 GGUF 内嵌模板渲染消息历史，而 GGUF 导入模型的
        内嵌模板普遍缺 tool 段，导致 tool 角色消息渲染 400。这里把 tool 协议降级为
        纯文本对话（工具调用与结果都以文本形式出现在 user/assistant 消息中），
        self.messages 中的结构化消息不受影响。"""
        norm = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                content = m.get("content", "")
                if isinstance(content, list):
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                prev = norm[-1] if norm else None
                if prev and prev.get("role") == "user" and str(prev.get("content", "")).startswith("[工具结果]"):
                    prev["content"] += "\n[工具结果] " + str(content)
                else:
                    norm.append({"role": "user", "content": "[工具结果] " + str(content)})
            elif role == "assistant" and m.get("tool_calls"):
                parts = []
                if m.get("content"):
                    parts.append(str(m["content"]))
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    parts.append("[已调用工具] {0}({1})".format(fn.get("name", ""), fn.get("arguments", "")))
                norm.append({"role": "assistant", "content": "\n".join(parts)})
            else:
                norm.append(dict(m))
        return norm

    def _chat_ollama(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        url = f"{self.config.base_url or 'http://localhost:11434'}/api/chat"
        payload = {
            "model": self.config.model,
            "messages": self._normalize_messages_for_ollama(messages),
            "stream": False,
            "options": {"temperature": self.config.temperature}
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t["function"]} for t in tools]
        # 本地服务：trust_env=False 跳过环境变量与系统代理，避免 FastGithub 等代理残留劫持 localhost 请求
        session = requests.Session()
        session.trust_env = False
        r = session.post(url, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []
        # 兼容层：GGUF 导入的模型常把工具调用输出为文本（```json {...}``` 或
        # <tool_call>{...}</tool_call>），Ollama 解析不出结构化 tool_calls 时在客户端提取
        if not tool_calls and content:
            parsed = _extract_tool_call_from_text(content)
            if parsed:
                tool_calls = [parsed]
                content = ""
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls
        }


class FallbackLLMClient:
    """auto 模式：先走本地 Ollama，任何异常自动切换云端重试一次"""

    def __init__(self, local: LLMClient, cloud: LLMClient,
                 on_fallback=None):
        self.local = local
        self.cloud = cloud
        self.on_fallback = on_fallback  # 回调：on_fallback(error) 切换时通知界面
        self.config = local.config

    def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
        try:
            return self.local.chat(messages, tools)
        except Exception as local_err:
            if self.on_fallback:
                try:
                    self.on_fallback(str(local_err))
                except Exception:
                    pass
            try:
                return self.cloud.chat(messages, tools)
            except Exception as cloud_err:
                raise RuntimeError(
                    f"本地与云端模型均调用失败。本地: {local_err}；云端: {cloud_err}"
                ) from cloud_err

    def check_connection(self) -> tuple:
        ok_local, msg_local = self.local.check_connection()
        ok_cloud, msg_cloud = self.cloud.ping()
        if ok_local or ok_cloud:
            parts = []
            if ok_local:
                parts.append(f"本地可用")
            if ok_cloud:
                parts.append(f"云端可用")
            return True, "，".join(parts)
        return False, f"本地: {msg_local}；云端: {msg_cloud}"


def build_llm_client(settings, on_fallback=None):
    """按 model_mode 构造 LLM 客户端：local / cloud / auto（本地失败切云端）"""
    mode = settings.get("model_mode", "local")
    local_cfg_dict = settings.get("local", {})
    local_client = LLMClient(LLMConfig(
        provider=LLMProvider.OLLAMA,
        base_url=local_cfg_dict.get("base_url", "http://localhost:11434"),
        model=local_cfg_dict.get("model", "qwen2.5-coder:7b"),
        temperature=0.1,
    ))
    if mode == "local":
        return local_client

    cloud_cfg_dict = dict(settings.get("cloud", {}))
    cloud_cfg_dict["api_key"], _key_src = resolve_api_key(cloud_cfg_dict)
    provider_value = PROVIDER_ENUM.get(cloud_cfg_dict.get("provider", "zhipu"), "other")
    if not cloud_cfg_dict["api_key"]:
        if mode == "cloud":
            raise RuntimeError("云端 API Key 未配置：请在设置中填写，或设置对应的环境变量")
        return local_client  # auto 模式静默降级为纯本地
    cloud_client = LLMClient(LLMConfig(
        provider=LLMProvider(provider_value),
        api_key=cloud_cfg_dict["api_key"],
        base_url=cloud_cfg_dict.get("base_url", ""),
        model=cloud_cfg_dict.get("model", ""),
        temperature=0.1,
    ))
    if mode == "cloud":
        return cloud_client
    return FallbackLLMClient(local_client, cloud_client, on_fallback=on_fallback)


def _extract_tool_call_from_text(text: str) -> Optional[Dict]:
    """从模型文本输出中提取工具调用，兼容两种常见格式：
    1. <tool_call>{"name": ..., "arguments": {...}}</tool_call>
    2. ```json {"name": ..., "arguments": {...}} ```
    没有工具调用时返回 None。
    """
    import re
    raw = None
    m = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', text, re.S)
    if m:
        raw = m.group(1)
    else:
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
        if m:
            raw = m.group(1)
        else:
            t = text.strip()
            if t.startswith('{') and t.endswith('}'):
                raw = t
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    name = obj.get("name")
    if not isinstance(name, str) or not name or "arguments" not in obj:
        return None
    args = obj["arguments"]
    if isinstance(args, dict):
        args = json.dumps(args, ensure_ascii=False)
    return {"function": {"name": name, "arguments": args}}


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "点击屏幕坐标",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X坐标"},
                    "y": {"type": "integer", "description": "Y坐标"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "clicks": {"type": "integer", "default": 1}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "在光标位置输入文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文本"},
                    "interval": {"type": "number", "default": 0.05}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "按下按键",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名，如 enter, esc, tab, ctrl, alt, shift, win, up, down, left, right"},
                    "presses": {"type": "integer", "default": 1}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hotkey",
            "description": "组合键",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "按键列表，如 ['ctrl', 'c']"}
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_to",
            "description": "移动鼠标到坐标",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "duration": {"type": "number", "default": 0.5}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "滚动鼠标滚轮",
            "parameters": {
                "type": "object",
                "properties": {
                    "clicks": {"type": "integer", "description": "正数向上，负数向下"}
                },
                "required": ["clicks"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "截图保存",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "screenshot.png"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "locate_on_screen",
            "description": "在屏幕上查找图片（模板匹配），返回中心坐标",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "图片路径，需在脚本目录下"},
                    "confidence": {"type": "number", "default": 0.8}
                },
                "required": ["image_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "等待秒数",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number", "default": 1}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "通过Win+R打开应用",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "应用名称，如 notepad, calc, cmd, explorer"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_screen",
            "description": "看一眼当前屏幕并回答问题（视觉分析，约30秒）。适用于：了解屏幕上有什么、某应用是否打开、界面当前处于什么状态。只回答内容，不返回坐标",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "想了解的问题，如：屏幕上有哪些应用窗口？记事本现在是空白还是有文字？"}
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_windows",
            "description": "列出当前所有可见窗口的标题、位置和活动状态",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "把指定标题的窗口切到前台（标题模糊匹配）",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "窗口标题的一部分，如：记事本"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_ui_elements",
            "description": "列出窗口内可操作控件（按钮/菜单/输入框）及其精确坐标。这是了解一个应用能做什么的最可靠方式，推荐在点击前先列出",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_title": {"type": "string", "description": "窗口标题的一部分；不填则用当前活动窗口"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_ui_element",
            "description": "按名称点击窗口内的控件（菜单项/按钮等），最可靠的点击方式。点击前建议先用 list_ui_elements 查看控件名称",
            "parameters": {
                "type": "object",
                "properties": {
                    "window_title": {"type": "string", "description": "窗口标题的一部分；不填则用当前活动窗口"},
                    "name": {"type": "string", "description": "控件名称，如：格式(O)、保存"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_read",
            "description": "读取剪贴板里的文本内容",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_write",
            "description": "把文本写入剪贴板（之后可用 ctrl+v 粘贴）",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要写入的文本"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "verify_message_sent",
            "description": "发送消息类任务（微信/QQ/邮件等）发送后必须调用：用视觉确认消息是否真的出现在聊天窗口。返回 sent（已确认发出）/ unclear（无法确认）/ failed（确认未发出）",
            "parameters": {
                "type": "object",
                "properties": {
                    "expected_text": {"type": "string", "description": "你刚发送的消息原文"}
                },
                "required": ["expected_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_feishu_message",
            "description": "把一条文本消息发到用户的飞书群（手机和电脑同步可见）。凡是涉及飞书的通知、留言、发消息类任务，优先用这个工具直接发送，不要去操作飞书界面。未配置 Webhook 时会返回配置指引",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要发送的消息内容"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_mouse_position",
            "description": "获取当前鼠标坐标",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_screen_size",
            "description": "获取屏幕分辨率",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]


def _locate_on_screen(args: dict) -> str:
    """在屏幕上查找图片，区分永久错误和暂时错误"""
    image_path = args["image_path"]

    # 永久错误：文件不存在或不可读，不重试
    if not os.path.isfile(image_path):
        return f"错误: 图像文件不存在 - {image_path}，请停止操作"
    if not os.access(image_path, os.R_OK):
        return f"错误: 图像文件不可读 - {image_path}，请停止操作"

    # 暂时错误：图像未找到
    try:
        location = pyautogui.locateOnScreen(image_path, confidence=args.get("confidence", 0.8))
        if location is None:
            return "未找到图像 - 请停止操作，不要点击任何坐标"
        center = pyautogui.center(location)
        return f"found at {center}"
    except Exception as e:
        return f"错误: 图像识别异常 - {e}，请停止操作"


def _type_text_with_space(text: str, interval: float = 0.05):
    # 优先使用剪贴板粘贴，避免空格丢失且支持中文
    try:
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
    except Exception:
        # 剪贴板方式失败时回退到逐字符输入
        try:
            pyautogui.write(text, interval=interval)
        except Exception:
            for char in text:
                if char == ' ':
                    pyautogui.press('space')
                else:
                    pyautogui.write(char)
                time.sleep(interval)


def _open_app(app_name: str):
    # 纯白名单启动：可执行名全部硬编码，模型输出只用于查表，杜绝命令注入
    app_map = {
        "notepad": "notepad.exe", "记事本": "notepad.exe", "文本编辑器": "notepad.exe",
        "calc": "calc.exe", "计算器": "calc.exe",
        "cmd": "cmd.exe", "命令行": "cmd.exe", "命令提示符": "cmd.exe", "终端": "cmd.exe",
        "explorer": "explorer.exe", "资源管理器": "explorer.exe", "文件管理器": "explorer.exe",
        "paint": "mspaint.exe", "画图": "mspaint.exe", "画板": "mspaint.exe",
        "控制面板": "control.exe", "任务管理器": "taskmgr.exe", "截图工具": "snippingtool.exe",
    }
    exe = app_map.get(app_name.strip()) or app_map.get(app_name.strip().lower())
    if not exe:
        return ("错误: 仅支持打开以下应用: 记事本(notepad)、计算器(calc)、命令行(cmd)、"
                "资源管理器(explorer)、画图(paint)、控制面板、任务管理器。请改用这些名称")
    os.startfile(exe)  # ShellExecute 启动，exe 只能是上面白名单中的常量
    time.sleep(2)
    return f"opened {app_name}"


TOOL_FUNCTIONS = {
    "click": lambda args: pyautogui.click(args["x"], args["y"], button=args.get("button", "left"), clicks=args.get("clicks", 1)) or f"clicked at ({args['x']}, {args['y']})",
    "type_text": lambda args: (_type_text_with_space(args["text"], args.get("interval", 0.05)) or f"typed: {args['text'][:50]}"),
    "press_key": lambda args: pyautogui.press(args["key"], presses=args.get("presses", 1)) or f"pressed {args['key']}",
    "hotkey": lambda args: pyautogui.hotkey(*args["keys"]) or f"hotkey {'+'.join(args['keys'])}",
    "move_to": lambda args: pyautogui.moveTo(args["x"], args["y"], duration=args.get("duration", 0.5)) or f"moved to ({args['x']}, {args['y']})",
    "scroll": lambda args: pyautogui.scroll(args["clicks"]) or f"scrolled {args['clicks']}",
    "screenshot": lambda args: (lambda _p: (Path("screenshots").mkdir(exist_ok=True), pyautogui.screenshot().save(Path("screenshots") / _p)) and f"screenshot saved: screenshots/{_p}")(args.get("path", f"screenshot_{int(time.time())}.png")),
    "locate_on_screen": _locate_on_screen,
    "wait": lambda args: (time.sleep(args.get("seconds", 1)) or f"waited {args.get('seconds', 1)}s"),
    "open_app": lambda args: _open_app(args["app_name"]),
    "get_mouse_position": lambda args: (lambda pos: f"mouse at {pos}")(pyautogui.position()),
    "get_screen_size": lambda args: (lambda sz: f"screen size {sz}")(pyautogui.size()),
    "analyze_screen": lambda args: analyze_screen(args["question"]),
    "list_windows": lambda args: _list_windows_impl(),
    "focus_window": lambda args: _focus_window_impl(args["title"]),
    "list_ui_elements": lambda args: _list_ui_elements_impl(args.get("window_title", "")),
    "click_ui_element": lambda args: _click_ui_element_impl(args.get("window_title", ""), args["name"]),
    "clipboard_read": lambda args: _clipboard_read_impl(),
    "clipboard_write": lambda args: _clipboard_write_impl(args["text"]),
    "verify_message_sent": lambda args: check_message_sent(args["expected_text"]),
    "send_feishu_message": lambda args: _send_feishu_impl(args["text"]),
}


# 最终回复中的失败信号（防假成功）。注意"没找到"不是"没有找到"的子串，
# 所以必须同时收录否定式变体，才能覆盖模型常见的"没有找到微信窗口"这类汇报；
# "不确定"对应诚实汇报规则里"我不确定是否发送成功"的情形，同样不算成功。
FAILURE_MARKERS = ("没找到", "没有找到", "找不到", "未找到",
                   "无法", "失败", "错误", "未能", "不确定")


def final_reply_failed(text) -> bool:
    """检查 Agent 最后一条回复，判断任务是否实际失败（而非流程走完就算成功）"""
    if not text:
        return False
    return any(marker in str(text) for marker in FAILURE_MARKERS)


SYSTEM_PROMPT = """你是一个电脑操作助手，通过工具帮用户完成桌面任务。你能看屏幕、管窗口、点控件、用剪贴板。

可用工具：
- list_windows(): 列出所有可见窗口
- focus_window(title): 把窗口切到前台
- analyze_screen(question): 看一眼屏幕并回答问题（约30秒，较慢，必要时才用）
- list_ui_elements(window_title): 列出窗口内的控件（按钮/菜单/输入框）及精确坐标
- click_ui_element(window_title, name): 按名称点击控件——最可靠的点击方式
- open_app(app_name): 打开应用（notepad/calc/cmd/explorer/paint/记事本/计算器等）
- click(x, y): 点击屏幕坐标；type_text(text): 在光标处输入文本（支持中文，自动粘贴）
- press_key(key) / hotkey(keys): 按键与组合键；scroll(clicks): 滚动；move_to(x, y): 移动鼠标
- clipboard_read() / clipboard_write(text): 读写剪贴板
- verify_message_sent(expected_text): 发消息后验证消息是否真的出现在聊天窗口
- send_feishu_message(text): 把消息直接发到用户的飞书群（手机电脑同步可见）。
  飞书相关的通知/发消息任务首选这个工具，比操作飞书界面快且可靠
- locate_on_screen(image_path): 用模板图片找位置（需要预先准备好的png）
- wait(seconds): 等待；screenshot(path): 截图保存

标准工作流（重要）：
1. 了解环境：先 list_windows 看有哪些窗口；需要目标应用时先 open_app 或 focus_window 把它切到前台
2. 操作控件：list_ui_elements 查看目标窗口的控件名称 → click_ui_element 按名称点击。
   这比猜坐标可靠得多，是首选
3. 看懂界面：需要了解屏幕内容/确认操作结果时用 analyze_screen（较慢，别每轮都用）
4. 兜底手段：控件方式行不通时，才用 analyze_screen 了解大致位置，再 click(x, y) 坐标点击
5. 输入文本：先点击输入框获得焦点，再 type_text

安全规则：
1. 不要执行任何危险或破坏性操作（删除文件、关闭系统、修改系统设置等）
2. 应用响应慢时用 wait 等待，不要连点
3. 坐标基于主屏幕左上角(0,0)

【重要】消息发送类任务（微信/QQ/邮件等）的诚实汇报规则：
1. 发送消息后，必须调用 verify_message_sent(你发送的原文) 验证消息是否真的发出
2. 返回 sent → 才能说"任务完成"
3. 返回 unclear → 必须明确告诉用户"我不确定消息是否发送成功，请人工检查"，禁止说"任务完成"
4. 返回 failed → 必须明确告诉用户"消息没有发送成功"，禁止说"任务完成"
5. 如果连验证手段都不可用（如聊天窗口不在前台），同样要说"我不确定"，不要声称完成

收到用户指令后，规划步骤并调用工具。每步完成后简要汇报。任务完成后，用一句明确的话告诉用户结果；没把握的事不要说"完成"。"""


class DesktopAgent:
    def __init__(self, llm: LLMClient = None, workdir: Path = None,
                 auditor: AuditLogger = None, history: TaskHistory = None,
                 approval=None):
        """auditor/history/approval 为企业化基础设施（core 包），依赖注入：
        不传则无审计无历史，高危操作按 AutoDenyPolicy 拒绝。"""
        self.workdir = workdir or Path.cwd()
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.max_turns = 10
        self._image_located = False   # locate_on_screen 是否成功（供旧逻辑兼容）
        self._last_locate_failed = False  # 上一次 locate_on_screen 失败 → 拦截下一次盲点击
        self._stop_requested = False  # 用户请求停止
        self.on_tool_call = None      # 回调：工具调用前
        self.on_tool_result = None    # 回调：工具调用后
        self.on_log = None            # 回调：通用日志
        self.on_retry = None          # 回调：工具重试中（attempt, max_retries）
        self.current_turn = 0         # 当前轮次（供界面显示）

        self.auditor = auditor
        self.history = history
        self.approval = approval if approval is not None else AutoDenyPolicy()

        # 如果没有传入 LLM，使用 None（会在 run 时创建）
        self.llm = llm

    def stop(self):
        """请求停止执行，在下一轮开始前生效"""
        self._stop_requested = True

    def _execute_tool(self, name: str, args: dict, risk: str):
        """执行单个工具：重试（指数退避）+ 动作后校验，全部事件入审计"""
        if name not in TOOL_FUNCTIONS:
            return f"错误: 未知工具 {name}"
        retryable = risk != "high" and guard.is_retryable(name)

        # click 前截图供"动作后校验"做界面变化对比
        before_img = None
        if name == "click":
            try:
                before_img = pyautogui.screenshot()
            except Exception:
                before_img = None

        result, attempts, final_ok = run_with_retry(
            lambda: TOOL_FUNCTIONS[name](args), name, retryable,
            auditor=self.auditor,
            on_retry=lambda attempt, mx, wait: self._on_retry(name, attempt, mx))

        # 动作后校验（仅首次即成功的关键动作；重试路径已含在失败判定里）
        if final_ok and attempts >= 1:
            ok, detail = self._verify_action(name, args, result, before_img)
            if ok is not None:
                if self.auditor:
                    self.auditor.emit("verify", tool=name, ok=ok, detail=detail)
                if not ok:
                    result = f"{result}（校验未通过: {detail}）"
                    self._log(f"[校验] {name}: {detail}")

        if attempts > 1:
            self._log(f"[重试] {name} 共执行 {attempts} 次，"
                      + ("最终成功" if final_ok else "仍然失败"))
        return result

    def _on_retry(self, tool: str, attempt: int, max_retries: int):
        if self.on_retry:
            try:
                self.on_retry(tool, attempt, max_retries)
            except Exception:
                pass

    def _verify_action(self, name: str, args: dict, result: str, before_img):
        """按工具类型做动作后校验；返回 (ok|None, detail)，None 表示无校验手段"""
        try:
            if name == "open_app" and not str(result).startswith("错误"):
                return core_verify.verify_open_app(args.get("app_name", ""))
            if name == "click" and before_img is not None:
                return core_verify.verify_click(before_img)
            if name == "clipboard_write" and not str(result).startswith("错误"):
                return core_verify.verify_clipboard(args.get("text", ""))
            if name == "screenshot":
                path = str(args.get("path", "") or "")
                if path and not path.startswith("screenshot_"):
                    return core_verify.verify_file_exists(path)
        except Exception as e:
            return True, f"校验异常(忽略): {e}"
        return None, ""

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)
        else:
            print(msg)

    def run(self, user_input: str) -> str:
        """任务入口：包装历史记录与审计生命周期，循环体在 _run_loop"""
        self.messages.append({"role": "user", "content": user_input})
        task_id = self.history.start(user_input) if self.history else None
        start = time.time()
        if self.auditor:
            self.auditor.emit("task_start", task_id=task_id, input=user_input)
        error = None
        try:
            result = self._run_loop()
        except Exception as e:
            error = str(e)
            result = f"错误: {error}"
            self._log(f"[错误] {result}")
        finally:
            if task_id and self.history:
                status = ("error" if error else
                          "stopped" if "停止" in (result or "") else
                          "max_turns" if "最大轮次" in (result or "") else
                          "failed" if final_reply_failed(result) else
                          "success")
                self.history.end(task_id, status, result or "",
                                 self.current_turn, time.time() - start)
            if self.auditor:
                self.auditor.emit("task_end", task_id=task_id,
                                  status="error" if error else "finished",
                                  turns=self.current_turn,
                                  elapsed_s=round(time.time() - start, 1))
        return result

    def _run_loop(self) -> str:
        for turn in range(self.max_turns):
            if self._stop_requested:
                return "已按要求停止执行。"
            self.current_turn = turn + 1
            self._log(f"\n── 第 {turn + 1}/{self.max_turns} 轮 ──")

            # 如果没有传入 LLM，创建一个本机 Ollama 客户端
            if self.llm is None:
                config = LLMConfig(
                    provider=LLMProvider.OLLAMA,
                    base_url="http://localhost:11434",
                    model="qwen2.5-coder:7b",
                    temperature=0.1
                )
                self.llm = LLMClient(config)

            # LLM 调用
            llm_start = time.time()
            resp = self.llm.chat(self.messages, TOOLS_SCHEMA)
            self._log(f"思考用时 {time.time() - llm_start:.1f} 秒")

            self.messages.append(resp)

            # 没有工具调用 = 模型给出了最终答复（或无有效输出，避免空转浪费轮次）
            tool_calls = resp.get("tool_calls") or []
            if not tool_calls:
                content = resp.get("content", "")
                if content:
                    self._log(f"[助手] {content}")
                    return content
                return "模型未返回有效内容，请重试或换一种说法描述任务。"

            for tc in tool_calls:
                if self._stop_requested:
                    return "已按要求停止执行。"
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"]
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except (ValueError, TypeError):
                        args = {}
                else:
                    args = raw_args or {}

                # 审计 + 风险评估 + 高危操作确认（core 基础设施）
                if self.auditor:
                    self.auditor.emit("tool_call", tool=name, args=args)
                risk, reason = guard.evaluate(name, args)
                if risk == "high":
                    allowed = self.approval.decide(name, args, risk, reason)
                    if self.auditor:
                        self.auditor.emit("approval", tool=name, reason=reason,
                                          allowed=allowed)
                    if not allowed:
                        result = (f"该操作被安全策略拦截（{reason}）。"
                                  f"请改用安全的方式完成任务，或说明需要用户手动处理")
                        self._log(f"[拦截] {name}: {reason}")
                        if self.on_tool_result:
                            self.on_tool_result(name, args, result)
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": str(result)
                        })
                        continue
                    self._log(f"[确认] 「{name}」已获用户批准（{reason}）")

                if self.on_tool_call:
                    self.on_tool_call(name, args)
                else:
                    self._log(f"[调用工具] {name} {args}")

                # 安全拦截：仅当上一步 locate_on_screen 失败时，拦截紧随其后的盲坐标点击
                if name == "click" and self._last_locate_failed:
                    result = ("错误: 上一步图像定位失败，禁止立即点击坐标。"
                              "请改用 click_ui_element 按名称点击，或重新 locate_on_screen")
                    self._log(f"[拦截] {result}")
                    self._last_locate_failed = False
                else:
                    exec_start = time.time()
                    result = self._execute_tool(name, args, risk)
                    self._log(f"工具执行用时 {time.time() - exec_start:.1f} 秒")
                    if name == "locate_on_screen":
                        self._image_located = "found at" in str(result)
                        self._last_locate_failed = not self._image_located
                    if str(result).startswith("错误"):
                        self._log(f"[错误] {result}")

                if self.on_tool_result:
                    self.on_tool_result(name, args, result)
                else:
                    self._log(f"[结果] {result}")
                if self.auditor:
                    self.auditor.emit("tool_result", tool=name, result=str(result)[:300])

                self.messages.append({
                    "role": "tool",
                    # Ollama 的 tool_calls 无 id 字段；content 需为纯文本（Ollama /api/chat 不接受数组格式）
                    "tool_call_id": tc.get("id", ""),
                    "content": str(result)
                })

        return "已达到最大轮次限制，任务未完成。请尝试把任务描述得更简单一些。"


def load_config() -> LLMConfig:
    script_dir = Path(__file__).parent
    config_path = script_dir / "agent_config.json"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return LLMConfig(
            provider=LLMProvider(data.get("provider", "openai")),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url", ""),
            model=data.get("model", ""),
            temperature=data.get("temperature", 0.1)
        )
    return LLMConfig(provider=LLMProvider.OPENAI)


def save_config(config: LLMConfig):
    script_dir = Path(__file__).parent
    config_path = script_dir / "agent_config.json"
    data = {
        "provider": config.provider.value,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "model": config.model,
        "temperature": config.temperature
    }
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def setup_wizard():
    print("=== 配置向导 ===")
    print("1. OpenAI (ChatGPT)")
    print("2. 智谱 AI (GLM)")
    print("3. DeepSeek")
    print("4. Ollama (本地)")
    print("5. 其他 OpenAI 兼容 API")
    choice = input("选择提供商 [1-5]: ").strip()

    provider_map = {
        "1": (LLMProvider.OPENAI, "gpt-4o-mini", "https://api.openai.com/v1"),
        "2": (LLMProvider.ZHIPU, "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4"),
        "3": (LLMProvider.DEEPSEEK, "deepseek-chat", "https://api.deepseek.com/v1"),
        "4": (LLMProvider.OLLAMA, "qwen2.5-coder:7b", "http://localhost:11434"),
        "5": (LLMProvider.OTHER, "", ""),
    }
    provider, default_model, default_url = provider_map.get(choice, (LLMProvider.OPENAI, "", ""))

    api_key = ""
    base_url = default_url
    model = default_model

    if provider != LLMProvider.OLLAMA:
        api_key = input(f"API Key: ").strip()
        if not api_key:
            print("API Key 不能为空")
            return None
    else:
        base_url = input(f"Ollama 地址 [{default_url}]: ").strip() or default_url
        model = input(f"模型名 [{default_model}]: ").strip() or default_model

    if provider == LLMProvider.OTHER:
        base_url = input("Base URL: ").strip()
        model = input("模型名: ").strip()

    config = LLMConfig(provider=provider, api_key=api_key, base_url=base_url, model=model)
    save_config(config)
    print("配置已保存到 agent_config.json")
    return config


def main():
    print("=== Desktop Agent - LLM 对话式自动化 ===\n")

    config = load_config()
    if not config.api_key and config.provider != LLMProvider.OLLAMA:
        print("未找到有效配置，进入向导...")
        config = setup_wizard()
        if not config:
            return

    print(f"\n当前配置: {config.provider.value} / {config.model}")
    print("输入 'quit' 退出, 'config' 重新配置, 'help' 查看帮助\n")

    llm = LLMClient(config)
    agent = DesktopAgent(llm)

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ('quit', 'exit', 'q'):
            break
        if user_input.lower() == 'config':
            config = setup_wizard()
            if config:
                llm = LLMClient(config)
                agent = DesktopAgent(llm)
            continue
        if user_input.lower() == 'help':
            print("""
示例指令:
- "打开记事本并输入 hello world"
- "点击坐标 500 500"
- "截图保存为 test.png"
- "找到屏幕上的 btn_ok.png 并点击它"
- "按 win+r 打开运行框"
- "获取当前鼠标位置"
- "等待 2 秒"
            """)
            continue

        agent.run(user_input)


if __name__ == "__main__":
    main()