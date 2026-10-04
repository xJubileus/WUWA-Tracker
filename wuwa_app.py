import os, sys, ctypes, traceback, threading, time
import webview

def base_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WuWaTracker")
DATA_FILE = os.path.join(DATA_DIR, "progress.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
TITLE = "WUWA Tracker"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

def log(msg):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def bg_color():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
        return "#f4f5f8" if light else "#12141b"
    except Exception:
        return "#12141b"

def hwnd():
    u = ctypes.windll.user32
    u.FindWindowW.restype = ctypes.c_void_p
    return u.FindWindowW(None, TITLE)

def write(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)

def read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default

class FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]

import ctypes.wintypes as wt
U = ctypes.windll.user32
U.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
U.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
U.GetWindowLongW.restype = ctypes.c_long
U.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
U.SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_ubyte, ctypes.c_uint]
U.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
U.FindWindowW.restype = ctypes.c_void_p
U.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
U.SendMessageW.restype = ctypes.c_void_p
U.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
U.LoadImageW.restype = ctypes.c_void_p

WINDOW = None
CH_H = None
CH_W = None
_token = 0
OVERLAY = {"on": False, "op": 55, "typing": False}

class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint), ("hCursor", ctypes.c_void_p), ("pt", wt.POINT)]
U.SetForegroundWindow.argtypes = [ctypes.c_void_p]

def animate(w, tw, th):
    global _token
    _token += 1
    tok = _token
    sw_, sh_ = w.width, w.height

    def run():
        steps = 8
        for i in range(1, steps + 1):
            if tok != _token:
                return
            t = i / steps
            e = 1 - (1 - t) ** 3
            try:
                w.resize(int(sw_ + (tw - sw_) * e), int(sh_ + (th - sh_) * e))
            except Exception:
                return
            time.sleep(0.012)

    threading.Thread(target=run, daemon=True).start()

def _ov_apply(h, hot):
    ex = U.GetWindowLongW(h, -20)
    if OVERLAY["on"]:
        ex |= 0x80000
        if hot:
            ex &= ~0x20
            a = 245
        else:
            ex |= 0x20
            a = int(255 * OVERLAY["op"] / 100)
        if OVERLAY["typing"]:
            ex &= ~0x08000000
        else:
            ex |= 0x08000000
        U.SetWindowLongW(h, -20, ex)
        U.SetLayeredWindowAttributes(h, 0, a, 2)
    else:
        U.SetWindowLongW(h, -20, ex & ~(0x20 | 0x08000000))
        U.SetLayeredWindowAttributes(h, 0, 255, 2)

def _ov_loop():
    h = hwnd()
    last = None
    pt = wt.POINT()
    rc = wt.RECT()
    while OVERLAY["on"]:
        try:
            alt = bool(U.GetAsyncKeyState(0x12) & 0x8000)
            U.GetCursorPos(ctypes.byref(pt))
            U.GetWindowRect(h, ctypes.byref(rc))
            inside = rc.left <= pt.x < rc.right and rc.top <= pt.y < rc.bottom
            hot = inside and alt
            key = (hot, OVERLAY["op"], OVERLAY["typing"])
            if key != last:
                _ov_apply(h, hot)
                last = key
        except Exception:
            log(traceback.format_exc())
        time.sleep(0.03)
    try:
        _ov_apply(h, False)
    except Exception:
        pass

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hWnd", ctypes.c_void_p), ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint), ("uCallbackMessage", ctypes.c_uint), ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128), ("dwState", ctypes.c_uint), ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256), ("uTimeout", ctypes.c_uint), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", ctypes.c_void_p)]

def balloon(title, msg):
    sh = ctypes.windll.shell32
    sh.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.POINTER(NOTIFYICONDATAW)]
    U.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    U.LoadImageW.restype = ctypes.c_void_p
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = hwnd()
    nid.uID = 7
    nid.uFlags = 0x2 | 0x4
    nid.hIcon = U.LoadImageW(None, os.path.join(base_dir(), "wuwa.ico"), 1, 16, 16, 0x10)
    nid.szTip = TITLE
    sh.Shell_NotifyIconW(0, ctypes.byref(nid))
    nid.uFlags = 0x10
    nid.szInfoTitle = str(title)[:63]
    nid.szInfo = str(msg)[:255]
    nid.dwInfoFlags = 1
    sh.Shell_NotifyIconW(1, ctypes.byref(nid))

    def cleanup():
        time.sleep(12)
        sh.Shell_NotifyIconW(2, ctypes.byref(nid))

    threading.Thread(target=cleanup, daemon=True).start()

