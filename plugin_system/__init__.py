"""插件系统（独立模块）：把用户插件目录里的 .py 文件变成 Agent 可用工具。

对外只暴露 PluginManager；插件怎么写见 contract.py 模块注释与 docs/插件开发指南.md，
整体设计见 docs/插件模块化方案.md。

依赖边界（单向，禁止反向）：本包只允许 import core/，
禁止 import agent_loop / gui —— 这保证插件系统可以独立开发、独立测试。
"""
from .contract import PluginContractError, PluginInfo, PluginTool
from .manager import PluginManager

__all__ = ["PluginManager", "PluginInfo", "PluginTool", "PluginContractError"]
