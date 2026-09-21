# -*- coding: utf-8 -*-
"""
T2 多靶子决策测试

验证 Agent 能区分红色和蓝色靶子，只点红色，点蓝扣分。
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

GAME_PATH = r"E:\agent_test\game.py"
WINDOW_TITLE_KEYWORD = "Target Game"
STATE_FILE = r"E:\agent_test\game_state.json"

RUNS = 3
MAX_CLICKS = 100
ROUND_TIMEOUT = 30

RED_LOWER1 = np.array([0, 100, 100])
RED_UPPER1 = np.array([10, 255, 255])
RED_LOWER2 = np.array([170, 100, 100])
RED_UPPER2 = np.array([180, 255, 255])

BLUE_LOWER = np.array([100, 100, 100])
BLUE_UPPER = np.array([130, 255, 255])


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


def find_targets_by_color(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Red detection (two ranges)
    red_mask1 = cv2.inRange(hsv, RED_LOWER1, RED_UPPER1)
    red_mask2 = cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)

    # Blue detection
    blue_mask = cv2.inRange(hsv, BLUE_LOWER, BLUE_UPPER)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_CLOSE, kernel)
    blue_mask = cv2.morphologyEx(blue_mask, cv2.MORPH_OPEN, kernel)

    red_targets = []
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
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
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        red_targets.append((cx, cy, area))

    blue_targets = []
    contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
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
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        blue_targets.append((cx, cy, area))

    return red_targets, blue_targets


def run_one_round(io):
    proc = subprocess.Popen(
        ["python", GAME_PATH, "--multi-target"],
        cwd=r"E:\agent_test"
    )
    time.sleep(1.5)

    hwnd = find_window()
    if hwnd is None:
        proc.terminate()
        return None

    window_rect = get_window_rect(hwnd)
    io.set_window_rect(window_rect)

    clicks = 0
    red_hits = 0
    blue_mistakes = 0
    start = time.perf_counter()
    last_score = 0

    click_times = []
    while clicks < MAX_CLICKS:
        if time.perf_counter() - start > ROUND_TIMEOUT:
            break

        t0 = time.perf_counter()
        img = io.screenshot()
        red_targets, blue_targets = find_targets_by_color(img)
        t1 = time.perf_counter()

        if not red_targets:
            time.sleep(0.05)
            continue

        # Pick the largest red target
        best_red = max(red_targets, key=lambda t: t[2])
        rx, ry, _ = best_red

        io.click(rx, ry)
        t2 = time.perf_counter()
        clicks += 1
        click_times.append({
            "click": clicks,
            "screenshot_ms": (t1 - t0) * 1000,
            "detect_ms": (t1 - t0) * 1000,
            "click_ms": (t2 - t1) * 1000,
            "total_ms": (t2 - t0) * 1000,
        })

        time.sleep(0.05)

        state = read_state()
        if state is not None:
            score = state.get("score", 0)
            if score > last_score:
                red_hits += 1
                last_score = score
            elif score < last_score:
                blue_mistakes += 1
                last_score = score

            if state.get("finished"):
                break

    duration = time.perf_counter() - start
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    return {
        "clicks": clicks,
        "red_hits": red_hits,
        "blue_mistakes": blue_mistakes,
        "hit_rate": red_hits / clicks if clicks > 0 else 0,
        "passed": last_score >= 10,
        "duration": duration,
        "final_score": last_score,
        "click_times": click_times,
    }


def main():
    print("=" * 60)
    print("T2 多靶子决策测试")
    print("=" * 60)

    io = FastIO()
    results = []

    for i in range(RUNS):
        print(f"\n--- 第 {i+1}/{RUNS} 局 ---")
        r = run_one_round(io)
        if r is None:
            print("  游戏窗口未找到，跳过")
            continue
        results.append(r)
        print(f"  点击数: {r['clicks']}")
        print(f"  红靶命中: {r['red_hits']}")
        print(f"  误点蓝靶: {r['blue_mistakes']}")
        print(f"  命中率: {r['hit_rate']:.1%}")
        print(f"  最终得分: {r['final_score']}")
        print(f"  通关: {'是' if r['passed'] else '否'}")
        print(f"  耗时: {r['duration']:.1f}s")
        if r.get("click_times"):
            print(f"  --- 每次点击耗时 ---")
            for ct in r["click_times"]:
                print(f"    #{ct['click']:2d}  截屏+检测={ct['screenshot_ms']:.1f}ms  "
                      f"点击={ct['click_ms']:.1f}ms  合计={ct['total_ms']:.1f}ms")
            avg_total = sum(c["total_ms"] for c in r["click_times"]) / len(r["click_times"])
            print(f"    平均: {avg_total:.1f}ms/次")

    if not results:
        print("\n无有效结果")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("汇总")
    print(f"{'='*60}")
    all_passed = all(r["passed"] for r in results)
    total_blue = sum(r["blue_mistakes"] for r in results)
    avg_hit = sum(r["hit_rate"] for r in results) / len(results)
    avg_dur = sum(r["duration"] for r in results) / len(results)

    print(f"总局数: {len(results)}")
    print(f"全部通关: {'是' if all_passed else '否'}")
    print(f"误点蓝靶总次数: {total_blue}")
    print(f"平均命中率: {avg_hit:.1%}")
    print(f"平均耗时: {avg_dur:.1f}s")

    pass_criteria = (all_passed and total_blue == 0 and avg_hit > 0.9 and avg_dur < 15)
    print(f"\n验收: {'通过' if pass_criteria else '未通过'}")

    with open("T2_results.json", "w", encoding="utf-8") as f:
        json.dump({
            "runs": results,
            "summary": {
                "all_passed": all_passed,
                "total_blue_mistakes": total_blue,
                "avg_hit_rate": avg_hit,
                "avg_duration": avg_dur,
                "pass_criteria": pass_criteria,
            }
        }, f, indent=2, ensure_ascii=False)

    print("结果已保存到 T2_results.json")

    sys.exit(0 if pass_criteria else 1)


if __name__ == "__main__":
    main()
