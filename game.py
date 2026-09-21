# game.py
import tkinter as tk
import random
import json
import time
import os
import math
import argparse

STATE_FILE = "game_state.json"
EVENT_FILE = "game_events.json"


class TargetGame:
    def __init__(self, total=10, target_radius=30, seed=None, move_speed=0,
                 multi_target=False, width=800, height=600):
        self.total = total
        self.target_radius = target_radius
        self.move_speed = move_speed
        self.multi_target = multi_target
        self.width = width
        self.height = height
        self.score = 0
        self.finished = False
        self.event_log = []
        self.start_time = time.time()

        if seed is not None:
            random.seed(seed)

        self.root = tk.Tk()
        self.root.title("Target Game - Agent Test")
        self.root.geometry(f"{width}x{height}")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(self.root, width=width, height=height, bg="#1e1e1e")
        self.canvas.pack()

        self.score_text = self.canvas.create_text(
            100, 30, fill="white", text="Score: 0/10",
            font=("Arial", 20), anchor="w"
        )
        self.status_text = self.canvas.create_text(
            400, 300, fill="yellow", text="",
            font=("Arial", 40)
        )

        if self.multi_target:
            self.targets = []
            self._new_targets()
        else:
            self.target_id = None
            self.target_pos = (0, 0)
            self.vx = 0.0
            self.vy = 0.0
            self._new_target()

        self.canvas.bind("<Button-1>", self._on_click)

        self._write_state()

        if self.move_speed > 0 or self.multi_target:
            self._update()

    def _random_pos(self, exclude_positions=None):
        r = self.target_radius
        for _ in range(100):
            x = random.randint(r + 20, self.width - r - 20)
            y = random.randint(r + 60, self.height - r - 20)
            if exclude_positions:
                ok = True
                for ex, ey in exclude_positions:
                    if ((x - ex) ** 2 + (y - ey) ** 2) ** 0.5 < r * 3:
                        ok = False
                        break
                if ok:
                    return x, y
        return x, y

    def _new_targets(self):
        for tid, _, _ in self.targets:
            self.canvas.delete(tid)
        self.targets = []
        positions = []
        # 1 red
        rx, ry = self._random_pos()
        positions.append((rx, ry))
        r = self.target_radius
        rid = self.canvas.create_oval(
            rx - r, ry - r, rx + r, ry + r,
            fill="#ff5050", outline="#ffaaaa", width=2, tags="target"
        )
        self.targets.append((rid, (rx, ry), "#ff5050"))
        # 2 blue
        for _ in range(2):
            bx, by = self._random_pos(exclude_positions=positions)
            positions.append((bx, by))
            bid = self.canvas.create_oval(
                bx - r, by - r, bx + r, by + r,
                fill="#5050ff", outline="#aaaaff", width=2, tags="target"
            )
            self.targets.append((bid, (bx, by), "#5050ff"))

    def _new_target(self):
        if self.target_id:
            self.canvas.delete(self.target_id)
        x = random.randint(self.target_radius + 20, self.width - self.target_radius - 20)
        y = random.randint(self.target_radius + 60, self.height - self.target_radius - 20)
        self.target_pos = (x, y)
        r = self.target_radius
        self.target_id = self.canvas.create_oval(
            x - r, y - r, x + r, y + r,
            fill="#ff5050", outline="#ffaaaa", width=2,
            tags="target"
        )
        if self.move_speed > 0:
            angle = random.uniform(0, 2 * math.pi)
            self.vx = self.move_speed * math.cos(angle)
            self.vy = self.move_speed * math.sin(angle)
        else:
            self.vx = 0.0
            self.vy = 0.0

    def _update(self):
        if self.finished:
            return
        if self.multi_target:
            for i, (tid, (x, y), color) in enumerate(self.targets):
                if self.move_speed > 0:
                    pass
                self.canvas.coords(tid, x - self.target_radius,
                                   y - self.target_radius,
                                   x + self.target_radius,
                                   y + self.target_radius)
            self._write_state()
            self.root.after(16, self._update)
        else:
            if self.target_id is None:
                return
            x, y = self.target_pos
            r = self.target_radius
            x += self.vx
            y += self.vy
            if x - r < 0:
                x = r
                self.vx = abs(self.vx)
            elif x + r > self.width:
                x = self.width - r
                self.vx = -abs(self.vx)
            if y - r < 0:
                y = r
                self.vy = abs(self.vy)
            elif y + r > self.height:
                y = self.height - r
                self.vy = -abs(self.vy)
            self.target_pos = (x, y)
            self.canvas.coords(self.target_id, x - r, y - r, x + r, y + r)
            self._write_state()
            self.root.after(16, self._update)

    def _on_click(self, event):
        if self.multi_target:
            self._on_click_multi(event)
        else:
            self._on_click_single(event)

    def _on_click_single(self, event):
        x, y = self.target_pos
        dist = ((event.x - x) ** 2 + (event.y - y) ** 2) ** 0.5
        hit = dist <= self.target_radius

        self.event_log.append({
            "type": "click",
            "x": event.x,
            "y": event.y,
            "hit": hit,
            "target": {"x": x, "y": y, "r": self.target_radius},
            "timestamp": time.time() - self.start_time,
        })

        if hit:
            self.score += 1
            self.canvas.itemconfig(
                self.score_text, text=f"Score: {self.score}/{self.total}"
            )
            if self.score >= self.total:
                self.finished = True
                self.canvas.itemconfig(self.status_text, text="PASS!")
                if self.target_id:
                    self.canvas.delete(self.target_id)
                    self.target_id = None
            else:
                self._new_target()

        self._write_state()

    def _on_click_multi(self, event):
        clicked_color = None
        for tid, (tx, ty), color in self.targets:
            dist = ((event.x - tx) ** 2 + (event.y - ty) ** 2) ** 0.5
            if dist <= self.target_radius:
                clicked_color = color
                break

        self.event_log.append({
            "type": "click",
            "x": event.x,
            "y": event.y,
            "clicked_color": clicked_color,
            "timestamp": time.time() - self.start_time,
        })

        if clicked_color == "#ff5050":
            self.score += 1
        elif clicked_color == "#5050ff":
            self.score = max(0, self.score - 1)

        self.canvas.itemconfig(
            self.score_text, text=f"Score: {self.score}/{self.total}"
        )

        if self.score >= self.total:
            self.finished = True
            self.canvas.itemconfig(self.status_text, text="PASS!")
            for tid, _, _ in self.targets:
                self.canvas.delete(tid)
            self.targets = []
        else:
            self._new_targets()

        self._write_state()

    def _write_state(self):
        if self.multi_target:
            targets_data = [
                {"x": pos[0], "y": pos[1], "r": self.target_radius,
                 "color": color}
                for _, pos, color in self.targets
            ]
            state = {
                "score": self.score,
                "total": self.total,
                "finished": self.finished,
                "targets": targets_data,
                "move_speed": self.move_speed,
                "multi_target": True,
                "window": {"x": 0, "y": 0, "w": self.width, "h": self.height},
            }
        else:
            state = {
                "score": self.score,
                "total": self.total,
                "finished": self.finished,
                "target": (
                    {"x": self.target_pos[0], "y": self.target_pos[1],
                     "r": self.target_radius,
                     "vx": self.vx, "vy": self.vy}
                    if self.target_id else None
                ),
                "move_speed": self.move_speed,
                "window": {"x": 0, "y": 0, "w": self.width, "h": self.height},
            }
        tmp = STATE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, STATE_FILE)
        except PermissionError:
            pass

    def _write_events(self):
        with open(EVENT_FILE, "w", encoding="utf-8") as f:
            json.dump(self.event_log, f, indent=2)

    def get_state(self):
        if self.multi_target:
            return {
                "score": self.score,
                "total": self.total,
                "finished": self.finished,
                "targets": [
                    {"x": pos[0], "y": pos[1], "r": self.target_radius,
                     "color": color}
                    for _, pos, color in self.targets
                ],
                "move_speed": self.move_speed,
                "multi_target": True,
            }
        return {
            "score": self.score,
            "total": self.total,
            "finished": self.finished,
            "target": (
                {"x": self.target_pos[0], "y": self.target_pos[1],
                 "r": self.target_radius,
                 "vx": self.vx, "vy": self.vy}
                if self.target_id else None
            ),
            "move_speed": self.move_speed,
        }

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self._write_events()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Target Game for Agent Testing")
    parser.add_argument("--speed", type=float, default=0,
                        help="靶子移动速度(像素/帧)，0=静止")
    parser.add_argument("--total", type=int, default=10,
                        help="通关所需命中数")
    parser.add_argument("--seed", type=int, default=None,
                        help="随机种子")
    parser.add_argument("--target-radius", type=int, default=30,
                        help="靶子半径")
    parser.add_argument("--multi-target", action="store_true",
                        help="多靶子模式：1红+2蓝，点红+1点蓝-1")
    parser.add_argument("--width", type=int, default=800,
                        help="窗口宽度")
    parser.add_argument("--height", type=int, default=600,
                        help="窗口高度")
    args = parser.parse_args()
    TargetGame(total=args.total, target_radius=args.target_radius,
               seed=args.seed, move_speed=args.speed,
               multi_target=args.multi_target,
               width=args.width, height=args.height).run()
