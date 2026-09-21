# -*- coding: utf-8 -*-
"""
T1 移动靶预判测试

测试 Agent 在移动靶场景下的命中率，对比：
- 无预判
- 预判（mss + ctypes）
- 预判（pyautogui）
"""

import sys
import time
import json
import subprocess
import ctypes
import warnings
from ctypes import wintypes

warnings.filterwarnings("ignore")

import cv2
import numpy as np
import mss

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

GAME_PATH = r"E:\agent_test\game.py"
WINDOW_TITLE_KEYWORD = "Target Game"
STATE_FILE = r"E:\agent_test\game_state.json"

SPEEDS = [0, 2, 5, 8]
RUNS_PER_SPEED = 3
MAX_CLICKS = 100
ROUND_TIMEOUT = 60

LATENCY_MSS = 0.017
LATENCY_PYAUTOGUI = 0.050
SPEED_CORRECTION = 1.4

RED_LOWER1 = np.array([0, 100, 100])
RED_UPPER1 = np.array([10, 255, 255])
RED_LOWER2 = np.array([170, 100, 100])
RED_UPPER2 = np.array([180, 255, 255])


class FastIO:
    def __init__(self, window_rect=None):
        self.sct = mss.MSS()
        self.window_rect = window_rect

    def set_window_rect(self, window_rect):
        self.window_rect = window_rect

    def screenshot(self):
        if self.window_rect:
            left, top, right, bottom = self.window_rect
            monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            monitor = self.sct.monitors[1]
        img = np.array(self.sct.grab(monitor))
        return img[:, :, :3]

    def click(self, x, y):
        if self.window_rect:
            left, top, _, _ = self.window_rect
            x += left
            y += top
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


class PyAutoGUI_IO:
    def __init__(self, window_rect=None):
        self.window_rect = window_rect

    def set_window_rect(self, window_rect):
        self.window_rect = window_rect

    def screenshot(self):
        if self.window_rect:
            left, top, right, bottom = self.window_rect
            img = pyautogui.screenshot(region=(left, top, right - left, bottom - top))
        else:
            img = pyautogui.screenshot()
        return np.array(img)[:, :, ::-1]

    def click(self, x, y):
        if self.window_rect:
            left, top, _, _ = self.window_rect
            x += left
            y += top
        pyautogui.click(x, y)


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


def get_window_rect(hwnd):
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt1 = wintypes.POINT(rect.left, rect.top)
    pt2 = wintypes.POINT(rect.right, rect.bottom)
    user32.ClientToScreen(hwnd, ctypes.byref(pt1))
    user32.ClientToScreen(hwnd, ctypes.byref(pt2))
    return pt1.x, pt1.y, pt2.x, pt2.y


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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


class Predictor:
    def __init__(self, window_size=10, teleport_dist=200):
        self.window = []
        self.window_size = window_size
        self.teleport_dist = teleport_dist
        self.vx = 0.0
        self.vy = 0.0
        self.alpha = 0.3

    def add(self, x, y):
        now = time.perf_counter()
        if self.window:
            prev_t, prev_x, prev_y = self.window[-1]
            dist = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
            if dist > self.teleport_dist:
                self.window = [(now, x, y)]
                self.vx = 0.0
                self.vy = 0.0
                return
            dt = now - prev_t
            if dt > 0:
                inst_vx = (x - prev_x) / dt
                inst_vy = (y - prev_y) / dt
                self.vx = self.alpha * inst_vx + (1 - self.alpha) * self.vx
                self.vy = self.alpha * inst_vy + (1 - self.alpha) * self.vy
        self.window.append((now, x, y))
        if len(self.window) > self.window_size:
            self.window.pop(0)

    def estimate_velocity(self):
        n = len(self.window)
        if n < 2:
            return 0.0, 0.0
        return float(self.vx), float(self.vy)

    def predict(self, x, y, latency, radius=30, bounds=(0, 0, 800, 600)):
        vx, vy = self.estimate_velocity()
        if vx == 0 and vy == 0 and len(self.window) >= 2:
            prev_t, prev_x, prev_y = self.window[-2]
            cur_t, cur_x, cur_y = self.window[-1]
            dt = cur_t - prev_t
            if dt > 0:
                vx = (cur_x - prev_x) / dt
                vy = (cur_y - prev_y) / dt
        px = x + vx * latency * SPEED_CORRECTION
        py = y + vy * latency * SPEED_CORRECTION
        max_offset = radius * 0.8
        dx, dy = px - x, py - y
        dist = (dx ** 2 + dy ** 2) ** 0.5
        if dist > max_offset and dist > 0:
            px = x + dx / dist * max_offset
            py = y + dy / dist * max_offset
        px = max(bounds[0], min(bounds[2], px))
        py = max(bounds[1], min(bounds[3], py))
        return px, py


