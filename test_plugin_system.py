"""plugin_system 独立测试。

本文件禁止 import agent_loop / gui——插件系统必须能在没有主程序的情况下
独立工作（模块边界由测试自证）。与内置工具清单的一致性核对在
test_plugin_boundary.py 里做。
"""
import json
from pathlib import Path

import pytest

from core.settings import Settings
from plugin_system import PluginContractError, PluginManager
from plugin_system.contract import build_tools

GOOD_PLUGIN = '''
NAME = "测试插件"
VERSION = "1.2.0"
DESCRIPTION = "用于测试的插件"

def tool_a(args):
    return f"A:{args}"

def tool_b(args):
    return "B"

def get_tools():
    return [
        {
            "name": "test_plugin_tool_a",
            "description": "工具A",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
            "run": tool_a,
            "prompt_hint": "test_plugin_tool_a(x): 测试工具A",
            "default_risk": "none",
        },
        {
            "name": "test_plugin_tool_b",
            "description": "工具B",
            "parameters": {},
            "run": tool_b,
        },
    ]
'''

GOOD_PLUGIN_A = '''
NAME = "插件甲"
VERSION = "1.2.0"
DESCRIPTION = "用于测试的插件A"

def tool_a(args):
    return f"A:{args}"

def tool_b(args):
    return "B"

def get_tools():
    return [
        {
            "name": "test_plugin_a_tool_a",
            "description": "工具A",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
            "run": tool_a,
            "prompt_hint": "test_plugin_a_tool_a(x): 测试工具A",
            "default_risk": "none",
        },
        {
            "name": "test_plugin_a_tool_b",
            "description": "工具B",
            "parameters": {},
            "run": tool_b,
        },
    ]
'''

GOOD_PLUGIN_B = '''
NAME = "插件乙"
VERSION = "1.2.0"
DESCRIPTION = "用于测试的插件B"

def tool_a(args):
    return f"A:{args}"

def tool_b(args):
    return "B"

def get_tools():
    return [
        {
            "name": "test_plugin_b_tool_a",
            "description": "工具A",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
            "run": tool_a,
            "prompt_hint": "test_plugin_b_tool_a(x): 测试工具A",
            "default_risk": "none",
        },
        {
            "name": "test_plugin_b_tool_b",
            "description": "工具B",
            "parameters": {},
            "run": tool_b,
        },
    ]
'''


def make_manager(tmp_path, monkeypatch=None) -> PluginManager:
    settings = Settings(file_path=tmp_path / "settings.json")
    return PluginManager(settings, directory=tmp_path / "plugins")


def write_plugin(tmp_path, stem: str, source: str) -> Path:
    d = tmp_path / "plugins"
    d.mkdir(exist_ok=True)
    p = d / f"{stem}.py"
    p.write_text(source, encoding="utf-8")
    return p


# ---------- 基本加载 ----------

def test_empty_dir_no_crash(tmp_path):
    m = make_manager(tmp_path)
    assert m.list() == []
    assert m.enabled_tools() == ()


def test_valid_plugin_loads(tmp_path):
    write_plugin(tmp_path, "good", GOOD_PLUGIN)
    m = make_manager(tmp_path)
    infos = m.list()
    assert len(infos) == 1
    info = infos[0]
    assert info.status == "ok"
    assert info.name == "测试插件"
    assert info.version == "1.2.0"
    assert len(info.tools) == 2

    tools = m.enabled_tools()
    a, b = tools
    assert a.default_risk == "none"          # 显式声明优先
    assert b.default_risk == "medium"        # 缺省 fail-closed
    assert b.prompt_hint == "test_plugin_tool_b: 工具B"  # hint 缺省自动生成
    assert a.prompt_hint == "test_plugin_tool_a(x): 测试工具A"

    schema = a.schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "test_plugin_tool_a"
    assert schema["function"]["parameters"]["type"] == "object"
    assert a.plugin_name == "测试插件"


def test_parameters_shortform_normalized(tmp_path):
    """parameters 简写 {"字段": {...}} 自动补 type/properties"""
    write_plugin(tmp_path, "p", '''
NAME = "简写插件"
def run(args):
    return "ok"
def get_tools():
    return [{"name": "short_form_tool", "description": "d", "parameters":
             {"city": {"type": "string"}}, "run": run}]
''')
    m = make_manager(tmp_path)
    tool = m.enabled_tools()[0]
    assert tool.parameters == {"type": "object",
                               "properties": {"city": {"type": "string"}}}


# ---------- 契约校验：坏插件必须被拒，且错误信息可操作 ----------

def test_missing_name(tmp_path):
    write_plugin(tmp_path, "p", 'def get_tools(): return []')
    m = make_manager(tmp_path)
    info = m.list()[0]
    assert info.status == "error"
    assert "NAME" in info.error


def test_missing_get_tools(tmp_path):
    write_plugin(tmp_path, "p", 'NAME = "坏插件"')
    m = make_manager(tmp_path)
    assert "get_tools" in m.list()[0].error


def test_get_tools_returns_not_list(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return {"name": "x"}
''')
    m = make_manager(tmp_path)
    assert "应为列表" in m.list()[0].error


def test_empty_tools_list_rejected(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return []
''')
    m = make_manager(tmp_path)
    assert "至少" in m.list()[0].error


def test_missing_parameters(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return [{"name": "no_params_tool", "description": "d", "run": print}]
''')
    m = make_manager(tmp_path)
    assert "parameters" in m.list()[0].error


def test_bad_risk_value_rejected(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return [{"name": "risky_tool", "description": "d", "parameters": {},
             "run": print, "default_risk": "low"}]
''')
    m = make_manager(tmp_path)
    assert "none/medium/high" in m.list()[0].error


