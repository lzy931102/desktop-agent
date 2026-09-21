import subprocess
import time
import os
import sys

try:
    import pyautogui
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyautogui", "-q"])
    import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.3

# 测试路径
TEST_DIR = r"E:\agent_test"
TEST_FOLDER = "test_folder_p3"
TEST_FILE = "test_file.txt"

def log_step(num, action, start):
    elapsed = time.time() - start
    print(f"[Step {num:2d}] {action:<35} {elapsed:.2f}s", flush=True)
    return elapsed

def wait_window(title, timeout=5):
    """等待窗口出现"""
    import ctypes
    from ctypes import wintypes
    
    user32 = ctypes.windll.user32
    
    start = time.time()
    while time.time() - start < timeout:
        found = False
        def callback(hwnd, lParam):
            nonlocal found
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if title.lower() in buf.value.lower():
                        found = True
            return True
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(callback), 0)
        if found:
            return True
        time.sleep(0.3)
    return False

def main():
    total_start = time.time()
    step_durations = []
    
    print("=" * 60, flush=True)
    print("P3 文件夹操作 E2E Test (GUI)", flush=True)
    print("=" * 60, flush=True)
    
    try:
        # Step 1: 打开资源管理器
        t = time.time()
        subprocess.Popen(["explorer.exe", TEST_DIR])
        time.sleep(2)
        dur = log_step(1, "打开资源管理器", t)
        step_durations.append(dur)
        
        # Step 2: 等待窗口
        t = time.time()
        ready = wait_window("agent_test", timeout=5)
        time.sleep(1)
        dur = log_step(2, f"等待窗口 ({'OK' if ready else 'FAIL'})", t)
        step_durations.append(dur)
        
        # Step 3: 新建文件夹 (Ctrl+Shift+N)
        t = time.time()
        pyautogui.hotkey('ctrl', 'shift', 'n')
        time.sleep(1)
        pyautogui.typewrite(TEST_FOLDER, interval=0.03)
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(1)
        dur = log_step(3, f"新建文件夹 {TEST_FOLDER}", t)
        step_durations.append(dur)
        
        # Step 4: 进入文件夹 (Enter)
        t = time.time()
        # 新建后文件夹已选中，直接Enter进入
        pyautogui.press('enter')
        time.sleep(1)
        dur = log_step(4, "进入文件夹", t)
        step_durations.append(dur)
        
        # Step 5: 新建文本文件
        t = time.time()
        # 右键 → 新建 → 文本文档
        pyautogui.rightClick(960, 540)  # 屏幕中央
        time.sleep(1)
        # 找"新建"菜单项 - 用键盘导航
        pyautogui.press('w')  # 新建
        time.sleep(0.5)
        pyautogui.press('t')  # 文本文档
        time.sleep(1)
        # 输入文件名
        pyautogui.typewrite(TEST_FILE, interval=0.03)
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(1)
        # 处理扩展名确认
        pyautogui.press('enter')
        time.sleep(0.5)
        dur = log_step(5, f"新建文件 {TEST_FILE}", t)
        step_durations.append(dur)
        
        # Step 6: 复制文件
        t = time.time()
        # 文件应该已选中
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1)
        # 处理重名确认
        pyautogui.press('tab')
        time.sleep(0.2)
        pyautogui.press('enter')
        time.sleep(0.5)
        dur = log_step(6, "复制文件 (Ctrl+C → Ctrl+V)", t)
        step_durations.append(dur)
        
        # Step 7: 重命名 (F2)
        t = time.time()
        # 选中第一个文件
        pyautogui.click(960, 400)
        time.sleep(0.3)
        pyautogui.press('f2')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyautogui.typewrite("renamed_file.txt", interval=0.03)
        time.sleep(0.3)
        pyautogui.press('enter')
        time.sleep(0.5)
        dur = log_step(7, "重命名文件", t)
        step_durations.append(dur)
        
        # Step 8: 删除 (Delete)
        t = time.time()
        pyautogui.press('delete')
        time.sleep(0.5)
        pyautogui.press('enter')  # 确认删除
        time.sleep(1)
        dur = log_step(8, "删除文件", t)
        step_durations.append(dur)
        
        # Step 9: 关闭资源管理器
        t = time.time()
        pyautogui.hotkey('alt', 'f4')
        time.sleep(1)
        dur = log_step(9, "关闭资源管理器", t)
        step_durations.append(dur)
        
        # Step 10: 验证目录状态
        t = time.time()
        folder_path = os.path.join(TEST_DIR, TEST_FOLDER)
        folder_exists = os.path.exists(folder_path)
        if folder_exists:
            files = os.listdir(folder_path)
        else:
            files = []
        dur = log_step(10, f"验证: 文件夹={folder_exists}, 文件={files}", t)
        step_durations.append(dur)
        
        # Step 11: 清理
        t = time.time()
        if folder_exists:
            # 删除文件夹内所有文件
            for f in files:
                os.remove(os.path.join(folder_path, f))
            os.rmdir(folder_path)
        dur = log_step(11, "清理测试目录", t)
        step_durations.append(dur)
        
        # 打印汇总
        total_time = time.time() - total_start
        print("\n" + "=" * 60, flush=True)
        print("每步耗时汇总", flush=True)
        print("=" * 60, flush=True)
        for i, d in enumerate(step_durations, 1):
            print(f"  Step {i:2d}: {d:.2f}s", flush=True)
        print("-" * 60, flush=True)
        print(f"  总耗时: {total_time:.2f}s", flush=True)
        
        # 判断通过：文件夹曾经存在，最终被清理
        passed = folder_exists and total_time < 60
        print(f"\n{'✓ TEST PASSED' if passed else '✗ TEST FAILED'}", flush=True)
        return passed
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
