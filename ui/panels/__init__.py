"""ui.panels —— AgentGUI 各面板 Mixin 包（T4 Phase 2 从 gui.py 抽出）。

每个面板一个模块、一个 Mixin，gui.py 的 AgentGUI 组合继承全部 Mixin；
面板之间互不依赖，跨面板调用一律经 self（由 AgentGUI 实例统一路由）。
"""
