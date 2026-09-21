# -*- coding: utf-8 -*-
"""
第三步：测量 system_latency
- 启动 speed=0 静止靶
- 循环：截屏→感知→点击→确认命中
- 输出平均延迟
"""
import sys
import time
import json
import subprocess
import ctypes
from ctypes import wintypes

import cv2
import numpy as np
import mss

GAME_PATH = r"E:\agent_test\game.py"
STATE_FILE = r"E:\agent_test\game_state.json"
WINDOW_TITLE_KEYWORD = "Target Game"

RED_LOWER1 = np.array([0, 100, 100])
RED_UPPER1 = np.array([10, 255, 255])
RED_LOWER2 = np.array([170, 100, 100])
RED_UPPER2 = np.array([180, 255, 255])


def find_window():
    user32 = ctypes.windll.user32
    result = []

    def enum_cb(hwnd, lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if WINDOW_TITLE_KEYWORD in buf.value:
                result.append(hwnd)
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
    )
    user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
    return result[0] if result else None


def get_client_rect(hwnd):
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt1 = wintypes.POINT(rect.left, rect.top)
    pt2 = wintypes.POINT(rect.right, rect.bottom)
    user32.ClientToScreen(hwnd, ctypes.byref(pt1))
    user32.ClientToScreen(hwnd, ctypes.byref(pt2))
    return pt1.x, pt1.y, pt2.x, pt2.y


def find_target(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOWER1, RED_UPPER1)
    mask2 = cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    mask = cv2.bitwise_or(mask1, mask2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 300:
            continue
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue
        circularity = 4 * 3.14159 * area / (perimeter ** 2)
        if circularity < 0.3:
            continue
        if area > best_area:
            best_area = area
            best = c
    if best is None:
        return None
    M = cv2.moments(best)
    if M["m00"] == 0:
        return None
    return int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def click_screen(sct, monitor, x, y, hwnd):
    screen_x = monitor["left"] + x
    screen_y = monitor["top"] + y
    ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def main():
    proc = subprocess.Popen(
        ["python", GAME_PATH, "--speed", "0"],
        cwd=r"E:\agent_test"
    )
    time.sleep(2)

    hwnd = find_window()
    if hwnd is None:
        print("ERROR: 找不到游戏窗口")
        proc.terminate()
        return

    user32 = ctypes.windll.user32
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(0.5)

    client_rect = get_client_rect(hwnd)
    print("Client size: {}x{}".format(client_rect[2] - client_rect[0],
                                      client_rect[3] - client_rect[1]))

    sct = mss.MSS()
    monitor = {
        "left": client_rect[0],
        "top": client_rect[1],
        "width": client_rect[2] - client_rect[0],
        "height": client_rect[3] - client_rect[1],
    }

    perceive_times = []
    click_times = []
    total_times = []
    hits = 0

    print("\n轮  感知耗时(ms)  点击耗时(ms)  总延迟(ms)  命中")
    print("-" * 50)

    for i in range(20):
        state_before = read_state()
        score_before = state_before.get("score", 0) if state_before else 0

        t0 = time.perf_counter()
        img = np.array(sct.grab(monitor))[:, :, :3]
        target = find_target(img)
        t1 = time.perf_counter()

        if target is None:
            print("{:2d}  感知失败".format(i))
            time.sleep(0.1)
            continue

        x, y = target
        click_screen(sct, monitor, x, y, hwnd)
        time.sleep(0.05)
        t2 = time.perf_counter()

        state_after = read_state()
        score_after = state_after.get("score", 0) if state_after else 0
        is_hit = score_after > score_before

        perceive_ms = (t1 - t0) * 1000
        click_ms = (t2 - t1) * 1000
        total_ms = (t2 - t0) * 1000

        perceive_times.append(perceive_ms)
        click_times.append(click_ms)
        total_times.append(total_ms)
        if is_hit:
            hits += 1

        print("{:2d}  {:8.1f}    {:8.1f}    {:8.1f}    {}".format(
            i, perceive_ms, click_ms, total_ms,
            "HIT" if is_hit else "miss"))

        time.sleep(0.05)

    print("\n--- 汇总 ---")
    print("感知耗时: avg={:.1f}ms".format(
        sum(perceive_times) / len(perceive_times) if perceive_times else 0))
    print("点击耗时: avg={:.1f}ms".format(
        sum(click_times) / len(click_times) if click_times else 0))
    print("总延迟:   avg={:.1f}ms".format(
        sum(total_times) / len(total_times) if total_times else 0))
    print("命中率: {}/{} = {:.0%}".format(
        hits, len(total_times), hits / len(total_times) if total_times else 0))

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


if __name__ == "__main__":
    main()
