"""
test_calculator_e2e.py - T6 Calculator E2E Test
Button coordinates measured from actual calculator screenshot.
Window: (76,100) 336x541
"""

import sys
import os
import re
import time
import subprocess
import ctypes
import ctypes.wintypes
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, str(Path(__file__).parent))

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.12
except ImportError:
    print("ERROR: pyautogui not installed")
    sys.exit(1)

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
MAX_RETRIES = 3
WAIT_TIMEOUT = 5.0
user32 = ctypes.windll.user32


@dataclass
class StepResult:
    name: str
    success: bool
    duration_ms: float
    retries: int
    error: str = ""
    screenshot_path: str = ""


@dataclass
class TestReport:
    steps: List[StepResult] = field(default_factory=list)
    calc1_result: str = ""
    calc2_result: str = ""
    overall_success: bool = True


# ---- Window ----

def find_calc():
    best = [None]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                r = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                w, h = r.right - r.left, r.bottom - r.top
                if 200 < w < 600 and 300 < h < 800:
                    best[0] = (hwnd, r.left, r.top, w, h)
        return True
    user32.EnumWindows(cb, 0)
    return best[0]


def wait_calc(timeout=WAIT_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = find_calc()
        if r:
            return r
        time.sleep(0.3)
    return None


def focus(hwnd):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


# ---- Buttons ----
# Measured from screenshot: window (76,100) 336x541
# Display: top 30%, memory row: 38%, buttons start at 44%
# 6 rows, each ~9.5% height; 4 cols at 18%, 40%, 62%, 84%

def btn_xy(name, wl, wt, ww, wh):
    COL = [0.18, 0.40, 0.62, 0.84]
    ROW = {
        "%": 0.44, "CE": 0.44, "C": 0.44, "BS": 0.44,
        "1/x": 0.535, "x2": 0.535, "sqrt": 0.535, "/": 0.535,
        "7": 0.63, "8": 0.63, "9": 0.63, "*": 0.63,
        "4": 0.725, "5": 0.725, "6": 0.725, "-": 0.725,
        "1": 0.82, "2": 0.82, "3": 0.82, "+": 0.82,
        "neg": 0.915, "0": 0.915, ".": 0.915, "=": 0.915,
    }
    CIDX = {"%":0,"CE":1,"C":2,"BS":3,
            "1/x":0,"x2":1,"sqrt":2,"/":3,
            "7":0,"8":1,"9":2,"*":3,
            "4":0,"5":1,"6":2,"-":3,
            "1":0,"2":1,"3":2,"+":3,
            "neg":0,"0":1,".":2,"=":3}
    col = CIDX[name]
    row = ROW[name]
    return wl + int(COL[col] * ww), wt + int(row * wh)


def click_btn(name, wl, wt, ww, wh):
    x, y = btn_xy(name, wl, wt, ww, wh)
    pyautogui.click(x, y)
    time.sleep(0.12)


def read_display(wl, wt, ww, wh):
    dh = int(wh * 0.28)
    img = pyautogui.screenshot(region=(wl, wt, ww, dh))
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    img.save(str(SCREENSHOT_DIR / "calc_disp.png"))
    if not HAS_OCR:
        return ""
    import cv2
    import numpy as np
    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    y1, y2 = int(gray.shape[0] * 0.5), gray.shape[0]
    crop = gray[y1:y2, :]
    _, thresh = cv2.threshold(crop, 80, 255, cv2.THRESH_BINARY)
    big = cv2.resize(thresh, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    txt = pytesseract.image_to_string(big, config='--psm 7 -c tessedit_char_whitelist=0123456789.,-').strip()
    cleaned = txt.replace(',', '').replace(' ', '')
    return cleaned


def save_ss(name, retry):
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    fp = SCREENSHOT_DIR / f"{name.replace(' ','_')}_retry{retry}.png"
    pyautogui.screenshot().save(str(fp))
    return str(fp)


class CalcTest:
    def __init__(self):
        self.report = TestReport()
        self.c = None

    def _refind(self):
        self.c = wait_calc()
        if self.c:
            focus(self.c[0])
            return True
        return False

    def _run(self, name, fn, check=None):
        for i in range(MAX_RETRIES):
            t0 = time.perf_counter()
            try:
                fn()
                time.sleep(0.3)
                if check and not check():
                    raise Exception("verify failed")
                ms = (time.perf_counter() - t0) * 1000
                print(f"  [PASS] {name} ({ms:.0f}ms)")
                return StepResult(name=name, success=True, duration_ms=ms, retries=i)
            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000
                ss = save_ss(name, i)
                print(f"  [FAIL] {name} #{i+1}: {e}")
                if i == MAX_RETRIES - 1:
                    return StepResult(name=name, success=False, duration_ms=ms,
                                      retries=i, error=str(e), screenshot_path=ss)
                try:
                    if self._refind():
                        wl, wt, ww, wh = self.c[1:]
                        click_btn("C", wl, wt, ww, wh)
                        time.sleep(0.3)
                except Exception:
                    pass
                time.sleep(0.5)
        return StepResult(name=name, success=False, duration_ms=0,
                          retries=MAX_RETRIES, error="max retries")

    def s1_open(self):
        subprocess.Popen(["calc.exe"])
        time.sleep(2.0)
        if not self._refind():
            raise Exception("Calculator not found")
        # Clear any previous state
        wl, wt, ww, wh = self.c[1:]
        click_btn("C", wl, wt, ww, wh)
        time.sleep(0.3)

    def s1_ok(self):
        return self.c is not None

    def s2_calc1(self):
        wl, wt, ww, wh = self.c[1:]
        for b in ["1","2","3","*","4","5","6","="]:
            click_btn(b, wl, wt, ww, wh)
        time.sleep(0.5)

    def s2_ok(self):
        wl, wt, ww, wh = self.c[1:]
        r = read_display(wl, wt, ww, wh)
        self.report.calc1_result = r
        print(f"    OCR: '{r}' (expect 56088)")
        return r == "56088"

    def s3_clear(self):
        wl, wt, ww, wh = self.c[1:]
        click_btn("C", wl, wt, ww, wh)
        time.sleep(0.3)

    def s4_calc2(self):
        wl, wt, ww, wh = self.c[1:]
        for b in ["9","9","9","+","1","="]:
            click_btn(b, wl, wt, ww, wh)
        time.sleep(0.5)

    def s4_ok(self):
        wl, wt, ww, wh = self.c[1:]
        r = read_display(wl, wt, ww, wh)
        self.report.calc2_result = r
        print(f"    OCR: '{r}' (expect 1000)")
        return r == "1000"

    def s5_close(self):
        if self.c:
            user32.PostMessageW(self.c[0], 0x0010, 0, 0)
            time.sleep(0.5)

    def run(self):
        print("=" * 60)
        print("T6 Calculator E2E Test")
        print("=" * 60)
        steps = [
            ("1. Open Calc", self.s1_open, self.s1_ok),
            ("2. 123x456", self.s2_calc1, self.s2_ok),
            ("3. Clear", self.s3_clear, None),
            ("4. 999+1", self.s4_calc2, self.s4_ok),
            ("5. Close", self.s5_close, None),
        ]
        for name, fn, chk in steps:
            print(f"\n--- {name} ---")
            r = self._run(name, fn, chk)
            self.report.steps.append(r)
            if not r.success:
                self.report.overall_success = False
                print(f"\n  FATAL: '{name}' failed.")
                break
        self._report()
        return self.report

    def _report(self):
        print("\n" + "=" * 60)
        print("TEST REPORT")
        print("=" * 60)
        total = 0
        for s in self.report.steps:
            st = "PASS" if s.success else "FAIL"
            total += s.duration_ms
            ex = f" retries={s.retries}" if s.retries else ""
            if s.error:
                ex += f" err={s.error}"
            print(f"  [{st}] {s.name}: {s.duration_ms:.0f}ms{ex}")
        print(f"\n  123 x 456 = {self.report.calc1_result} (expect 56088)")
        print(f"  999 + 1   = {self.report.calc2_result} (expect 1000)")
        print(f"  Total: {total:.0f}ms  Overall: {'PASS' if self.report.overall_success else 'FAIL'}")
        if not self.report.overall_success:
            for s in self.report.steps:
                if not s.success:
                    print(f"  Failed: {s.name}")
                    if s.screenshot_path:
                        print(f"  Screenshot: {s.screenshot_path}")
                    break
        print("=" * 60)


if __name__ == "__main__":
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    print("T6 Calculator E2E - starting in 3s...")
    print("Do NOT touch mouse/keyboard.")
    time.sleep(3)
    r = CalcTest().run()
    sys.exit(0 if r.overall_success else 1)
