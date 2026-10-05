"""T31/T32 记事本会话恢复防护回归测试。

背景（2026-10-05 用户 exe 验收实测，audit 铁证）：Win11 记事本「启动时
恢复上次会话」会把未保存文档放进新开窗口的激活标签——Agent open_app
后 type_text 的粘贴进了用户的旧文档：
  - 15:15:46 回显「已输入到「*你好你好 - Notepad」」（旧文档已有 1 份"你好"）
  - 15:16:08 回显「已输入到「*你好你好你好 - Notepad」」（叠了 3 份）
T30 的焦点校验是窗口级的（窗口对就放行），防不住窗口内恢复的旧标签。
判别信号：恢复标签未保存，窗口标题带 * 前缀（探针三次实测一致）；
Agent 刚 open_app 的干净记事本标题是「无标题 - Notepad」（无 *）。

T32 改无条件方案（2026-10-05 18:47 四连漏 audit 铁证后立）：恢复标签
的 * 标记异步出现、晚于检查时刻（open_app 检查时干净、粘贴回显已带
*），按 * 判别有竞态死角——开窗后**无条件**置顶+click 激活 → Ctrl+N
新建空白标签（Ctrl+N 只新建，绝无关闭标签/删除内容操作；本机实测
Ctrl+N=新标签），锚定必然落在新空白页，不依赖恢复时序。

四块机制，全部离线（不开真窗口、mock 走 monkeypatch 自动还原）：
  1. open_app 防护：notepad 开窗后**无条件**置顶+click 激活 →
     Ctrl+N（失败补 Ctrl+Shift+N）→ 新窗口出现则换锚（record 更新
     hwnd）；无新窗口但原窗口标题变干净（同窗口新标签）也算成功；
     原标题带 * 且两招都失败 → 如实报告（模型不输入直接汇报用户）；
     原标题干净时新建成功零文案（克制）；激活失败绝不发快捷键
  2. type_text 兜底拒粘：锚定 hwnd 是记事本且粘贴前标题带 * → 拒粘
     （剪贴板/键盘一次都不碰），引导告知用户——不给"自己 Ctrl+N"
     的引导（新窗口 hwnd 不在记录里会造成锚定死循环）
  3. 回归保护：非记事本应用（calc 等）不做此防护
  4. 真实 GUI 进程才过得了前台锁（SetForegroundWindow 规则）——
     离线测试只 mock 到行为层，前置/快捷键的真实生效由手动验证兜底
"""
import pytest

import agent_loop


def _fake_startfile(monkeypatch):
    launched = []

    def fake_startfile(what):
        launched.append(str(what))

    monkeypatch.setattr(agent_loop.os, "startfile", fake_startfile)
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    return launched


def _mock_restore_scene(monkeypatch, hwnd=0x360534, restored_title="*你好 - Notepad",
                        after_hotkey=None, foreground_ok=True):
    """搭「open_app 遇到会话恢复」的离线环境。

    after_hotkey：hotkey 调用后的窗口标题序列（每次 hotkey 后弹出一项，
    决定防护路径走向）；None = 不变（仍带 *）。
    返回记录器 dict：clicks / hotkeys / topmost。
    """
    rec = {"clicks": [], "hotkeys": [], "topmost": 0}
    state = {"windows": {hwnd: restored_title}}
    launched = []

    monkeypatch.setattr(agent_loop.os, "startfile",
                        lambda what: launched.append(str(what)))
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: hwnd)
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: h in state["windows"])
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "notepad.exe")
    monkeypatch.setattr(agent_loop, "_window_title",
                        lambda h: state["windows"].get(h, ""))
    monkeypatch.setattr(agent_loop.pyautogui, "click",
                        lambda *a, **k: rec["clicks"].append(a))
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey",
                        lambda *keys, **k: (rec["hotkeys"].append(keys),
                                            apply_step()))
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (foreground_ok, "x"))
    # 差集来源：防护函数里 hotkey 前后各枚举一次"当前窗口"
    monkeypatch.setattr(agent_loop, "_candidate_windows",
                        lambda exe: list(state["windows"]))

    def apply_step():
        if after_hotkey:
            step = after_hotkey.pop(0) if after_hotkey else None
            if step == "new_window":
                state["windows"][0x4D2] = "无标题 - Notepad"   # 新 hwnd
            elif step == "clean_same":
                state["windows"][hwnd] = "无标题 - Notepad"    # 同窗口新标签
            elif step == "still_dirty":
                state["windows"][hwnd] = "*你好 - Notepad"

    rec["apply_step"] = apply_step
    return rec