class Api:
    def fit(self, content_h, inner_h, need_w=0, inner_w=0):
        global CH_H, CH_W
        try:
            w = WINDOW
            if CH_H is None:
                c = w.height - int(inner_h)
                CH_H = c if 0 <= c <= 6 else 2
                c = w.width - int(inner_w)
                CH_W = c if 0 <= c <= 6 else 0
            th = max(150, min(int(content_h) + CH_H - 2, 1000))
            tw = w.width
            if int(need_w) > int(inner_w):
                tw = int(need_w) + CH_W
            if abs(th - w.height) > 2 or abs(tw - w.width) > 2:
                animate(w, tw, th)
        except Exception:
            log(traceback.format_exc())

    def start_drag(self):
        h = hwnd()

        def run():
            pt = wt.POINT()
            rc = wt.RECT()
            U.GetCursorPos(ctypes.byref(pt))
            U.GetWindowRect(h, ctypes.byref(rc))
            ox, oy = pt.x - rc.left, pt.y - rc.top
            while U.GetAsyncKeyState(0x01) & 0x8000:
                U.GetCursorPos(ctypes.byref(pt))
                U.SetWindowPos(h, None, pt.x - ox, pt.y - oy, 0, 0, 0x15)
                time.sleep(0.004)

        threading.Thread(target=run, daemon=True).start()

    def typing(self, flag):
        try:
            OVERLAY["typing"] = bool(flag)
            if flag and OVERLAY["on"]:
                time.sleep(0.06)
                U.SetForegroundWindow(hwnd())
        except Exception:
            log(traceback.format_exc())

    def minimize(self):
        try:
            WINDOW.minimize()
        except Exception:
            log(traceback.format_exc())

    def close(self):
        try:
            WINDOW.destroy()
        except Exception:
            os._exit(0)

    def load(self):
        return read(DATA_FILE, "{}")

    def save(self, data):
        try:
            write(DATA_FILE, data)
            return True
        except Exception:
            log(traceback.format_exc())
            return False

    def load_tasks(self):
        return read(TASKS_FILE, "")

    def save_tasks(self, data):
        try:
            write(TASKS_FILE, data)
            return True
        except Exception:
            log(traceback.format_exc())
            return False

    def open_tasks(self):
        try:
            if not os.path.exists(TASKS_FILE):
                write(TASKS_FILE, "[]")
            os.startfile(TASKS_FILE)
        except Exception:
            log(traceback.format_exc())

    def set_on_top(self, flag, op=55):
        try:
            h = hwnd()
            OVERLAY["op"] = max(20, min(100, int(op)))
            U.SetWindowPos(h, ctypes.c_void_p(-1 if flag else -2), 0, 0, 0, 0, 0x0013)
            if flag and not OVERLAY["on"]:
                OVERLAY["on"] = True
                threading.Thread(target=_ov_loop, daemon=True).start()
            elif not flag:
                OVERLAY["on"] = False
        except Exception:
            log(traceback.format_exc())

    def get_autostart(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, TITLE)
            return True
        except Exception:
            return False

    def set_autostart(self, flag):
        try:
            import winreg
            if getattr(sys, "frozen", False):
                cmd = '"%s"' % sys.executable
            else:
                cmd = '"%s" "%s"' % (sys.executable, os.path.abspath(__file__))
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if flag:
                    winreg.SetValueEx(k, TITLE, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(k, TITLE)
                    except FileNotFoundError:
                        pass
        except Exception:
            log(traceback.format_exc())
        return self.get_autostart()

    def notify(self, title, msg):
        try:
            fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd(), 3 | 12, 5, 0)
            U.FlashWindowEx(ctypes.byref(fi))
        except Exception:
            log(traceback.format_exc())
        try:
            balloon(title, msg)
        except Exception:
            log(traceback.format_exc())

def set_icon(*args):
    try:
        h = hwnd()
        path = os.path.join(base_dir(), "wuwa.ico")
        big = U.LoadImageW(None, path, 1, 32, 32, 0x10)
        small = U.LoadImageW(None, path, 1, 16, 16, 0x10)
        if big:
            U.SendMessageW(h, 0x80, 1, big)
        if small:
            U.SendMessageW(h, 0x80, 0, small)
    except Exception:
        log(traceback.format_exc())

if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WuWaTracker.App")
    except Exception:
        pass
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    os.makedirs(DATA_DIR, exist_ok=True)
    html = os.path.join(base_dir(), "wuwa-tracker-en.html")
    icon = os.path.join(base_dir(), "wuwa.ico")
    WINDOW = webview.create_window(TITLE, html, js_api=Api(), width=360, height=640,
                                   min_size=(300, 150), background_color=bg_color(),
                                   frameless=True, easy_drag=False)
    WINDOW.events.shown += set_icon
    webview.start(icon=icon, private_mode=False, storage_path=os.path.join(DATA_DIR, "webview"))
