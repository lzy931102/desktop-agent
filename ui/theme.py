# 从 gui.py 抽出的界面常量（配色 / 状态映射 / 工具名映射 / 人性化文案）。
# T4 Phase 1 纯搬运，零内容变更；gui.py 经兼容层再导出这些名字。

# 版本号：显示在窗口标题栏，方便用户与 GitHub Releases 对照（避免旧版新版分不清）
APP_VERSION = "2.0.16"

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5-coder:7b"
DEFAULT_MAX_CONCURRENT = 3
# 首启引导（UX-P1-6）：本地路线的官方下载直链 / 云端配置图文教程
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
CLOUD_TUTORIAL_URL = "https://github.com/lzy931102/desktop-agent#readme"

# ---------------- 配色（GitHub Dark 体系 · T24 配色改造 · WCAG AA） ----------------
# 色板真名（任务书 T24 定义的 GitHub Dark 色，全项目颜色一律从这取）：
BG_PRIMARY = "#0D1117"    # 最底层：主窗口 / 对话区
BG_SECONDARY = "#161B22"  # 侧栏 / 面板 / 过程卡 / 输入框
BG_TERTIARY = "#21262D"   # Agent 气泡 / 卡片
BORDER = "#30363D"        # 边框 / 分隔线
TEXT_PRIMARY = "#E6EDF3"  # 普通文字（浅白）
TEXT_SECONDARY = "#8B949E"  # 次要/弱化文字（GitHub -mute）
ACCENT_BLUE = "#58A6FF"   # 链接 / 用户气泡 / 主按钮（截图中「最亮的颜色」）
ACCENT_GREEN = "#3FB950"  # 成功 / 文件路径
ACCENT_YELLOW = "#D29922" # 命令 / 快捷键 / 警告
ACCENT_RED = "#F85149"    # 错误

# 既有语义常量 → GitHub Dark 色板映射（值换了，名字与引用处零改动）：
BG = BG_PRIMARY           # 主背景（原 gray-900 #111827）
SIDEBAR = BG_SECONDARY    # 侧边栏 / 日志区（原 #0D1526）
CARD = BG_TERTIARY        # 卡片 / Agent 气泡（原 #1F2937）
CARD_2 = BG_SECONDARY     # 工具卡 / thought 卡背景 / hover（原 #374151）
                          # （hover 比本体深一档，暗色主题惯例）
INPUT_BG = BG_SECONDARY   # 输入框背景（任务书：输入框 #161B22）
ACCENT = ACCENT_BLUE      # 主色（原 #3B82F6）
ACCENT_HOVER = "#4493F8"  # 主按钮 hover（GitHub btn-primary hover）
BUBBLE_USER = ACCENT_BLUE # 用户气泡（原 #1E40AF → 任务书亮蓝，全界面最醒目）
TEXT = TEXT_PRIMARY       # 正文（原 #F3F4F6）
MUTED = "#C9D1D9"         # 次要文字。**不用 TEXT_SECONDARY**：50 岁用户实测
                          # 反馈灰字看不清（theme 注释原记录），#C9D1D9 对
                          # #0D1117 对比 10.4:1 舒适；#8B949E（4.9:1）只用于
                          # 真正弱化处（FAINT）
FAINT = TEXT_SECONDARY    # 弱化文字：分隔线文案 / 「试试：」/ turn 线等
OK = ACCENT_GREEN         # 成功（原 #34D399）
ERR = ACCENT_RED          # 失败（原 #F87171）
WARN = ACCENT_YELLOW      # 警告（原 #FBBF24）
RUNBLUE = ACCENT_BLUE     # 执行中（原 #60A5FA）
AMBER = ACCENT_YELLOW     # 隐私条文字（原 #FCD34D）
TOOLC = "#79C0FF"         # 工具名（比链接蓝浅一档，加粗小字更易读）

# 对话流富文本高亮 tag 色（T24 任务 3）：tag 名 → 前景色
LINK = ACCENT_BLUE        # 网址（可点击，下划线）
PATHC = ACCENT_GREEN      # 文件路径（可点击定位）
KEYC = ACCENT_YELLOW      # 命令 / 快捷键

# 用户气泡反色高亮（T24e 扩展）：BUBBLE_USER 亮蓝底上，默认的链接蓝
# 与底色同色不可读，改用任务书点名的反色；普通文字仍白色
LINK_ON_ACCENT = "#FBBF24"   # 网址（蓝底亮黄，可点击，下划线）
PATH_ON_ACCENT = "#4ADE80"   # 路径（蓝底亮绿，可点击定位）

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

PLACEHOLDER = "用一句话描述你想让我做什么，例如：打开记事本，输入“你好”"

# 输入框正上方的一行小字（T24 任务 3）：让第一次用的人一眼知道「在哪输入」
MSG_INPUT_HINT = "我能帮你操作电脑，在这里输入你想做的事："

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

# 「怎么用」首启引导（T24 任务 1 → T24a 重做）：嵌在对话区顶部的卡片，
# 教第一次用的人两件事——能干什么、在哪输入；用户开始输入即柔和淡出
WELCOME_CARD_HEAD = "👋 欢迎使用 Desktop Agent"
WELCOME_CARD_LINES = (
    "我可以帮你：",
    "· 🖥️ 打开软件，比如记事本、计算器",
    "· 📁 整理文件、查看窗口",
    "· 📝 帮你输入文字、查资料",
    "· 🧮 算数、截图",
    "",
    "在下面的输入框里，用一句话告诉我你想做的事。",
)
# 嵌入式引导卡配色（T24a 任务 3，用户拍板的柔和方案）：
WELCOME_BG = "#1C2128"    # 卡片底（比主背景略亮一档，有层次不刺眼）
# 边框沿用 BORDER #30363D（1px 轻微）；标题沿用 TEXT #E6EDF3；
# 正文沿用 MUTED #C9D1D9——不再新增独立色，全项目颜色一个来源
# 「重看使用引导」按钮文案（设置面板里，T24 任务 1 第 4 点）
MSG_RESHOW_WELCOME = "👋 重看使用引导"
