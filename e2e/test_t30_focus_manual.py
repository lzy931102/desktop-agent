"""test_t30_focus_manual.py - T30 手动验证：双记事本焦点校验

复现 2026-10-05 事故场景并验证修复（需要交互桌面，跑在前台）：
  1. 先开记事本 A（扮演"用户已开着的记事本"）
  2. Agent 走完整 T22 流程 open_app 再开记事本 B（差集抓到 B 的 hwnd）
  3. type_text 带 T22 记录锚定 B → 应自动把 B 拉到前台并粘进 B
  4. 三方断言：前台==B；B 标题出现 * （有未保存改动=粘进去了）；
     A 标题保持无 * （=没被污染）。修复前这一步会把文字粘进 A 且毫无提示。
  5. 反例：锚定一个已关闭的 hwnd → 必须拒粘，两窗口标题都不变
  6. verify_open_app 差集：B 开出后凭动作前快照判"新窗口已出现"；
     无新窗口时判失败（用户已开的 A 不再算数）
  7. 清理：只 taskkill 本次打开的两个记事本 PID（不碰用户窗口），
     恢复剪贴板原内容

运行：在仓库根目录 `python e2e/test_t30_focus_manual.py`
"""
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyautogui  # noqa: E402  物理急停保持开启（工作准则 §五.5）
pyautogui.FAILSAFE = True

import agent_loop  # noqa: E402
from core import verify as core_verify  # noqa: E402

try:
    import pyperclip
except ImportError:
    print("ERROR: pyperclip 未安装")
    sys.exit(1)

user32 = ctypes.windll.user32
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def wait_new_window(before, deadline_s=12.0):
    """轮询等一个 before 里没有的新记事本窗口"""
    end = time.time() + deadline_s
    while time.time() < end:
        for hwnd in agent_loop._candidate_windows("notepad.exe"):
            if hwnd not in before:
                return hwnd
        time.sleep(0.4)
    return 0


def kill_pid(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                   capture_output=True, timeout=10)


def main():
    saved_clip = ""
    try:
        saved_clip = pyperclip.paste()
    except Exception:
        pass

    hwnd_a = hwnd_b = 0
    pid_a = pid_b = 0
    try:
        # ---- 1. 开记事本 A（"用户已开的记事本"）----
        pre0 = agent_loop._candidate_windows("notepad.exe")
        os.startfile("notepad.exe")
        hwnd_a = wait_new_window(pre0)
        check("开记事本 A（用户窗口）", bool(hwnd_a),
              f"hwnd={hwnd_a:#x} 标题={agent_loop._window_title(hwnd_a)!r}")
        if not hwnd_a:
            return finish()
        pid_a = pid_of(hwnd_a)
        time.sleep(1.0)
        title_a_before = agent_loop._window_title(hwnd_a)

        # ---- 2. Agent 流程：动作前快照 + open_app 开 B（T22 记录 hwnd）----
        pre_windows = core_verify.snapshot_windows()
        record = []
        agent_loop._open_app({"app_name": "notepad", "reason": "结果载体",
                              "purpose": "T30 手动验证"}, record)
        hwnd_b = (record[0] or {}).get("hwnd", 0) if record else 0
        pid_b = pid_of(hwnd_b) if hwnd_b else 0
        check("open_app 差集抓到新窗口 B（非 A）",
              bool(hwnd_b) and hwnd_b != hwnd_a,
              f"hwnd={hwnd_b:#x}")
        if not hwnd_b:
            return finish()

        # verify_open_app 差集：凭 pre_windows 应认出 B 是新窗口
        ok, detail = core_verify.verify_open_app("notepad", pre_windows=pre_windows)
        check("verify_open_app 差集判'新窗口已出现'", ok, detail)

        # ---- 3. type_text 锚定 B 粘贴（dispatch 语义：记录经 args 搭载）----
        out = agent_loop.TOOL_FUNCTIONS["type_text"](
            {"text": "T30焦点校验", "_agent_opened": record})
        print(f"      工具回显: {out}")
        time.sleep(1.2)  # 记事本标题（* 未保存标记）异步刷新，等它稳定
        fg = user32.GetForegroundWindow()
        title_b = agent_loop._window_title(hwnd_b)
        title_a_after = agent_loop._window_title(hwnd_a)
        check("粘贴后前台是 B", fg == hwnd_b,
              f"前台标题={agent_loop._window_title(fg)!r}")
        check("文字进了 B（标题出现 * 未保存标记）",
              "*" in title_b, f"B 标题={title_b!r}")
        check("A 未被污染（标题无 *）", title_a_after == title_a_before,
              f"A 标题={title_a_after!r}")
        check("回显报出接收窗口", "已输入到「" in out, out[:60])

        # ---- 4. 反例：锚定已关闭的窗口必须拒粘 ----
        out2 = agent_loop.TOOL_FUNCTIONS["type_text"](
            {"text": "不该出现", "_agent_opened": [{"type": "app", "hwnd": 0x1}]})
        check("锚定窗口已关闭 → 拒粘", "已拒绝输入" in out2, out2[:60])
        check("拒粘后 A/B 标题都没变",
              "*" not in agent_loop._window_title(hwnd_a)
              and agent_loop._window_title(hwnd_b) == title_b)

        # ---- 5. verify_open_app 差集反例：无新窗口时不得假阳性 ----
        ok2, detail2 = core_verify.verify_open_app(
            "notepad", pre_windows=core_verify.snapshot_windows())
        check("verify_open_app 差集：无新窗口判失败", ok2 is False, detail2)

    finally:
        # ---- 6. 清理：只杀本次打开的两个记事本，恢复剪贴板 ----
        for pid in (pid_b, pid_a):
            if pid:
                kill_pid(pid)
        if saved_clip:
            try:
                pyperclip.copy(saved_clip)
            except Exception:
                pass
    return finish()


def finish():
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{'=' * 46}\nT30 手动验证：{len(RESULTS) - len(failed)}/{len(RESULTS)} 项通过")
    if failed:
        for name, _ok, detail in failed:
            print(f"  FAIL: {name}  {detail}")
        return 1
    print("全部通过——盲粘事故路径已由焦点校验封死")
    return 0


if __name__ == "__main__":
    sys.exit(main())
