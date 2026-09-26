"""设置窗口最小化修复验收脚本 v2（真实 gui.py 应用，端到端）。

用法：
  1. 启动应用:  python gui.py
  2. 运行:      python verify_fix_minimize.py <gui_pid>

断言清单（C 组按 DeepSeek 建议拆为独立断言，不再依赖"任务栏新按钮"
——本机任务栏开启「始终合并」，同进程窗口共用一个组按钮，
独立的"新按钮"永远不会出现）：
  A. 主窗口 / 设置窗口出现（按标题+PID 过滤）
  B. 点设置「—」→ showCmd==2（最小化生效）
  C1. 设置窗口样式位：WS_EX_APPWINDOW 已置、WS_EX_TOOLWINDOW 已清
  C2. SW_RESTORE 恢复 → showCmd!=2 且 rect 回到正常位置（可恢复性）
  D. 点「□」最大化 → showCmd==3；再点还原
  E. 点「×」→ 窗口销毁
  F. 主窗口「—」最小化 → showCmd==2 → 恢复（主界面回归）
所有点击坐标按窗口实时 rect 计算；每步打印 PASS/FAIL。
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
import pyautogui

user32 = ctypes.windll.user32

WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


class PLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                ("rcNormalPosition", wt.RECT)]


WPF = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def windows_with_title(title, pid=None):
    found = []

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if buf.value == title:
            wpid = wt.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
            if pid is None or wpid.value == pid:
                found.append(h)
        return True

    user32.EnumWindows(WPF(cb), 0)
    return found


def wait_window(title, pid, timeout=15.0, stable=0.6):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for h in windows_with_title(title, pid):
            if user32.IsWindowVisible(h):
                time.sleep(stable)
                if user32.IsWindowVisible(h):
                    return h
        time.sleep(0.3)
    return None


def rect_of(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def show_cmd(hwnd):
    p = PLACEMENT()
    p.length = ctypes.sizeof(p)
    user32.GetWindowPlacement(hwnd, ctypes.byref(p))
    return p.showCmd   # 1=normal 2=minimized 3=maximized


def exstyle_of(hwnd):
    return user32.GetWindowLongW(hwnd, -16)   # GWL_EXSTYLE


def main(pid):
    # ---- A ----
    hwnd_main = wait_window("Desktop Agent - 智能桌面助手", pid)
    check("A1 主窗口出现", hwnd_main is not None)
    if not hwnd_main:
        return
    user32.ShowWindow(hwnd_main, 9)   # SW_RESTORE：防止上轮测试残留隐藏/最小化
    time.sleep(0.8)
    rm = rect_of(hwnd_main)
    pyautogui.click(rm.left + 135, rm.top + 736)   # 侧栏「设置」
    hwnd_set = wait_window("设置", pid)
    check("A2 设置窗口出现", hwnd_set is not None)
    if not hwnd_set:
        return
    time.sleep(1.0)

    # ---- B. 点「—」----
    rs = rect_of(hwnd_set)
    pyautogui.click(rs.right - 122, rs.top + 15)
    time.sleep(1.5)
    cmd = show_cmd(hwnd_set)
    check("B1 点「—」后最小化", cmd == 2, f"showCmd={cmd}")

    # ---- C1. 样式位 ----
    ex = exstyle_of(hwnd_set)
    check("C1 样式位 APPWINDOW=1 / TOOLWINDOW=0",
          bool(ex & WS_EX_APPWINDOW) and not (ex & WS_EX_TOOLWINDOW),
          f"exstyle={ex:#x}")

    # ---- C2. SW_RESTORE 可恢复性 ----
    before = PLACEMENT()
    before.length = ctypes.sizeof(before)
    user32.GetWindowPlacement(hwnd_set, ctypes.byref(before))
    user32.ShowWindow(hwnd_set, 9)   # SW_RESTORE
    time.sleep(1.2)
    cmd = show_cmd(hwnd_set)
    rs = rect_of(hwnd_set)
    same_pos = (abs(rs.left - before.rcNormalPosition.left) < 60 and
                abs(rs.top - before.rcNormalPosition.top) < 60)
    check("C2 恢复后 showCmd!=2 且位置还原", cmd != 2 and same_pos,
          f"showCmd={cmd} rect=({rs.left},{rs.top})")

    # ---- D. □ 最大化 / 还原 ----
    rs = rect_of(hwnd_set)
    pyautogui.click(rs.right - 77, rs.top + 15)
    time.sleep(1.5)
    cmd = show_cmd(hwnd_set)
    check("D1 点「□」后最大化", cmd == 3, f"showCmd={cmd}")
    if cmd == 3:
        rs = rect_of(hwnd_set)
        pyautogui.click(rs.right - 77, rs.top + 15)
        time.sleep(1.5)
        check("D2 再点「□」还原", show_cmd(hwnd_set) != 3)

    # ---- E. × 关闭 ----
    rs = rect_of(hwnd_set)
    pyautogui.click(rs.right - 32, rs.top + 15)
    time.sleep(1.5)
    gone = not windows_with_title("设置", pid)
    check("E1 点「×」后窗口关闭", gone)

    # ---- F. 主窗口「—」回归 ----
    hwnd_main = wait_window("Desktop Agent - 智能桌面助手", pid, timeout=5)
    if hwnd_main and user32.IsWindowVisible(hwnd_main):
        enabled = user32.IsWindowEnabled(hwnd_main)
        check("F0 主窗口已解除禁用（模态恢复）", bool(enabled),
              f"IsWindowEnabled={enabled}")
        rm = rect_of(hwnd_main)
        # 移出遮挡区并置顶，排除其他窗口截走点击的干扰
        user32.SetWindowPos(hwnd_main, -1, 40, 40, 0, 0, 0x0001 | 0x0004)
        time.sleep(0.6)
        rm = rect_of(hwnd_main)
        pyautogui.screenshot("screenshots/verify_f1_before.png")
        pyautogui.click(rm.right - 122, rm.top + 15)
        time.sleep(1.5)
        pyautogui.screenshot("screenshots/verify_f1_after.png")
        cmd = show_cmd(hwnd_main)
        check("F1 主窗口「—」最小化正常", cmd == 2, f"showCmd={cmd}")
        user32.ShowWindow(hwnd_main, 9)
        time.sleep(0.8)
        check("F2 主窗口恢复", show_cmd(hwnd_main) != 2)
    else:
        check("F1 主窗口「—」最小化正常", False, "主窗口不可见")

    fails = [r for r in results if not r[1]]
    print(f"\n===== 汇总: {len(results) - len(fails)}/{len(results)} PASS =====")


if __name__ == "__main__":
    main(int(sys.argv[1]))
