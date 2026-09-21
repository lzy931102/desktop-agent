import pyautogui
import time
import json
import sys
from pathlib import Path

# 安全设置：移动鼠标到左上角(0,0)会触发异常停止
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5  # 每次操作间隔

class DesktopAgent:
    def __init__(self, config_file="agent_config.json"):
        self.config_file = Path(config_file)
        self.load_config()

    def load_config(self):
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {"actions": []}
            self.save_config()

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    # 基础动作
    def click(self, x, y, button='left', clicks=1):
        pyautogui.click(x, y, button=button, clicks=clicks)
        self._log(f"click({x},{y})")

    def type_text(self, text, interval=0.05):
        pyautogui.write(text, interval=interval)
        self._log(f"type: {text}")

    def press_key(self, key, presses=1):
        pyautogui.press(key, presses=presses)
        self._log(f"press: {key}")

    def hotkey(self, *keys):
        pyautogui.hotkey(*keys)
        self._log(f"hotkey: {'+'.join(keys)}")

    def move_to(self, x, y, duration=0.5):
        pyautogui.moveTo(x, y, duration=duration)
        self._log(f"move_to({x},{y})")

    def scroll(self, clicks):
        pyautogui.scroll(clicks)
        self._log(f"scroll: {clicks}")

    def screenshot(self, path="screenshot.png"):
        img = pyautogui.screenshot()
        img.save(path)
        self._log(f"screenshot saved: {path}")
        return path

    def locate_on_screen(self, image_path, confidence=0.8):
        try:
            loc = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if loc:
                center = pyautogui.center(loc)
                self._log(f"found {image_path} at {center}")
                return center
        except Exception as e:
            self._log(f"locate failed: {e}")
        return None

    def wait(self, seconds):
        time.sleep(seconds)
        self._log(f"wait: {seconds}s")

    def _log(self, msg):
        print(f"[Agent] {msg}")

    # 组合动作示例
    def open_run_dialog(self):
        self.hotkey('win', 'r')
        self.wait(0.5)

    def open_app(self, app_name):
        self.open_run_dialog()
        self.type_text(app_name)
        self.press_key('enter')
        self.wait(2)

    def record_action(self, action_type, **kwargs):
        self.config["actions"].append({"type": action_type, **kwargs})
        self.save_config()

    def replay_actions(self):
        for action in self.config["actions"]:
            getattr(self, action["type"])(**action.get("args", {}))


def main():
    agent = DesktopAgent()

    if len(sys.argv) < 2:
        print("用法:")
        print("  python desktop_agent.py click x y")
        print("  python desktop_agent.py type 'text'")
        print("  python desktop_agent.py hotkey ctrl c")
        print("  python desktop_agent.py screenshot")
        print("  python desktop_agent.py find image.png")
        print("  python desktop_agent.py open notepad")
        print("  python desktop_agent.py demo")
        return

    cmd = sys.argv[1]

    if cmd == "click":
        agent.click(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "type":
        agent.type_text(sys.argv[2])
    elif cmd == "hotkey":
        agent.hotkey(*sys.argv[2:])
    elif cmd == "screenshot":
        agent.screenshot()
    elif cmd == "find":
        result = agent.locate_on_screen(sys.argv[2])
        if result:
            print(f"找到: {result}")
    elif cmd == "open":
        agent.open_app(sys.argv[2])
    elif cmd == "demo":
        print("5秒后开始演示，请准备...")
        time.sleep(5)
        agent.open_app("notepad")
        agent.type_text("Hello from Desktop Agent!\n")
        agent.type_text("自动化测试成功")
        agent.hotkey('ctrl', 's')
        agent.wait(1)
        agent.type_text("auto_save.txt")
        agent.press_key('enter')
        print("演示完成")
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()