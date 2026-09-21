import sys, subprocess, time, json
sys.path.insert(0, r'F:\opencode-workspace')
from test_moving_target import FastIO, find_window, get_window_rect, find_target
import cv2
import numpy as np

proc = subprocess.Popen(['python', r'E:\agent_test\game.py', '--speed', '0'], cwd=r'E:\agent_test')
time.sleep(2)

hwnd = find_window()
rect = get_window_rect(hwnd)
print('Client rect (screen):', rect)
io = FastIO()
io.set_window_rect(rect)

for i in range(5):
    img = io.screenshot()
    visual = find_target(img)

    with open(r'E:\agent_test\game_state.json', 'r') as f:
        state = json.load(f)
    t = state['target']
    sx, sy = int(t['x']), int(t['y'])

    print('iter {} visual={} state=({},{})'.format(i, visual, sx, sy))

    if visual:
        vx, vy = visual
        print('  pixel at visual({},{}) = {}'.format(vx, vy, img[vy, vx] if 0 <= vy < img.shape[0] and 0 <= vx < img.shape[1] else 'OOB'))

    print('  pixel at state({},{}) = {}'.format(sx, sy, img[sy, sx] if 0 <= sy < img.shape[0] and 0 <= sx < img.shape[1] else 'OOB'))

    # Find red blobs
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0,100,100]), np.array([10,255,255]))
    mask2 = cv2.inRange(hsv, np.array([170,100,100]), np.array([180,255,255]))
    mask = cv2.bitwise_or(mask1, mask2)
    print('  red pixels:', cv2.countNonZero(mask))

    cv2.imwrite('F:/opencode-workspace/debug_frame_{}.png'.format(i), img)
    cv2.imwrite('F:/opencode-workspace/debug_mask_{}.png'.format(i), mask)
    time.sleep(0.5)

proc.terminate()
