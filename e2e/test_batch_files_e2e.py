# -*- coding: utf-8 -*-
"""
P7 批量文件操作 E2E 测试（GUI 版 - 重命名）

用 pyautogui 操作资源管理器，批量重命名 .txt 文件。
流程：打开资源管理器 → 选中 .txt 文件 → F2 → 输入新名字 → Enter → 验证
"""

import os
import sys
import time
import subprocess
import shutil
from pathlib import Path

import pyautogui

TEST_DIR = Path(r"E:\agent_test\batch_test")
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.3


def log_step(num, action, start):
    """记录步骤耗时"""
    elapsed = time.time() - start
    print(f"[Step {num:2d}] {action:<35} {elapsed:.2f}s", flush=True)
    return elapsed


def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def take_screenshot(name):
    path = SCREENSHOT_DIR / f"{name}.png"
    pyautogui.screenshot(str(path))
    log(f"截图: {name}.png")


def setup_test_files():
    log("准备测试目录")
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir(parents=True)

    files = ["file1.txt", "file2.txt", "file3.txt", "image1.png", "doc1.docx"]
    for f in files:
        (TEST_DIR / f).write_text(f"content of {f}", encoding="utf-8")

    log(f"创建了 {len(files)} 个文件")
    return files


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


def batch_rename():
    """批量重命名所有 .txt 文件"""
    log("开始批量重命名 .txt 文件")

    # 原始文件名列表
    original_files = ["file1.txt", "file2.txt", "file3.txt"]
    new_names = ["text_001.txt", "text_002.txt", "text_003.txt"]

    # 先截图一个 .txt 文件图标，用于定位
    log("截图 .txt 文件图标")
    screenshot_path = "screenshot_txt_icon.png"
    pyautogui.screenshot(screenshot_path)
    time.sleep(0.5)

    # 1. 逐个重命名 .txt 文件
    for i, (old_name, new_name) in enumerate(zip(original_files, new_names)):
        t = time.time()
        log(f"重命名文件 {i+1}/{len(original_files)}: {old_name} → {new_name}")

        # 使用 locateOnScreen 定位 .txt 文件图标
        log("定位文件图标...")
        try:
            loc = pyautogui.locateOnScreen(screenshot_path, confidence=0.8, grayscale=True)
            if loc is None:
                log(f"警告: 无法定位 {old_name}，尝试使用屏幕中央")
                # 回退到固定坐标
                file_y = 150 + i * 25
                pyautogui.click(400, file_y)
            else:
                # 获取中心点坐标
                center = pyautogui.center(loc)
                pyautogui.click(center.x, center.y)
                log(f"找到文件图标位置: {center}")
        except Exception as e:
            log(f"定位失败: {e}，使用固定坐标")
            file_y = 150 + i * 25
            pyautogui.click(400, file_y)

        time.sleep(0.3)

        # 按 F2 重命名
        pyautogui.press('f2')
        time.sleep(0.3)

        # 全选当前文件名
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)

        # 输入新文件名
        pyautogui.typewrite(new_name, interval=0.03)
        time.sleep(0.3)

        # 按 Enter 确认
        pyautogui.press('enter')
        time.sleep(0.5)

        log_step(i+1, f"重命名 {old_name} → {new_name}", t)

    take_screenshot("01_renamed")


def verify_result():
    log("验证结果...")

    files = sorted([f.name for f in TEST_DIR.iterdir()])
    log(f"文件列表: {files}")

    # 检查重命名后的文件
    renamed_files = [f for f in files if f.startswith("text_00") and f.endswith(".txt")]
    log(f"重命名后的文件: {renamed_files}")

    # 原始文件
    original_files = [f for f in files if f in ["file1.txt", "file2.txt", "file3.txt", "image1.png", "doc1.docx"]]
    log(f"原始文件: {original_files}")

    # 验证: 3 个 .txt 文件被重命名为 text_00x.txt
    all_renamed = len(renamed_files) >= 3

    return all_renamed


def close_explorer():
    log("关闭资源管理器")
    subprocess.run(["taskkill", "/F", "/IM", "explorer.exe"], capture_output=True)
    time.sleep(1)


def main():
    total_start = time.time()
    step_durations = []

    print("=" * 60, flush=True)
    print("P7 批量文件操作 E2E Test (GUI - 重命名)", flush=True)
    print("=" * 60, flush=True)

    try:
        # Step 1: 准备测试文件
        t = time.time()
        setup_test_files()
        dur = log_step(1, "准备测试文件", t)
        step_durations.append(dur)

        # Step 2: 打开资源管理器
        t = time.time()
        subprocess.Popen(["explorer.exe", str(TEST_DIR)])
        time.sleep(2)
        dur = log_step(2, "打开资源管理器", t)
        step_durations.append(dur)

        # Step 3: 等待窗口
        t = time.time()
        ready = wait_window("batch_test", timeout=5)
        time.sleep(1)
        dur = log_step(3, f"等待窗口 ({'OK' if ready else 'FAIL'})", t)
        step_durations.append(dur)

        # Step 4: 批量重命名
        t = time.time()
        batch_rename()
        dur = log_step(4, "批量重命名 .txt 文件", t)
        step_durations.append(dur)

        # Step 5: 验证结果
        t = time.time()
        passed = verify_result()
        dur = log_step(5, f"验证结果 ({'通过' if passed else '失败'})", t)
        step_durations.append(dur)

        # Step 6: 关闭资源管理器
        t = time.time()
        close_explorer()
        dur = log_step(6, "关闭资源管理器", t)
        step_durations.append(dur)

        # Step 7: 清理
        t = time.time()
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR)
        dur = log_step(7, "清理测试目录", t)
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

        # 判断通过
        passed = passed and total_time < 30
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
