"""test_resolution_e2e.py - T4 Resolution Change Test
Verify Agent perception and clicking work correctly across different window sizes.
"""
import subprocess
import time
import json
import os
import sys
import ctypes
import ctypes.wintypes
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
import mss

GAME_PATH = r"E:\agent_test\game.py"
STATE_FILE = r"E:\agent_test\game_state.json"
WINDOW_TITLE = "Target Game"
user32 = ctypes.windll.user32

RED_LOWER1 = np.array([0, 100, 100])
RED_UPPER1 = np.array([10, 255, 255])
RED_LOWER2 = np.array([170, 100, 100])
RED_UPPER2 = np.array([180, 255, 255])

TARGET_SCORE = 10
MAX_CLICKS = 200
TIMEOUT = 30

TEST_MATRIX = [
    (800, 600, 30),
    (1280, 720, 30),
    (1920, 1080, 30),
    (800, 600, 15),
    (1280, 720, 15),
    (1920, 1080, 15),
]


@dataclass
class RoundResult:
    width: int = 0
    height: int = 0
    radius: int = 0
    clicks: int = 0
    hits: int = 0
    passed: bool = False
    duration: float = 0.0
    final_score: int = 0
    vision_failures: int = 0


@dataclass
class TestReport:
    rounds: List[RoundResult] = field(default_factory=list)
    total_duration: float = 0.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None


def find_windows_by_title(keyword):
    results = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if keyword.lower() in buf.value.lower():
                    results.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return results


def get_game_window_rect():
    for hwnd in find_windows_by_title(WINDOW_TITLE):
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        pt = ctypes.wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return pt.x, pt.y, rect.right, rect.bottom
    return None


def focus_game():
    for hwnd in find_windows_by_title(WINDOW_TITLE):
        try:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            return True
        except:
            pass
    return False


def find_red_target(sct, window_rect) -> Optional[Tuple[int, int]]:
    """mss screenshot + OpenCV HSV red detection"""
    left, top, w, h = window_rect
    monitor = {"left": left, "top": top, "width": w, "height": h}
    img = np.array(sct.grab(monitor))[:, :, :3]  # BGR

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOWER1, RED_UPPER1)
    mask2 = cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    red_mask = cv2.bitwise_or(mask1, mask2)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_area = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 100:
            continue
        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue
        circularity = 4 * 3.14159 * area / (perimeter ** 2)
        if circularity < 0.2:
            continue
        if area > best_area:
            best_area = area
            best = c

    if best is None:
        return None

    M = cv2.moments(best)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return cx, cy


