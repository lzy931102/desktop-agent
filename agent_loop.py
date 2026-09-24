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
}


SYSTEM_PROMPT = """你是一个桌面自动化助手，可以通过工具控制鼠标、键盘、截图、查找图片等。

可用工具：
- click(x, y, button, clicks): 点击屏幕坐标
- type_text(text, interval): 输入文本
- press_key(key, presses): 按键
- hotkey(keys): 组合键
- move_to(x, y, duration): 移动鼠标
- scroll(clicks): 滚动
- screenshot(path): 截图
- locate_on_screen(image_path, confidence): 在屏幕上查找图像模板（需要预先准备好的png图片），返回坐标
- wait(seconds): 等待
- open_app(app_name): 打开应用（如 notepad, calc, cmd, explorer）
- get_mouse_position(): 获取鼠标位置
- get_screen_size(): 获取屏幕大小

工具选择指南：
1. 要打开应用程序（如记事本、计算器、游戏、文件夹等）→ 用 open_app
2. 要点击屏幕上某个按钮/图标（需要预先截图作为模板）→ 用 locate_on_screen 找到坐标，再用 click 点击
3. locate_on_screen 需要的是图片文件（.png），不是应用程序名称

安全规则：
1. 不要执行任何危险或破坏性操作（删除文件、关闭系统、修改系统设置等）
2. 连续操作间留出等待时间
3. 坐标基于主屏幕左上角(0,0)
4. 【重要】如果 locate_on_screen 返回"未找到图像"或"错误"，必须停止操作，绝对不要点击任何坐标
5. 【重要】只有 locate_on_screen 返回 "found at (x, y)" 时才能继续点击操作

收到用户指令后，规划步骤并调用工具。每步完成后简要汇报结果。任务完成后，用一句明确的话告诉用户结果（如"计算器已打开"）。"""


class DesktopAgent:
    def __init__(self, llm: LLMClient = None, workdir: Path = None):
        self.workdir = workdir or Path.cwd()
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.max_turns = 10
        self._image_located = False  # 追踪图像是否识别成功
        self._stop_requested = False  # 用户请求停止
        self.on_tool_call = None      # 回调：工具调用前
        self.on_tool_result = None    # 回调：工具调用后
        self.on_log = None            # 回调：通用日志
        self.current_turn = 0         # 当前轮次（供界面显示）

        # 如果没有传入 LLM，使用 None（会在 run 时创建）
        self.llm = llm

    def stop(self):
        """请求停止执行，在下一轮开始前生效"""
        self._stop_requested = True

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)
        else:
            print(msg)

    def run(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})

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

                if self.on_tool_call:
                    self.on_tool_call(name, args)
                else:
                    self._log(f"[调用工具] {name} {args}")

                # 安全拦截：图像识别失败后禁止点击
                if name == "click" and not self._image_located:
                    result = "错误: 图像未识别成功，禁止点击操作"
                    self._log(f"[拦截] {result}")
                else:
                    try:
                        exec_start = time.time()
                        result = TOOL_FUNCTIONS[name](args)
                        self._log(f"工具执行用时 {time.time() - exec_start:.1f} 秒")
                        if name == "locate_on_screen":
                            self._image_located = "found at" in str(result)
                    except KeyError:
                        result = f"错误: 未知工具 {name}"
                        self._log(f"[错误] {result}")
                    except Exception as e:
                        result = f"错误: {e}"
                        self._log(f"[错误] {result}")

                if self.on_tool_result:
                    self.on_tool_result(name, args, result)
                else:
                    self._log(f"[结果] {result}")

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