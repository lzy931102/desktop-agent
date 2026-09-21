import ctypes
import ctypes.wintypes

user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

results = []

@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
def callback(hwnd, lparam):
    if user32.IsWindowVisible(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            rect = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if 'Target' in title or 'target' in title or 'Game' in title:
                results.append((hwnd, title, rect.left, rect.top, rect.right, rect.bottom))
    return True

user32.EnumWindows(callback, 0)
for r in results:
    print(f'Found: [{r[0]}] "{r[1]}" at ({r[2]},{r[3]})-({r[4]},{r[5]}) size={r[4]-r[2]}x{r[5]-r[3]}')

if not results:
    print('No game window found. Listing all visible windows:')
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def list_all(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                rect = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                print(f'  [{hwnd}] "{buf.value}" at ({rect.left},{rect.top})-({rect.right},{rect.bottom})')
        return True
    user32.EnumWindows(list_all, 0)
