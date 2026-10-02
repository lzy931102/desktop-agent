# 从 gui.py 抽出的界面常量（配色 / 状态映射 / 工具名映射 / 人性化文案）。
# T4 Phase 1 纯搬运，零内容变更；gui.py 经兼容层再导出这些名字。

# 版本号：显示在窗口标题栏，方便用户与 GitHub Releases 对照（避免旧版新版分不清）
APP_VERSION = "2.0.15"

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5-coder:7b"
DEFAULT_MAX_CONCURRENT = 3
# 首启引导（UX-P1-6）：本地路线的官方下载直链 / 云端配置图文教程
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
CLOUD_TUTORIAL_URL = "https://github.com/lzy931102/desktop-agent#readme"

# ---------------- 配色（gray-900 体系 · 对话流补充色 · WCAG AA） ----------------
BG = "#111827"            # 主背景（gray-900）
SIDEBAR = "#0D1526"       # 侧边栏（比主背景更深一档，形成分区）
CARD = "#1F2937"          # 卡片 / Agent 气泡（gray-800）
CARD_2 = "#374151"        # 工具卡片 / 活动高亮（gray-700）
BORDER = "#4B5563"        # 边框（gray-600）
INPUT_BG = "#374151"      # 输入框背景
ACCENT = "#3B82F6"        # 主色（blue-500）
ACCENT_HOVER = "#2563EB"
BUBBLE_USER = "#1E40AF"   # 用户气泡（blue-800）
TEXT = "#F3F4F6"          # 正文（gray-100）
MUTED = "#E5E7EB"         # 次要文字（gray-200，加深可读性：50岁用户反馈灰字看不清）
FAINT = "#D1D5DB"         # 弱化文字（gray-300）
OK = "#34D399"            # 成功（emerald-400）
ERR = "#F87171"           # 失败（red-400）
WARN = "#FBBF24"          # 警告（amber-400）
RUNBLUE = "#60A5FA"       # 执行中（blue-400）
AMBER = "#FCD34D"         # 隐私条文字
TOOLC = "#93C5FD"         # 工具名（blue-300）

STATUS_COLOR = {"draft": FAINT, "queued": FAINT, "running": RUNBLUE,
                "done": OK, "failed": ERR, "stopped": WARN}
STATUS_ICON = {"draft": "○", "queued": "⏸", "running": "⏳",
               "done": "✓", "failed": "✗", "stopped": "⏹"}
STATUS_TEXT = {"draft": "还没开始", "queued": "排队等待中", "running": "执行中",
               "done": "已完成", "failed": "失败", "stopped": "已停止"}

TOOL_CHIP = {  # 工具卡状态 → (文案, 颜色)
    "run": ("⏳ 执行中…", RUNBLUE), "ok": ("✓ 完成", OK),
    "err": ("✗ 出错", ERR), "block": ("🚫 已拦截", WARN),
}

PLACEHOLDER = "用一句话描述你想让我做什么，例如：打开记事本，输入 你好"

TOOL_NAMES = {
    "open_app": "打开应用", "click": "点击", "type_text": "输入文字",
    "press_key": "按键", "hotkey": "按快捷键", "move_to": "移动鼠标",
    "scroll": "滚动", "screenshot": "截取屏幕", "locate_on_screen": "查找屏幕图像",
    "wait": "等待", "get_mouse_position": "获取鼠标位置", "get_screen_size": "获取分辨率",
    "analyze_screen": "看屏幕", "list_windows": "查看窗口列表",
    "focus_window": "切换窗口", "list_ui_elements": "查看窗口控件",
    "click_ui_element": "点击控件", "clipboard_read": "读取剪贴板",
    "clipboard_write": "写入剪贴板", "verify_message_sent": "确认消息已发出",
    "send_feishu_message": "发飞书消息", "install_skill": "安装技能包",
}

EXAMPLES = ["打开计算器", "打开记事本，输入 你好", "截取屏幕", "看看现在有哪些窗口"]

# ---------------- 人性化文案 ----------------
WELCOME_HEAD = "👋 你好呀，我是你的桌面助手"
MSG_ON_IT = "收到！马上开始，过程都在下面 👇"
MSG_QUEUED = "现在已经有 {n} 个任务在跑啦，这个先排个队，轮到就自动开始 ⏳"
MSG_DONE_OK = "✓ 搞定！{extra}有别的需要随时叫我。"
MSG_DONE_FAIL = ("抱歉，这次没能完成：{reason}\n"
                 "要不换个说法再试一次？或者把任务拆小一点，我们一步一步来。")
MSG_STOPPED = "⏹ 好的，已经停下。想继续随时说一声。"
MSG_NEED_INPUT = "先告诉我你想做什么吧，比如：打开计算器 😊"
MSG_APPROVED = "✓ 好的，你已允许，我继续了。"
MSG_DENIED = "🚫 收到，这一步我不做了，换个安全的方式试试。"
MSG_BLOCKED_SUB = "没关系，我会换个安全的方式，或者这件事需要你手动处理。"
MSG_CONFIRM_HEAD = "这一步有点风险，需要你点头确认："
