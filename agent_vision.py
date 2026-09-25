"""agent_vision.py - 顶级电脑操作 agent 的核心扩展能力包

对标 Computer Use 类 agent 的能力分层：
1. 视觉理解   analyze_screen     —— qwen-vl 看懂屏幕（回答"屏幕上有什么/某应用开没开"）
2. 窗口管理   list_windows / focus_window —— 枚举并前置窗口（ctypes，零依赖）
3. 元素级操作 list_ui_elements / click_ui_element —— Windows UIA 控件树，
   拿到控件真实名字与精确坐标，比"看图猜坐标"可靠得多
4. 剪贴板    clipboard_read / clipboard_write
"""
import base64
import ctypes
import ctypes.wintypes
import io
import time

import requests

try:
    import pyautogui
    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None

OLLAMA_URL = "http://localhost:11434"
VISION_MODEL = "qwen-vl"


# ============================ 1. 视觉理解 ============================

class ScreenVision:
    """用本地多模态模型看懂屏幕。只做"理解"，不做坐标定位
    （小参数量量化模型的 grounding 噪声大，定位交给 UIA 控件树）。"""

    def __init__(self, base_url: str = OLLAMA_URL, model: str = VISION_MODEL):
        self.base_url = base_url
        self.model = model
        self._session = None
        self._available = None  # None=未知

    def _http(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False  # 本地服务，绕过一切代理
        return self._session

    def is_available(self) -> bool:
        """视觉模型是否已就绪（带缓存，失败后 10 分钟内不重复探测）"""
        if self._available is not None:
            return self._available
        try:
            r = self._http().get(f"{self.base_url}/api/tags", timeout=4)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            self._available = any(n.split(":")[0] == self.model.split(":")[0] for n in names)
        except Exception:
            self._available = False
        return self._available

    def ask(self, question: str, timeout: int = 150) -> str:
        """截取当前屏幕，让视觉模型回答问题"""
        if pyautogui is None:
            return "错误: pyautogui 不可用，无法截屏"
        if not self.is_available():
            return ("错误: 视觉模型未就绪。请执行 ollama create 导入 qwen-vl "
                    "多模态模型后重试；本任务可改用 list_ui_elements 等方式完成")
        try:
            img = pyautogui.screenshot()
        except Exception as e:
            return f"错误: 截屏失败 - {e}"

        # 缩到 1280 宽，控制传输与推理耗时
        w, h = img.size
        if w > 1280:
            img = img.resize((1280, int(h * 1280 / w)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()

        try:
            r = self._http().post(
                f"{self.base_url}/api/chat",
                json={"model": self.model,
                      "messages": [{"role": "user", "content": question, "images": [b64]}],
                      "stream": False, "options": {"temperature": 0.1}},
                timeout=timeout)
            r.raise_for_status()
            text = r.json().get("message", {}).get("content", "").strip()
            return text or "视觉模型没有返回内容"
        except Exception as e:
            return f"错误: 视觉分析失败 - {e}"


# ============================ 2. 窗口管理 ============================

_user32 = ctypes.windll.user32


def _enum_windows():
    """枚举可见的、有标题的、有实际尺寸的顶层窗口 [(title, (l,t,r,b), hwnd)]"""
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            n = _user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, buf, n + 1)
                r = ctypes.wintypes.RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(r))
                if r.right - r.left > 60 and r.bottom - r.top > 60:
                    out.append((buf.value, (r.left, r.top, r.right, r.bottom), hwnd))
        return True

    _user32.EnumWindows(cb, 0)
    return out


def list_visible_windows() -> str:
    """列出所有可见窗口：标题 + 位置 + 是否当前活动窗口"""
    fg = _user32.GetForegroundWindow()
    lines = []
    for title, rect, hwnd in _enum_windows():
        mark = " ←当前" if hwnd == fg else ""
        lines.append(f"- {title}  位置{rect}{mark}")
    if not lines:
        return "没有可见窗口"
    return "当前可见窗口：\n" + "\n".join(lines)


def focus_window(title: str) -> str:
    """按标题模糊匹配并把窗口切到前台"""
    targets = [(t, h) for t, _r, h in _enum_windows() if title.lower() in t.lower()]
    if not targets:
        return (f"错误: 找不到标题包含「{title}」的窗口。"
                f"可先用 list_windows 查看现有窗口")
    if len(targets) > 1:
        names = "、".join(t for t, _ in targets[:5])
        return f"匹配到多个窗口: {names}，请用更完整的标题"
    title_, hwnd = targets[0]
    _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    return f"已将窗口「{title_}」切到前台"


# ============================ 3. UIA 元素级操作 ============================

UIA_TYPES = ("Button", "MenuItem", "Edit", "Document", "CheckBox",
             "RadioButton", "ComboBox", "ListItem", "TabItem", "Hyperlink")


def _pywinauto_desktop():
    """延迟导入 pywinauto（导入较慢，且 exe 环境可能缺失）"""
    try:
        from pywinauto import Desktop
        return Desktop(backend="uia")
    except ImportError:
        return None


def _find_window_wrapper(desktop, title=None):
    """按标题模糊找窗口；不传标题则取当前前台窗口"""
    wins = [w for w in desktop.windows() if w.is_visible()]
    if title:
        for w in wins:
            if title.lower() in w.window_text().lower():
                return w, None
        names = "、".join(w.window_text() for w in wins[:6])
        return None, f"错误: 找不到窗口「{title}」。可见窗口有: {names}"
    # 取前台窗口标题来匹配
    fg = _user32.GetForegroundWindow()
    n = _user32.GetWindowTextLengthW(fg)
    buf = ctypes.create_unicode_buffer(n + 1) if n else ctypes.create_unicode_buffer(2)
    _user32.GetWindowTextW(fg, buf, n + 1) if n else None
    for w in wins:
        if w.window_text() == buf.value:
            return w, None
    return (wins[0], None) if wins else (None, "错误: 没有可见窗口")


def list_ui_elements(window_title: str = "", limit: int = 40) -> str:
    """列出窗口内可操作控件（类型/名称/精确坐标）——元素级定位的主力工具"""
    desktop = _pywinauto_desktop()
    if desktop is None:
        return "错误: pywinauto 未安装，元素级操作不可用"
    win, err = _find_window_wrapper(desktop, window_title or None)
    if err:
        return err
    try:
        found = []
        for ctype in UIA_TYPES:
            try:
                found.extend(win.descendants(control_type=ctype))
            except Exception:
                pass
        if not found:
            return (f"窗口「{win.window_text()}」中没有发现标准控件"
                    f"（可能是自绘界面），建议改用 analyze_screen 了解界面内容")
        lines = [f"窗口「{win.window_text()}」的可操作控件："]
        seen = set()
        count = 0
        for c in found:
            if count >= limit:
                lines.append(f"…（还有更多，可缩小窗口范围或指定更具体的控件类型）")
                break
            try:
                txt = c.window_text().strip()
                r = c.rectangle()
                if not txt or r.width() <= 0:
                    continue
                key = (txt, r.left, r.top)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- [{c.element_info.control_type}] {txt}  中心({(r.left + r.right) // 2},{(r.top + r.bottom) // 2})")
                count += 1
            except Exception:
                continue
        return "\n".join(lines) if count else "未发现带名称的可操作控件"
    except Exception as e:
        return f"错误: 控件枚举失败 - {e}"


def click_ui_element(window_title: str, name: str) -> str:
    """按名称点击窗口内的控件——最可靠的点击方式（精确匹配→包含匹配）"""
    desktop = _pywinauto_desktop()
    if desktop is None:
        return "错误: pywinauto 未安装，元素级操作不可用"
    win, err = _find_window_wrapper(desktop, window_title or None)
    if err:
        return err
    try:
        candidates = []
        for ctype in UIA_TYPES:
            try:
                candidates.extend(win.descendants(control_type=ctype))
            except Exception:
                pass
        exact = [c for c in candidates if c.window_text().strip() == name]
        partial = [c for c in candidates
                   if name.lower() in c.window_text().strip().lower()
                   and c not in exact]
        target_list = exact or partial
        target_list = [c for c in target_list if c.rectangle().width() > 0]
        if not target_list:
            if not candidates:
                return (f"错误: 窗口「{win.window_text()}」没有任何可枚举的标准控件"
                        f"（自绘界面）。不要再用 click_ui_element，改用 analyze_screen "
                        f"看清界面后用 click(x,y) 坐标点击")
            names = "、".join({c.window_text().strip() for c in candidates
                               if c.window_text().strip()})[:200]
            return (f"错误: 窗口「{win.window_text()}」中找不到名为「{name}」的控件。"
                    f"现有控件: {names}")
        target = target_list[0]
        if exact:
            pass
        elif len(target_list) > 1:
            names = "、".join({c.window_text().strip() for c in target_list[:6]})
            return f"「{name}」匹配到多个控件: {names}，请用更完整的名称"
        clicked_name = target.window_text().strip() or name  # 先存名字：点击可能销毁窗口
        try:
            target.set_focus()
            target.click_input()
        except Exception as e:
            return f"错误: 点击「{clicked_name}」时失败 - {e}"
        time.sleep(0.5)
        return f"已点击「{clicked_name}」"
    except Exception as e:
        return f"错误: 点击失败 - {e}"


# ============================ 4. 剪贴板 ============================

def clipboard_read() -> str:
    try:
        import pyperclip
        text = pyperclip.paste()
        return text if text else "剪贴板为空"
    except Exception as e:
        return f"错误: 读取剪贴板失败 - {e}"


def clipboard_write(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        preview = text if len(text) <= 50 else text[:50] + "…"
        return f"已写入剪贴板: {preview}"
    except Exception as e:
        return f"错误: 写入剪贴板失败 - {e}"


# ============================ 便捷入口 ============================

_screen_vision = None


def get_vision() -> ScreenVision:
    global _screen_vision
    if _screen_vision is None:
        _screen_vision = ScreenVision()
    return _screen_vision


def analyze_screen(question: str) -> str:
    return get_vision().ask(question)
