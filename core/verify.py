"""动作后校验：每步关键操作后验证是否真的生效，失败信号会触发重试。

可验证的动作：
- open_app  → 枚举窗口，确认应用窗口已出现
- click     → 前后截图对比，确认界面发生了变化（best-effort，无变化仅警告）
- clipboard_write → 回读剪贴板比对
- screenshot / 保存文件 → 检查文件是否存在
其余动作（输入、按键等）没有可靠的本地验证手段，标记 skip 不阻塞流程。
"""
import os
import time

if os.name == "nt":
    import pyautogui
    from PIL import ImageChops

    _user32 = __import__("ctypes").windll.user32


def _window_titles() -> list:
    out = []

    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _l):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                out.append(buf.value)
        return True

    user32.EnumWindows(cb, 0)
    return out


# open_app 白名单里 exe 名 → 常见窗口标题关键词
_APP_TITLE_HINTS = {
    "notepad.exe": ["记事本", "notepad"],
    "calc.exe": ["计算器", "calculator"],
    "cmd.exe": ["cmd", "命令提示符"],
    "explorer.exe": [],  # 文件管理器标题随目录变化，靠 exe 名兜底
    "mspaint.exe": ["画图", "paint"],
    "control.exe": ["控制面板", "control"],
    "taskmgr.exe": ["任务管理器"],
    "snippingtool.exe": ["截图"],
}


def verify_open_app(app_name: str) -> tuple:
    """确认打开应用后窗口已出现"""
    titles = " ".join(_window_titles()).lower()
    hints = None
    key = app_name.strip().lower()
    for exe, words in _APP_TITLE_HINTS.items():
        if key == exe[:-4] or key == exe:
            hints = words
            break
    if hints is None:
        hints = [app_name]
    hit = any(h.lower() in titles for h in hints if h) or \
          any(key in t.lower() for t in _window_titles())
    return (True, "窗口已出现") if hit else (False, "未检测到应用窗口")


def _small_gray(img):
    return img.convert("L").resize((256, 144))


def verify_click(before_img, threshold: float = 0.004) -> tuple:
    """点击后截图对比：界面有变化即通过（best-effort）"""
    try:
        time.sleep(1.2)  # 给界面反应时间
        after = pyautogui.screenshot()
        diff = ImageChops.difference(_small_gray(before_img), _small_gray(after))
        hist = diff.histogram()
        total = sum(hist)
        changed = sum(hist[8:])  # 像素差 > 8 视为变化
        ratio = changed / max(total, 1)
        if ratio >= threshold:
            return True, f"界面已变化（差异 {ratio:.1%}）"
        return False, f"界面无变化（差异 {ratio:.1%}），点击可能未生效"
    except Exception as e:
        return True, f"校验跳过: {e}"  # 校验自身失败不阻塞主流程


def verify_file_exists(path: str) -> tuple:
    if os.path.isfile(path):
        return True, f"文件已生成: {path}"
    return False, f"文件不存在: {path}"


def verify_clipboard(expected: str) -> tuple:
    try:
        import pyperclip
        return (True, "剪贴板一致") if pyperclip.paste() == expected else \
               (False, "剪贴板内容与预期不符")
    except Exception as e:
        return True, f"校验跳过: {e}"
