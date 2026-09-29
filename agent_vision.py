"""agent_vision.py - 顶级电脑操作 agent 的核心扩展能力包

对标 Computer Use 类 agent 的能力分层：
1. 视觉理解   analyze_screen     —— 看懂屏幕（默认走云端，回答"屏幕上有什么/某应用开没开"）
2. 窗口管理   list_windows / focus_window —— 枚举并前置窗口（ctypes，零依赖）
3. 元素级操作 list_ui_elements / click_ui_element —— Windows UIA 控件树，
   拿到控件真实名字与精确坐标，比"看图猜坐标"可靠得多
4. 剪贴板    clipboard_read / clipboard_write

★ 视觉模型为什么换（2026-09-28）：
本机 Ollama 的 qwen-vl 实测看一张屏要 107 秒，而原来的等待上限只有 90 秒 ——
也就是说「看屏幕」在本机这条路上**注定超时**。改用云端免费视觉模型后
（glm-4v-flash + 1600 宽，实测 1.1~4.6 秒），快了两个数量级，认界面也更准。
云端不可用时自动回退本机 qwen-vl，不至于两手空空。
注意：云端模式会把截图上传到所选服务商。
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
VISION_MODEL = "qwen-vl"              # 本机兜底模型（Ollama）
VISION_CLOUD_MODEL = "glm-4v-flash"   # 云端默认视觉模型（智谱，免费）
VISION_WIDTH = 1600                   # 送模型前的缩放宽度


def _vision_config() -> dict:
    """读取设置里的视觉后端配置；任何异常都退回「只用本机」。"""
    cfg = {"mode": "local", "width": VISION_WIDTH, "timeout": 45,
           "cloud_base_url": "", "cloud_api_key": "", "cloud_model": "",
           "cloud_provider": ""}
    try:
        from core.settings import Settings, resolve_api_key, VISION_MODEL_PRESETS
        settings = Settings()
        vis = settings.get("vision", {}) or {}
        cloud = settings.get("cloud", {}) or {}
        provider = cloud.get("provider", "zhipu")
        key, _src = resolve_api_key(cloud)
        cfg.update({
            "mode": str(vis.get("mode") or "auto").lower(),
            "width": int(vis.get("width") or VISION_WIDTH),
            "timeout": int(vis.get("timeout") or 45),
            "cloud_provider": provider,
            "cloud_base_url": str(cloud.get("base_url") or "").rstrip("/"),
            "cloud_api_key": key,
            "cloud_model": (vis.get("cloud_model")
                            or VISION_MODEL_PRESETS.get(provider, "")
                            or VISION_CLOUD_MODEL),
        })
    except Exception:
        pass
    return cfg


# ============================ 1. 视觉理解 ============================

class ScreenVision:
    """看懂屏幕。只做“理解”，不做坐标定位
    （小参数模型的 grounding 噪声大，定位交给 UIA 控件树）。

    默认走云端视觉模型（快），云端没配好或调用失败时自动回退本机 qwen-vl。
    ★ 云端模式下截图会上传到所选服务商，这是“用云端”的代价，界面须如实提示。
    """

    def __init__(self, base_url: str = OLLAMA_URL, model: str = VISION_MODEL,
                 cfg: dict = None):
        self.base_url = base_url
        self.model = model
        self.cfg = cfg if cfg is not None else _vision_config()
        self._session = None
        self._available = None  # None=未知

    def _http(self):
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False  # 出网统一策略（SEC-P1-2）：本地/云端共用此会话，绕过环境变量与系统代理
        return self._session

    # ---------------- 后端选择 ----------------

    @property
    def backend(self) -> str:
        """当前实际会用哪个后端：cloud / local

        - mode=local → 永远本机
        - mode=cloud → 云端（没配 Key 也走云端，让报错说清原因，别偷偷变慢）
        - mode=auto  → 云端配好了就走云端，否则本机
        """
        mode = self.cfg.get("mode", "auto")
        cloud_ready = bool(self.cfg.get("cloud_api_key")
                           and self.cfg.get("cloud_base_url"))
        if mode == "local":
            return "local"
        if mode == "cloud":
            return "cloud"
        return "cloud" if cloud_ready else "local"

    def describe(self) -> str:
        """一句话说明「看屏幕」走哪条路（供界面/日志显示）"""
        if self.backend == "cloud":
            return f"云端 · {self.active_model}"
        return f"本机 · {self.active_model}"

    @property
    def active_model(self) -> str:
        """当前后端实际会用的模型名"""
        if self.backend == "cloud":
            return self.cfg.get("cloud_model") or VISION_CLOUD_MODEL
        return self.model

    def is_available(self) -> bool:
        """当前后端的视觉能力是否就绪（结果缓存，避免重复探测）

        cloud：只看有没有配好 Key 与地址（不发请求，秒回）
        local：查 Ollama 的 /api/tags 里有没有这个模型
        """
        if self.backend == "cloud":
            return bool(self.cfg.get("cloud_api_key")
                        and self.cfg.get("cloud_base_url"))
        if self._available is not None:
            return self._available
        try:
            r = self._http().get(f"{self.base_url}/api/tags", timeout=4)
            r.raise_for_status()
            names = [m.get("name", "") for m in r.json().get("models", [])]
            self._available = any(n.split(":")[0] == self.model.split(":")[0]
                                  for n in names)
        except Exception:
            self._available = False
        return self._available

    # ---------------- 主流程 ----------------

    def ask(self, question: str, timeout: int = None) -> str:
        """截取当前屏幕，让视觉模型回答问题"""
        if pyautogui is None:
            return "错误: pyautogui 不可用，无法截屏"
        try:
            img = pyautogui.screenshot()
        except Exception as e:
            return f"错误: 截屏失败 - {e}"
        b64 = self._encode(img)
        limit = timeout or int(self.cfg.get("timeout") or 45)

        if self.backend == "cloud":
            text, err = self._ask_cloud(question, b64, limit)
            if err is None:
                return text
            # 自动模式：云端失败就换本机，别让整个任务卡死在这一步
            if self.cfg.get("mode", "auto") == "auto":
                fallback, ferr = self._ask_local(question, b64, timeout=90)
                if ferr is None:
                    return (f"{fallback}\n（云端看屏幕失败，已改用本机模型；"
                            f"原因：{err}）")
                return (f"错误: 看屏幕失败。云端：{err}；本机：{ferr}。"
                        f"可改用 list_windows / list_ui_elements 等不看屏的方式")
            return f"错误: 云端看屏幕失败 - {err}"
        text, err = self._ask_local(question, b64, timeout=limit)
        return text if err is None else f"错误: 看屏幕失败 - {err}"

    def _encode(self, img) -> str:
        """按设置里的宽度缩放后编码为 base64 JPEG（宽度不够会看不清界面文字）"""
        width = int(self.cfg.get("width") or VISION_WIDTH)
        w, h = img.size
        if width and w > width:
            img = img.resize((width, int(h * width / w)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    def _ask_cloud(self, question: str, b64: str, timeout: int) -> tuple:
        """云端（OpenAI 兼容 /chat/completions），返回 (文本, 错误或 None)"""
        key = self.cfg.get("cloud_api_key")
        base = self.cfg.get("cloud_base_url") or ""
        if not key:
            return "", "未配置云端 API Key（在「设置 → 云端模型」里填，或设环境变量）"
        if not base:
            return "", "未配置云端接口地址"
        payload = {
            "model": self.active_model,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]}],
        }
        try:
            # 云端路径复用 _http()（trust_env=False）：用户开着代理软件时截图上传
            # 不被路由进失效/劫持的代理——"看屏幕莫名失败而聊天正常"的根因就在这类裸调用
            r = self._http().post(f"{base}/chat/completions",
                                  headers={"Authorization": f"Bearer {key}"},
                                  json=payload, timeout=timeout)
            if r.status_code != 200:
                return "", f"HTTP {r.status_code} {r.text[:120]}"
            data = r.json()
            text = (data["choices"][0]["message"].get("content") or "").strip()
            return (text or "视觉模型没有返回内容"), None
        except requests.exceptions.Timeout:
            return "", f"超时（{timeout} 秒）"
        except requests.exceptions.ConnectionError as e:
            return "", f"连不上服务商（{str(e)[:80]}）"
        except Exception as e:
            return "", f"{type(e).__name__}: {str(e)[:100]}"

    def _ask_local(self, question: str, b64: str, timeout: int = 90) -> tuple:
        """本机 Ollama，返回 (文本, 错误或 None)"""
        if not self.is_available():
            return "", ("本机视觉模型未就绪（Ollama 里没有 qwen-vl）——"
                        "可执行 ollama create 导入，或改用云端视觉")
        try:
            r = self._http().post(
                f"{self.base_url}/api/chat",
                json={"model": self.model,
                      "messages": [{"role": "user", "content": question,
                                    "images": [b64]}],
                      "stream": False, "options": {"temperature": 0.1}},
                timeout=timeout)
            r.raise_for_status()
            text = r.json().get("message", {}).get("content", "").strip()
            return (text or "视觉模型没有返回内容"), None
        except requests.exceptions.Timeout:
            return "", f"本机视觉超时（{timeout} 秒，CPU 推理很慢）"
        except Exception as e:
            return "", f"{type(e).__name__}: {str(e)[:100]}"


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


def _menu_popups():
    """当前打开的 Win32 菜单弹窗（#32768 独立顶层窗口，不在主窗口控件树里）。

    点开「格式」这类菜单后，菜单项必须来这里找——记事本格式→字体 即此场景。
    """
    pops = []
    try:
        from pywinauto import Application, Desktop
        for w in Desktop(backend="win32").windows(class_name="#32768"):
            try:
                if not w.is_visible():
                    continue
                app = Application(backend="uia").connect(handle=w.handle, timeout=1)
                pops.append(app.window(handle=w.handle))
            except Exception:
                continue
    except Exception:
        pass
    return pops


def _menu_items_win32(hwnd):
    """经典 Win32 菜单树（无需点开菜单）：[(文本, 命令ID, 完整路径)]。

    pywinauto 两个后端都枚举不到 #32768 菜单弹窗，这里直接走 GetMenu API，
    是「格式→字体」这类经典菜单唯一可靠的枚举/点击通道。
    """
    u32 = ctypes.windll.user32
    root = u32.GetMenu(hwnd)
    if not root:
        return []
    out = []

    def menu_text(hmenu, i):
        n = u32.GetMenuStringW(hmenu, i, None, 0, 0x400)  # MF_BYPOSITION
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetMenuStringW(hmenu, i, buf, n + 1, 0x400)
        return buf.value

    def walk(hmenu, path):
        count = u32.GetMenuItemCount(hmenu)
        if count <= 0:
            return
        for i in range(count):
            text = menu_text(hmenu, i).split("\t")[0]  # 去掉快捷键后缀，展示更干净
            sub = u32.GetSubMenu(hmenu, i)
            nid = u32.GetMenuItemID(hmenu, i)
            if text:
                out.append((text, nid, " → ".join(path + [text])))
            if sub and len(path) < 3:
                walk(sub, path + [text])

    walk(root, [])
    return out


def list_ui_elements(window_title: str = "", limit: int = 40) -> str:
    """列出窗口内可操作控件（类型/名称/精确坐标）——元素级定位的主力工具"""
    desktop = _pywinauto_desktop()
    if desktop is None:
        return "错误: pywinauto 未安装，元素级操作不可用"
    win, err = _find_window_wrapper(desktop, window_title or None)
    if err:
        return err
    pops = _menu_popups()  # 打开中的菜单弹窗（如 记事本 格式→字体）
    try:
        found = []
        for ctype in UIA_TYPES:
            try:
                found.extend(win.descendants(control_type=ctype))
            except Exception:
                pass
        if not found and not pops:
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
        # 打开中的菜单：菜单项单独列出（主窗口控件树里看不到）
        for p in pops:
            try:
                items = p.descendants(control_type="MenuItem")
            except Exception:
                continue
            menu_lines = []
            for it in items:
                try:
                    txt = it.window_text().strip()
                    r = it.rectangle()
                    if not txt or r.width() <= 0:
                        continue
                    menu_lines.append(
                        f"- [MenuItem] {txt}  中心({(r.left + r.right) // 2},{(r.top + r.bottom) // 2})")
                except Exception:
                    continue
            if menu_lines:
                lines.append("打开的菜单里的项（可直接 click_ui_element 点击）：")
                lines.extend(menu_lines[:15])
        # 经典菜单树（GetMenu API）：无需点开菜单即可列出全部层级
        try:
            tree_lines = [f"- [Menu] {path}"
                          for _t, _nid, path in _menu_items_win32(win.handle)[:20]]
        except Exception:
            tree_lines = []
        if tree_lines:
            lines.append("窗口菜单（click_ui_element 可直接点，无需先点开菜单）：")
            lines.extend(tree_lines)
        return "\n".join(lines) if lines else "未发现带名称的可操作控件"
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
            # 经典菜单项（如 记事本 格式→字体）：直接发菜单命令，无需点开菜单
            try:
                menu_items = _menu_items_win32(win.handle)
            except Exception:
                menu_items = []
            for match_exact in (True, False):
                for text, nid, path in menu_items:
                    if match_exact:
                        hit = text.strip() == name
                    else:
                        hit = name.lower() in text.lower()
                    if not hit or nid in (0, -1, 0xFFFF, 0xFFFFFFFF):
                        continue  # 分隔符/子菜单目录项没有命令 ID
                    try:
                        ctypes.windll.user32.PostMessageW(
                            win.handle, 0x111, nid, 0)  # WM_COMMAND
                    except Exception as e:
                        return f"错误: 菜单命令「{path}」发送失败 - {e}"
                    time.sleep(0.6)
                    return f"已通过菜单命令点击「{path}」"
            # 菜单树没有 → 找打开中的菜单弹窗（动态菜单/上下文菜单）
            for p in _menu_popups():
                try:
                    items = p.descendants(control_type="MenuItem")
                except Exception:
                    continue
                m_exact = [c for c in items if c.window_text().strip() == name]
                m_part = [c for c in items
                          if name.lower() in c.window_text().strip().lower()]
                m_list = m_exact or m_part
                m_list = [c for c in m_list if c.rectangle().width() > 0]
                if m_list:
                    tgt = m_list[0]
                    clicked_name = tgt.window_text().strip() or name
                    try:
                        tgt.click_input()
                    except Exception as e:
                        return f"错误: 点击菜单项「{clicked_name}」时失败 - {e}"
                    time.sleep(0.5)
                    return f"已点击菜单项「{clicked_name}」"
            if not candidates:
                return (f"错误: 窗口「{win.window_text()}」没有任何可枚举的标准控件"
                        f"（自绘界面）。不要再用 click_ui_element，改用 analyze_screen "
                        f"看清界面后用 click(x,y) 坐标点击")
            names = "、".join({c.window_text().strip() for c in candidates
                               if c.window_text().strip()})[:200]
            return (f"错误: 窗口「{win.window_text()}」中找不到名为「{name}」的控件。"
                    f"现有控件: {names}。"
                    f"若该项在某个菜单里，请先点开所在菜单，再重新 list_ui_elements 查看")
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


def reset_vision():
    """设置改动后调用：下次用新的视觉配置（换后端/换模型/换宽度）"""
    global _screen_vision
    _screen_vision = None


def vision_status() -> str:
    """给界面看的一句话状态：走云端还是本机、用的哪个模型、是否就绪"""
    v = get_vision()
    return f"{v.describe()}（{'就绪' if v.is_available() else '未就绪'}）"


def analyze_screen(question: str) -> str:
    return get_vision().ask(question)
