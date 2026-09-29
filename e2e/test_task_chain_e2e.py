"""
test_task_chain_e2e.py - T11 Task Chain Test
Calculator -> Notepad -> Save -> Verify

Flow:
1. Open calculator, compute 123 * 456
2. OCR verify result == 56088
3. Copy result, verify clipboard == "56088"
4. Open notepad, paste result
5. Save to E:\agent_test\task_chain_result.txt
6. Close notepad
7. Verify file content == "56088"
"""

import sys
import os
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
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
RESULT_FILE = r"E:\agent_test\task_chain_result.txt"
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
    calc_result: str = ""
    clipboard_content: str = ""
    file_content: str = ""
    overall_success: bool = True
    total_duration_ms: float = 0.0


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


def find_notepad():
    results = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value.lower()
                if "记事本" in t or "notepad" in t or "无标题" in t:
                    results.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return results[0] if results else None


def wait_notepad(timeout=WAIT_TIMEOUT):
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = find_notepad()
        if h:
            return h
        time.sleep(0.3)
    return None


def focus(hwnd):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


# ---- Calculator Buttons ----

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
    CIDX = {
        "%": 0, "CE": 1, "C": 2, "BS": 3,
        "1/x": 0, "x2": 1, "sqrt": 2, "/": 3,
        "7": 0, "8": 1, "9": 2, "*": 3,
        "4": 0, "5": 1, "6": 2, "-": 3,
        "1": 0, "2": 1, "3": 2, "+": 3,
        "neg": 0, "0": 1, ".": 2, "=": 3,
    }
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
    img.save(str(SCREENSHOT_DIR / "chain_calc_disp.png"))
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
    txt = pytesseract.image_to_string(
        big, config='--psm 7 -c tessedit_char_whitelist=0123456789.,-'
    ).strip()
    return txt.replace(',', '').replace(' ', '')


def set_clipboard(text):
    if HAS_CLIPBOARD:
        pyperclip.copy(text)
        time.sleep(0.2)
        return
    escaped = text.replace('"', '`"')
    cmd = f'Set-Clipboard -Value "{escaped}"'
    subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=5)
    time.sleep(0.3)


