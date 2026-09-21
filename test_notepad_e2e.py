"""
test_notepad_e2e.py - T5 Notepad E2E Test
Uses subprocess to launch notepad directly (avoids Run dialog focus issues).
"""

import sys
import os
import time
import subprocess
import ctypes
import ctypes.wintypes
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from desktop_agent import DesktopAgent

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
except ImportError:
    print("ERROR: pyautogui not installed")
    sys.exit(1)


TEST_TEXT = "Hello from Agent!"
TEST_FILE = r"E:\agent_test\agent_test.txt"
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
    final_content: str = ""
    overall_success: bool = True


def set_clipboard(text):
    escaped = text.replace('"', '`"')
    cmd = f'Set-Clipboard -Value "{escaped}"'
    subprocess.run(["powershell", "-Command", cmd], capture_output=True, timeout=5)
    time.sleep(0.3)


def find_window_by_title(keyword):
    results = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if keyword.lower() in buf.value.lower():
                    results.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return results[0] if results else None


def wait_for_window(keyword, timeout=WAIT_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        hwnd = find_window_by_title(keyword)
        if hwnd:
            return hwnd
        time.sleep(0.3)
    return None


def focus_window(hwnd):
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)


def save_screenshot(step_name, retry):
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    filename = f"{step_name.replace(' ', '_')}_retry{retry}.png"
    filepath = SCREENSHOT_DIR / filename
    img = pyautogui.screenshot()
    img.save(str(filepath))
    return str(filepath)


