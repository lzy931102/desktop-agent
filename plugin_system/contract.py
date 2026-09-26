"""插件契约：一个插件 = 插件目录下的一个 .py 文件。

文件级约定（缺一即整个插件拒绝加载，错误信息直接告诉作者怎么改）：

    NAME         插件显示名，2~30 个字（插件面板展示）
    VERSION      版本字符串，如 "1.0.0"（面板展示）
    DESCRIPTION  一句话描述（面板展示）
    get_tools()  返回工具定义列表，每条：
        name          工具名，小写字母开头、仅含 [a-z0-9_]、2~64 位；
                      禁止与内置工具或其他插件重名（重名拒绝加载）
        description   给 LLM 看的工具说明（进工具 schema）
        parameters    参数 JSON Schema。完整写法 {"type": "object", "properties": {...}}；
                      允许简写：直接写 {"字段名": {...}}，加载器自动补 type/properties
        run(args)     实现，返回给 LLM 的字符串；抛异常由执行层兜底成"错误: ..."
        prompt_hint   进 system prompt 的一行用法说明（缺省由 name + description 生成）
        default_risk  "none" | "medium" | "high"，缺省 medium（fail-closed：
                      作者忘写风险级别时宁可多确认一次，也不放过危险操作）

安全边界：插件是任意可执行代码，只应安装可信来源的插件；加载器只做结构
校验、不做沙箱（有意取舍，见 docs/插件模块化方案.md §8）。"停用"意味着
代码一行都不跑——停用的插件不 import、不执行。
"""
import re
from dataclasses import dataclass
from typing import Callable

RISK_LEVELS = ("none", "medium", "high")
RISK_ORDER = {"none": 0, "medium": 1, "high": 2}
DEFAULT_RISK = "medium"

# 内置工具名（与 agent_loop.TOOL_FUNCTIONS 保持一致）。硬编码在此是为了维持
# plugin_system → agent_loop 的零依赖；agent_loop 侧增删工具时需同步此表，
# test_plugin_boundary.py 会在 CI 里核对两者一致。
RESERVED_TOOL_NAMES = frozenset({
    "click", "type_text", "press_key", "hotkey", "move_to", "scroll",
    "screenshot", "locate_on_screen", "wait", "open_app",
    "get_mouse_position", "get_screen_size", "analyze_screen",
    "list_windows", "focus_window", "list_ui_elements", "click_ui_element",
    "clipboard_read", "clipboard_write", "verify_message_sent",
    "send_feishu_message",
})

_TOOL_NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")


class PluginContractError(ValueError):
    """插件不符合契约。str(e) 面向插件作者，可直接照着改。"""


@dataclass
class PluginTool:
    """一个插件工具 = 内部工具的等价物（schema + 实现 + 风险级）"""
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], str]
    prompt_hint: str
    default_risk: str
    plugin_name: str = ""      # 所属插件显示名（执行报错时定位用）

    def schema(self) -> dict:
        """OpenAI function-calling 格式，与 agent_loop.TOOLS_SCHEMA 的元素同构"""
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }}


@dataclass
class PluginInfo:
    """单个插件的加载结果（插件面板展示与启停的最小单元）"""
    stem: str                  # 文件名去 .py，settings 里的启停标识
    path: object = None        # Path
    name: str = ""             # 显示名；停用/加载失败时为空 → 面板回退显示 stem
    version: str = ""
    description: str = ""
    enabled: bool = True
    error: str = ""            # 非空 = 加载失败（面向作者的可操作信息）
    tools: tuple = ()

    @property
    def status(self) -> str:
        """ok=已启用且加载成功；disabled=已停用（未加载）；error=启用但加载失败"""
        if self.error:
            return "error"
        return "ok" if self.enabled else "disabled"

    @property
    def display_name(self) -> str:
        return self.name or self.stem


def _normalize_parameters(raw, where: str) -> dict:
    if not isinstance(raw, dict):
        raise PluginContractError(f"{where}：parameters 必须是字典（JSON Schema）")
    if "type" in raw:
        if raw["type"] != "object":
            raise PluginContractError(
                f"{where}：parameters.type 只能是 \"object\"，收到 {raw['type']!r}")
        return raw
    # 简写：整个字典视为 properties
    return {"type": "object", "properties": raw}


def build_tools(raw_list, plugin_name: str, seen_tools: dict) -> tuple:
    """校验 get_tools() 的返回值，产出 PluginTool 元组。

    seen_tools: {工具名: 来源插件名}，跨插件查重；全部校验通过后才把本插件
    的工具登记进去（调用方传入副本、成功后合并），失败不污染其他插件。
    任何一条不合格抛 PluginContractError → 整个插件拒绝加载（fail-closed）。
    """
    tools = []
    for i, raw in enumerate(list(raw_list)):
        where = f"第 {i + 1} 个工具"
        if not isinstance(raw, dict):
            raise PluginContractError(
                f"{where}不是字典，应为 {{\"name\", \"run\", ...}} 形式")
        name = raw.get("name")
        if not isinstance(name, str) or not _TOOL_NAME_RE.fullmatch(name):
            raise PluginContractError(
                f"{where}的 name {name!r} 不合法：小写字母开头，只能含"
                f"小写字母/数字/下划线，2~64 位")
        if name in RESERVED_TOOL_NAMES:
            raise PluginContractError(
                f"{where}的 name {name!r} 与内置工具重名，请换一个名字")
        owner = seen_tools.get(name)
        if owner is not None:
            raise PluginContractError(
                f"{where}的 name {name!r} 与插件「{owner}」的工具重名，请换一个名字")
        desc = raw.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise PluginContractError(
                f"{where}（{name}）缺少 description：写一句给 AI 看的工具说明")
        run = raw.get("run")
        if not callable(run):
            raise PluginContractError(
                f"{where}（{name}）缺少可调用的 run(args) 函数")
        params = _normalize_parameters(raw.get("parameters"), f"{where}（{name}）")
        risk = raw.get("default_risk", DEFAULT_RISK)
        if risk not in RISK_LEVELS:
            raise PluginContractError(
                f"{where}（{name}）的 default_risk 只能是 none/medium/high，"
                f"收到 {risk!r}")
        hint = raw.get("prompt_hint")
        if not isinstance(hint, str) or not hint.strip():
            hint = f"{name}: {desc.strip()}"
        seen_tools[name] = plugin_name
        tools.append(PluginTool(name=name, description=desc.strip(),
                                parameters=params, run=run,
                                prompt_hint=hint.strip(), default_risk=risk,
                                plugin_name=plugin_name))
    if not tools:
        raise PluginContractError(
            "get_tools() 返回了空列表：插件至少要提供 1 个工具")
    return tuple(tools)
