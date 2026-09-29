"""test_popup_interference_e2e.py - T3 Popup Interference Test (Pure Vision)"""
import subprocess
import time
import json
import os
import sys
import ctypes
import ctypes.wintypes
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
import mss

GAME_PATH = r"E:\agent_test\game.py"
STATE_FILE = r"E:\agent_test\game_state.json"
WINDOW_TITLE = "Target Game"
user32 = ctypes.windll.user32
TARGET_SCORE = 10
MAX_CLICKS = 200
TIMEOUT = 30

RED_LOWER1 = np.array([0, 100, 100])
RED_UPPER1 = np.array([10, 255, 255])
RED_LOWER2 = np.array([170, 100, 100])
RED_UPPER2 = np.array([180, 255, 255])


@dataclass
class RoundResult:
    clicks: int = 0
    popups_appeared: int = 0
    popups_closed: int = 0
    passed: bool = False
    duration: float = 0.0
    final_score: int = 0


@dataclass
class TestReport:
    rounds: List[RoundResult] = field(default_factory=list)
    total_duration: float = 0.0


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def read_score():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
            return s.get("score", 0), s.get("finished", False)
    except:
        return 0, False


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


def close_popup(hwnd):
    try:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.1)
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(0.2)
        return True
    except:
        return False


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
    """Pure vision: mss screenshot + OpenCV HSV red detection"""
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
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    return cx, cy


def click_at(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def run_round(round_num):
    result = RoundResult()
    start = time.time()
    log(f"=== Round {round_num} ===")

    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        time.sleep(0.2)

    log("Launching game...")
    game_proc = subprocess.Popen(
        [sys.executable, GAME_PATH, "--speed", "0", "--target-radius", "30"],
        cwd=r"E:\agent_test",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # Wait for game window
    log("Waiting for game window...")
    wrect = None
    for _ in range(25):
        wrect = get_game_window_rect()
        if wrect:
            break
        time.sleep(0.2)

    if not wrect:
        log("ERROR: Game window not found")
        result.duration = time.time() - start
        game_proc.kill()
        return result

    log(f"Game window found: {wrect}")
    focus_game()
    time.sleep(0.5)

    popup_script = Path(__file__).parent / "popup_generator.py"
    log("Launching popup generator (5 popups)...")
    popup_proc = subprocess.Popen(
        [sys.executable, str(popup_script), "5"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    sct = mss.mss()
    last_score = 0

    while result.clicks < MAX_CLICKS:
        elapsed = time.time() - start
        if elapsed > TIMEOUT:
            log(f"Timeout after {TIMEOUT}s")
            break

        score, finished = read_score()
        if finished:
            result.passed = True
            result.final_score = score
            log(f"Game FINISHED! Score: {score}")
            break

        # Check for popups
        popups = find_windows_by_title("Interference")
        if popups:
            for hwnd in popups:
                result.popups_appeared += 1
                log(f"  Popup #{result.popups_appeared} detected, closing...")
                if close_popup(hwnd):
                    result.popups_closed += 1
                    log(f"  Popup closed OK")
                time.sleep(0.1)
            focus_game()
            time.sleep(0.1)

        # Re-check window rect (in case window moved)
        wrect = get_game_window_rect()
        if not wrect:
            time.sleep(0.1)
            continue

        # Pure vision: find red target via mss + OpenCV
        target = find_red_target(sct, wrect)
        if target is None:
            time.sleep(0.05)
            continue

        tx, ty = target
        # target is in client coords, convert to screen coords
        screen_x = wrect[0] + tx
        screen_y = wrect[1] + ty

        focus_game()
        time.sleep(0.03)
        click_at(screen_x, screen_y)
        result.clicks += 1

        time.sleep(0.05)
        new_score, _ = read_score()
        if new_score != last_score:
            log(f"  Click #{result.clicks}: score={new_score}/{TARGET_SCORE}")
            last_score = new_score

        time.sleep(0.05)

    result.duration = time.time() - start
    result.final_score = last_score

    try:
        game_proc.kill()
        game_proc.wait(timeout=2)
    except:
        pass
    try:
        popup_proc.kill()
        popup_proc.wait(timeout=2)
    except:
        pass

    for hwnd in find_windows_by_title("Interference"):
        try:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        except:
            pass

    return result


def main():
    print("=" * 60)
    print("T3 Popup Interference Test (Pure Vision)")
    print("=" * 60)

    report = TestReport()
    total_start = time.time()

    for i in range(1):
        r = run_round(i + 1)
        report.rounds.append(r)
        log(f"Round {i+1}: passed={r.passed}, clicks={r.clicks}, "
            f"popups={r.popups_appeared}, closed={r.popups_closed}, "
            f"duration={r.duration:.1f}s")

    report.total_duration = time.time() - total_start

    print("\n" + "=" * 60)
    print("TEST REPORT")
    print("=" * 60)
    for i, r in enumerate(report.rounds, 1):
        cr = (r.popups_closed / r.popups_appeared * 100) if r.popups_appeared > 0 else 100.0
        print(f"Round {i}:")
        print(f"  Clicks:          {r.clicks}")
        print(f"  Popups appeared: {r.popups_appeared}")
        print(f"  Popups closed:   {r.popups_closed}")
        print(f"  Close rate:      {cr:.1f}%")
        print(f"  Passed:          {r.passed}")
        print(f"  Final score:     {r.final_score}/{TARGET_SCORE}")
        print(f"  Duration:        {r.duration:.1f}s")

    ap = all(r.passed for r in report.rounds)
    ac = all((r.popups_closed == r.popups_appeared) if r.popups_appeared > 0 else True for r in report.rounds)
    wt = all(r.duration < TIMEOUT for r in report.rounds)

    print(f"\nOverall:")
    print(f"  All passed:        {ap}")
    print(f"  All popups closed: {ac}")
    print(f"  Within timeout:    {wt}")
    print(f"  Total duration:    {report.total_duration:.1f}s")
    print(f"  Vision method:     mss + OpenCV HSV red detection")

    ok = ap and ac and wt
    print(f"\nResult: {'PASS' if ok else 'FAIL'}")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