def run_one_round(speed, io, mode, target_radius=30, latency=LATENCY_MSS, debug=False):
    proc = subprocess.Popen(
        ["python", GAME_PATH, "--speed", str(speed),
         "--target-radius", str(target_radius)],
        cwd=r"E:\agent_test"
    )
    time.sleep(1.5)

    hwnd = find_window()
    if hwnd is None:
        proc.terminate()
        return None

    window_rect = get_window_rect(hwnd)
    io.set_window_rect(window_rect)

    predictor = Predictor()
    clicks = 0
    hits = 0
    offsets = []
    start = time.perf_counter()
    last_score = 0

    debug_lines = []

    while clicks < MAX_CLICKS:
        if time.perf_counter() - start > ROUND_TIMEOUT:
            break

        t_perceive_start = time.perf_counter()
        img = io.screenshot()
        target = find_target(img)
        t_perceive_end = time.perf_counter()

        if target is None:
            time.sleep(0.05)
            continue

        x, y = target
        predictor.add(x, y)

        if mode == "predict" and speed > 0:
            px, py = predictor.predict(x, y, latency, radius=target_radius)
        else:
            px, py = float(x), float(y)

        vx_est, vy_est = predictor.estimate_velocity()

        io.click(px, py)
        clicks += 1

        time.sleep(0.05)

        state = read_state()
        is_hit = False
        if state is not None:
            score = state.get("score", 0)
            if score > last_score:
                hits += 1
                last_score = score
                is_hit = True

        offset = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
        offsets.append(offset)

        if debug and clicks <= 20:
            tag = "HIT" if is_hit else "miss"
            perc_ms = (t_perceive_end - t_perceive_start) * 1000
            debug_lines.append(
                "  click {:2d}: perc=({:.0f},{:.0f}) v=({:.0f},{:.0f}) "
                "pred=({:.0f},{:.0f}) offset={:.1f}px [{:}] {:.1f}ms".format(
                    clicks, x, y, vx_est, vy_est, px, py,
                    offset, tag, perc_ms))

        if state is not None and state.get("finished"):
            break

    duration = time.perf_counter() - start
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    result = {
        "clicks": clicks,
        "hits": hits,
        "hit_rate": hits / clicks if clicks > 0 else 0,
        "avg_offset": sum(offsets) / len(offsets) if offsets else 0,
        "passed": last_score >= 10,
        "duration": duration,
    }
    if debug:
        result["debug_lines"] = debug_lines
    return result


def run_test_suite(radius, speeds, io_fast, io_slow):
    print(f"\n{'='*60}")
    print(f"靶子半径 = {radius}px")
    print(f"{'='*60}")

    results = {}
    for speed in speeds:
        print(f"\n=== 速度 {speed} ===")
        results[speed] = {}

        modes = [("no_predict", io_fast, "no_predict"),
                 ("predict_mss", io_fast, "predict")]
        if io_slow:
            modes.append(("predict_pyautogui", io_slow, "predict"))

        for name, io, mode in modes:
            lat = LATENCY_PYAUTOGUI if io is io_slow else LATENCY_MSS
            print(f"  跑 {name} (latency={lat*1000:.1f}ms)...")
            runs = []
            for i in range(RUNS_PER_SPEED):
                r = run_one_round(speed, io, mode,
                                  target_radius=radius, latency=lat,
                                  debug=(i == 0))
                if r:
                    runs.append(r)
                    print(f"    第{i+1}次: 命中率 {r['hit_rate']:.1%}, "
                          f"偏差 {r['avg_offset']:.1f}px, "
                          f"通关 {r['passed']}")
                    if r.get("debug_lines"):
                        for line in r["debug_lines"]:
                            print(line)
            if runs:
                results[speed][name] = {
                    "hit_rate": sum(x["hit_rate"] for x in runs) / len(runs),
                    "avg_offset": sum(x["avg_offset"] for x in runs) / len(runs),
                    "passed": all(x["passed"] for x in runs),
                }
    return results


def print_table(title, results, speeds):
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    header = f"{'速度':<6}{'无预判':<12}{'预判mss':<14}{'预判pyautogui':<16}"
    print(header)
    print("-" * 60)
    for speed in speeds:
        r = results.get(speed, {})
        np_r = r.get("no_predict", {}).get("hit_rate", 0)
        pm_r = r.get("predict_mss", {}).get("hit_rate", 0)
        pp_r = r.get("predict_pyautogui", {}).get("hit_rate", 0)
        print(f"{speed:<6}{np_r:<12.1%}{pm_r:<14.1%}{pp_r:<16.1%}")


def main():
    print("=" * 60)
    print("T1 移动靶预判测试")
    print("=" * 60)
    print("LATENCY_MSS = {}s, LATENCY_PYAUTOGUI = {}s, SPEED_CORRECTION = {}".format(
        LATENCY_MSS, LATENCY_PYAUTOGUI, SPEED_CORRECTION))

    fast_io = FastIO()
    slow_io = PyAutoGUI_IO() if HAS_PYAUTOGUI else None

    results_30 = run_test_suite(30, SPEEDS, fast_io, slow_io)
    results_15 = run_test_suite(15, SPEEDS, fast_io, slow_io)

    print_table("半径30px - 命中率", results_30, SPEEDS)
    print_table("半径15px - 命中率", results_15, SPEEDS)

    print("\n完成")


if __name__ == "__main__":
    main()
