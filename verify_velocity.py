# -*- coding: utf-8 -*-
"""
第二步：验证速度估计
- 用滑动窗口 + 线性回归估计速度
- 对比 game_state.json 里的真实速度
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


class VelocityEstimator:
    def __init__(self, window_size=10, teleport_threshold=200):
        self.window = []
        self.window_size = window_size
        self.teleport_threshold = teleport_threshold

    def add(self, timestamp, x, y):
        if self.window:
            _, prev_x, prev_y = self.window[-1]
            dist = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
            if dist > self.teleport_threshold:
                self.window.clear()
        self.window.append((timestamp, x, y))
        if len(self.window) > self.window_size:
            self.window.pop(0)

    def estimate(self):
        if len(self.window) < 2:
            return 0.0, 0.0
        ts = np.array([w[0] for w in self.window])
        xs = np.array([w[1] for w in self.window])
        ys = np.array([w[2] for w in self.window])
        ts = ts - ts[0]
        if ts[-1] == 0:
            return 0.0, 0.0
        try:
            vx = np.polyfit(ts, xs, 1)[0]
            vy = np.polyfit(ts, ys, 1)[0]
        except Exception:
            return 0.0, 0.0
        if len(ts) >= 3:
            x_fit = np.polyval(np.polyfit(ts, xs, 1), ts)
            y_fit = np.polyval(np.polyfit(ts, ys, 1), ts)
            ss_res = np.sum((xs - x_fit) ** 2) + np.sum((ys - y_fit) ** 2)
            ss_tot = np.sum((xs - xs.mean()) ** 2) + \
                     np.sum((ys - ys.mean()) ** 2)
            if ss_tot > 0:
                r2 = 1 - ss_res / ss_tot
                if r2 < 0.5:
                    vx = (xs[-1] - xs[-2]) / (ts[-1] - ts[-2])
                    vy = (ys[-1] - ys[-2]) / (ts[-1] - ts[-2])
        return float(vx), float(vy)


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
    print("Client size: {}x{}".format(client_rect[2] - client_rect[0],
                                      client_rect[3] - client_rect[1]))

    sct = mss.MSS()
    monitor = {
        "left": client_rect[0],
        "top": client_rect[1],
        "width": client_rect[2] - client_rect[0],
        "height": client_rect[3] - client_rect[1],
    }

    estimator = VelocityEstimator(window_size=10)

    print("\n帧  感知(x,y)    估计vx,vy      真实vx,vy     估计速  真实速  误差%")
    print("-" * 75)

    speed_errors = []

    for i in range(40):
        t0 = time.perf_counter()
        img = np.array(sct.grab(monitor))[:, :, :3]
        target = find_target(img)
        t1 = time.perf_counter()

        if target is None:
            time.sleep(0.05)
            continue

        vx_est, vy_est = estimator.estimate()

        estimator.add(t0, target[0], target[1])

        state = read_state()
        real_vx, real_vy = 0.0, 0.0
        if state and state.get("target"):
            real_vx = state["target"].get("vx", 0.0)
            real_vy = state["target"].get("vy", 0.0)

        est_speed = (vx_est ** 2 + vy_est ** 2) ** 0.5
        real_speed = (real_vx ** 2 + real_vy ** 2) ** 0.5

        if real_speed > 10:
            error_pct = abs(est_speed - real_speed) / real_speed * 100
            speed_errors.append(error_pct)
            print("{:2d}  ({:3d},{:3d})    ({:7.1f},{:7.1f})  ({:7.1f},{:7.1f})  {:5.1f}  {:5.1f}  {:4.0f}%".format(
                i, target[0], target[1], vx_est, vy_est,
                real_vx, real_vy, est_speed, real_speed, error_pct))
        else:
            print("{:2d}  ({:3d},{:3d})    ({:7.1f},{:7.1f})  ({:7.1f},{:7.1f})  {:5.1f}  {:5.1f}    -".format(
                i, target[0], target[1], vx_est, vy_est,
                real_vx, real_vy, est_speed, real_speed))

        time.sleep(0.05)

    print("\n--- 汇总 ---")
    if speed_errors:
        print("速度误差: avg={:.0f}%, max={:.0f}%, min={:.0f}%".format(
            sum(speed_errors) / len(speed_errors),
            max(speed_errors), min(speed_errors)))
    print("有效帧数: {}".format(len(speed_errors)))

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()


if __name__ == "__main__":
    main()
