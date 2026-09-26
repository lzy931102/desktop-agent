"""plugin_system 与主程序的一致性边界测试（唯一允许同时 import 双方的地方）。

contract.RESERVED_TOOL_NAMES 是内置工具名的硬拷贝（为了维持 plugin_system
→ agent_loop 零依赖）。agent_loop 增删内置工具时若忘了同步，这里立刻红。
"""
from plugin_system.contract import RESERVED_TOOL_NAMES
from plugin_system.sample import SAMPLE_FILENAME, SAMPLE_PLUGIN_SOURCE


def test_reserved_names_match_builtin_tools():
    import agent_loop
    assert RESERVED_TOOL_NAMES == set(agent_loop.TOOL_FUNCTIONS)


def test_sample_plugin_source_compiles_and_satisfies_contract():
    """示例插件必须始终是合法、可加载的插件——它会被 GUI 一键生成给用户"""
    import ast
    tree = ast.parse(SAMPLE_PLUGIN_SOURCE)
    assert tree  # 至少是合法 Python

    import tempfile
    from pathlib import Path

    from core.settings import Settings
    from plugin_system import PluginManager

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "plugins").mkdir()
        (root / "plugins" / SAMPLE_FILENAME).write_text(
            SAMPLE_PLUGIN_SOURCE, encoding="utf-8")
        m = PluginManager(Settings(file_path=root / "settings.json"),
                          directory=root / "plugins")
        infos = m.list()
        assert len(infos) == 1 and infos[0].status == "ok", infos[0].error
        tools = m.enabled_tools()
        assert len(tools) == 1
        assert tools[0].name == "query_weather"
        assert tools[0].run({"city": "北京"})   # 真跑一次示例实现
