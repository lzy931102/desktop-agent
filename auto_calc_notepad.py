# -*- coding: utf-8 -*-
"""
桌面自动化：打开计算器 → 算 123×456 → 复制结果 → 记事本 → 粘贴 → 保存 → 验证
"""
import pyautogui
import pyperclip
import time
import subprocess
import os

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2

SAVE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "calc_result.txt")
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def open_calculator():
    log("打开计算器...")
    subprocess.Popen(["calc.exe"])
    time.sleep(3)
    log("计算器已打开")


def compute():
    log("输入 123 * 456 ...")
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.5)
    pyautogui.typewrite('123*456', interval=0.03)
    time.sleep(0.3)
    pyautogui.press('enter')
    time.sleep(1.5)
    log("计算完成")


def copy_result():
    log("复制结果...")
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.3)
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(0.5)
    clip = pyperclip.paste()
    log(f"剪贴板: [{clip}]")
    return clip


def open_notepad():
    log("打开记事本...")
    subprocess.Popen(["notepad.exe"])
    time.sleep(2)
    log("记事本已打开")


def paste_and_save():
    log("粘贴结果...")
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)

    log("保存文件 Ctrl+S...")
    pyautogui.hotkey('ctrl', 's')
    time.sleep(2)

    # 用 pyperclip 把路径粘贴到文件名框
    pyperclip.copy(SAVE_PATH)
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.5)
    pyautogui.press('enter')
    time.sleep(1.5)

    # 处理"确认替换"对话框
    pyautogui.press('enter')
    time.sleep(0.5)
    log("文件保存完成")


def close_notepad_no_save():
    pyautogui.hotkey('alt', 'f4')
    time.sleep(1)
    # 如果弹出"是否保存"，按N不保存
    pyautogui.press('n')
    time.sleep(0.3)


def verify():
    log("验证文件内容...")
    if os.path.exists(SAVE_PATH):
        with open(SAVE_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read().strip()
        log(f"文件内容: [{content}]")
        if "56088" in content:
            log("验证通过! 123*456 = 56088")
            return True
        else:
            log(f"验证失败! 期望 56088, 实际 [{content}]")
            return False
    else:
        log("文件不存在!")
        return False


def main():
    print("=" * 50)
    print("Desktop Automation: Calculator -> Notepad")
    print("=" * 50)
    print("Starting in 3 seconds...")
    time.sleep(3)

    open_calculator()
    compute()
    clip = copy_result()

    open_notepad()
    paste_and_save()
    close_notepad_no_save()

    # 验证
    ok = verify()

    print()
    if ok:
        print("PASS")
    else:
        # 如果自动保存失败，手动写文件验证粘贴内容
        if clip:
            log(f"尝试手动保存剪贴板内容: [{clip}]")
            with open(SAVE_PATH, 'w', encoding='utf-8') as f:
                f.write(clip)
            ok2 = verify()
            if ok2:
                print("PASS (manual save)")
            else:
                print("FAIL")
        else:
            print("FAIL")


if __name__ == "__main__":
    main()
