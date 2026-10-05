"""test_t25_unsaved_manual.py - T25 手动验证：未保存对话框不空转

复现 2026-10-04 事故场景并验证修复（需要交互桌面 + 空闲任务栏、人在旁边，
pyautogui failsafe 急停保持开启——工作准则 §五.5）。三个场景走真实记事本：
  A. 主场景（事故复现）：open_app → type_text("你好") → close_app(unsaved=discard)
     修复前：弹「是否保存」后 Agent 不认识，空转 59 秒；
     修复后：自动点「不保存」，窗口关闭，全程计时（任务书口径 <10s）
  B. cancel 路径：close_app 不传 unsaved → 点「取消」收提示、窗口保留
     （交用户决定）；用户补指令后 close_app(unsaved=discard) 仍能正常关掉
  C. 硬停止：close_app(unsaved=save) 点保存 → 无标题文件弹另存为、窗口未关
     （失败 1）；再 close_app（cancel）→ 点「取消」收起另存为（失败 2）
     → 硬停止；第三次调用被直接拒绝，不再发任何关闭请求
  清理：A/B 场景窗口已被工具关闭；C 残留的记事本按 PID taskkill 强杀
     （窗口是本脚本开的，强杀无用户数据损失；请先确保任务栏没有别的记事本）

运行：在仓库根目录 `python e2e/test_t25_unsaved_manual.py`
"""
import ctypes
from ctypes import wintypes
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyautogui  # noqa: E402  物理急停保持开启（工作准则 §五.5）
pyautogui.FAILSAFE = True

import agent_loop  # noqa: E402

user32 = ctypes.windll.user32
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def kill_pid(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                   capture_output=True, timeout=10)


def click_editor(hwnd):
    """模拟模型真实行为：先点击编辑区获得焦点再输入（System Prompt 工作流 5）。
    记事本带会话恢复标签启动时，焦点不在编辑区，不点这下 type_text 会落空
    （2026-10-05 实测踩中：粘贴落空 → 窗口无未保存内容 → 确认框不弹）。"""
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    pyautogui.click(rect.left + (rect.right - rect.left) // 2,
                    rect.top + int((rect.bottom - rect.top) * 0.6))
    time.sleep(0.4)


def open_notepad(purpose):
    """Agent 流程开记事本（T22 记录 hwnd）；失败返回 (None, record)"""
    record = []
    agent_loop._open_app({"app_name": "notepad", "reason": "临时工具",
                          "purpose": purpose}, record)
    hwnd = (record[0] or {}).get("hwnd", 0) if record else 0
    return hwnd, record


def close_app(record, **kw):
    """dispatch 语义：记录经 args 搭载，工具入口取走"""
    return agent_loop.TOOL_FUNCTIONS["close_app"](
        {**kw, "_agent_opened": record})


def cleanup(record):
    """正常关窗收尾（unsaved=discard 本身就是又一遍真实验证）；
    关不掉（如硬停止计数已满）才 taskkill 兜底"""
    hwnd = (record[0] or {}).get("hwnd", 0) if record else 0
    if not hwnd or not agent_loop._window_alive(hwnd):
        return
    out = close_app(record, app_name="notepad", unsaved="discard")
    print(f"      [清理] {out[:60]}")
    time.sleep(0.8)
    if agent_loop._window_alive(hwnd):
        print(f"      [清理] discard 未生效，强杀 PID={pid_of(hwnd)}")
        kill_pid(pid_of(hwnd))
        time.sleep(0.5)


def dump_uia_buttons(hwnd, why):
    """诊断输出：识别落空时打印主窗口树里的可见按钮，便于定位命名差异"""
    try:
        btns = agent_loop._pywinauto_window_buttons(hwnd)
        names = [b.window_text() for b in btns]
        print(f"      [诊断] {why}：UIA 可见 Button = {names}")
    except Exception as e:
        print(f"      [诊断] {why}：UIA 枚举异常 {e}")