def _open_notepad(**kw):
    args = {"app_name": "notepad", "reason": "临时工具",
            "purpose": "T31 手动验证", "_agent_opened": [], **kw}
    record = args["_agent_opened"]
    out = agent_loop.TOOL_FUNCTIONS["open_app"](args)
    return out, record


# ==================== 1. open_app 防护：恢复会话 → 另开干净窗口 ====================

def test_open_app_notepad_restored_switches_to_new_window(monkeypatch):
    """Ctrl+N 开出新窗口：锚定 hwnd 换到新窗口，文案说明原窗口未动"""
    rec = _mock_restore_scene(monkeypatch, after_hotkey=["new_window", "skip"])
    out, record = _open_notepad()
    assert out.startswith("opened notepad")
    assert "上次未保存" in out and "新窗口" in out
    assert record[0]["hwnd"] == 0x4D2            # 锚定换到新窗口
    assert ("ctrl", "n") in rec["hotkeys"]       # 双试第一招发了


def test_open_app_notepad_restored_new_tab_same_window(monkeypatch):
    """无新窗口但原窗口标题变干净（同窗口新标签）：也算成功，锚定不变"""
    rec = _mock_restore_scene(monkeypatch, after_hotkey=["clean_same", "skip"])
    out, record = _open_notepad()
    assert "上次未保存" in out
    assert record[0]["hwnd"] == 0x360534         # 锚定 hwnd 不变
    assert record[0]["hwnd"] != 0x4D2


def test_open_app_notepad_restored_both_fail_reports(monkeypatch):
    """两招都失败：如实报告「未能另开空白窗口」，锚定保持但明确提示模型"""
    rec = _mock_restore_scene(monkeypatch, after_hotkey=["still_dirty",
                                                          "still_dirty"])
    out, record = _open_notepad()
    assert "未能" in out
    assert record[0]["hwnd"] == 0x360534


def test_open_app_notepad_restored_tries_shift_variant_on_failure(monkeypatch):
    """Ctrl+N 无效时补试 Ctrl+Shift+N（Win11 记事本两种新建快捷键）"""
    rec = _mock_restore_scene(monkeypatch,
                              after_hotkey=["still_dirty", "new_window"])
    out, record = _open_notepad()
    keys = rec["hotkeys"]
    assert ("ctrl", "n") in keys and ("ctrl", "shift", "n") in keys
    assert record[0]["hwnd"] == 0x4D2


# ==================== 2. 回归保护：干净标题 / 非记事本不受影响 ====================

def test_open_app_notepad_clean_title_unconditional_new_tab(monkeypatch):
    """干净标题（无 *）也无条件 Ctrl+N（T32：恢复标签的 * 异步出现晚于
    检查时刻，按 * 判别有竞态死角——18:47 四连漏 audit 铁证）；只发
    Ctrl+N 一招（标题已干净，无需补第二招），绝无其他按键（不含任何
    关标签/删内容的键），锚定不变，干净时零文案"""
    _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 0x1111)
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "无标题 - Notepad")
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "notepad.exe")
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (True, "无标题 - Notepad"))
    monkeypatch.setattr(agent_loop.pyautogui, "click", lambda *a, **kw: None)
    hot = []
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey", lambda *k, **kw: hot.append(k))
    out, record = _open_notepad()
    assert hot == [("ctrl", "n")]                # 无条件新标签，且仅此一招
    assert record[0]["hwnd"] == 0x1111           # 同窗口新标签，锚定不变
    assert out == "opened notepad"               # 干净时零文案（克制）


