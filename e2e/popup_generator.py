"""popup_generator.py - 随机干扰弹窗生成器"""
import tkinter as tk
import random
import time
import threading
import sys


def show_popup(popup_id, delay):
    time.sleep(delay)
    root = tk.Tk()
    root.title("Interference")
    root.geometry("300x150")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{sw//2 - 150 + random.randint(-80, 80)}+{sh//2 - 75 + random.randint(-60, 60)}")
    tk.Label(root, text=f"Popup #{popup_id}\nClose me!", font=("Arial", 12)).pack(expand=True)
    root.configure(bg="#ffeeba")
    root.mainloop()


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    threads = []
    for i in range(count):
        delay = random.uniform(0.5, 2.0)
        t = threading.Thread(target=show_popup, args=(i + 1, delay), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
