"""
GUI 截图脚本
使用 mss 库截图 GUI 状态
"""
import mss
import time
import subprocess
import os
import sys

# 确保目录存在
os.makedirs("docs", exist_ok=True)

print("="*60)
print("Desktop Agent GUI 截图脚本")
print("="*60)
print()

# 检查 mss 是否安装
try:
    import mss
except ImportError:
    print("错误：mss 未安装")
    print("请运行：pip install mss")
    sys.exit(1)

# 启动 GUI
print("1. 启动 GUI...")
process = subprocess.Popen(
    [sys.executable, "gui.py"],
    cwd="F:/opencode-workspace",
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

# 等待 GUI 启动
print("   等待 GUI 启动（5秒）...")
time.sleep(5)

print()
print("2. 操作 GUI：")
print("   - 在输入框中输入：'打开计算器'")
print("   - 点击'开始执行'按钮")
print("   - 等待执行完成")
print()
print("3. 完成后按回车键继续截图...")
print()

try:
    input()
except KeyboardInterrupt:
    print("\n\n取消截图")
    process.terminate()
    process.wait()
    sys.exit(0)

print()
print("开始截图...")

# 截图 1：初始状态
print("  截取初始状态...")
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_initial.png")
    print("     ✓ 已保存：docs/gui_screenshot_initial.png")

time.sleep(2)

# 截图 2：执行中
print("  截取执行中状态...")
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_running.png")
    print("     ✓ 已保存：docs/gui_screenshot_running.png")

time.sleep(2)

# 截图 3：完成状态
print("  截取完成状态...")
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_done.png")
    print("     ✓ 已保存：docs/gui_screenshot_done.png")

print()
print("="*60)
print("截图完成！")
print("="*60)
print()
print("3 张截图已保存到 docs/ 目录：")
print("  - gui_screenshot_initial.png")
print("  - gui_screenshot_running.png")
print("  - gui_screenshot_done.png")
print()

# 关闭 GUI
print("关闭 GUI...")
process.terminate()
process.wait()

print("完成！")
