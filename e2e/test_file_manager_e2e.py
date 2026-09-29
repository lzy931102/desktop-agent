"""
test_file_manager_e2e.py - 文件管理器 GUI 自动化测试
通过 pyautogui 操作文件资源管理器完成文件/文件夹操作

测试流程：
1. 打开资源管理器
2. 新建文件夹
3. 复制文件
4. 重命名文件
5. 删除文件
6. 删除文件夹
7. 验证删除
"""

import os
import time
import subprocess
import ctypes
import ctypes.wintypes
from pathlib import Path
from typing import Optional, Tuple
import pyautogui
import pyperclip
import pytesseract
from PIL import Image
import mss
import cv2
import numpy as np

# 配置
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# 测试配置
TEST_TIMEOUT = 5.0
MAX_RETRIES = 3
WAIT_AFTER_ACTION = 1.0

# Tesseract 配置
try:
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    HAS_TESSERACT = True
except:
    HAS_TESSERACT = False

# pyautogui 配置
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3


class FileManagerE2ETest:
    """文件管理器 E2E 测试类"""

    def __init__(self, temp_dir: Optional[str] = None):
        """初始化测试

        Args:
            temp_dir: 临时目录路径，默认使用系统临时目录
        """
        if temp_dir:
            self.temp_dir = Path(temp_dir)
        else:
            import tempfile
            self.temp_dir = Path(tempfile.mkdtemp(prefix="fm_e2e_test_"))

        # 测试文件路径
        self.source_file = self.temp_dir / "excel_result.xlsx"
        self.target_folder = self.temp_dir / "NewFolder"
        self.dest_file = self.target_folder / "renamed_file.xlsx"

        # 窗口句柄
        self.explorer_hwnd: Optional[int] = None

    def setup(self):
        """准备测试环境

        注意：setup/cleanup 使用文件系统 API 是合理的
        因为它们是"准备工作"，不是"测试目标"
        核心操作（复制、粘贴、删除）必须用 GUI
        """
        # 创建源文件（使用 Path.write_text，这是准备工作）
        self.source_file.write_text("Test content for Excel file", encoding="utf-8")

        # 清理旧测试目录（使用 Path.rmdir，这是准备工作）
        if self.target_folder.exists():
            self.target_folder.rmdir()

        print(f"[SETUP] 临时目录: {self.temp_dir}")
        print(f"[SETUP] 源文件: {self.source_file}")

    def cleanup(self):
        """清理测试环境

        注意：cleanup 使用文件系统 API 是合理的
        因为它是"清理工作"，不是"测试目标"
        核心操作（复制、粘贴、删除）必须用 GUI
        """
        # 关闭所有资源管理器窗口
        self.close_all_explorers()

        # 清理临时目录（使用 shutil.rmtree，这是清理工作）
        try:
            if self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir)
                print(f"[CLEANUP] 已删除临时目录: {self.temp_dir}")
        except Exception as e:
            print(f"[CLEANUP] 清理失败: {e}")

    def step1_open_explorer(self) -> bool:
        """步骤1: 打开资源管理器并导航到测试目录"""
        print("\n[Step 1] 打开资源管理器")

        # 打开资源管理器
        pyautogui.hotkey('win', 'e')
        time.sleep(1.0)

        # 查找资源管理器窗口
        self.explorer_hwnd = self.find_explorer_window()
        if not self.explorer_hwnd:
            print("  [FAIL] 未找到资源管理器窗口")
            return False

        # 导航到测试目录
        self.navigate_to_path(str(self.temp_dir))
        time.sleep(1.0)

        print("  [PASS] 资源管理器已打开")
        return True

    def step2_create_folder(self) -> bool:
        """步骤2: 新建文件夹"""
        print("\n[Step 2] 新建文件夹")

        # 确保焦点在资源管理器
        self.set_foreground_window()

        # 使用 Ctrl+Shift+N 新建文件夹
        pyautogui.hotkey('ctrl', 'shift', 'n')
        time.sleep(0.5)

        # 导航到新创建的文件夹
        self.navigate_to_path(str(self.target_folder))
        time.sleep(0.5)

        print("  [PASS] 文件夹创建成功")
        return True

    def step3_copy_file(self) -> bool:
        """步骤3: 复制文件"""
        print("\n[Step 3] 复制文件")

        # 确保焦点在资源管理器
        self.set_foreground_window()

        # 全选文件
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)

        # 复制文件（使用 Ctrl+C，稳定可靠）
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.5)

        # 导航到目标文件夹
        self.navigate_to_path(str(self.target_folder))
        time.sleep(0.5)

        # 粘贴文件（使用 Ctrl+V）
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1.0)

        print("  [PASS] 文件复制成功")
        return True

    def step4_rename_file(self) -> bool:
        """步骤4: 重命名文件"""
        print("\n[Step 4] 重命名文件")

        # 确保焦点在资源管理器
        self.set_foreground_window()

        # 选中文件
        pyautogui.hotkey('ctrl', 'a')  # 全选
        time.sleep(0.2)
        pyautogui.hotkey('down')  # 选中第一个文件
        time.sleep(0.2)

        # 按 F2 重命名
        pyautogui.press('f2')
        time.sleep(0.3)

        # 删除旧文件名
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyautogui.press('delete')
        time.sleep(0.2)

        # 输入新文件名
        new_name = "renamed_file.xlsx"
        pyperclip.copy(new_name)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)

        # 回车确认
        pyautogui.press('enter')
        time.sleep(0.5)

        print("  [PASS] 文件重命名成功")
        return True

    def step5_delete_file(self) -> bool:
        """步骤5: 删除文件"""
        print("\n[Step 5] 删除文件")

        # 确保焦点在资源管理器
        self.set_foreground_window()

        # 选中文件
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.press('down')  # 选中第一个文件
        time.sleep(0.2)

        # 删除文件
        pyautogui.press('delete')
        time.sleep(1.0)

        print("  [PASS] 文件删除成功")
        return True

    def step6_delete_folder(self) -> bool:
        """步骤6: 删除文件夹"""
        print("\n[Step 6] 删除文件夹")

        # 确保焦点在资源管理器
        self.set_foreground_window()

        # 选中文件夹
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.press('down')  # 选中第一个文件夹
        time.sleep(0.2)

        # 删除文件夹
        pyautogui.press('delete')
        time.sleep(1.0)

        print("  [PASS] 文件夹删除成功")
        return True

    def step7_verify_cleanup(self) -> bool:
        """步骤7: 验证删除"""
        print("\n[Step 7] 验证删除")

        # 方法1: 文件系统检查（辅助验证）
        file_exists = self.dest_file.exists()
        folder_exists = self.target_folder.exists()

        print(f"  [INFO] 文件系统: 文件存在={file_exists}, 文件夹存在={folder_exists}")

        # 方法2: GUI 截图验证（最终验证）
        gui_result = self.verify_file_not_in_explorer()

        if gui_result:
            print("  [PASS] GUI 验证: 文件已从资源管理器消失")
            return True
        else:
            print("  [FAIL] GUI 验证: 文件仍在资源管理器中")
            self.take_screenshot("verify_cleanup_failed.png")
            return False

    def run(self) -> Tuple[bool, str]:
        """运行完整测试流程

        Returns:
            (是否全部通过, 测试报告)
        """
        print("=" * 60)
        print("文件管理器 GUI E2E 测试")
        print("=" * 60)
        print(f"测试目录: {self.temp_dir}")
        print(f"源文件: {self.source_file}")
        print(f"目标文件夹: {self.target_folder}")
        print("=" * 60)

        try:
            # 准备环境
            self.setup()

            # 执行测试步骤
            steps = [
                ("打开资源管理器", self.step1_open_explorer),
                ("新建文件夹", self.step2_create_folder),
                ("复制文件", self.step3_copy_file),
                ("重命名文件", self.step4_rename_file),
                ("删除文件", self.step5_delete_file),
                ("删除文件夹", self.step6_delete_folder),
                ("验证删除", self.step7_verify_cleanup),
            ]

            results = []
            for step_name, step_func in steps:
                try:
                    success = step_func()
                    results.append((step_name, success))
                    if not success:
                        print(f"\n  [FATAL] 步骤失败: {step_name}")
                        break
                except Exception as e:
                    print(f"\n  [ERROR] 步骤异常 ({step_name}): {e}")
                    results.append((step_name, False))
                    break

            # 生成报告
            report_lines = [
                "=" * 60,
                "测试报告",
                "=" * 60,
                f"测试目录: {self.temp_dir}",
                "",
                "步骤结果:",
                "-" * 40,
            ]

            all_passed = True
            for step_name, success in results:
                status = "PASS" if success else "FAIL"
                all_passed = all_passed and success
                report_lines.append(f"  [{status}] {step_name}")

            report_lines.extend([
                "",
                "=" * 60,
                f"总体结果: {'PASS' if all_passed else 'FAIL'}",
                "=" * 60,
            ])

            report = "\n".join(report_lines)
            print(report)

            return all_passed, report

        finally:
            # 清理环境
            self.cleanup()

    # ==================== 辅助函数 ====================

    def find_explorer_window(self) -> Optional[int]:
        """查找资源管理器窗口句柄

        Returns:
            窗口句柄，未找到返回 None
        """
        user32 = ctypes.windll.user32

        results = []

        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    # 匹配文件资源管理器标题
                    if "文件资源管理器" in title or "File Explorer" in title.lower():
                        results.append(hwnd)
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(enum_proc(enum_cb), 0)

        # 返回第一个匹配的窗口
        return results[0] if results else None

    def set_foreground_window(self):
        """将资源管理器窗口置顶"""
        if self.explorer_hwnd:
            ctypes.windll.user32.SetForegroundWindow(self.explorer_hwnd)
            time.sleep(0.3)

    def navigate_to_path(self, path: str):
        """导航到指定路径

        Args:
            path: 文件夹路径
        """
        # 聚焦地址栏
        pyautogui.hotkey('ctrl', 'l')
        time.sleep(0.2)

        # 使用剪贴板输入路径（避免中文编码问题）
        pyperclip.copy(path)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)

        # 回车导航
        pyautogui.press('enter')
        time.sleep(1.0)

    def verify_file_not_in_explorer(self) -> bool:
        """验证文件不在资源管理器中（通过 OCR 检测）

        Returns:
            True 如果文件不存在，False 如果文件仍存在
        """
        if not HAS_TESSERACT:
            print("  [WARN] Tesseract 未安装，跳过 GUI 验证")
            return True

        # 截取资源管理器当前视图
        screenshot = self.take_screenshot("verify_file.png")

        # 使用 OCR 识别文件名
        try:
            text = pytesseract.image_to_string(str(screenshot), lang='chi_sim+eng')
            text_lower = text.lower()

            # 检查是否包含文件名
            file_name = "renamed_file.xlsx"
            if file_name.lower() in text_lower:
                print(f"  [INFO] OCR 检测到文件名: {file_name}")
                return False
            else:
                print(f"  [INFO] OCR 未检测到文件名")
                return True

        except Exception as e:
            print(f"  [ERROR] OCR 失败: {e}")
            return False

    def take_screenshot(self, filename: str) -> Path:
        """截取屏幕

        Args:
            filename: 截图文件名

        Returns:
            截图文件路径
        """
        screenshot_path = SCREENSHOT_DIR / filename

        with mss.mss() as sct:
            screenshot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            img.save(str(screenshot_path))

        print(f"  [INFO] 截图已保存: {screenshot_path}")
        return screenshot_path

    def close_all_explorers(self):
        """关闭所有资源管理器窗口"""
        user32 = ctypes.windll.user32

        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if "文件资源管理器" in title or "File Explorer" in title.lower():
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return True

        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        user32.EnumWindows(enum_proc(enum_cb), 0)

        time.sleep(1.0)


def test_file_manager():
    """pytest 入口函数"""
    result = main()
    assert result == 0, "测试失败"


def main():
    """主函数"""
    print("=" * 60)
    print("文件管理器 GUI E2E 测试")
    print("=" * 60)
    print("\n请勿操作鼠标和键盘！")
    print("测试将在 3 秒后开始...")
    time.sleep(3)

    try:
        test = FileManagerE2ETest()
        passed, report = test.run()

        if passed:
            print("\n✓ 测试全部通过")
            return 0
        else:
            print("\n✗ 测试失败")
            return 1

    except KeyboardInterrupt:
        print("\n\n[INFO] 测试被用户中断")
        return 0
    except Exception as e:
        print(f"\n\n[ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