def get_clipboard():
    if HAS_CLIPBOARD:
        return pyperclip.paste()
    result = subprocess.run(
        ["powershell", "-Command", "Get-Clipboard"],
        capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip()


def save_ss(name, retry):
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    fp = SCREENSHOT_DIR / f"chain_{name.replace(' ', '_')}_retry{retry}.png"
    pyautogui.screenshot().save(str(fp))
    return str(fp)


class TaskChainTest:
    def __init__(self):
        self.report = TestReport()
        self.calc = None
        self.notepad_hwnd = None

    def _refind_calc(self):
        self.calc = wait_calc()
        if self.calc:
            focus(self.calc[0])
            return True
        return False

    def _refind_notepad(self):
        self.notepad_hwnd = wait_notepad()
        if self.notepad_hwnd:
            focus(self.notepad_hwnd)
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
                time.sleep(0.5)
        return StepResult(name=name, success=False, duration_ms=0,
                          retries=MAX_RETRIES, error="max retries")

    # ---- Steps ----

    def step1_open_calc(self):
        subprocess.Popen(["calc.exe"])
        time.sleep(2.0)
        self.calc = wait_calc()
        if not self.calc:
            raise Exception("Calculator not found")
        focus(self.calc[0])
        wl, wt, ww, wh = self.calc[1:]
        click_btn("C", wl, wt, ww, wh)
        time.sleep(0.3)

    def step2_compute(self):
        wl, wt, ww, wh = self.calc[1:]
        for b in ["1", "2", "3", "*", "4", "5", "6", "="]:
            click_btn(b, wl, wt, ww, wh)
        time.sleep(0.5)

    def step3_verify_calc(self):
        wl, wt, ww, wh = self.calc[1:]
        r = read_display(wl, wt, ww, wh)
        self.report.calc_result = r
        print(f"    OCR result: '{r}' (expect 56088)")
        return r == "56088"

    def step4_copy_result(self):
        wl, wt, ww, wh = self.calc[1:]
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.3)

    def step5_verify_clipboard(self):
        clip = get_clipboard()
        self.report.clipboard_content = clip
        print(f"    Clipboard: '{clip}' (expect 56088)")
        return clip == "56088"

    def step6_open_notepad(self):
        subprocess.Popen(["notepad.exe"])
        time.sleep(2.0)
        self.notepad_hwnd = wait_notepad()
        if not self.notepad_hwnd:
            raise Exception("Notepad not found")
        focus(self.notepad_hwnd)

    def step7_paste(self):
        if not self.notepad_hwnd or not user32.IsWindow(self.notepad_hwnd):
            self.notepad_hwnd = wait_notepad()
        if self.notepad_hwnd:
            focus(self.notepad_hwnd)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)

    def step8_save(self):
        if not self.notepad_hwnd or not user32.IsWindow(self.notepad_hwnd):
            self.notepad_hwnd = wait_notepad()
        if self.notepad_hwnd:
            focus(self.notepad_hwnd)
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 's')
        time.sleep(2.0)
        # Focus filename field
        pyautogui.hotkey('alt', 'n')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        set_clipboard(RESULT_FILE)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
        pyautogui.press('enter')
        time.sleep(2.0)

    def step9_close_notepad(self):
        if self.notepad_hwnd and user32.IsWindow(self.notepad_hwnd):
            focus(self.notepad_hwnd)
            pyautogui.hotkey('alt', 'f4')
            time.sleep(1.0)
            # Handle "save?" dialog - press N for no
            for _ in range(3):
                if self.notepad_hwnd and not user32.IsWindow(self.notepad_hwnd):
                    break
                pyautogui.press('n')
                time.sleep(0.3)

    def step10_close_calc(self):
        if self.calc and user32.IsWindow(self.calc[0]):
            user32.PostMessageW(self.calc[0], 0x0010, 0, 0)
            time.sleep(0.5)

    def step11_verify_file(self):
        if not os.path.exists(RESULT_FILE):
            raise Exception(f"File not found: {RESULT_FILE}")
        with open(RESULT_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        self.report.file_content = content
        print(f"    File content: '{content}' (expect 56088)")
        return content == "56088"

    def run(self):
        print("=" * 60)
        print("T11 Task Chain Test: Calculator -> Notepad -> Verify")
        print("=" * 60)
        os.makedirs(r"E:\agent_test", exist_ok=True)
        # Remove old result file
        if os.path.exists(RESULT_FILE):
            os.remove(RESULT_FILE)

        t_start = time.perf_counter()
        steps = [
            ("1. Open Calculator", self.step1_open_calc, None),
            ("2. Compute 123*456", self.step2_compute, None),
            ("3. Verify Calc Result", self.step3_verify_calc, None),
            ("4. Copy Result", self.step4_copy_result, None),
            ("5. Verify Clipboard", self.step5_verify_clipboard, None),
            ("6. Open Notepad", self.step6_open_notepad, None),
            ("7. Paste Result", self.step7_paste, None),
            ("8. Save File", self.step8_save, None),
            ("9. Close Notepad", self.step9_close_notepad, None),
            ("10. Close Calculator", self.step10_close_calc, None),
            ("11. Verify File", self.step11_verify_file, None),
        ]
        for name, fn, chk in steps:
            print(f"\n--- {name} ---")
            r = self._run(name, fn, chk)
            self.report.steps.append(r)
            if not r.success:
                self.report.overall_success = False
                print(f"\n  FATAL: '{name}' failed.")
                break

        self.report.total_duration_ms = (time.perf_counter() - t_start) * 1000
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
        print(f"\n  Calc OCR:    '{self.report.calc_result}' (expect 56088)")
        print(f"  Clipboard:   '{self.report.clipboard_content}' (expect 56088)")
        print(f"  File:        '{self.report.file_content}' (expect 56088)")
        print(f"  File path:   {RESULT_FILE}")
        print(f"  Steps time:  {total:.0f}ms")
        print(f"  Total time:  {self.report.total_duration_ms:.0f}ms")
        ok = self.report.overall_success
        print(f"  Overall:     {'PASS' if ok else 'FAIL'}")
        if not ok:
            for s in self.report.steps:
                if not s.success:
                    print(f"\n  Failed at: {s.name}")
                    if s.screenshot_path:
                        print(f"  Screenshot: {s.screenshot_path}")
                    break
        print("=" * 60)


if __name__ == "__main__":
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    print("T11 Task Chain Test - starting in 3s...")
    print("Do NOT touch mouse/keyboard.")
    time.sleep(3)
    r = TaskChainTest().run()
    sys.exit(0 if r.overall_success else 1)