def scenario_a():
    print("\n---- 场景 A：事故复现「输入你好」→ 关闭（unsaved=discard）----")
    t0 = time.time()
    hwnd, record = open_notepad("T25 手动验证 A")
    check("open_app 抓到新记事本 hwnd", bool(hwnd), f"hwnd={hwnd:#x}")
    if not hwnd:
        return
    click_editor(hwnd)
    out_t = agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "你好", "_agent_opened": record})
    check("type_text 输入到记事本", "已输入到「" in out_t, out_t[:60])
    out_c = close_app(record, app_name="notepad", unsaved="discard")
    elapsed = time.time() - t0
    print(f"      close_app 回复: {out_c}")
    check("点「不保存」关闭（不再请用户手动确认）",
          "已点「不保存」" in out_c and "手动确认" not in out_c, out_c[:50])
    check("窗口确实关闭", not agent_loop._window_alive(hwnd))
    check(f"工具序列总耗时 <10s（实测 {elapsed:.1f}s）", elapsed < 10)
    if agent_loop._window_alive(hwnd):
        dump_uia_buttons(hwnd, "场景 A 窗口未关")
    cleanup(record)


def scenario_b():
    print("\n---- 场景 B：不传 unsaved（cancel）→ 窗口保留 → 补 discard ----")
    hwnd, record = open_notepad("T25 手动验证 B")
    check("open_app 抓到新记事本 hwnd", bool(hwnd), f"hwnd={hwnd:#x}")
    if not hwnd:
        return
    click_editor(hwnd)
    agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "T25 cancel 路径", "_agent_opened": record})
    r1 = close_app(record, app_name="notepad")
    print(f"      第一次 close_app 回复: {r1}")
    check("点「取消」收起提示、窗口保留", "窗口保留" in r1
          and agent_loop._window_alive(hwnd), r1[:50])
    time.sleep(1.0)  # 等确认框关闭动画走完再发下一次 WM_CLOSE（~0.5s 动画）
    r2 = close_app(record, app_name="notepad", unsaved="discard")
    print(f"      第二次 close_app 回复: {r2}")
    check("补传 discard 后正常关掉",
          "已点「不保存」" in r2 and not agent_loop._window_alive(hwnd), r2[:50])
    if agent_loop._window_alive(hwnd):
        dump_uia_buttons(hwnd, "场景 B 窗口未关")
    cleanup(record)


def scenario_c():
    print("\n---- 场景 C：unsaved=save → 另存为 → 第二次失败 → 硬停止 ----")
    hwnd, record = open_notepad("T25 手动验证 C")
    check("open_app 抓到新记事本 hwnd", bool(hwnd), f"hwnd={hwnd:#x}")
    if not hwnd:
        return
    click_editor(hwnd)
    agent_loop.TOOL_FUNCTIONS["type_text"](
        {"text": "T25 save 路径", "_agent_opened": record})
    r1 = close_app(record, app_name="notepad", unsaved="save")
    print(f"      第一次 close_app 回复: {r1}")
    check("点「保存」但窗口未关（无标题文件先弹另存为）",
          "仍未关闭" in r1 and "另存为" in r1, r1[:60])
    check("失败计数 1", record[0].get("close_fails") == 1,
          str(record[0].get("close_fails")))
    time.sleep(1.0)  # 同 B：等另存为/确认框状态稳定
    r2 = close_app(record, app_name="notepad")  # 第二次不传 → cancel
    print(f"      第二次 close_app 回复: {r2}")
    check("第二次失败 → 硬停止（2 次上限）",
          "错误" in r2 and "2 次" in r2 and "停止" in r2, r2[:60])
    r3 = close_app(record, app_name="notepad", unsaved="discard")
    print(f"      第三次 close_app 回复: {r3}")
    check("第三次直接拒绝（连 WM_CLOSE 都不再发）",
          "已停止自动关闭" in r3 and "不要再" in r3, r3[:60])
    if agent_loop._window_alive(hwnd):
        print(f"      [清理] 硬停止后窗口仍开，强杀 PID={pid_of(hwnd)}")
        kill_pid(pid_of(hwnd))
        time.sleep(0.5)
    check("清理后窗口已消失", not agent_loop._window_alive(hwnd))


def main():
    scenario_a()
    scenario_b()
    scenario_c()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{'=' * 46}\nT25 手动验证：{len(RESULTS) - len(failed)}/{len(RESULTS)} 项通过")
    if failed:
        for name, _ok, detail in failed:
            print(f"  FAIL: {name}  {detail}")
        return 1
    print("全部通过——未保存对话框不再触发空转")
    return 0


if __name__ == "__main__":
    sys.exit(main())