def click_at(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def kill_game_windows():
    for hwnd in find_windows_by_title(WINDOW_TITLE):
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except:
            pass
    time.sleep(0.5)


def run_round(width, height, radius):
    result = RoundResult(width=width, height=height, radius=radius)
    start = time.time()

    log(f"--- {width}x{height} r={radius} ---")

    # Clean old state
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        time.sleep(0.1)

    # Launch game
    log("  Launching game...")
    game_proc = subprocess.Popen(
        [sys.executable, GAME_PATH,
         "--speed", "0",
         "--target-radius", str(radius),
         "--width", str(width),
         "--height", str(height)],
        cwd=r"E:\agent_test",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait for game window
    log("  Waiting for game window...")
    wrect = None
    for _ in range(30):
        wrect = get_game_window_rect()
        if wrect:
            # Verify client size matches expected
            if wrect[2] == width and wrect[3] == height:
                break
            log(f"  Window found but size={wrect[2]}x{wrect[3]}, retrying...")
        wrect = None
        time.sleep(0.2)

    if not wrect:
        log("  ERROR: Game window not found")
        result.duration = time.time() - start
        game_proc.kill()
        return result

    log(f"  Window OK: client={wrect[2]}x{wrect[3]}")
    focus_game()
    time.sleep(0.3)

    sct = mss.mss()
    last_score = 0

    while result.clicks < MAX_CLICKS:
        elapsed = time.time() - start
        if elapsed > TIMEOUT:
            log(f"  TIMEOUT after {TIMEOUT}s")
            break

        # Check state for score
        state = read_state()
        if state and state.get("finished"):
            result.passed = True
            result.final_score = state.get("score", 0)
            log(f"  PASSED! score={result.final_score}")
            break

        # Vision: find red target
        wrect = get_game_window_rect()
        if not wrect:
            time.sleep(0.1)
            continue

        target = find_red_target(sct, wrect)
        if target is None:
            result.vision_failures += 1
            time.sleep(0.05)
            continue

        tx, ty = target
        screen_x = wrect[0] + tx
        screen_y = wrect[1] + ty

        focus_game()
        time.sleep(0.02)
        click_at(screen_x, screen_y)
        result.clicks += 1

        time.sleep(0.05)
        new_state = read_state()
        if new_state:
            new_score = new_state.get("score", 0)
            if new_score > last_score:
                result.hits += 1
                last_score = new_score
            if new_state.get("finished"):
                result.passed = True
                result.final_score = new_score
                log(f"  PASSED! score={new_score}")
                break

    result.duration = time.time() - start
    result.final_score = last_score

    try:
        game_proc.kill()
        game_proc.wait(timeout=2)
    except:
        pass

    kill_game_windows()

    hit_rate = result.hits / result.clicks * 100 if result.clicks > 0 else 0
    log(f"  clicks={result.clicks} hits={result.hits} "
        f"hit_rate={hit_rate:.1f}% duration={result.duration:.1f}s "
        f"vision_fails={result.vision_failures}")
    return result


def main():
    print("=" * 60)
    print("T4 Resolution Change Test (Pure Vision)")
    print("=" * 60)
    print(f"Test matrix: {len(TEST_MATRIX)} combinations")
    for w, h, r in TEST_MATRIX:
        print(f"  {w}x{h} r={r}")
    print()

    report = TestReport()
    total_start = time.time()

    for w, h, r in TEST_MATRIX:
        kill_game_windows()
        time.sleep(0.5)
        result = run_round(w, h, r)
        report.rounds.append(result)

    report.total_duration = time.time() - total_start

    # Print table
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"| {'Window':<12} | {'Radius':<6} | {'Pass':<5} | {'Duration':<8} | {'Clicks':<7} | {'Hits':<5} | {'HitRate':<8} | {'VisionFails':<11} |")
    print(f"|{'-'*14}|{'-'*8}|{'-'*7}|{'-'*10}|{'-'*9}|{'-'*7}|{'-'*10}|{'-'*13}|")
    for r in report.rounds:
        hit_rate = r.hits / r.clicks * 100 if r.clicks > 0 else 0
        print(f"| {r.width}x{r.height:<6} | {r.radius:<6} | {'Y' if r.passed else 'N':<5} "
              f"| {r.duration:<7.1f}s | {r.clicks:<7} | {r.hits:<5} "
              f"| {hit_rate:<7.1f}% | {r.vision_failures:<11} |")

    # Summary
    all_passed = all(r.passed for r in report.rounds)
    all_hit_rates = []
    for r in report.rounds:
        if r.clicks > 0:
            all_hit_rates.append(r.hits / r.clicks * 100)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  All passed:     {all_passed}")
    print(f"  Total duration: {report.total_duration:.1f}s")
    if all_hit_rates:
        avg_hit = sum(all_hit_rates) / len(all_hit_rates)
        min_hit = min(all_hit_rates)
        print(f"  Avg hit rate:   {avg_hit:.1f}%")
        print(f"  Min hit rate:   {min_hit:.1f}%")

    # Check acceptance criteria
    ok = all_passed and (min(all_hit_rates) > 90 if all_hit_rates else False)
    print(f"\n  Acceptance: {'PASS' if ok else 'FAIL'}")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