class NotepadE2ETest:
    def __init__(self):
        self.agent = DesktopAgent()
        self.report = TestReport()
        self.notepad_hwnd = None

    def _ensure_notepad_focused(self):
        if self.notepad_hwnd and user32.IsWindow(self.notepad_hwnd):
            focus_window(self.notepad_hwnd)
            return True
        self.notepad_hwnd = find_window_by_title("记事本")
        if not self.notepad_hwnd:
            self.notepad_hwnd = find_window_by_title("Notepad")
        if not self.notepad_hwnd:
            self.notepad_hwnd = find_window_by_title("无标题")
        if self.notepad_hwnd:
            focus_window(self.notepad_hwnd)
            return True
        return False

    def _run_step(self, name, func, verify_func=None):
        for attempt in range(MAX_RETRIES):
            start = time.perf_counter()
            try:
                func()
                time.sleep(0.5)
                if verify_func and not verify_func():
                    raise Exception("Verification failed")
                duration = (time.perf_counter() - start) * 1000
                print(f"  [PASS] {name} ({duration:.0f}ms)")
                return StepResult(name=name, success=True,
                                  duration_ms=duration, retries=attempt)
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                ss = save_screenshot(name, attempt)
                print(f"  [FAIL] {name} attempt {attempt+1}: {e}")
                if attempt == MAX_RETRIES - 1:
                    return StepResult(name=name, success=False,
                                      duration_ms=duration, retries=attempt,
                                      error=str(e), screenshot_path=ss)
                time.sleep(1)
        return StepResult(name=name, success=False, duration_ms=0,
                          retries=MAX_RETRIES, error="Max retries")

    def step1_open_notepad(self):
        """直接用 subprocess 打开记事本，避免 Run 对话框焦点问题"""
        subprocess.Popen(["notepad.exe"])
        time.sleep(2.0)
        self.notepad_hwnd = wait_for_window("记事本", timeout=WAIT_TIMEOUT)
        if not self.notepad_hwnd:
            self.notepad_hwnd = wait_for_window("Notepad", timeout=2)
        if not self.notepad_hwnd:
            self.notepad_hwnd = wait_for_window("无标题", timeout=2)
        if self.notepad_hwnd:
            focus_window(self.notepad_hwnd)
        else:
            raise Exception("Notepad window not found")

    def verify1_notepad_window(self):
        return self.notepad_hwnd is not None and user32.IsWindow(self.notepad_hwnd)

    def step2_type_content(self):
        self._ensure_notepad_focused()
        set_clipboard(TEST_TEXT)
        self.agent.hotkey('ctrl', 'v')
        time.sleep(0.3)

    def step3_save_with_path(self):
        self._ensure_notepad_focused()
        time.sleep(0.3)
        self.agent.hotkey('ctrl', 's')
        time.sleep(2.0)
        self.agent.hotkey('alt', 'n')
        time.sleep(0.3)
        self.agent.hotkey('ctrl', 'a')
        time.sleep(0.1)
        set_clipboard(TEST_FILE)
        self.agent.hotkey('ctrl', 'v')
        time.sleep(0.5)
        self.agent.press_key('enter')
        time.sleep(2.0)

    def verify3_file_exists(self):
        return os.path.exists(TEST_FILE)

    def step4_close_notepad(self):
        self._ensure_notepad_focused()
        self.agent.hotkey('alt', 'f4')
        time.sleep(1.0)
        for _ in range(5):
            if self.notepad_hwnd and not user32.IsWindow(self.notepad_hwnd):
                break
            time.sleep(0.3)

    def step5_reopen_and_verify(self):
        subprocess.Popen(["notepad.exe"])
        time.sleep(2.0)
        self.notepad_hwnd = wait_for_window("记事本", timeout=WAIT_TIMEOUT)
        if not self.notepad_hwnd:
            self.notepad_hwnd = wait_for_window("Notepad", timeout=2)
        if not self.notepad_hwnd:
            self.notepad_hwnd = wait_for_window("无标题", timeout=2)
        if self.notepad_hwnd:
            focus_window(self.notepad_hwnd)
        else:
            raise Exception("Notepad not found on reopen")
        self.agent.hotkey('ctrl', 'o')
        time.sleep(1.5)
        self.agent.hotkey('alt', 'n')
        time.sleep(0.3)
        self.agent.hotkey('ctrl', 'a')
        time.sleep(0.1)
        set_clipboard(TEST_FILE)
        self.agent.hotkey('ctrl', 'v')
        time.sleep(0.5)
        self.agent.press_key('enter')
        time.sleep(1.5)

    def verify5_content(self):
        try:
            with open(TEST_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
            self.report.final_content = content
            return TEST_TEXT in content
        except Exception as e:
            print(f"  [WARN] File read error: {e}")
            return False

    def run(self):
        print("=" * 60)
        print("T5 Notepad E2E Test")
        print("=" * 60)
        steps = [
            ("1. Open Notepad", self.step1_open_notepad, self.verify1_notepad_window),
            ("2. Type Content", self.step2_type_content, None),
            ("3. Save with Path", self.step3_save_with_path, self.verify3_file_exists),
            ("4. Close Notepad", self.step4_close_notepad, None),
            ("5. Reopen & Verify", self.step5_reopen_and_verify, self.verify5_content),
        ]
        for name, func, verify in steps:
            print(f"\n--- Step: {name} ---")
            result = self._run_step(name, func, verify)
            self.report.steps.append(result)
            if not result.success:
                self.report.overall_success = False
                print(f"\n  FATAL: '{name}' failed. Aborting.")
                break
        self._print_report()
        return self.report

    def _print_report(self):
        print("\n" + "=" * 60)
        print("TEST REPORT")
        print("=" * 60)
        total_ms = 0
        for s in self.report.steps:
            status = "PASS" if s.success else "FAIL"
            total_ms += s.duration_ms
            extra = f", retries={s.retries}" if s.retries else ""
            if s.error:
                extra += f", err={s.error}"
            print(f"  [{status}] {s.name}: {s.duration_ms:.0f}ms{extra}")
        print(f"\n  Total time: {total_ms:.0f}ms")
        print(f"  Overall: {'PASS' if self.report.overall_success else 'FAIL'}")
        if self.report.final_content:
            preview = self.report.final_content[:100].replace('\n', '\\n')
            print(f"  Final content: '{preview}'")
        if not self.report.overall_success:
            failed = [s for s in self.report.steps if not s.success]
            if failed:
                print(f"\n  Failed at: {failed[0].name}")
                if failed[0].screenshot_path:
                    print(f"  Screenshot: {failed[0].screenshot_path}")
        print("=" * 60)


if __name__ == "__main__":
    os.makedirs("E:\\agent_test", exist_ok=True)
    print("Starting T5 Notepad E2E Test in 3 seconds...")
    print("Please do NOT touch the mouse or keyboard.")
    time.sleep(3)
    test = NotepadE2ETest()
    report = test.run()
    sys.exit(0 if report.overall_success else 1)
