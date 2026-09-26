"""示例插件源码（单一事实来源）。

GUI「生成示例插件」按钮与 examples/ 目录下的示例文件都由本文件的
SAMPLE_PLUGIN_SOURCE 生成，改示例只改这里。
"""

SAMPLE_FILENAME = "示例插件-天气查询.py"

SAMPLE_PLUGIN_SOURCE = '''"""示例插件：天气查询（演示数据，无需联网）

安装：把本文件放进插件文件夹（插件面板 → 「打开插件文件夹」），点「刷新」。
写自己的插件照这个骨架来：NAME / VERSION / DESCRIPTION + get_tools()，
字段含义与更多写法见 docs/插件开发指南.md
"""
NAME = "天气查询"
VERSION = "1.0.0"
DESCRIPTION = "查询城市今天的天气（示例插件，返回演示数据）"

# 演示数据：接真实服务时，把 query_weather 里的逻辑换成你的 API 调用即可
_FAKE_WEATHER = {
    "北京": ("晴", 26), "上海": ("多云", 29), "广州": ("雷阵雨", 31),
    "深圳": ("晴", 32), "杭州": ("小雨", 24),
}


def query_weather(args):
    city = str(args.get("city", "")).strip() or "北京"
    sky, temp = _FAKE_WEATHER.get(city, ("暂无演示数据（只有北上广深杭）", "--"))
    return f"{city}：{sky}，{temp}℃（演示数据）"


def get_tools():
    return [{
        "name": "query_weather",
        "description": "查询城市今天的天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
            "required": ["city"],
        },
        "run": query_weather,
        "prompt_hint": "query_weather(city): 查询城市今天的天气（演示数据）",
        "default_risk": "none",
    }]
'''
