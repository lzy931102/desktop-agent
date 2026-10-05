"""动作后校验：每步关键操作后验证是否真的生效，失败信号会触发重试。

可验证的动作：
- open_app  → 枚举窗口做差集，确认"新"应用窗口已出现（T30；
              无动作前快照时退回存在性检查）
- click     → 前后截图对比，确认界面发生了变化（best-effort，无变化仅警告）；
              点在控件上（Button/MenuItem 等，REL-P1-4）走强校验：
              UIA 断言目标元素/焦点变化，确定落空才触发重试，
              分级与回退见 verify_click_strong 与 docs/verify_click收紧设计-2026-09-30.md
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


def _enum_visible_windows() -> list:
    """全部可见顶层窗口的 (hwnd, 标题) 列表（T30 差集校验用）"""
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
                out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _window_titles() -> list:
    return [title for _hwnd, title in _enum_visible_windows()]


def snapshot_windows() -> list:
    """动作前窗口快照 [(hwnd, 标题), ...]（T30：open_app 前取，供差集校验）"""
    return _enum_visible_windows()


def _is_new_app_window(current: list, pre_windows: list,
                       hints: tuple, key: str) -> bool:
    """快照之外新出现的 hwnd 里，有没有标题命中 hints/key 的（T30 差集）。

    按 hwnd 差集而不是标题差集：已有窗口的标题变化（如记事本的 * 未保存
    标记是异步刷新的）不得误判成"新窗口"——2026-10-05 手动验证实测。"""
    pre_hwnds = {hwnd for hwnd, _title in pre_windows}
    return any(any(h.lower() in title.lower() for h in hints if h)
               or key in title.lower()
               for hwnd, title in current if hwnd not in pre_hwnds)


# open_app 白名单里 exe 名 → 常见窗口标题关键词
_APP_TITLE_HINTS = {
    "notepad.exe": ["记事本", "notepad"],
    "calc.exe": ["计算器", "calculator"],
    "cmd.exe": ["cmd", "命令提示符"],
    # explorer 窗口标题以"文件资源管理器"结尾（发现 G②：修复前此列表为空、
    # 回退的 exe 名匹配也命不中中文标题，open_app("explorer") 的校验
    # 永远假阴性，诱导模型重开出双窗口歧义）
    "explorer.exe": ["文件资源管理器", "资源管理器", "explorer"],
    "mspaint.exe": ["画图", "paint"],
    "control.exe": ["控制面板", "control"],
    "taskmgr.exe": ["任务管理器"],
    "snippingtool.exe": ["截图"],
}


def verify_open_app(app_name: str, attempts: int = 4,
                    interval: float = 1.0, pre_windows: list = None) -> tuple:
    """确认打开应用后窗口已出现。

    T30 差集：调用方在 open_app 动作前用 snapshot_windows() 取快照传入
    （pre_windows），只有"新出现的 hwnd 且标题命中"才算打开成功——修复前
    只查"屏幕上有没有"，用户自己开着的同名窗口就能让校验假阳性通过
    （2026-10-05 实录：新窗口没出现、type_text 盲粘进了用户已有窗口，
    校验却报"窗口已出现"）。无快照时（旧调用方/直调）退回存在性检查。

    轮询等待（发现 G②）：应用冷启动要数秒才出窗口，修复前只查一次，
    explorer 实测每次误报"未检测到应用窗口"。最多等 attempts×interval 秒，
    任一轮命中即通过；仍然未命中才判失败。"""
    key = app_name.strip().lower()
    hints = None
    for exe, words in _APP_TITLE_HINTS.items():
        if key == exe[:-4] or key == exe:
            hints = words
            break
    if hints is None:
        hints = [app_name]
    for i in range(attempts):
        if pre_windows is not None:
            if _is_new_app_window(_enum_visible_windows(), pre_windows,
                                  hints, key):
                return True, "新窗口已出现"
        else:
            titles = _window_titles()
            joined = " ".join(titles).lower()
            if any(h.lower() in joined for h in hints if h) or \
                    any(key in t.lower() for t in titles):
                return True, "窗口已出现"
        if i < attempts - 1:
            time.sleep(interval)
    if pre_windows is not None:
        return False, "未检测到新窗口——可能只聚焦了已有窗口，并未新开"
    return False, "未检测到应用窗口"


def _small_gray(img):
    return img.convert("L").resize((256, 144))


def _pixel_changed(before_img, threshold: float = 0.004) -> tuple:
    """点击前后截图对比。返回 (ok, detail)：ok ∈ True/False/None，
    None 表示比对自身失败（截图/比对异常），由调用方决定兜底方式。"""
    try:
        after = pyautogui.screenshot()
        diff = ImageChops.difference(_small_gray(before_img), _small_gray(after))
        hist = diff.histogram()
        total = sum(hist)
        changed = sum(hist[8:])  # 像素差 > 8 视为变化
        ratio = changed / max(total, 1)
        if ratio >= threshold:
            return True, f"界面已变化（差异 {ratio:.1%}）"
        return False, f"界面无变化（差异 {ratio:.1%}）"
    except Exception as e:
        return None, f"像素比对跳过: {e}"


def verify_click(before_img, threshold: float = 0.004) -> tuple:
    """点击后截图对比：界面有变化即通过（best-effort，非关键点击路径）"""
    time.sleep(1.2)  # 给界面反应时间
    ok, detail = _pixel_changed(before_img, threshold)
    if ok is None:
        return True, detail  # 校验自身失败不阻塞主流程
    if ok:
        return True, detail
    return False, f"{detail}，点击可能未生效"


# ---- 关键点击强校验（REL-P1-4，docs/verify_click收紧设计-2026-09-30.md） ----

# 点下去应当产生可观测效果的目标控件类型；之外的（Pane/Document/空白等）
# 没有可靠的控件级断言，维持像素校验
_CRITICAL_CONTROL_TYPES = {"Button", "MenuItem", "CheckBox", "RadioButton",
                           "Hyperlink", "ListItem", "TabItem", "TreeItem",
                           "DataItem"}


def _runtime_id(el):
    """UIA runtime id 统一成 list（跨查询可比较）；取不到返回 None（无信号）。

    el 兼容两种形态：原始 IUIAutomationElement（GetRuntimeId 方法）与
    UIAElementInfo 包装对象（runtime_id 属性，COMError 时回落 0——按无效处理）。
    实机教训：方法在原始元素上，包装对象没有——两种形态都必须能取（任务 17）。
    """
    try:
        rid = el.GetRuntimeId()              # 原始 COM 元素
    except AttributeError:
        try:
            rid = el.runtime_id              # UIAElementInfo 包装对象
        except Exception:
            return None
    except Exception:
        return None
    if rid is None or rid == 0:              # 0 是属性层 COMError 的哨兵值
        return None
    try:
        return list(rid)
    except TypeError:
        return None


def capture_click_target(x, y):
    """click 前采集点击目标（UIA ElementFromPoint），决定校验档位。

    返回 (status, info)：
    - ("critical", info)   点在可观测控件上 → 走强校验（verify_click_strong）
    - ("plain", None)      非控件目标 → 维持像素校验（现行为）
    - ("unavailable", 原因) UIA 不可用/查询失败 → 像素校验并标注弱校验

    pywinauto API 面刻意最小化：只用 ElementFromPoint + GetFocusedElement +
    runtime_id（见设计文档第 3 节）。
    """
    try:
        from pywinauto.uia_element_info import UIAElementInfo
        from pywinauto.uia_defines import IUIA
        el = UIAElementInfo.from_point(x, y)
        if el is None or el.control_type not in _CRITICAL_CONTROL_TYPES:
            return "plain", None
        rid = _runtime_id(el)
        if rid is None:
            return "plain", None
        try:
            focused = IUIA().get_focused_element()
            focused_rid = _runtime_id(focused) if focused else None
        except Exception:
            focused_rid = None
        info = {"x": x, "y": y, "runtime_id": rid,
                "control_type": el.control_type, "name": el.name or "",
                "was_focused": focused_rid is not None
                               and focused_rid == rid}
        return "critical", info
    except Exception as e:
        return "unavailable", f"{type(e).__name__}: {e}"[:80]


def verify_click_strong(info: dict, before_img, threshold: float = 0.004) -> tuple:
    """关键点击的强校验。判定矩阵见 docs/verify_click收紧设计-2026-09-30.md 第 5 节：

    1. 任一强信号成立 → (True, 强校验…, "strong")：目标元素消失/被替换
       （如确认弹窗关闭）或键盘焦点迁移到目标控件（对动画免疫）；
    2. 强信号均不成立 + 像素无变化 → (False, …, "fail")：确定落空，
       交由既定重试策略（此时重试无双击风险——第一次什么都没触发）；
    3. 强信号均不成立 + 像素有变化 → (True, 弱校验…, "weak")：可能来自
       动画/计时器，不自动重试（防重复提交），标注交回模型；
    4. after 阶段元素断言不可用 → 回退纯像素判定并标注弱校验。
    """
    time.sleep(1.2)  # 与 verify_click 相同的界面反应窗口

    element_changed = None   # None = after 阶段查询失败（断言不可用）
    focus_moved = None
    try:
        from pywinauto.uia_element_info import UIAElementInfo
        el2 = UIAElementInfo.from_point(info["x"], info["y"])
        rid2 = _runtime_id(el2) if el2 is not None else None
        element_changed = None if rid2 is None else rid2 != info["runtime_id"]
    except Exception:
        pass
    if info["was_focused"]:
        focus_moved = False  # 点击前焦点已在目标上：无迁移信号可言
    else:
        try:
            from pywinauto.uia_defines import IUIA
            focused = IUIA().get_focused_element()
            focused_rid = _runtime_id(focused) if focused else None
            focus_moved = (focused_rid is not None
                           and focused_rid == info["runtime_id"])
        except Exception:
            pass

    if element_changed or focus_moved:
        signal = ("目标元素已消失/被替换" if element_changed
                  else "键盘焦点已迁移到目标控件")
        return True, f"强校验通过：{signal}", "strong"

    pixel_ok, pixel_detail = _pixel_changed(before_img, threshold)

    if element_changed is None:
        # 元素级断言不可用 → 回退现行为（像素判定）并标注弱校验（设计 5.4）
        if pixel_ok:
            return True, (f"弱校验（UIA 元素断言不可用，回退像素比对）："
                          f"{pixel_detail}"), "weak"
        if pixel_ok is None:
            return True, "弱校验（UIA 与像素比对均不可用，跳过）", "weak"
        return False, (f"弱校验（UIA 元素断言不可用，回退像素比对）："
                       f"{pixel_detail}，点击可能未生效"), "fail"

    if pixel_ok:
        return (True, "弱校验：目标控件无变化，仅界面像素有变化"
                      "（可能来自动画/计时器，不作为点击落地证据）", "weak")
    if pixel_ok is None:
        return True, "弱校验：UIA 无信号且像素比对不可用", "weak"
    return False, "强校验失败：目标控件无变化且界面无像素变化，点击确定落空", "fail"


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


# ====================== 消息发送验证（三态） ======================

def check_message_sent(expected_text: str) -> tuple:
    """验证"消息是否真的发出"。

    借助本地视觉模型读当前聊天窗口，判断最新消息是否包含预期文本。
    返回 (status, detail)：status ∈
      "sent"     已确认消息出现在聊天窗口
      "unclear"  无法确认（视觉不可用/看不清）——调用方不得声称任务完成
      "failed"   确认聊天窗口中没有该消息
    """
    from agent_vision import get_vision  # 延迟导入避免循环依赖
    vision = get_vision()
    if not vision.is_available():
        return "unclear", "视觉模型未就绪，无法确认消息是否发出"
    q = ("请看屏幕上的聊天窗口。判断最新一条发出的消息是否包含这段文字："
         f"「{expected_text}」。"
         "只输出三个词之一：SENT（确认已发出且能看到）、"
         "UNCLEAR（看不清或无法判断）、NOT_SENT（确认没有发出）。")
    answer = vision.ask(q).strip().upper()
    if "SENT" in answer and "NOT_SENT" not in answer:
        return "sent", "已确认：消息出现在聊天窗口中"
    if "NOT_SENT" in answer:
        return "failed", "已确认：聊天窗口中没有看到该消息，消息可能未发出"
    return "unclear", "视觉模型无法确认消息是否发出，请人工检查"
