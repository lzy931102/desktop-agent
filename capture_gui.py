"""
GUI 截图脚本
"""
import mss
import time
import subprocess
import os

# 确保目录存在
os.makedirs("docs", exist_ok=True)

print("=== GUI 截图脚本 ===\n")
print("1. 启动 GUI...")
print("2. 输入任务：'打开计算器'")
print("3. 截取初始状态...")
print("4. 截取执行中状态...")
print("5. 截取完成状态...\n")

# 启动 GUI
process = subprocess.Popen(["python", "gui.py"], cwd="F:/opencode-workspace")

# 等待 GUI 启动
print("等待 GUI 启动...")
time.sleep(5)

print("\n请手动操作 GUI：")
print("1. 在输入框中输入：'打开计算器'")
print("2. 点击'开始执行'按钮")
print("3. 等待执行完成...")
print("\n完成后按回车继续截图...")

input()

print("\n开始截图...")

# 初始状态截图
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_initial.png")
    print("✓ 初始状态已截图：docs/gui_screenshot_initial.png")

time.sleep(2)

# 执行中截图
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_running.png")
    print("✓ 执行中已截图：docs/gui_screenshot_running.png")

time.sleep(2)

# 完成状态截图
with mss.mss() as sct:
    screenshot = sct.shot(output="docs/gui_screenshot_done.png")
    print("✓ 完成状态已截图：docs/gui_screenshot_done.png")

print("\n=== 截图完成 ===")
print("3 张截图已保存到 docs/ 目录")

# 关闭 GUI
print("\n关闭 GUI...")
process.terminate()
process.wait()

print("完成！")