def test_reserved_tool_name_rejected(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return [{"name": "click", "description": "d", "parameters": {}, "run": print}]
''')
    m = make_manager(tmp_path)
    assert "内置工具重名" in m.list()[0].error


def test_bad_tool_name_format(tmp_path):
    write_plugin(tmp_path, "p", '''
NAME = "坏插件"
def get_tools():
    return [{"name": "Bad-Name", "description": "d", "parameters": {}, "run": print}]
''')
    m = make_manager(tmp_path)
    assert "不合法" in m.list()[0].error


def test_syntax_error_isolated(tmp_path):
    """一个文件语法坏掉，其他插件照常加载"""
    write_plugin(tmp_path, "a_good", GOOD_PLUGIN)
    write_plugin(tmp_path, "b_broken", 'NAME = ("坏掉的语法')
    m = make_manager(tmp_path)
    by_stem = {i.stem: i for i in m.list()}
    assert by_stem["a_good"].status == "ok"
    assert by_stem["b_broken"].status == "error"
    assert "语法错误" in by_stem["b_broken"].error
    assert len(m.enabled_tools()) == 2


def test_top_level_crash_isolated(tmp_path):
    """插件顶层代码抛异常（如联网失败）只影响它自己"""
    write_plugin(tmp_path, "a_good", GOOD_PLUGIN)
    write_plugin(tmp_path, "b_crash", '''
NAME = "会炸的插件"
raise RuntimeError("数据库连不上")
''')
    m = make_manager(tmp_path)
    by_stem = {i.stem: i for i in m.list()}
    assert by_stem["a_good"].status == "ok"
    assert by_stem["b_crash"].status == "error"
    assert "RuntimeError" in by_stem["b_crash"].error


def test_duplicate_plugin_name(tmp_path):
    write_plugin(tmp_path, "a", GOOD_PLUGIN)
    write_plugin(tmp_path, "b", GOOD_PLUGIN)   # NAME 相同
    m = make_manager(tmp_path)
    by_stem = {i.stem: i for i in m.list()}
    assert by_stem["a"].status == "ok"
    assert by_stem["b"].status == "error"
    assert "重复" in by_stem["b"].error


def test_cross_plugin_tool_collision(tmp_path):
    write_plugin(tmp_path, "a", '''
NAME = "插件A"
def run(args):
    return "a"
def get_tools():
    return [{"name": "same_tool_name", "description": "d", "parameters": {}, "run": run}]
''')
    write_plugin(tmp_path, "b", '''
NAME = "插件B"
def run(args):
    return "b"
def get_tools():
    return [{"name": "same_tool_name", "description": "d", "parameters": {}, "run": run}]
''')
    m = make_manager(tmp_path)
    by_stem = {i.stem: i for i in m.list()}
    assert by_stem["a"].status == "ok"
    assert by_stem["b"].status == "error"
    assert "插件「插件A」" in by_stem["b"].error


# ---------- 启停 ----------

def test_disable_persists_and_skips_loading(tmp_path):
    write_plugin(tmp_path, "good", GOOD_PLUGIN)
    m = make_manager(tmp_path)
    assert m.enabled_tools()

    m.set_enabled("good", False)
    # 设置真的落盘了
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["plugins"]["disabled"] == ["good"]

    m.reload()
    info = m.list()[0]
    assert info.status == "disabled"
    assert m.enabled_tools() == ()

    m.set_enabled("good", True)
    m.reload()
    assert m.list()[0].status == "ok"
    assert len(m.enabled_tools()) == 2


def test_disabled_plugin_code_never_runs(tmp_path):
    """停用 = 代码一行不跑：加载阶段就会炸的插件，停用后不报错"""
    write_plugin(tmp_path, "dangerous", 'raise RuntimeError("停用后不应执行到我")')
    m = make_manager(tmp_path)
    assert m.list()[0].status == "error"       # 启用时加载失败
    m.set_enabled("dangerous", False)
    m.reload()
    assert m.list()[0].status == "disabled"    # 停用后不执行、不报错


# ---------- 稳定性与排序 ----------

def test_output_order_stable_by_stem(tmp_path):
    write_plugin(tmp_path, "bbb", GOOD_PLUGIN)
    write_plugin(tmp_path, "aaa", GOOD_PLUGIN_A)
    write_plugin(tmp_path, "ccc", GOOD_PLUGIN_B)
    m = make_manager(tmp_path)
    assert [i.stem for i in m.list()] == ["aaa", "bbb", "ccc"]
    # 工具顺序：插件甲(2) → 测试插件(2) → 插件乙(2)
    assert [t.plugin_name for t in m.enabled_tools()] == \
        ["插件甲", "插件甲", "测试插件", "测试插件", "插件乙", "插件乙"]


def test_underscore_and_non_py_files_ignored(tmp_path):
    write_plugin(tmp_path, "_private", 'raise RuntimeError("boom")')
    (tmp_path / "plugins" / "说明.txt").write_text("不是插件")
    (tmp_path / "plugins" / "__init__.py").write_text("")
    m = make_manager(tmp_path)
    assert m.list() == []


# ---------- 契约函数直测（不经文件加载） ----------

def test_build_tools_rejects_non_dict_entry():
    with pytest.raises(PluginContractError):
        build_tools(["不是字典"], "插件", {})
