# -*- coding: utf-8 -*-
"""
第一步：验证感知链路
- 截屏游戏窗口区域
- 用 OpenCV 找红靶
- 对比 game_state.json 真实位置
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


def get_window_rect(hwnd):
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


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


def main():
    proc = subprocess.Popen(
        ["python", GAME_PATH, "--speed", "8"],
        cwd=r"E:\agent_test"
    )
    time.sleep(2)

    hwnd = find_window()
    if hwnd is None:
        print("ERROR: 找不到游戏窗口")
        proc.terminate()
        return

    client_rect = get_client_rect(hwnd)
    window_rect = get_window_rect(hwnd)
    print("Client rect (screen):", client_rect)
    print("Window rect (screen):", window_rect)
    print("Client size: {}x{}".format(client_rect[2] - client_rect[0],
                                      client_rect[3] - client_rect[1]))

    sct = mss.MSS()
    monitor = {
        "left": client_rect[0],
        "top": client_rect[1],
        "width": client_rect[2] - client_rect[0],
        "height": client_rect[3] - client_rect[1],
    }

    print("\n帧  感知(x,y)    耗时(ms)  真实(x,y)    偏差(px)")
    print("-" * 55)

    offsets = []
    latencies = []

    for i in range(30):
        t0 = time.perf_counter()
        img = np.array(sct.grab(monitor))[:, :, :3]
        target = find_target(img)
        t1 = time.perf_counter()

        perceive_ms = (t1 - t0) * 1000
        latencies.append(perceive_ms)

        state = read_state()
        real_x, real_y = -1, -1
        if state and state.get("target"):
            real_x = int(state["target"]["x"])
            real_y = int(state["target"]["y"])

        if target:
            vx, vy = target
            dist = ((vx - real_x) ** 2 + (vy - real_y) ** 2) ** 0.5
            offsets.append(dist)
            print("{:2d}  ({:3d},{:3d})    {:5.1f}    ({:3d},{:3d})    {:5.1f}".format(
                i, vx, vy, perceive_ms, real_x, real_y, dist))
        else:
            print("{:2d}  None         {:5.1f}    ({:3d},{:3d})      -".format(
                i, perceive_ms, real_x, real_y))

        time.sleep(0.05)

    print("\n--- 汇总 ---")
    if offsets:
        print("感知偏差: avg={:.1f}px, max={:.1f}px, min={:.1f}px".format(
            sum(offsets) / len(offsets), max(offsets), min(offsets)))
    else:
        print("没有成功感知到靶子!")
    print("截屏耗时: avg={:.1f}ms, max={:.1f}ms".format(
        sum(latencies) / len(latencies), max(latencies)))
    print("总帧数: {}".format(len(latencies)))
    print("成功感知: {}/{}".format(len(offsets), len(latencies)))

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


if __name__ == "__main__":
    main()