def test_open_app_notepad_no_hotkey_when_activation_fails(monkeypatch):
    """激活失败绝不发快捷键——Ctrl+N 落进未知前台窗口是危险操作"""
    _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 0x1111)
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: True)
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "无标题 - Notepad")
    monkeypatch.setattr(agent_loop, "_window_process_exe", lambda h: "notepad.exe")
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (False, "别的窗口"))
    monkeypatch.setattr(agent_loop.pyautogui, "click", lambda *a, **kw: None)
    hot = []
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey", lambda *k, **kw: hot.append(k))
    out, record = _open_notepad()
    assert hot == []                             # 一颗键都不发
    assert out == "opened notepad"               # 静默放行，交给下游兜底


def test_open_app_calc_skips_protection(monkeypatch):
    """非记事本应用不做恢复防护（calc 无会话恢复行为）"""
    _fake_startfile(monkeypatch)
    monkeypatch.setattr(agent_loop, "_capture_app_window", lambda *a, **k: 0x2222)
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: "计算器")
    hot = []
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey", lambda *k, **kw: hot.append(k))
    args = {"app_name": "calc", "reason": "临时工具", "purpose": "算数",
            "_agent_opened": []}
    record = args["_agent_opened"]
    out = agent_loop.TOOL_FUNCTIONS["open_app"](args)
    assert out == "opened calc"
    assert hot == []


# ==================== 3. type_text 兜底拒粘 ====================

def _type_env(monkeypatch, hwnd, title, exe="notepad.exe"):
    monkeypatch.setattr(agent_loop, "_window_alive", lambda h: h == hwnd)
    monkeypatch.setattr(agent_loop, "_window_title", lambda h: title)
    monkeypatch.setattr(agent_loop.pyautogui, "hotkey",
                        lambda *k, **kw: hot.append(k))
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    hot, clip, typed = [], [], []
    import pyperclip
    monkeypatch.setattr(pyperclip, "copy", lambda t: clip.append(t))
    return hot, clip, typed


def test_type_text_refuses_when_anchor_is_restored_doc(monkeypatch):
    """锚定的记事本窗口带 *（恢复的未保存文档）：拒粘，剪贴板键盘都不碰"""
    hot, clip, typed = _type_env(monkeypatch, 0x360534, "*你好你好 - Notepad")
    record = [{"type": "app", "name": "notepad", "exe": "notepad.exe",
               "hwnd": 0x360534, "reason": "临时工具", "purpose": "x",
               "opened_at": 0.0}]
    out = agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "你好", "_agent_opened": record})
    assert "已拒绝输入" in out
    assert "上次未保存" in out or "未保存" in out
    assert clip == [] and typed == [] and hot == []


def test_type_text_allows_clean_notepad(monkeypatch):
    """锚定的记事本窗口干净（无 *）：正常输入（回归保护）"""
    hot, clip, typed = _type_env(monkeypatch, 0x1111, "无标题 - Notepad")
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (True, "无标题 - Notepad"))
    monkeypatch.setattr(agent_loop, "_foreground_title",
                        lambda: "无标题 - Notepad")
    record = [{"type": "app", "name": "notepad", "exe": "notepad.exe",
               "hwnd": 0x1111, "reason": "临时工具", "purpose": "x",
               "opened_at": 0.0}]
    out = agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "你好", "_agent_opened": record})
    assert "已完整输入" in out
    assert clip == ["你好"]                      # 剪贴板正常走粘贴路径


def test_type_text_star_guard_only_for_notepad(monkeypatch):
    """带 * 的锚定窗口若不是记事本（如画图），不做此拒粘（回归保护）"""
    hot, clip, typed = _type_env(monkeypatch, 0x3333, "*未命名 - 画图")
    monkeypatch.setattr(agent_loop, "_ensure_foreground",
                        lambda h, poll_seconds=2.0: (True, "*未命名 - 画图"))
    monkeypatch.setattr(agent_loop, "_foreground_title",
                        lambda: "*未命名 - 画图")
    record = [{"type": "app", "name": "paint", "exe": "mspaint.exe",
               "hwnd": 0x3333, "reason": "临时工具", "purpose": "x",
               "opened_at": 0.0}]
    out = agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "你好", "_agent_opened": record})
    assert "已完整输入" in out
    assert clip == ["你好"]
