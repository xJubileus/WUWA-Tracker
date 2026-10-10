"""WUWA Tracker - a daily / weekly / monthly checklist for Wuthering Waves.

Python owns the native side: the frameless window (pywebview + Edge WebView2),
the see-through overlay mode, single-instance handling, storage, notifications,
the self-healing watchdog and the self-update. The whole user interface is the
HTML/CSS/JS string at the end of this file; it calls back into Python through
``pywebview.api.<method>`` (see class ``Api``).
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import winreg

import webview

# ---------------------------------------------------------------- app constants

APP_VERSION = "1.4.0"
APP_TITLE = "WUWA Tracker"
APP_USER_MODEL_ID = "WuWaTracker.App"
FROZEN = bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()  # PyInstaller / Nuitka
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(BASE_DIR, "wuwa.ico")

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WuWaTracker")
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
WINDOW_FILE = os.path.join(DATA_DIR, "window.json")
SHOW_REQUEST_FILE = os.path.join(DATA_DIR, "show.request")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
OLD_LOG_FILE = os.path.join(DATA_DIR, "error.old.log")
LOG_MAX_BYTES = 512 * 1024

REPO_URL = "https://github.com/xJubileus/WUWA-Tracker"
UPDATE_URL_PREFIX = REPO_URL + "/releases/download/"
UPDATE_FILE = os.path.join(tempfile.gettempdir(), "WUWA-Tracker-Update.exe")
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/CURRENTUSER", "/UPDATE=1"]
BACKUP_FORMAT = 1

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MUTEX_NAME = "Local\\WUWA_Tracker_Instance"

READY_TIMEOUT = 15   # seconds the UI gets to call ready() after start
BEAT_TIMEOUT = 150   # seconds without a heartbeat (while visible) before the UI is reloaded
RESTART_AFTER = 30   # seconds after such a reload before the whole app restarts

# ---------------------------------------------------------------- logging

_log_lock = threading.Lock()


def log(msg):
    """Appends a timestamped line to error.log (rotated at LOG_MAX_BYTES). Never raises."""
    try:
        with _log_lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
                os.replace(LOG_FILE, OLD_LOG_FILE)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + str(msg).rstrip() + "\n")
    except Exception:
        pass


def log_exception():
    log(traceback.format_exc())


sys.excepthook = lambda t, v, tb: log("".join(traceback.format_exception(t, v, tb)))
threading.excepthook = lambda a: log("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))

# ---------------------------------------------------------------- Win32 bindings
# Every function gets argtypes/restype: handles are 64-bit and ctypes would truncate them to int.
# Private WinDLL instances, so these declarations never clash with other libraries using ctypes.windll.

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
RDW_REPAINT = 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400  # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW | FRAME
SW_RESTORE = 9
VK_LBUTTON, VK_MENU = 0x01, 0x12
KEY_DOWN = 0x8000
SPI_GETWORKAREA = 0x30
DESKTOP_SWITCHDESKTOP = 0x0100
ASFW_ANY = 0xFFFFFFFF
ERROR_ALREADY_EXISTS = 183
WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_ICON, NIF_TIP, NIF_INFO = 0x2, 0x4, 0x10
NIIF_INFO = 0x1
MB_ICONWARNING = 0x30


class FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("hWnd", ctypes.c_void_p), ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint), ("uCallbackMessage", ctypes.c_uint), ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128), ("dwState", ctypes.c_uint), ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256), ("uTimeout", ctypes.c_uint), ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", ctypes.c_void_p)]


HANDLE = ctypes.c_void_p
ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, HANDLE, HANDLE)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


def _declare(dll, signatures):
    for name, restype, argtypes in signatures:
        fn = getattr(dll, name)
        fn.restype, fn.argtypes = restype, argtypes


_declare(user32, [
    ("EnumWindows", wt.BOOL, [ENUMPROC, HANDLE]),
    ("GetWindowTextW", ctypes.c_int, [HANDLE, wt.LPWSTR, ctypes.c_int]),
    ("GetClassNameW", ctypes.c_int, [HANDLE, wt.LPWSTR, ctypes.c_int]),
    ("GetWindowThreadProcessId", wt.DWORD, [HANDLE, ctypes.POINTER(wt.DWORD)]),
    ("IsWindow", wt.BOOL, [HANDLE]),
    ("IsIconic", wt.BOOL, [HANDLE]),
    ("IsWindowVisible", wt.BOOL, [HANDLE]),
    ("ShowWindow", wt.BOOL, [HANDLE, ctypes.c_int]),
    ("SetForegroundWindow", wt.BOOL, [HANDLE]),
    ("AllowSetForegroundWindow", wt.BOOL, [wt.DWORD]),
    ("GetWindowRect", wt.BOOL, [HANDLE, ctypes.POINTER(wt.RECT)]),
    ("SetWindowPos", wt.BOOL, [HANDLE, HANDLE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]),
    ("GetWindowLongW", ctypes.c_long, [HANDLE, ctypes.c_int]),
    ("SetWindowLongW", ctypes.c_long, [HANDLE, ctypes.c_int, ctypes.c_long]),
    ("SetLayeredWindowAttributes", wt.BOOL, [HANDLE, wt.DWORD, ctypes.c_ubyte, wt.DWORD]),
    ("RedrawWindow", wt.BOOL, [HANDLE, HANDLE, HANDLE, ctypes.c_uint]),
    ("MonitorFromPoint", HANDLE, [wt.POINT, wt.DWORD]),
    ("SystemParametersInfoW", wt.BOOL, [ctypes.c_uint, ctypes.c_uint, HANDLE, ctypes.c_uint]),
    ("GetCursorPos", wt.BOOL, [ctypes.POINTER(wt.POINT)]),
    ("GetAsyncKeyState", ctypes.c_short, [ctypes.c_int]),
    ("OpenInputDesktop", HANDLE, [wt.DWORD, wt.BOOL, wt.DWORD]),
    ("CloseDesktop", wt.BOOL, [HANDLE]),
    ("SendMessageW", HANDLE, [HANDLE, ctypes.c_uint, HANDLE, HANDLE]),
    ("LoadImageW", HANDLE, [HANDLE, wt.LPCWSTR, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]),
    ("FlashWindowEx", wt.BOOL, [ctypes.POINTER(FLASHWINFO)]),
    ("MessageBoxW", ctypes.c_int, [HANDLE, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_uint]),
])
_declare(kernel32, [
    ("CreateMutexW", HANDLE, [HANDLE, wt.BOOL, wt.LPCWSTR]),
    ("CloseHandle", wt.BOOL, [HANDLE]),
])
_declare(shell32, [
    ("IsUserAnAdmin", wt.BOOL, []),
    ("ShellExecuteW", HANDLE, [HANDLE, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]),
    ("Shell_NotifyIconW", wt.BOOL, [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]),
    ("SetCurrentProcessExplicitAppUserModelID", ctypes.c_long, [wt.LPCWSTR]),
])

# ---------------------------------------------------------------- process: elevation, single instance, restart

_mutex = None


def self_command(*extra):
    """The command line that starts this app again (exe when packaged, python + script otherwise)."""
    return [sys.executable] + ([] if FROZEN else [os.path.abspath(__file__)]) + list(extra)


def is_elevated():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated():
    """Starts an elevated copy (UAC prompt). The game runs elevated, and Windows (UIPI) hides the
    key state from lower-integrity processes, so the overlay could not see ALT otherwise."""
    cmd = self_command()
    result = shell32.ShellExecuteW(None, "runas", cmd[0], subprocess.list2cmdline(cmd[1:]), None, 1)
    return (result or 0) > 32


def take_mutex():
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return bool(_mutex) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def release_mutex():
    global _mutex
    if _mutex:
        kernel32.CloseHandle(_mutex)
        _mutex = None


def ask_running_copy():
    """Asks the copy that already runs to show itself. Its window is not touched directly
    (it may be elevated, UIPI would block us); its monitor() thread picks up the request file."""
    try:
        user32.AllowSetForegroundWindow(ASFW_ANY)
        write_text(SHOW_REQUEST_FILE, str(time.time()))
    except Exception:
        log_exception()


def restart_self(flag):
    release_mutex()
    subprocess.Popen(self_command(flag), close_fds=True)
    os._exit(0)


def remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass

# ---------------------------------------------------------------- storage

_write_lock = threading.Lock()   # every UI call runs on its own thread: two saves must not share the .tmp file
_tasks_lock = threading.Lock()
_tasks_last = None               # tasks.json content as we last read/wrote it, to detect outside edits
NOTICES = []                     # messages for the UI, handed over once through Api.take_notices


def write_text(path, data):
    """Atomic write: a crash or power cut leaves either the old or the new file, never half of one."""
    with _write_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def read_json_text(path):
    """Returns the file's JSON text, or "" when it is missing. A damaged file is moved aside
    to *.bad.json (and the user is told) instead of being silently overwritten."""
    text = read_text(path)
    if not text.strip():
        return ""
    try:
        json.loads(text)
        return text
    except ValueError:
        bad = os.path.splitext(path)[0] + ".bad.json"
        try:
            with _write_lock:
                os.replace(path, bad)
            log("%s was damaged, moved it to %s" % (path, bad))
            NOTICES.append("%s was damaged and could not be loaded. A copy was kept as %s."
                           % (os.path.basename(path), os.path.basename(bad)))
        except OSError:
            log_exception()
        return ""


def text_editor():
    """Notepad++ when installed (it reloads files changed on disk), Notepad otherwise."""
    for key in (r"SOFTWARE\Notepad++", r"SOFTWARE\WOW6432Node\Notepad++"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                path = os.path.join(winreg.QueryValueEx(k, "")[0], "notepad++.exe")
                if os.path.exists(path):
                    return path
        except OSError:
            pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        path = os.path.join(base or "", "Notepad++", "notepad++.exe")
        if base and os.path.exists(path):
            return path
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "notepad.exe")


def open_in_editor(path):
    subprocess.Popen([text_editor(), path])

# ---------------------------------------------------------------- window helpers

WINDOW = None
_hwnd = None
_placed = threading.Event()   # set once the window was moved from off-screen to its real place


def app_windows(pid=None):
    """Top-level WinForms windows titled APP_TITLE (optionally of one process). Matching the title
    alone is not enough: an Explorer folder named "WUWA Tracker" has the same title."""
    found = []
    title, cls, owner = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256), wt.DWORD()

    def check(h, _):
        user32.GetWindowTextW(h, title, 256)
        if title.value == APP_TITLE:
            user32.GetClassNameW(h, cls, 256)
            if cls.value.startswith("WindowsForms"):
                user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
                if pid is None or owner.value == pid:
                    found.append(h)
        return True

    user32.EnumWindows(ENUMPROC(check), None)
    return found


def own_hwnd():
    global _hwnd
    if not (_hwnd and user32.IsWindow(_hwnd)):
        windows = app_windows(os.getpid())
        _hwnd = windows[0] if windows else None
    return _hwnd


def window_rect(h):
    rc = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(rc))
    return rc


def repaint():
    """Forces WebView2 to draw again: it can stay blank after a UAC prompt, the lock screen or a restore."""
    try:
        h = own_hwnd()
        if h:
            user32.RedrawWindow(h, None, None, RDW_REPAINT)
        width, height = WINDOW.width, WINDOW.height
        WINDOW.resize(width, height + 1)
        time.sleep(0.08)
        WINDOW.resize(width, height)
    except Exception:
        log_exception()


def reload_ui():
    try:
        WINDOW.load_html(HTML)
    except Exception:
        log_exception()


def save_window_pos():
    try:
        rc = window_rect(own_hwnd())
        write_text(WINDOW_FILE, json.dumps({"x": rc.left, "y": rc.top}))
    except Exception:
        log_exception()


def saved_window_pos():
    """The remembered position, or None when there is none or it is no longer on any monitor."""
    try:
        pos = json.loads(read_text(WINDOW_FILE, "{}"))
        x, y = int(pos["x"]), int(pos["y"])
        return (x, y) if user32.MonitorFromPoint(wt.POINT(x + 40, y + 10), 0) else None
    except Exception:
        return None


def place_window():
    """The window is created off-screen (no empty frame while WebView2 starts) and moved here once."""
    if _placed.is_set():
        return
    _placed.set()
    try:
        h = own_hwnd()
        pos = saved_window_pos()
        if pos is None:
            rc, area = window_rect(h), wt.RECT()
            user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
            pos = (area.left + (area.right - area.left - (rc.right - rc.left)) // 2,
                   area.top + (area.bottom - area.top - (rc.bottom - rc.top)) // 2)
        user32.SetWindowPos(h, None, pos[0], pos[1], 0, 0, SWP_NOSIZE | SWP_NOZORDER)
        user32.SetForegroundWindow(h)
    except Exception:
        log_exception()


def bring_to_front():
    place_window()
    h = own_hwnd()
    if not h:
        return
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    user32.SetForegroundWindow(h)
    repaint()


def set_window_icon(*_):
    try:
        h = own_hwnd()
        big = user32.LoadImageW(None, ICON_PATH, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, ICON_PATH, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if big:
            user32.SendMessageW(h, WM_SETICON, ICON_BIG, big)
        if small:
            user32.SendMessageW(h, WM_SETICON, ICON_SMALL, small)
    except Exception:
        log_exception()


_resize_generation = 0


def animate_resize(width, height):
    """Eases the window to the new size in 8 steps; a newer call cancels a running one."""
    global _resize_generation
    _resize_generation += 1
    generation = _resize_generation
    start_w, start_h = WINDOW.width, WINDOW.height

    def run():
        steps = 8
        for i in range(1, steps + 1):
            if generation != _resize_generation:
                return
            ease = 1 - (1 - i / steps) ** 3
            try:
                WINDOW.resize(int(start_w + (width - start_w) * ease), int(start_h + (height - start_h) * ease))
            except Exception:
                return
            time.sleep(0.012)

    threading.Thread(target=run, daemon=True).start()


def input_desktop_is_secure():
    """True while the UAC prompt or the lock screen (the secure desktop) is shown."""
    desktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if desktop:
        user32.CloseDesktop(desktop)
    return not desktop


def monitor():
    """Background loop: exits with the window, repaints after the secure desktop, answers show requests."""
    secure, had_window, missing_for = False, False, 0
    while True:
        time.sleep(0.5)
        try:
            if own_hwnd():
                had_window, missing_for = True, 0
            elif had_window:
                missing_for += 1
                if missing_for >= 10:
                    log("window is gone but the process was still running, exiting")
                    release_mutex()
                    os._exit(0)
            now_secure = input_desktop_is_secure()
            if secure and not now_secure:
                log("UAC prompt or lock screen closed, repainting the window")
                time.sleep(0.5)
                repaint()
            secure = now_secure
            if os.path.exists(SHOW_REQUEST_FILE):
                remove_quietly(SHOW_REQUEST_FILE)
                bring_to_front()
        except Exception:
            log_exception()
            time.sleep(5)

# ---------------------------------------------------------------- overlay (always on top, see-through, click-through)

OVERLAY = {"on": False, "opacity": 55, "typing": False, "generation": 0}


def _apply_overlay_style(h, hot):
    """hot = the user holds ALT over the window: make it solid and clickable for that moment."""
    ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
    if not OVERLAY["on"]:
        user32.SetWindowLongW(h, GWL_EXSTYLE, ex & ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_LAYERED))
        return
    ex |= WS_EX_LAYERED
    if hot:
        ex &= ~WS_EX_TRANSPARENT
        alpha = 245
    else:
        ex |= WS_EX_TRANSPARENT
        alpha = int(255 * OVERLAY["opacity"] / 100)
    # NOACTIVATE keeps the game focused; it is dropped while a text field needs the keyboard.
    ex = ex & ~WS_EX_NOACTIVATE if OVERLAY["typing"] else ex | WS_EX_NOACTIVATE
    user32.SetWindowLongW(h, GWL_EXSTYLE, ex)
    user32.SetLayeredWindowAttributes(h, 0, alpha, LWA_ALPHA)


def _overlay_loop(generation):
    h = own_hwnd()
    last, cursor = None, wt.POINT()
    while OVERLAY["on"] and OVERLAY["generation"] == generation:
        try:
            alt = bool(user32.GetAsyncKeyState(VK_MENU) & KEY_DOWN)
            user32.GetCursorPos(ctypes.byref(cursor))
            rc = window_rect(h)
            inside = rc.left <= cursor.x < rc.right and rc.top <= cursor.y < rc.bottom
            state = (inside and alt, OVERLAY["opacity"], OVERLAY["typing"])
            if state != last:
                _apply_overlay_style(h, state[0])
                last = state
        except Exception:
            log_exception()
        time.sleep(0.03)
    if not OVERLAY["on"]:
        try:
            _apply_overlay_style(h, False)
            repaint()
        except Exception:
            log_exception()

# ---------------------------------------------------------------- notifications

_balloon = {"generation": 0, "icon": None}


def show_balloon(title, msg):
    """Tray balloon via Shell_NotifyIcon. The temporary tray icon is removed 12 s after the last balloon."""
    if not _balloon["icon"]:
        _balloon["icon"] = user32.LoadImageW(None, ICON_PATH, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = own_hwnd()
    nid.uID = 7
    nid.uFlags = NIF_ICON | NIF_TIP
    nid.hIcon = _balloon["icon"]
    nid.szTip = APP_TITLE
    shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))  # fails harmlessly while the icon is still there
    nid.uFlags = NIF_INFO
    nid.szInfoTitle = str(title)[:63]
    nid.szInfo = str(msg)[:255]
    nid.dwInfoFlags = NIIF_INFO
    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
    _balloon["generation"] += 1
    generation = _balloon["generation"]

    def remove_later():
        time.sleep(12)
        if _balloon["generation"] == generation:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    threading.Thread(target=remove_later, daemon=True).start()


def flash_taskbar():
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), own_hwnd(), FLASHW_ALL | FLASHW_TIMERNOFG, 5, 0)
    user32.FlashWindowEx(ctypes.byref(info))

# ---------------------------------------------------------------- watchdog

HEARTBEAT = {"ready": False, "last": time.time()}


def watchdog():
    threading.Thread(target=monitor, daemon=True).start()
    _wait_for_ui()
    _watch_heartbeat()


def _wait_for_ui():
    """The UI must call ready() in time: else reload it, then restart once, then give up with a message."""
    started, reloaded = time.time(), False
    while not HEARTBEAT["ready"]:
        time.sleep(0.5)
        if time.time() - started <= READY_TIMEOUT:
            continue
        if not reloaded:
            log("window stayed blank for %d s, reloading the interface" % READY_TIMEOUT)
            reloaded, started = True, time.time()
            place_window()
            reload_ui()
        elif "--retry" not in sys.argv:
            log("window still blank, restarting the app")
            restart_self("--retry")
        else:
            log("window still blank after a restart, giving up")
            user32.MessageBoxW(None, "WUWA Tracker could not load its window.\nRestart your PC or reinstall the "
                               "Microsoft WebView2 Runtime.\nDetails: " + LOG_FILE, APP_TITLE, MB_ICONWARNING)
            os._exit(1)


def _watch_heartbeat():
    """The UI sends beat() every 15 s. A frozen UI is reloaded, and if that does not help, the app restarts."""
    previous, reloaded_at = time.time(), 0
    while True:
        time.sleep(5)
        now = time.time()
        h = own_hwnd()
        # No beats are expected after sleep/hibernation or while the window is minimized or hidden.
        if now - previous > 30 or not h or user32.IsIconic(h) or not user32.IsWindowVisible(h):
            HEARTBEAT["last"] = now
        previous = now
        if now - HEARTBEAT["last"] <= BEAT_TIMEOUT:
            reloaded_at = 0
        elif not reloaded_at:
            log("interface stopped responding, reloading it")
            reloaded_at = now
            reload_ui()
        elif now - reloaded_at > RESTART_AFTER:
            log("interface still not responding, restarting the app")
            restart_self("--restarted")

# ---------------------------------------------------------------- file dialogs

def _file_dialog(kind, **options):
    dialog = getattr(webview, "FileDialog", None)
    kinds = {"save": dialog.SAVE if dialog else webview.SAVE_DIALOG,
             "open": dialog.OPEN if dialog else webview.OPEN_DIALOG}
    result = WINDOW.create_file_dialog(kinds[kind], **options)
    if isinstance(result, (list, tuple)):
        result = result[0] if result else None
    return result or None

# ---------------------------------------------------------------- API for the user interface

class Api:
    """Methods the UI calls as pywebview.api.<name>(...). pywebview runs every call on its own thread."""

    # ---- window

    def ready(self):
        if not HEARTBEAT["ready"]:
            log("interface ready")
        HEARTBEAT["ready"] = True
        HEARTBEAT["last"] = time.time()
        if not _placed.is_set():
            threading.Timer(0.2, place_window).start()

    def beat(self):
        HEARTBEAT["last"] = time.time()

    _chrome = None   # (height, width) the window frame adds around the page, measured on the first fit

    def fit(self, content_h, inner_h, need_w=0, inner_w=0, anchor_right=False):
        """Resizes the window to the page: content height, and need_w = the layout's width (full or compact view).
        anchor_right keeps the right edge in place, so the timers stay put when the compact view is switched."""
        try:
            if Api._chrome is None:
                ch, cw = WINDOW.height - int(inner_h), WINDOW.width - int(inner_w)
                Api._chrome = (ch if 0 <= ch <= 6 else 2, cw if 0 <= cw <= 6 else 0)
            chrome_h, chrome_w = Api._chrome
            height = max(150, min(int(content_h) + chrome_h - 2, 1000))
            width = int(need_w) + chrome_w if int(need_w) > 0 else WINDOW.width
            if abs(height - WINDOW.height) <= 2 and abs(width - WINDOW.width) <= 2:
                return
            if anchor_right and _placed.is_set():
                h = own_hwnd()
                before = window_rect(h)
                WINDOW.resize(width, height)
                after = window_rect(h)
                user32.SetWindowPos(h, None, before.right - (after.right - after.left), after.top, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                save_window_pos()
            elif _placed.is_set():
                animate_resize(width, height)
            else:
                WINDOW.resize(width, height)
        except Exception:
            log_exception()

    def start_drag(self):
        """Moves the window with the mouse until the left button is released (the title bar is HTML)."""
        h = own_hwnd()

        def run():
            cursor = wt.POINT()
            user32.GetCursorPos(ctypes.byref(cursor))
            rc = window_rect(h)
            dx, dy = cursor.x - rc.left, cursor.y - rc.top
            while user32.GetAsyncKeyState(VK_LBUTTON) & KEY_DOWN:
                user32.GetCursorPos(ctypes.byref(cursor))
                user32.SetWindowPos(h, None, cursor.x - dx, cursor.y - dy, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                time.sleep(0.004)
            save_window_pos()

        threading.Thread(target=run, daemon=True).start()

    def minimize(self):
        try:
            WINDOW.minimize()
        except Exception:
            log_exception()

    def close(self):
        try:
            WINDOW.destroy()
        except Exception:
            os._exit(0)

    def typing(self, flag):
        """A text field got (1) or lost (0) focus: the overlay must accept keyboard focus meanwhile."""
        try:
            OVERLAY["typing"] = bool(flag)
            if flag and OVERLAY["on"]:
                time.sleep(0.06)
                user32.SetForegroundWindow(own_hwnd())
        except Exception:
            log_exception()

    def set_on_top(self, flag, opacity=55):
        try:
            OVERLAY["opacity"] = max(20, min(100, int(opacity)))
            user32.SetWindowPos(own_hwnd(), HWND_TOPMOST if flag else HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            if flag and not OVERLAY["on"]:
                OVERLAY["on"] = True
                OVERLAY["generation"] += 1
                threading.Thread(target=_overlay_loop, args=(OVERLAY["generation"],), daemon=True).start()
            elif not flag:
                OVERLAY["on"] = False
        except Exception:
            log_exception()

    def notify(self, title, msg):
        for action in (flash_taskbar, lambda: show_balloon(title, msg)):
            try:
                action()
            except Exception:
                log_exception()

    # ---- storage

    def load(self):
        return read_json_text(PROGRESS_FILE)

    def save(self, data):
        try:
            write_text(PROGRESS_FILE, data)
            return True
        except Exception:
            log_exception()
            return False

    def load_tasks(self):
        global _tasks_last
        with _tasks_lock:
            _tasks_last = read_json_text(TASKS_FILE)
            return _tasks_last

    def save_tasks(self, data):
        global _tasks_last
        try:
            with _tasks_lock:
                write_text(TASKS_FILE, data)
                _tasks_last = data
            return True
        except Exception:
            log_exception()
            return False

    def tasks_changed(self):
        """The new tasks.json content when it was edited outside the app since we last touched it, else ""."""
        with _tasks_lock:
            current = read_text(TASKS_FILE)
            return current if _tasks_last is not None and current != _tasks_last else ""

    def open_tasks(self):
        try:
            if not os.path.exists(TASKS_FILE):
                write_text(TASKS_FILE, "[]")
            open_in_editor(TASKS_FILE)
        except Exception:
            log_exception()

    def take_notices(self):
        notes = NOTICES[:]
        del NOTICES[:]
        return notes

    def export_data(self, progress, tasks):
        """Saves progress + tasks into one backup file the user picks."""
        try:
            path = _file_dialog("save", save_filename="WUWA-Tracker-backup-%s.json" % time.strftime("%Y-%m-%d"),
                                file_types=("Backup files (*.json)", "All files (*.*)"))
            if not path:
                return "cancelled"
            backup = {"app": APP_TITLE, "format": BACKUP_FORMAT, "version": APP_VERSION,
                      "exported": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "progress": json.loads(progress), "tasks": json.loads(tasks)}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup, f, ensure_ascii=False, indent=1)
            return "ok"
        except Exception:
            log_exception()
            return "could not write the file"

    def import_data(self):
        """Reads a backup file. The current files are copied to *.before-import.json first."""
        try:
            path = _file_dialog("open", file_types=("Backup files (*.json)", "All files (*.*)"))
            if not path:
                return {"cancelled": True}
            backup = json.loads(read_text(path))
            if not (isinstance(backup, dict) and backup.get("app") == APP_TITLE
                    and isinstance(backup.get("progress"), dict) and isinstance(backup.get("tasks"), list)):
                return {"error": "this is not a WUWA Tracker backup"}
            for current in (PROGRESS_FILE, TASKS_FILE):
                if os.path.exists(current):
                    shutil.copyfile(current, os.path.splitext(current)[0] + ".before-import.json")
            return {"progress": json.dumps(backup["progress"]), "tasks": json.dumps(backup["tasks"])}
        except ValueError:
            return {"error": "the file is damaged"}
        except Exception:
            log_exception()
            return {"error": "could not read the file"}

    # ---- system

    def get_autostart(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_TITLE)
            return True
        except OSError:
            return False

    def set_autostart(self, flag):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if flag:
                    command = " ".join('"%s"' % part for part in self_command())
                    winreg.SetValueEx(k, APP_TITLE, 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(k, APP_TITLE)
                    except FileNotFoundError:
                        pass
        except Exception:
            log_exception()
        return self.get_autostart()

    def open_url(self, url):
        """Opens our GitHub page in the normal (non-elevated) browser."""
        try:
            if str(url).startswith(REPO_URL):
                subprocess.Popen(["explorer.exe", url])
        except Exception:
            log_exception()

    def open_log(self):
        try:
            if not os.path.exists(LOG_FILE):
                log("log file created")
            open_in_editor(LOG_FILE)
        except Exception:
            log_exception()

    def log_js(self, msg):
        log("JS: " + str(msg)[:2000])

    def do_update(self, url, digest=""):
        """Downloads the release installer, checks its sha256 when GitHub gave one, runs it silently, exits."""
        try:
            if not str(url).startswith(UPDATE_URL_PREFIX):
                return "invalid address"
            request = urllib.request.Request(url, headers={"User-Agent": "WUWA-Tracker"})
            sha = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=60) as response, open(UPDATE_FILE, "wb") as f:
                for chunk in iter(lambda: response.read(1 << 16), b""):
                    f.write(chunk)
                    sha.update(chunk)
            digest = str(digest)
            if digest.startswith("sha256:") and sha.hexdigest() != digest[7:].lower():
                remove_quietly(UPDATE_FILE)
                return "checksum mismatch"
            subprocess.Popen([UPDATE_FILE] + INSTALLER_ARGS, close_fds=True)
            threading.Timer(1.5, lambda: os._exit(0)).start()
            return "ok"
        except Exception:
            log_exception()
            return "download error"

# ---------------------------------------------------------------- start

def system_background():
    """Window color before the page paints, matching the Windows app theme."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0]
        return "#eef3f6" if light else "#0d1b24"
    except OSError:
        return "#0d1b24"


def main():
    global WINDOW
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    os.makedirs(DATA_DIR, exist_ok=True)
    if not take_mutex():
        ask_running_copy()
        sys.exit(0)
    if not is_elevated() and "--noadmin" not in sys.argv:
        release_mutex()
        if relaunch_elevated():
            sys.exit(0)
        log("administrator rights were declined, running without them")
        if not take_mutex():
            ask_running_copy()
            sys.exit(0)
    remove_quietly(SHOW_REQUEST_FILE)
    WINDOW = webview.create_window(APP_TITLE, html=HTML, js_api=Api(), width=642, height=400, min_size=(170, 150),
                                   background_color=system_background(), x=-20000, y=-20000,
                                   frameless=True, easy_drag=False)
    WINDOW.events.shown += set_window_icon
    log("start v%s, administrator: %s" % (APP_VERSION, is_elevated()))
    threading.Thread(target=watchdog, daemon=True).start()
    # Elevated and normal WebView2 processes must not share one user-data folder.
    webview.start(icon=ICON_PATH, private_mode=False,
                  storage_path=os.path.join(DATA_DIR, "webview-admin" if is_elevated() else "webview"))
    log("window closed, exiting")
    release_mutex()
    os._exit(0)  # pywebview may leave non-daemon threads behind; never linger as a zombie process

# ---------------------------------------------------------------- user interface
# Rules for this string: no backslash escapes inside JS template literals (`\D` silently becomes `D`),
# never three double quotes in a row, and it must not end with a backslash.

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>WUWA Tracker</title>
<style>
/* "Resonator HUD": deep ink panels, gold for progress and actions, cyan for time; chamfered rows echo the game UI. */
:root{
  color-scheme:dark;
  --ink:#0d1b24;--panel:#13283a;--panel-2:#183247;--hover:#1a3349;--line:#24445c;
  --text:#dde8ee;--muted:#7f98a8;--faded:#536d7e;
  --gold:#e6c36a;--on-gold:#1b1405;--gold-glow:rgba(230,195,106,.14);--cyan:#69d2d6;
  --warn:#e5a33d;--bad:#e86a5f;--danger:#d9434f;--shadow:0 14px 34px rgba(0,0,0,.55);
}
:root[data-theme="light"]{
  color-scheme:light;
  --ink:#eef3f6;--panel:#ffffff;--panel-2:#dce6ed;--hover:#e5eef4;--line:#c8d6e0;
  --text:#14232d;--muted:#5b7181;--faded:#9caebb;
  --gold:#b8891c;--on-gold:#ffffff;--gold-glow:rgba(184,137,28,.13);--cyan:#1f949a;
  --warn:#c27c12;--bad:#c94a3f;--shadow:0 14px 34px rgba(20,40,60,.22);
}
*{box-sizing:border-box;scrollbar-width:none}   /* no scrollbars anywhere: the window resizes to its content */
::-webkit-scrollbar{display:none;width:0;height:0}
html,body{height:100%}
body{margin:0;background:var(--ink);color:var(--text);border:1px solid var(--line);font:13px/1.3 Bahnschrift,"Segoe UI",sans-serif;overflow-y:auto}
body.dragging-row{cursor:grabbing;user-select:none}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--cyan);outline-offset:1px}
.muted{color:var(--muted);font-size:11.5px}
.warn-text{color:var(--warn)}
.bad-text{color:var(--bad)}
.link{text-decoration:underline;cursor:pointer}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.row.between{justify-content:space-between}

/* Frame: title bar, then navigation | content | gauges */
#app{width:640px}   /* fixed design width: measuring the height must not depend on the window's current width */
#app.mini{width:180px}
#app.picker-open{min-height:360px}
#titlebar{display:flex;align-items:center;gap:8px;height:30px;padding:0 4px 0 10px;border-bottom:1px solid var(--line);user-select:none}
#titlebar img{width:20px;height:20px}
#titlebar .title{flex:1;min-width:0;overflow:hidden;white-space:nowrap;color:var(--muted);font-size:12px;letter-spacing:.07em}
#titlebar .title b{color:var(--gold);font-weight:600}
#titlebar button{width:32px;height:22px;border:0;background:none;color:var(--muted);font-size:13px;line-height:1}
#titlebar button:hover{background:var(--hover);color:var(--text)}
#titlebar .close:hover{background:var(--danger);color:#fff}
.layout{display:grid;grid-template-columns:118px minmax(0,1fr) 178px}
nav{display:flex;flex-direction:column;gap:2px;padding:10px 0 10px 8px;border-right:1px solid var(--line)}
.nav-item{display:flex;justify-content:space-between;align-items:baseline;gap:6px;width:100%;padding:7px 10px 7px 11px;border:0;border-left:2px solid transparent;background:none;color:var(--muted);font-size:14px;text-align:left;transition:color .15s,background .15s}
.nav-item:hover{color:var(--text);background:var(--hover)}
.nav-item.active{color:var(--text);border-left-color:var(--gold);background:linear-gradient(90deg,var(--gold-glow),transparent)}
.nav-item .label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-item small{flex:none;font-size:11px;font-variant-numeric:tabular-nums}
.nav-item.active small{color:var(--gold)}
.nav-item.settings{margin-top:auto;font-size:13px}
main{display:flex;flex-direction:column;gap:5px;min-width:0;padding:10px 12px}
#notices:empty{display:none}
#view{flex:1;display:flex;flex-direction:column;gap:5px}
aside{display:flex;flex-direction:column;gap:11px;min-width:0;padding:12px;border-left:1px solid var(--line)}

/* Buttons and fields */
.btn{padding:4px 10px;border:1px solid var(--line);background:var(--panel);font-size:12px;transition:border-color .15s,background .15s}
.btn:hover{border-color:var(--muted)}
.btn.primary{background:var(--gold);border-color:var(--gold);color:var(--on-gold)}
.btn.primary:hover{filter:brightness(1.08)}
.icon-btn{flex:none;padding:0 4px;border:0;background:none;color:var(--muted);font-size:13px;line-height:1.4}
.icon-btn:hover{color:var(--text)}
.mini-btn{padding:0 5px;border:1px solid var(--line);background:none;color:var(--gold);font-size:11px}
.mini-btn:hover{border-color:var(--gold)}
.armed,.armed:hover{background:var(--danger);border-color:var(--danger);color:#fff}
.field{min-width:0;padding:3px 7px;border:1px solid var(--line);border-radius:0;background:var(--ink);color:var(--text);font-size:12px}
.field:focus{border-color:var(--cyan);outline:none}
.field::placeholder{color:var(--faded)}
.field.num{width:46px;text-align:center}
.field.date{cursor:pointer}
select.field{padding:2px 4px}
input.check{appearance:none;flex:none;width:11px;height:11px;margin:0 2px;border:1.5px solid var(--muted);transform:rotate(45deg);cursor:pointer;transition:background .15s,border-color .15s}
input.check:checked,.mark.on{background:var(--gold);border-color:var(--gold)}
.mark{flex:none;width:11px;height:11px;margin:0 2px;border:1.5px solid var(--muted);transform:rotate(45deg)}

/* Content header */
.head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.head h1{margin:0;font-size:17px;font-weight:600;letter-spacing:.02em;white-space:nowrap}
.head .streak{margin-left:7px;color:var(--gold);font-size:12px;font-weight:400}
.head .when{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.head .when b{color:var(--cyan);font-weight:400}
.progress{height:2px;margin:1px 0 3px;background:var(--panel-2)}
.progress i{display:block;width:0;height:100%;background:var(--gold);transition:width .3s}

/* Task rows */
.task{display:flex;gap:9px;align-items:center;padding:6px 9px;background:var(--panel);user-select:none;transition:background .15s;
  clip-path:polygon(0 0,100% 0,100% calc(100% - 7px),calc(100% - 7px) 100%,0 100%)}
.task.clickable{cursor:pointer}
.task.clickable:hover{background:var(--hover)}
.task-text{flex:1;min-width:0}
.task-text b{display:block;font-size:13.5px;font-weight:400}
.task-text span{display:block;color:var(--muted);font-size:11px}
.task.done,.task.done .task-text span{color:var(--faded)}
.task.done b{text-decoration:line-through}
.count{flex:none;color:var(--gold);font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
.chip{position:relative;padding:2px 7px;border:1px solid var(--line);color:var(--muted);font-size:11px;cursor:pointer;transition:border-color .15s,color .15s}
.chip:hover{border-color:var(--muted);color:var(--text)}
.chip:focus-within{outline:2px solid var(--cyan);outline-offset:1px}
.chip input{position:absolute;width:0;height:0;opacity:0}
.chip.on{border-color:var(--gold);color:var(--gold)}
.empty{padding:16px 4px;color:var(--gold);text-align:center}
details>.task{margin-top:5px}
summary{color:var(--muted);font-size:12px;cursor:pointer}

/* Drag and drop */
.task.lifted{position:relative;z-index:5;opacity:.92;pointer-events:none;filter:drop-shadow(0 6px 10px rgba(0,0,0,.45))}
.drop-before{box-shadow:inset 0 3px 0 0 var(--gold)}
.drop-after{box-shadow:inset 0 -3px 0 0 var(--gold)}

/* Edit mode */
.task.editor{flex-direction:column;align-items:stretch;gap:4px;cursor:default}
.sub-list{display:flex;flex-direction:column;gap:3px}

/* Add rows */
.add-row{display:flex;gap:4px;margin-top:auto;padding-top:3px}
.add-row .field{flex:1;padding:5px 9px;border-style:dashed;background:none}
.add-row .btn{padding:4px 12px;font-size:14px}
.add-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:auto;padding-top:3px}
.task .add-grid{width:100%;margin-top:0;padding-top:0}
.add-grid label{display:flex;flex-direction:column;gap:2px;min-width:0;color:var(--muted);font-size:11px}
.add-grid .field{width:100%;height:28px}
.add-grid>.btn{height:28px;align-self:end;font-size:14px}
.add-grid>.row{align-self:end}

/* Settings */
.settings{display:flex;flex-direction:column;gap:7px;font-size:12.5px}
.settings label{display:flex;gap:8px;align-items:center}

/* Banners */
.banner{cursor:grab}
.banner-head{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.banner-head>b{display:flex;align-items:center;gap:6px;min-width:0}
.banner-head>span{color:var(--muted);font-size:11px;white-space:nowrap}
.countdown{margin:1px 0;font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}
.banner.ended{opacity:.5}
.actions{display:flex;gap:2px;align-self:flex-start}

/* Right column: Waveplate ring and the other timers */
.gauge{position:relative;width:116px;height:116px;margin:0 auto}
.gauge .ring{position:absolute;inset:0;border-radius:50%;background:conic-gradient(var(--ring,var(--cyan)) calc(var(--p,0) * 1%),var(--panel-2) 0);
  -webkit-mask:radial-gradient(circle 49px,transparent 98%,#000 100%);mask:radial-gradient(circle 49px,transparent 98%,#000 100%);}
.gauge.full{--ring:var(--gold)}
.gauge .inside{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;text-align:center}
.gauge img{width:16px;height:16px;margin-bottom:3px}
.gauge b{font-size:26px;font-weight:600;line-height:1;font-variant-numeric:tabular-nums}
.gauge .inside>span{margin-top:2px;color:var(--muted);font-size:11px}
.gauge small{color:var(--muted);font-size:10px}
.stat{color:var(--muted);font-size:12px}
.stat.jump{cursor:pointer}
.stat.jump:hover b{color:var(--gold)}
.stat-head{display:flex;align-items:center;gap:4px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.stat-head img{width:13px;height:13px}
.stat-value{display:flex;justify-content:space-between;align-items:center;gap:6px;min-height:21px}
.editable{border-bottom:1px dashed transparent;cursor:text;transition:border-color .15s,color .15s}
.editable:hover,.editable:focus-visible{border-bottom-color:var(--gold);color:var(--gold);outline:none}
.inline-edit{width:3.2ch;padding:0;border:0;border-bottom:1px solid var(--gold);background:none;color:var(--gold);font:inherit;text-align:center;outline:none}
.stat b{display:block;color:var(--text);font-size:13px;font-weight:400;font-variant-numeric:tabular-nums;white-space:nowrap}
.stat b.warn-text{color:var(--warn)}
.stat b.bad-text{color:var(--bad)}
.stat small{display:block;color:var(--muted);font-size:11px}
.tools{display:flex;gap:3px;align-items:center}
.meter{height:3px;margin-top:4px;background:var(--panel-2)}
.meter i{display:block;width:0;height:100%;background:var(--gold);transition:width .3s}
.meter i.cyan{background:var(--cyan)}
.meter i.warn{background:var(--warn)}
.meter i.bad{background:var(--bad)}
.sub-editor{display:flex;gap:4px;margin-top:6px}
.sub-editor .field{height:22px;padding:1px 4px;font-size:11px}
.sub-editor .field.num{width:44px}
.sub-editor .field.date{flex:1}

/* Notices (update available, import done, damaged file ...) */
.notice{padding:5px 8px;background:var(--gold);color:var(--on-gold);font-size:12px;cursor:pointer}
.notice.warn{background:var(--warn);color:#fff}

/* Date picker */
.picker-backdrop{position:fixed;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:8px;background:rgba(5,12,18,.6)}
.picker{width:100%;max-width:290px;padding:12px;border:1px solid var(--line);background:var(--panel);box-shadow:var(--shadow);
  clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,12px 100%,0 calc(100% - 12px))}
.picker-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;font-weight:600}
.picker-head button{width:28px;height:28px;border:1px solid var(--line);background:var(--ink);font-size:15px;line-height:1}
.picker-weekdays,.picker-days{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center}
.picker-weekdays span{padding-bottom:2px;color:var(--muted);font-size:10px}
.picker-days button{height:28px;border:0;background:none;font-size:12px}
.picker-days button:hover{background:var(--hover)}
.picker-days button.today{outline:1px solid var(--cyan)}
.picker-days button.selected{background:var(--gold);color:var(--on-gold)}
.picker-time{display:flex;align-items:center;gap:4px;margin-top:10px;font-size:12px}
.picker-time .field{width:34px;padding:5px 2px;text-align:center}
.picker-time .grow{flex:1}
.picker-time .btn{padding:5px 11px}

/* Week overview (Weekly tab) */
.week-strip{display:flex;align-items:flex-end;gap:10px;margin:0 0 3px 1px;color:var(--muted);font-size:10px}
.week-strip .day{display:flex;flex-direction:column;align-items:center;gap:5px}
.week-strip .day i{width:9px;height:9px;border:1.5px solid var(--line);transform:rotate(45deg)}
.week-strip .day.on i{background:var(--gold);border-color:var(--gold)}
.week-strip .day.today{color:var(--cyan)}
.week-strip .day.today i{border-color:var(--cyan)}
.week-strip .day.future{opacity:.45}
.week-strip .total{margin-left:auto;font-size:11.5px}
.week-strip .total b{color:var(--gold);font-weight:400}
.tag{flex:none;padding:0 5px;border:1px solid var(--cyan);color:var(--cyan);font-size:10px;font-weight:400;vertical-align:1px}
.keys{color:var(--faded);font-size:11px}

/* Compact view: only the right column, for playing with the overlay */
.mini-only{display:none}
#app.mini .mini-only{display:block}
#app.mini .layout{grid-template-columns:minmax(0,1fr)}
#app.mini nav,#app.mini main{display:none}
#app.mini aside{border-left:0}
#app.mini #titlebar .title{visibility:hidden}
#side-timers{display:flex;flex-direction:column;gap:11px}
.mini-head{display:flex;justify-content:space-between;align-items:baseline;gap:6px;color:var(--muted);font-size:12px}
.mini-head b{color:var(--text);font-size:13px;font-weight:600}
.mini-reset{margin-top:1px;color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.mini-list{display:flex;flex-direction:column;gap:3px;margin-top:7px}
.mini-task{display:flex;align-items:center;gap:7px;padding:4px 7px;background:var(--panel);font-size:12px;user-select:none;cursor:pointer;transition:background .15s;
  clip-path:polygon(0 0,100% 0,100% calc(100% - 5px),calc(100% - 5px) 100%,0 100%)}
.mini-task:hover{background:var(--hover)}
.mini-task.group{cursor:default}
.mini-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mini-task.done{color:var(--faded)}
.mini-task.done .mini-title{text-decoration:line-through}
.mini-subs{display:flex;flex:none;gap:6px}
.mini-subs input.check{width:9px;height:9px;margin:0 1px}

/* Motion: the ring fills smoothly, ticks give a short gold burst, tabs fade in */
@property --p{syntax:'<number>';inherits:false;initial-value:0}
.gauge .ring{transition:--p .9s cubic-bezier(.2,.7,.2,1)}
.gauge.flash .ring{animation:ring-flash 1.4s ease-out}
@keyframes ring-flash{0%,100%{filter:none}30%{filter:drop-shadow(0 0 9px var(--gold))}}
input.check.pop{animation:diamond-pop .45s ease-out}
@keyframes diamond-pop{0%{transform:rotate(45deg) scale(1);box-shadow:0 0 0 0 var(--gold)}45%{transform:rotate(45deg) scale(1.55)}100%{transform:rotate(45deg) scale(1);box-shadow:0 0 0 8px transparent}}
.chip.pop{animation:chip-pop .5s ease-out}
@keyframes chip-pop{0%{box-shadow:0 0 0 0 var(--gold);background:var(--gold-glow)}100%{box-shadow:0 0 0 6px transparent;background:transparent}}
.count.pop{display:inline-block;animation:count-pop .35s ease-out}
@keyframes count-pop{40%{transform:scale(1.4)}}
.task.glow{animation:row-glow .7s ease-out}
@keyframes row-glow{0%{background:var(--gold-glow)}100%{background:var(--panel)}}
#view.enter{animation:view-in .22s ease-out}
@keyframes view-in{from{opacity:0;transform:translateY(5px)}}
:root[data-motion="off"] *,:root[data-motion="off"] *::before,:root[data-motion="off"] *::after{animation:none!important;transition:none!important}
</style></head>
<body><div id="app">
<div id="titlebar"><img id="app-icon" alt=""><span class="title"><b>WUWA</b> TRACKER</span><button id="compact-btn" data-act="toggleCompact" title="Compact view: only the timers">&#8863;</button><button data-act="minimize" title="Minimize">&#8211;</button><button class="close" data-act="close" title="Close">&#10005;</button></div>
<div class="layout"><nav id="nav"></nav><main><div id="notices"></div><div id="view"></div></main><aside id="side"><div id="side-tasks" class="mini-only"></div><div id="side-timers"></div></aside></div>
<div id="picker"></div>
</div>
<script>
const IMAGES = {
  app: 'data:image/png;base64,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',
  waveplate: 'data:image/png;base64,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',
  crystal: 'data:image/png;base64,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',
};
</script>
<script>
'use strict';

// =============================================================== constants

const VERSION = '__APP_VERSION__';
const RELEASES_API = 'https://api.github.com/repos/xJubileus/WUWA-Tracker/releases/latest';
const MINUTE = 6e4, HOUR = 36e5, DAY = 864e5;
const RESET_HOUR = 4;                                   // daily reset, server time
const WAVEPLATE_MAX = 240, WAVEPLATE_REGEN = 6 * MINUTE;
const CRYSTAL_MAX = 480, CRYSTAL_REGEN = 12 * MINUTE;   // fills only while Waveplate is full
const SUBSCRIPTION_DAYS = 30, SUBSCRIPTION_WARN = 3 * DAY;
const BEAT_EVERY = 15e3, UPDATE_CHECK_EVERY = 6 * HOUR;
const DEFAULTS_VERSION = 5;                             // bump + add a step in migrate() when DEFAULT_TASKS change

const CATEGORIES = {
  d: {name: 'Daily', hint: 'every day'},
  w: {name: 'Weekly', hint: 'every Monday'},
  m: {name: 'Monthly', hint: '1st of month'},
  b: {name: 'Banners', hint: 'limited'},
};
const SERVERS = {
  EU: {name: 'Europe', offset: 1},
  AM: {name: 'America', offset: -5},
  AS: {name: 'Asia', offset: 8},
  SEA: {name: 'SEA', offset: 8},
  HMT: {name: 'HMT', offset: 8},
};
const THEMES = {auto: 'System', light: 'Light', dark: 'Dark'};
const MOTION = {on: 'On', auto: 'Follow Windows', off: 'Off'};
// Saved in progress.json, so the short keys stay: top = overlay, op = overlay opacity %, auto = start with
// Windows, rem/remH = daily reminder + hours before reset, wpn/wpm = Waveplate alert + minutes before full,
// upd = update check, edit = edit mode, srv = server, mini = compact view, motion = animations (on / auto = follow Windows / off).
const DEFAULT_SETTINGS = {top: 0, auto: 0, rem: 1, remH: 3, edit: 0, op: 55, srv: 'EU', wpn: 1, wpm: 15, upd: 1, theme: 'auto', mini: 0, motion: 'on'};

// Task: c = category, id, t = title, s = description, v = DEFAULTS_VERSION that added it,
// mx = counter target (0 = checkbox), sub = items of a group.
const DEFAULT_TASKS = [
  {c: 'd', id: 'daily', t: 'Daily Activity (Guidebook)', s: 'Complete daily tasks, reach 100 activity and claim the Astrite', v: 1, mx: 0},
  {c: 'd', id: 'podcast', t: 'Pioneer Podcast daily tasks', s: 'Battle pass XP, claim the rewards', v: 1, mx: 0},
  {c: 'd', id: 'resp', t: 'Open-world gathering / Echo farming', s: 'Reset respawns materials and enemies', v: 1, mx: 0},
  {c: 'd', id: 'nests', t: 'Nightmare Nests', s: 'Up to 36 Tacet Discords per nest each day', v: 5, mx: 0, sub: [
    {id: 'fg', t: 'Fallen Grave', s: 'Dream of the Lost · Havoc Warrior, Glacio Predator, Tambourinist'},
    {id: 'hc', t: 'Honami City', s: 'Thread of Severed Fate · Tick Tack, Dwarf Cassowary, Roseshroom'},
    {id: 'tw', t: 'The Wastelands', s: 'Crown of Valor · Electro Predator, Aero Predator, Violet-Feathered Heron'},
    {id: 'thc', t: "Three Heroes' Crest", s: "Flamewing's Shadow · Baby Roseshroom, Baby Viridblaze Saurian, Viridblaze Saurian"},
    {id: 'tv', t: 'Tideline Verge', s: 'Law of Harmony · Gulpuff, Chirpuff, Cyan-Feathered Heron'},
  ]},
  {c: 'w', id: 'boss', t: '3 Weekly Challenge boss rewards', s: '3 rewards per week, 60 Waveplates each: Forte materials and Echoes', v: 1, mx: 3},
  {c: 'w', id: 'pod', t: 'Pioneer Podcast weekly tasks', s: 'Weekly missions, claim the rewards', v: 1, mx: 0},
  {c: 'w', id: 'ww', t: 'Whimpering Wastes', s: 'Weekly reset, challenges give Astrite (check current status after each patch)', v: 1, mx: 0},
  {c: 'w', id: 'toa', t: 'Tower of Adversity: Stable/Experimental Zone', s: 'Uses Vigor, crests = Astrite. Check the current cycle', v: 1, mx: 0},
  {c: 'w', id: 'echo', t: 'Use boosted Echo drop chances', s: 'Weekly allowance, see how many are left in the Data Bank', v: 1, mx: 0},
  {c: 'w', id: 'holo', t: 'Tactical Hologram challenges', s: 'If there is a new or uncleared stage', v: 1, mx: 0},
  {c: 'w', id: 'dream', t: 'Fantasies of the Thousand Gateways', s: 'Dreamscape Mode: 13-stage combat challenge', v: 2, mx: 0},
  {c: 'm', id: 'hazard', t: 'Tower of Adversity: Hazard Zone', s: 'Cycle may change (14 days or 1 month), check the current dates', v: 1, mx: 0},
  {c: 'm', id: 'events', t: 'Version events and battle pass season', s: 'Check which event or BP level ends soon', v: 1, mx: 0},
];

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

// =============================================================== state

// Saved state (progress.json). done: id -> period key it was ticked in; cnt: id -> {k: period, v: count};
// wp: {v: Waveplate, c: Crystal, ts: when entered}; mc: Lunite Subscription {start, end}; banners: [{id, n, s, e}];
// streak/lastFull/prev: fully completed days (fullDays: their day keys, last 60); remDay/mcN/wpFor: which reminder was already sent.
// A banner with k: 'e' is a general event countdown.
const freshState = () => ({done: {}, tab: 'd', set: {...DEFAULT_SETTINGS}, cnt: {}, mc: null, mcN: -1, wp: null,
  streak: 0, lastFull: -1, prev: null, remDay: -1, banners: [], ui: 0});   // fullDays is added by migrate()

let st = freshState();
let tasks = [];
let booted = false;
let resetShift = (RESET_HOUR - 1) * HOUR;   // ms from UTC midnight to the server's daily reset
let shownPeriods = {};                      // period keys of the last render: a change means a reset happened
let lastBeat = 0;
let update = null;                          // newer release found on GitHub
let notices = [];
let editingBanner = null;
let showCompleted = false;
let editingSubscription = false;
let editingValue = null;   // 'waveplate' or 'crystal' while that number is being typed over
let picker = null;
let popTarget = null;      // data-pop key of the element that gets the tick animation after the next render
let shownView = '';        // last rendered view, to fade in only when it changes
let sideHtml = '';         // last right-column markup: unchanged markup is kept, so the ring can animate
let gaugeWasFull = null;
let drag = null, dragEndedAt = 0;

// =============================================================== helpers

const $ = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
const HTML_ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => HTML_ESCAPES[ch]);
const pad2 = n => String(n).padStart(2, '0');
const percent = (part, whole) => whole > 0 ? Math.max(0, Math.min(100, part / whole * 100)) : 0;
const setText = (id, text) => { const el = $(id); if (el) el.textContent = text; };

// Calls Python; resolves to null when the call fails, so callers never see a rejected promise.
function api(name, ...args) {
  try {
    return Promise.resolve(pywebview.api[name](...args)).catch(() => null);
  } catch (e) {
    return Promise.resolve(null);
  }
}
const save = () => api('save', JSON.stringify(st));
const saveTasks = () => api('save_tasks', JSON.stringify(tasks));

window.addEventListener('error', e => api('log_js', `${e.message || 'error'} (line ${e.lineno || '?'})`));
window.addEventListener('unhandledrejection', e => api('log_js', 'promise: ' + ((e.reason && e.reason.message) || e.reason)));

function compareVersions(a, b) {
  const x = a.split('.').map(Number), y = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0);
  }
  return 0;
}

function formatDuration(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(s / 86400), hours = Math.floor(s % 86400 / 3600), minutes = Math.floor(s % 3600 / 60);
  return `${days ? days + 'd ' : ''}${hours}h ${pad2(minutes)}m ${pad2(s % 60)}s`;
}
const formatLocal = t => new Date(t).toLocaleString('en-GB', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});

// Two clicks for destructive buttons: the first one asks, the second one (within 3 s) confirms.
function confirmed(button, question) {
  if (button.dataset.armed) return true;
  const label = button.textContent;
  button.dataset.armed = '1';
  button.classList.add('armed');
  button.textContent = question;
  setTimeout(() => {
    if (!button.isConnected) return;
    delete button.dataset.armed;
    button.classList.remove('armed');
    button.textContent = label;
  }, 3000);
  return false;
}

// =============================================================== theme

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
const calmQuery = window.matchMedia('(prefers-reduced-motion: reduce)');   // Windows animation effects switched off
function applyTheme() {
  const choice = st.set.theme, motion = st.set.motion;
  document.documentElement.dataset.theme = choice === 'light' || choice === 'dark' ? choice : (darkQuery.matches ? 'dark' : 'light');
  document.documentElement.dataset.motion = motion === 'off' || (motion === 'auto' && calmQuery.matches) ? 'off' : 'on';
}
darkQuery.addEventListener('change', applyTheme);
calmQuery.addEventListener('change', applyTheme);
applyTheme();

// =============================================================== server time and reset periods

const serverOffset = () => (SERVERS[st.set.srv] || SERVERS.EU).offset;
const utcLabel = offset => 'UTC' + (offset < 0 ? '' : '+') + offset;
function updateResetShift() { resetShift = (RESET_HOUR - serverOffset()) * HOUR; }
// A Date whose UTC fields show the server's wall clock.
const serverNow = () => new Date(Date.now() + serverOffset() * HOUR);

// Period keys (d: day number, w: week number, weeks start Monday, m: month number) and the next reset times.
function periodKeys() {
  const shifted = Date.now() - resetShift;
  const day = Math.floor(shifted / DAY), date = new Date(shifted);
  const week = Math.floor((day + 3) / 7);   // day 0 (1 Jan 1970) was a Thursday
  return {
    d: day,
    w: week,
    m: date.getUTCFullYear() * 12 + date.getUTCMonth(),
    next: {
      d: (day + 1) * DAY + resetShift,
      w: ((week + 1) * 7 - 3) * DAY + resetShift,
      m: Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1) + resetShift,
    },
  };
}

// Date picker values are "yyyy-mm-ddThh:mm" in server time.
function parseServerInput(value) {
  if (!value) return null;
  const [datePart, timePart] = value.split('T');
  const [y, m, d] = datePart.split('-').map(Number), [h, mi] = timePart.split(':').map(Number);
  return Date.UTC(y, m - 1, d, h - serverOffset(), mi);
}
const toServerInput = ms => new Date(ms + serverOffset() * HOUR).toISOString().slice(0, 16);
const formatServerInput = v => `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)} ${v.slice(11, 16)}`;

// =============================================================== tasks

const findTask = id => tasks.find(t => t.id === id);
const counterValue = t => { const c = st.cnt[t.id]; return c && c.k === periodKeys()[t.c] ? c.v : 0; };
const isSubDone = (t, sub) => st.done[t.id + '/' + sub.id] === periodKeys()[t.c];
const isDone = t => t.sub ? t.sub.length > 0 && t.sub.every(sub => isSubDone(t, sub))
  : t.mx > 0 ? counterValue(t) >= t.mx
  : st.done[t.id] === periodKeys()[t.c];

// Streak of fully completed days; st.prev allows undoing the last step when a task is unticked again.
function updateStreak() {
  const today = periodKeys().d, daily = tasks.filter(t => t.c === 'd');
  if (!daily.length) return;
  const complete = daily.every(isDone);
  st.fullDays = (st.fullDays || []).filter(d => d !== today && d > today - 60);
  if (complete) st.fullDays.push(today);
  if (complete && st.lastFull !== today) {
    st.prev = {s: st.streak || 0, l: st.lastFull};
    st.streak = (st.lastFull === today - 1 ? st.streak : 0) + 1;
    st.lastFull = today;
  } else if (!complete && st.lastFull === today && st.prev) {
    st.streak = st.prev.s;
    st.lastFull = st.prev.l;
    st.prev = null;
  }
}

function toggleTask(id) {
  const key = periodKeys()[findTask(id).c];
  st.done[id] = st.done[id] === key ? null : key;
  updateStreak();
  save();
  setTimeout(render, 380);   // let the tick animation play before the row moves to "Completed"
}

function toggleSubTask(id, subId) {
  const task = findTask(id), key = periodKeys()[task.c], doneKey = id + '/' + subId;
  st.done[doneKey] = st.done[doneKey] === key ? null : key;
  updateStreak();
  save();
  if (isDone(task)) {
    setTimeout(render, 380);   // the whole group is done: let the animation play before it moves away
  } else {
    popTarget = st.done[doneKey] ? doneKey : null;
    render();
  }
}

function changeCounter(id, delta) {
  const task = findTask(id);
  st.cnt[id] = {k: periodKeys()[task.c], v: Math.max(0, Math.min(task.mx, counterValue(task) + delta))};
  updateStreak();
  save();
  popTarget = delta > 0 ? id : null;
  render();
}

function addTask() {
  const title = $('new-task').value.trim();
  if (!title) return;
  tasks.push({c: st.tab, id: 'c' + Date.now(), t: title, s: ''});
  saveTasks();
  render();
}

function deleteTask(id) {
  tasks = tasks.filter(t => t.id !== id);
  saveTasks();
  updateStreak();
  save();
  render();
}

function restoreDefaultTasks() {
  tasks = DEFAULT_TASKS.map(clone);
  saveTasks();
  render();
}

// =============================================================== Waveplate and Waveplate Crystal

function waveplateNow() {
  if (!st.wp) return null;
  const now = Date.now(), {v, ts} = st.wp, crystalAtEntry = st.wp.c || 0;
  const fullAt = v >= WAVEPLATE_MAX ? ts : ts + (WAVEPLATE_MAX - v) * WAVEPLATE_REGEN;
  const crystal = Math.min(CRYSTAL_MAX, crystalAtEntry + Math.max(0, Math.floor((now - fullAt) / CRYSTAL_REGEN)));
  return {
    waveplate: v >= WAVEPLATE_MAX ? v : Math.min(WAVEPLATE_MAX, v + Math.floor((now - ts) / WAVEPLATE_REGEN)),
    fullIn: Math.max(0, fullAt - now),
    crystal,
    crystalFullIn: crystal >= CRYSTAL_MAX ? 0 : Math.max(0, fullAt + (CRYSTAL_MAX - crystalAtEntry) * CRYSTAL_REGEN - now),
  };
}

function readNumber(id, max) {
  const value = parseInt($(id).value, 10);
  return isNaN(value) || value < 0 ? null : Math.min(max, value);
}

function setWaveplate() {
  const value = readNumber('waveplate-input', CRYSTAL_MAX);   // refills can push it above the regen cap
  editingValue = null;
  if (value === null) {
    render();
    return;
  }
  const w = waveplateNow();
  st.wp = {v: value, ts: Date.now(), c: w ? w.crystal : 0};
  save();
  render();
}

function setCrystal() {
  const value = readNumber('crystal-input', CRYSTAL_MAX);
  editingValue = null;
  if (value === null) {
    render();
    return;
  }
  const w = waveplateNow();
  st.wp = {v: w ? w.waveplate : WAVEPLATE_MAX, ts: Date.now(), c: value};
  save();
  render();
}

// =============================================================== Lunite Subscription

const subscriptionLeft = () => st.mc ? st.mc.end - Date.now() : null;
const subscriptionStart = () => st.mc.start || st.mc.end - SUBSCRIPTION_DAYS * DAY;
const subscriptionLevel = left => left === null ? '' : left <= 0 ? 'bad' : left <= SUBSCRIPTION_WARN ? 'warn' : '';

function subscriptionText(left) {
  if (left === null) return 'Not set';
  if (left <= 0) return 'Expired, renew?';
  return `${Math.floor(left / DAY)}d ${pad2(Math.floor(left % DAY / HOUR))}h left`;
}

function setSubscriptionDays() {
  const days = readNumber('sub-days', 99);
  if (days === null) return;
  const end = periodKeys().next.d + (days - 1) * DAY;   // the last day ends with a daily reset
  st.mc = {start: Math.min(end - SUBSCRIPTION_DAYS * DAY, Date.now()), end};
  editingSubscription = false;
  save();
  render();
}

function setSubscriptionDate(value) {
  const bought = parseServerInput(value);
  if (!bought) return;
  st.mc = {start: bought, end: bought + SUBSCRIPTION_DAYS * DAY};
  editingSubscription = false;
  save();
  render();
}

function renewSubscription() {
  const active = !!st.mc && st.mc.end > Date.now();
  st.mc = {
    start: active ? subscriptionStart() : Date.now(),
    end: (active ? st.mc.end : Date.now()) + SUBSCRIPTION_DAYS * DAY,
  };
  editingSubscription = false;
  save();
  render();
}

// =============================================================== banners and events

const isEvent = b => b.k === 'e';
const sortedBanners = () => (st.banners || []).slice().sort((a, b) => (a.e < Date.now()) - (b.e < Date.now()));
// The countdown in the right column and the Banners tab label: the first banner, or the first event when there is none.
const featuredTimer = () => { const all = sortedBanners(); return all.find(b => !isEvent(b)) || all[0]; };
const bannerCountdown = (b, now) => now < b.s ? `Starts in ${formatDuration(b.s - now)}` : now >= b.e ? 'Ended' : formatDuration(b.e - now);

function addBanner() {
  const name = $('banner-name').value.trim(), end = parseServerInput($('banner-end').dataset.v);
  if (!name || !end) return;
  const timer = {id: 'b' + Date.now(), n: name, s: parseServerInput($('banner-start').dataset.v) || Date.now(), e: end};
  if ($('banner-kind').value === 'e') timer.k = 'e';
  st.banners.push(timer);
  save();
  render();
}

function saveBanner(id) {
  const name = $('edit-name').value.trim(), end = parseServerInput($('edit-end').dataset.v);
  if (!name || !end) return;
  const banner = st.banners.find(b => b.id === id);
  banner.n = name;
  banner.e = end;
  banner.s = parseServerInput($('edit-start').dataset.v) || banner.s;
  if ($('edit-kind').value === 'e') banner.k = 'e';
  else delete banner.k;
  editingBanner = null;
  save();
  render();
}

function deleteBanner(id) {
  st.banners = st.banners.filter(b => b.id !== id);
  save();
  render();
}

function updateBannerCountdowns(now) {
  for (const row of document.querySelectorAll('.banner')) {
    const el = row.querySelector('.countdown'), start = +el.dataset.start, end = +el.dataset.end;
    el.textContent = bannerCountdown({s: start, e: end}, now);
    row.querySelector('.meter i').style.width = percent(now - start, end - start) + '%';
  }
}

// =============================================================== settings

function setSetting(key, value) {
  st.set[key] = value;
  if (key === 'top' || key === 'op') api('set_on_top', st.set.top, st.set.op);
  if (key === 'rem') st.remDay = -1;
  if (key === 'srv') {   // another server means other reset times: the old ticks no longer fit
    updateResetShift();
    st.done = {};
    st.cnt = {};
  }
  if (key === 'theme' || key === 'motion') applyTheme();
  if (key === 'upd' && value) checkForUpdate();
  if (key === 'auto') {
    api('set_autostart', value).then(actual => {
      if (actual === null) return;
      st.set.auto = actual ? 1 : 0;
      save();
      render();
    });
  }
  save();
  render();
}

// Settings that live outside this page: overlay, theme and the autostart registry value.
function applyRuntimeSettings() {
  applyTheme();
  api('set_on_top', st.set.top, st.set.op);
  api('get_autostart').then(on => {
    if (on === null || (on ? 1 : 0) === st.set.auto) return;
    st.set.auto = on ? 1 : 0;
    save();
    render();
  });
}

// =============================================================== reminders and live clock

function notify(message) { api('notify', 'WUWA Tracker', message); }

function checkReminders(k, now) {
  const left = subscriptionLeft();
  if (st.set.rem && left !== null && left > 0 && left <= SUBSCRIPTION_WARN && st.mcN !== k.d) {
    st.mcN = k.d;
    save();
    notify(`Lunite Subscription ends in ${Math.ceil(left / DAY)} day(s)`);
  }
  const w = waveplateNow();
  if (st.set.wpn && w && w.fullIn > 0 && w.fullIn <= st.set.wpm * MINUTE && st.wpFor !== st.wp.ts) {
    st.wpFor = st.wp.ts;
    save();
    notify(`Waveplate full in ${Math.ceil(w.fullIn / MINUTE)} min (${w.waveplate}/${WAVEPLATE_MAX})`);
  }
  if (st.set.rem && st.remDay !== k.d && k.next.d - now <= st.set.remH * HOUR) {
    const open = tasks.filter(t => t.c === 'd' && !isDone(t)).length;
    if (open) {
      st.remDay = k.d;
      save();
      notify(`${open} daily task(s) left. Reset in ${formatDuration(k.next.d - now)}`);
    }
  }
}

// Runs every second (and after each render with fromRender = true).
function tick(fromRender) {
  const now = Date.now();
  if (now - lastBeat > BEAT_EVERY) {
    lastBeat = now;
    api('beat');
  }
  const k = periodKeys();
  if (!fromRender && (k.d !== shownPeriods.d || k.w !== shownPeriods.w || k.m !== shownPeriods.m)) {
    render();   // a reset happened
    return;
  }
  if (!st.ui && st.tab === 'b') updateBannerCountdowns(now);
  if (!st.ui && st.tab !== 'b') setText('reset-in', formatDuration(k.next[st.tab] - now));
  updateSide(now, k);
  checkReminders(k, now);
}

// =============================================================== update check

function checkForUpdate() {
  if (!st.set.upd || (update && update.busy)) return;
  fetch(RELEASES_API)
    .then(response => response.ok ? response.json() : null)
    .then(release => {
      if (!release) return;
      const version = String(release.tag_name || '').replace(/^v/, '');
      if (!version || compareVersions(version, VERSION) <= 0 || (update && update.version === version)) return;
      const asset = (release.assets || []).find(a => /Setup[.]exe$/i.test(a.name || ''));
      update = {
        version,
        page: String(release.html_url),
        asset: asset ? String(asset.browser_download_url) : '',
        digest: asset ? String(asset.digest || '') : '',
        busy: false,
        message: '',
      };
      render();
    })
    .catch(() => {});
}

function installUpdate() {
  if (!update || update.busy) return;
  if (!update.asset) {
    api('open_url', update.page);
    return;
  }
  update.busy = true;
  update.message = 'Downloading update… the app will restart';
  render();
  api('do_update', update.asset, update.digest).then(result => {
    if (result === 'ok') return;
    update.busy = false;
    update.asset = '';
    update.message = `Update failed (${result || 'no answer'}), click to open the download page`;
    render();
  });
}

// =============================================================== notices

let noticeId = 0;
function showNotice(text, kind = '', hideAfter = 0) {
  const id = ++noticeId;
  notices.push({id, text, kind});
  renderNotices();
  fit();
  if (hideAfter) setTimeout(() => dismissNotice(id), hideAfter);
}

function dismissNotice(id) {
  notices = notices.filter(n => n.id !== id);
  renderNotices();
  fit();
}

// =============================================================== backup

function exportData() {
  api('export_data', JSON.stringify(st), JSON.stringify(tasks)).then(result => {
    if (result === 'ok') showNotice('Backup saved', '', 4000);
    else if (result !== 'cancelled') showNotice('Export failed: ' + (result || 'no answer'), 'warn');
  });
}

function importData(button) {
  if (!confirmed(button, 'Replace current data?')) return;
  api('import_data').then(result => {
    if (!result || result.cancelled) return;
    if (result.error) {
      showNotice('Import failed: ' + result.error, 'warn');
      return;
    }
    loadState(result.progress, result.tasks);
    st.ui = 1;
    save();
    saveTasks();
    applyRuntimeSettings();
    render();
    showNotice('Backup imported', '', 4000);
  });
}

// =============================================================== rendering

const WINDOW_WIDTH = 640, COMPACT_WIDTH = 180;   // the layout is designed for these widths; the height follows the content

function render() {
  const k = periodKeys();
  shownPeriods = k;
  $('app').classList.toggle('mini', !!st.set.mini);
  const compactButton = $('compact-btn');
  compactButton.innerHTML = st.set.mini ? '&#8862;' : '&#8863;';
  compactButton.title = st.set.mini ? 'Full view' : 'Compact view: only the timers';
  renderNav();
  renderNotices();
  if (st.ui) renderSettings();
  else if (st.tab === 'b') renderBannerTab();
  else renderTaskTab(k);
  const view = st.ui ? 'settings' : st.tab;
  if (view !== shownView) {   // fade the content in when another tab opens
    const el = $('view');
    el.classList.remove('enter');
    void el.offsetWidth;
    el.classList.add('enter');
    shownView = view;
  }
  if (popTarget) {
    const el = document.querySelector(`[data-pop="${CSS.escape(popTarget)}"]`);
    if (el) el.classList.add('pop');
    popTarget = null;
  }
  renderSide();
  tick(true);
  fit();
}

function openTab(tab) {
  st.tab = tab;
  st.ui = 0;
  st.set.mini = 0;
  save();
  render();
}

function renderNav() {
  const now = Date.now(), featured = featuredTimer();
  const progress = category => {
    const all = tasks.filter(t => t.c === category);
    return `${all.filter(isDone).length}/${all.length}`;
  };
  $('nav').innerHTML = Object.entries(CATEGORIES).map(([key, cat], i) => {
    const label = key === 'b' && featured ? esc(featured.n) : cat.name;
    const meta = key !== 'b' ? progress(key) : featured && featured.e > now ? Math.floor((featured.e - now) / DAY) + 'd' : '';
    return `<button class="nav-item ${!st.ui && key === st.tab ? 'active' : ''}" data-act="tab" data-tab="${key}" title="${cat.name}: ${cat.hint} (key ${i + 1})"><span class="label">${label}</span><small>${meta}</small></button>`;
  }).join('') + `<button class="nav-item settings ${st.ui ? 'active' : ''}" data-act="toggleSettings">⚙ Settings</button>`;
}

function renderNotices() {
  let html = notices.map(n => `<div class="notice ${n.kind}" data-act="dismissNotice" data-id="${n.id}" title="Click to hide">${esc(n.text)}</div>`).join('');
  if (update) html += `<div class="notice" data-act="installUpdate">${esc(update.message || `Update ${update.version} available – click to install`)}</div>`;
  $('notices').innerHTML = html;
}

const header = (title, right, extra = '') => `<div class="head"><h1>${title}${extra}</h1><span class="when">${right}</span></div>`;

function renderSettings() {
  const s = st.set;
  const checkbox = key => `<input class="check" type="checkbox" data-change="setting" data-key="${key}" ${s[key] ? 'checked' : ''}>`;
  const number = (key, min, max, fallback) => `<input class="field num" type="text" inputmode="numeric" maxlength="3" data-digits data-change="settingNumber" data-key="${key}" data-min="${min}" data-max="${max}" data-default="${fallback}" value="${s[key]}">`;
  const select = (key, options) => `<select class="field" data-change="setting" data-key="${key}">${Object.entries(options).map(([value, label]) => `<option value="${value}" ${s[key] === value ? 'selected' : ''}>${label}</option>`).join('')}</select>`;
  const servers = Object.fromEntries(Object.entries(SERVERS).map(([key, srv]) => [key, `${srv.name} (${utcLabel(srv.offset)})`]));
  $('view').innerHTML = header('Settings', `v${VERSION}`) + `<div class="settings">
    <div class="row"><label>Server ${select('srv', servers)}</label><label>Theme ${select('theme', THEMES)}</label><label>Animations ${select('motion', MOTION)}</label></div>
    <label>${checkbox('top')} Always on top <span class="muted">(see-through; hold ALT to use it)</span></label>
    ${s.top ? `<label>Opacity ${number('op', 20, 100, 55)} %</label>` : ''}
    <label>${checkbox('auto')} Start with Windows</label>
    <label>${checkbox('rem')} Task reminder ${number('remH', 1, 23, 3)} h before reset</label>
    <label>${checkbox('wpn')} Waveplate alert ${number('wpm', 5, 60, 15)} min before full</label>
    <label>${checkbox('upd')} Check for updates (GitHub)</label>
    <label>${checkbox('edit')} Edit tasks</label>
    ${s.edit ? `<div class="row"><button class="btn" data-act="restoreDefaults">Restore defaults</button><button class="btn" data-act="openTasksFile">Open tasks file</button></div>` : ''}
    <div class="row"><button class="btn" data-act="exportData">Export backup</button><button class="btn" data-act="importData">Import backup</button></div>
    <span class="keys">Keys: 1–4 switch tabs, Ctrl+N adds a task, Esc cancels</span>
    <span class="muted"><a class="link" data-act="openLog">Open error log</a></span>
  </div>`;
}

// Daily tab: which days of this week had every daily task done.
function renderWeekStrip(k) {
  const monday = k.w * 7 - 3, fullDays = st.fullDays || [];
  let full = 0;
  const days = WEEKDAYS.map((name, i) => {
    const day = monday + i, done = fullDays.includes(day);
    if (done) full++;
    const state = done ? 'on' : day === k.d ? 'today' : day > k.d ? 'future' : '';
    return `<span class="day ${state}" title="${done ? 'Every daily task done' : day === k.d ? 'Today' : day > k.d ? 'Coming up' : 'Not every daily task done'}"><i></i>${name}</span>`;
  }).join('');
  return `<div class="week-strip">${days}<span class="total"><b>${full}</b> / 7 full days</span></div>`;
}

function renderTaskTab(k) {
  const category = st.tab, all = tasks.filter(t => t.c === category);
  const done = all.filter(isDone), open = all.filter(t => !isDone(t));
  const streak = st.lastFull >= k.d - 1 ? st.streak : 0;
  const streakBadge = category === 'd' && streak ? `<span class="streak" title="Days in a row with every daily task done">🔥 ${streak}</span>` : '';
  let html = header(CATEGORIES[category].name, `<span title="${formatLocal(k.next[category])}">Reset in <b id="reset-in"></b></span>`, streakBadge)
    + `<div class="progress"><i style="width:${percent(done.length, all.length)}%"></i></div>`
    + (category === 'd' ? renderWeekStrip(k) : '');
  if (st.set.edit) {
    html += all.map(renderTaskEditor).join('');
  } else {
    html += (open.length ? open.map(t => renderTask(t, false)).join('') : '<div class="empty">All done, ready for the reset!</div>')
      + (done.length ? `<details id="completed" ${showCompleted ? 'open' : ''}><summary>Completed (${done.length}) – open to undo</summary>${done.map(t => renderTask(t, true)).join('')}</details>` : '');
  }
  html += `<div class="add-row"><input class="field" id="new-task" placeholder="+ Add task" title="Ctrl+N" data-enter="addTask"><button class="btn primary" data-act="addTask" title="Add task">+</button></div>`;
  $('view').innerHTML = html;
}

const renderText = (title, description) => `<div class="task-text"><b>${esc(title)}</b>${description ? `<span>${esc(description)}</span>` : ''}</div>`;

function renderTask(t, done) {
  const id = esc(t.id), dragAttr = done ? '' : `data-drag="t" data-id="${id}"`, state = done ? 'done' : '';
  const mark = `<span class="mark ${done ? 'on' : ''}"></span>`;
  if (t.sub) {
    const doneCount = t.sub.filter(sub => isSubDone(t, sub)).length;
    const chips = t.sub.map(sub => {
      const checked = isSubDone(t, sub);
      return `<label class="chip ${checked ? 'on' : ''}" title="${esc(sub.s)}" data-pop="${id}/${esc(sub.id)}"><input type="checkbox" data-change="toggleSub" data-id="${id}" data-sub="${esc(sub.id)}" ${checked ? 'checked' : ''}>${esc(sub.t)}</label>`;
    }).join('');
    return `<div class="task group ${state}" ${dragAttr}>${mark}<div class="task-text"><b>${esc(t.t)}</b>${t.s ? `<span>${esc(t.s)}</span>` : ''}<div class="chips">${chips}</div></div><span class="count">${doneCount}/${t.sub.length}</span></div>`;
  }
  if (t.mx > 0) {
    return `<div class="task clickable ${state}" ${dragAttr} data-act="${done ? 'counterDown' : 'counterUp'}" data-id="${id}" title="${done ? 'Click to undo one' : 'Click to count one'}">${mark}${renderText(t.t, t.s)}<span class="count" data-pop="${id}">${counterValue(t)}/${t.mx}</span><button class="icon-btn" data-act="counterDown" data-id="${id}" title="Undo one">−</button></div>`;
  }
  return `<label class="task clickable ${state}" ${dragAttr}><input class="check" type="checkbox" data-change="toggleTask" data-id="${id}" ${done ? 'checked' : ''}>${renderText(t.t, t.s)}</label>`;
}

function renderTaskEditor(t) {
  const id = esc(t.id);
  const subs = t.sub ? `<div class="sub-list">${t.sub.map(sub => `<div class="row"><input class="field" style="flex:1" value="${esc(sub.t)}" data-change="editSub" data-id="${id}" data-sub="${esc(sub.id)}"><button class="icon-btn" data-act="deleteSub" data-id="${id}" data-sub="${esc(sub.id)}" title="Remove item">✕</button></div>`).join('')}<input class="field" placeholder="Add item… (Enter)" data-enter="addSub" data-id="${id}"></div>` : '';
  const target = t.sub ? '<span></span>' : `<span class="muted">Counter target (0 = checkbox)</span><input class="field num" type="text" inputmode="numeric" maxlength="3" data-digits value="${t.mx || 0}" data-change="editTarget" data-id="${id}">`;
  return `<div class="task editor">
    <input class="field" value="${esc(t.t)}" data-change="editTask" data-field="t" data-id="${id}">
    <input class="field" value="${esc(t.s || '')}" placeholder="Description" data-change="editTask" data-field="s" data-id="${id}">
    ${subs}
    <div class="row between">${target}<button class="icon-btn" data-act="deleteTask" data-id="${id}">✕ Delete</button></div>
  </div>`;
}

const numberInput = (id, maxLength, enter, placeholder) => `<input class="field num" id="${id}" type="text" inputmode="numeric" maxlength="${maxLength}" placeholder="${placeholder}" title="Type the value and press Enter" data-digits data-enter="${enter}">`;

const dateInput = (id, value, placeholder = 'dd/mm/yyyy --:--', callback = '') => `<input class="field date" id="${id}" readonly placeholder="${placeholder}" data-v="${value}" value="${value ? formatServerInput(value) : ''}" data-act="openPicker"${callback ? ` data-callback="${callback}"` : ''}>`;

const kindSelect = (id, timer) => `<select class="field" id="${id}"><option value="b">Banner</option><option value="e" ${timer && isEvent(timer) ? 'selected' : ''}>Event</option></select>`;

function renderBannerTab() {
  const now = Date.now();
  $('view').innerHTML = header('Banners and events', `Server time ${utcLabel(serverOffset())}`)
    + (sortedBanners().map(b => b.id === editingBanner ? renderBannerEditor(b) : renderBanner(b, now)).join('') || '<div class="empty">No banners or events yet – add one below</div>')
    + `<div class="add-grid"><label>Name<input class="field" id="banner-name" placeholder="e.g. Hsin or Version 3.1"></label><label>Type${kindSelect('banner-kind')}</label><label>Start (server)${dateInput('banner-start', '')}</label><label>End (server)${dateInput('banner-end', '')}</label><span></span><button class="btn primary" data-act="addBanner" title="Add">+ Add</button></div>`;
}

const renderBanner = (b, now) => `<div class="task banner ${b.e < now ? 'ended' : ''}" data-drag="b" data-id="${esc(b.id)}">
  <div class="task-text"><div class="banner-head"><b>${esc(b.n)}${isEvent(b) ? '<span class="tag">Event</span>' : ''}</b><span>Ends ${formatLocal(b.e)}</span></div><div class="countdown" data-start="${b.s}" data-end="${b.e}"></div><div class="meter"><i class="cyan"></i></div></div>
  <div class="actions"><button class="icon-btn" data-act="editBanner" data-id="${esc(b.id)}" title="Edit">✎</button><button class="icon-btn" data-act="deleteBanner" data-id="${esc(b.id)}" title="Delete">✕</button></div>
</div>`;

const renderBannerEditor = b => `<div class="task editor"><div class="add-grid">
  <label>Name<input class="field" id="edit-name" value="${esc(b.n)}"></label>
  <label>Type${kindSelect('edit-kind', b)}</label>
  <label>Start (server)${dateInput('edit-start', toServerInput(b.s))}</label>
  <label>End (server)${dateInput('edit-end', toServerInput(b.e))}</label>
  <span></span><div class="row"><button class="btn primary" data-act="saveBanner" data-id="${esc(b.id)}">Save</button><button class="btn" data-act="cancelBanner">Cancel</button></div>
</div></div>`;

// A number in the right column that turns into a text field when clicked (Enter or leaving the field saves, Esc cancels).
function editableNumber(kind, id) {
  if (editingValue === kind) {
    return `<input class="inline-edit" id="${kind}-input" type="text" inputmode="numeric" maxlength="3" data-digits data-enter="${kind === 'waveplate' ? 'setWaveplate' : 'setCrystal'}">`;
  }
  return `<span class="editable" id="${id}" tabindex="0" data-act="editValue" data-enter="editValue" data-kind="${kind}" title="Click to change">–</span>`;
}

function cancelInlineEdit() {
  editingValue = null;
  render();
}

// Compact view: the daily tasks as a small checklist above the timers.
function renderMiniTasks() {
  const rows = tasks.filter(t => t.c === 'd').map(t => {
    const id = esc(t.id), done = isDone(t), state = done ? 'done' : '';
    if (t.sub) {
      const subs = t.sub.map(sub => `<input class="check" type="checkbox" title="${esc(sub.t)}" data-change="toggleSub" data-id="${id}" data-sub="${esc(sub.id)}" data-pop="${id}/${esc(sub.id)}" ${isSubDone(t, sub) ? 'checked' : ''}>`).join('');
      return `<div class="mini-task group ${state}"><span class="mini-title" title="${esc(t.t)}">${esc(t.t)}</span><span class="mini-subs">${subs}</span></div>`;
    }
    if (t.mx > 0) {
      return `<div class="mini-task ${state}" data-act="${done ? 'counterDown' : 'counterUp'}" data-id="${id}" title="${esc(t.t)}: ${done ? 'click to undo one' : 'click to count one'}"><span class="mark ${done ? 'on' : ''}"></span><span class="mini-title">${esc(t.t)}</span><span class="count" data-pop="${id}">${counterValue(t)}/${t.mx}</span></div>`;
    }
    return `<label class="mini-task ${state}" title="${esc(t.t)}"><input class="check" type="checkbox" data-change="toggleTask" data-id="${id}" ${done ? 'checked' : ''}><span class="mini-title">${esc(t.t)}</span></label>`;
  }).join('');
  return `<div class="mini-head"><span>Daily</span><b id="mini-daily"></b></div><div class="mini-reset" id="mini-reset"></div><div class="mini-list">${rows}</div>`;
}

// Right column: always visible. Each part only changes its markup when the structure changes (so the ring and
// the bars can animate between values); updateSide() fills in the numbers every second.
let sideTasksHtml = '';
function renderSide() {
  const tasksHtml = st.set.mini ? renderMiniTasks() : '';
  if (tasksHtml !== sideTasksHtml) {
    sideTasksHtml = tasksHtml;
    $('side-tasks').innerHTML = tasksHtml;
  }
  const featured = featuredTimer();
  const subEditor = editingSubscription || !st.mc;
  const timer = featured
    ? `<div class="stat jump" data-act="tab" data-tab="b" title="Open banners and events"><div class="stat-head" id="banner-label"></div><b id="banner-left"></b><div class="meter"><i class="cyan" id="banner-meter"></i></div></div>`
    : `<div class="stat jump" data-act="tab" data-tab="b" title="Open banners and events"><div class="stat-head">Banner</div><b>Add one in Banners</b></div>`;
  const html = `
    <div class="gauge" id="gauge"><div class="ring" id="ring"></div><div class="inside"><img src="${IMAGES.waveplate}" alt=""><b>${editableNumber('waveplate', 'wp-value')}</b><span>/ ${WAVEPLATE_MAX}</span><small>Waveplate</small></div></div>
    <div class="stat"><div class="stat-head">Full in</div><div class="stat-value"><b id="wp-full"></b></div><small id="wp-hint"></small></div>
    <div class="stat"><div class="stat-head"><img src="${IMAGES.crystal}" alt="">Waveplate Crystal</div><div class="stat-value"><b>${editableNumber('crystal', 'crystal-value')} / ${CRYSTAL_MAX}</b></div><small id="crystal-hint"></small><div class="meter"><i id="crystal-meter"></i></div></div>
    ${timer}
    <div class="stat"><div class="stat-head">Lunite Subscription</div>
      <div class="stat-value"><b id="sub-left"></b><span class="tools"><button class="icon-btn" data-act="toggleSubscriptionEditor" title="Enter days left or the purchase date">✎</button><button class="mini-btn" data-act="renewSubscription" title="Renewed: add 30 days">+30d</button></span></div><div class="meter"><i id="sub-meter"></i></div>
      ${subEditor ? `<div class="sub-editor">${numberInput('sub-days', 2, 'setSubscriptionDays', 'Days')}${dateInput('sub-date', '', 'Bought on', 'subscriptionDate')}</div>` : ''}
    </div>`;
  if (html === sideHtml) return;
  sideHtml = html;
  $('side-timers').innerHTML = html;
  const field = document.querySelector('.inline-edit');
  if (field) {
    const w = waveplateNow();
    field.value = w ? (editingValue === 'waveplate' ? w.waveplate : w.crystal) : '';
    field.focus();
    field.select();
  }
}

function updateSide(now, k) {
  const gauge = $('gauge');
  if (!gauge) return;
  const w = waveplateNow();
  // The ring moves continuously between whole numbers, so it visibly fills up.
  const exact = !w ? 0 : w.fullIn ? Math.min(WAVEPLATE_MAX, st.wp.v + (now - st.wp.ts) / WAVEPLATE_REGEN) : w.waveplate;
  $('ring').style.setProperty('--p', percent(exact, WAVEPLATE_MAX));
  const full = !!w && !w.fullIn;
  gauge.classList.toggle('full', full);
  if (full && gaugeWasFull === false) {   // just became full: one gold flash
    gauge.classList.remove('flash');
    void gauge.offsetWidth;
    gauge.classList.add('flash');
  }
  gaugeWasFull = full;
  setText('wp-value', w ? w.waveplate : '–');
  setText('wp-full', !w ? 'Click the number to set it' : w.fullIn ? formatDuration(w.fullIn) : 'Full now');
  let hint = '';
  if (w && !w.fullIn) hint = 'Regen is wasted, spend some';
  else if (w) {
    const overflow = w.waveplate + (k.next.d - now) / WAVEPLATE_REGEN - WAVEPLATE_MAX;
    if (overflow > 0) hint = `Spend ${Math.ceil(overflow)}+ before reset`;
  }
  setText('wp-hint', hint);
  setText('crystal-value', w ? w.crystal : '–');
  setText('crystal-hint', !w ? 'Click the number to set it' : w.crystal >= CRYSTAL_MAX ? 'Full, overflow is wasted' : w.fullIn ? 'Fills once Waveplate is full' : `Full in ${formatDuration(w.crystalFullIn)}`);
  $('crystal-meter').style.width = (w ? percent(w.crystal, CRYSTAL_MAX) : 0) + '%';

  const featured = featuredTimer();
  if (featured && $('banner-left')) {
    setText('banner-label', featured.n + (now < featured.s ? ' starts in' : now >= featured.e ? '' : ' ends in'));
    setText('banner-left', bannerCountdown(featured, now).replace('Starts in ', ''));
    $('banner-meter').style.width = percent(now - featured.s, featured.e - featured.s) + '%';
  }

  const left = subscriptionLeft(), level = subscriptionLevel(left), text = $('sub-left'), bar = $('sub-meter');
  text.textContent = subscriptionText(left);
  text.className = level ? level + '-text' : '';
  text.title = st.mc ? 'Ends ' + formatLocal(st.mc.end) : '';
  bar.className = level;
  bar.style.width = st.mc ? percent(now - subscriptionStart(), st.mc.end - subscriptionStart()) + '%' : '0';

  if (st.set.mini) {
    const daily = tasks.filter(t => t.c === 'd');
    setText('mini-daily', `${daily.filter(isDone).length}/${daily.length}`);
    setText('mini-reset', `Reset in ${formatDuration(k.next.d - now)}`);
  }
}

// Resizes the window to the content height at the design width. anchorRight keeps the right edge in place
// (switching to and from the compact view keeps the timers where they were).
let fitTimer = 0, fitAnchorRight = false;
function fit(anchorRight = false) {
  fitAnchorRight = fitAnchorRight || anchorRight;
  clearTimeout(fitTimer);
  fitTimer = setTimeout(() => {
    if (!window.pywebview || !pywebview.api || !pywebview.api.fit) return;
    const width = (st.set.mini ? COMPACT_WIDTH : WINDOW_WIDTH) + 2;
    api('fit', Math.ceil($('app').getBoundingClientRect().height) + 2, window.innerHeight, width, window.innerWidth, fitAnchorRight);
    fitAnchorRight = false;
  }, 60);
}

// =============================================================== date picker (server time)

function openPicker(input) {
  const value = input.dataset.v, now = serverNow();
  picker = {inputId: input.id, year: now.getUTCFullYear(), month: now.getUTCMonth(), day: now.getUTCDate(), hour: now.getUTCHours(), minute: now.getUTCMinutes()};
  if (value) {
    Object.assign(picker, {year: +value.slice(0, 4), month: +value.slice(5, 7) - 1, day: +value.slice(8, 10), hour: +value.slice(11, 13), minute: +value.slice(14, 16)});
  }
  picker.viewYear = picker.year;
  picker.viewMonth = picker.month;
  renderPicker();
}

function closePicker() {
  picker = null;
  renderPicker();
}

function renderPicker() {
  const host = $('picker'), frame = $('app');
  if (!picker) {
    host.innerHTML = '';
    frame.classList.remove('picker-open');
    fit();
    return;
  }
  const p = picker, today = serverNow();
  const leadingBlanks = (new Date(p.viewYear, p.viewMonth, 1).getDay() + 6) % 7;   // weeks start Monday
  const daysInMonth = new Date(p.viewYear, p.viewMonth + 1, 0).getDate();
  let days = '<span></span>'.repeat(leadingBlanks);
  for (let d = 1; d <= daysInMonth; d++) {
    const selected = p.year === p.viewYear && p.month === p.viewMonth && p.day === d;
    const isToday = today.getUTCFullYear() === p.viewYear && today.getUTCMonth() === p.viewMonth && today.getUTCDate() === d;
    days += `<button class="${selected ? 'selected' : ''} ${isToday ? 'today' : ''}" data-act="pickerDay" data-day="${d}">${d}</button>`;
  }
  const timeInput = (id, value, max) => `<input class="field" id="${id}" value="${pad2(value)}" maxlength="2" inputmode="numeric" data-digits data-change="pickerTime" data-max="${max}">`;
  frame.classList.add('picker-open');
  host.innerHTML = `<div class="picker-backdrop" data-act="closePicker"><div class="picker" data-act="none">
    <div class="picker-head"><button data-act="pickerMonth" data-step="-1" title="Previous month">‹</button><span>${MONTHS[p.viewMonth]} ${p.viewYear}</span><button data-act="pickerMonth" data-step="1" title="Next month">›</button></div>
    <div class="picker-weekdays">${WEEKDAYS.map(d => `<span>${d}</span>`).join('')}</div>
    <div class="picker-days">${days}</div>
    <div class="picker-time">${timeInput('picker-hour', p.hour, 23)}:${timeInput('picker-minute', p.minute, 59)}<span class="grow"></span><button class="btn" data-act="pickerToday">Today</button><button class="btn primary" data-act="pickerOk">OK</button></div>
  </div></div>`;
  fit();
}

function readPickerTime() {
  picker.hour = Math.min(23, +$('picker-hour').value || 0);
  picker.minute = Math.min(59, +$('picker-minute').value || 0);
}

function pickerMonth(step) {
  readPickerTime();
  picker.viewMonth += step;
  if (picker.viewMonth < 0) { picker.viewMonth = 11; picker.viewYear--; }
  if (picker.viewMonth > 11) { picker.viewMonth = 0; picker.viewYear++; }
  renderPicker();
}

function pickerDay(day) {
  readPickerTime();
  Object.assign(picker, {year: picker.viewYear, month: picker.viewMonth, day});
  renderPicker();
}

function pickerToday() {
  const now = serverNow();
  Object.assign(picker, {year: now.getUTCFullYear(), month: now.getUTCMonth(), day: now.getUTCDate(), hour: now.getUTCHours(), minute: now.getUTCMinutes()});
  picker.viewYear = picker.year;
  picker.viewMonth = picker.month;
  renderPicker();
}

const PICKER_CALLBACKS = {subscriptionDate: setSubscriptionDate};

function pickerOk() {
  readPickerTime();
  const p = picker, value = `${p.year}-${pad2(p.month + 1)}-${pad2(p.day)}T${pad2(p.hour)}:${pad2(p.minute)}`;
  const input = $(p.inputId);
  closePicker();
  if (!input) return;
  input.dataset.v = value;
  input.value = formatServerInput(value);
  const callback = PICKER_CALLBACKS[input.dataset.callback];
  if (callback) callback(value);
}

// =============================================================== user actions (event delegation)
// Elements name their action: data-act (click), data-change (change), data-enter (Enter key).

const ACTIONS = {
  none: () => {},
  minimize: () => api('minimize'),
  close: () => api('close'),
  tab: el => {
    const wasMini = st.set.mini;
    openTab(el.dataset.tab);
    if (wasMini) fit(true);
  },
  toggleCompact: () => { st.set.mini = st.set.mini ? 0 : 1; editingValue = null; save(); render(); fit(true); },
  toggleSettings: () => { st.ui = st.ui ? 0 : 1; save(); render(); },
  dismissNotice: el => dismissNotice(+el.dataset.id),
  installUpdate,
  openLog: () => api('open_log'),
  openTasksFile: () => api('open_tasks'),
  restoreDefaults: el => { if (confirmed(el, 'Replace all tasks?')) restoreDefaultTasks(); },
  exportData,
  importData,
  setting: el => setSetting(el.dataset.key, el.type === 'checkbox' ? (el.checked ? 1 : 0) : el.value),
  settingNumber: el => setSetting(el.dataset.key, Math.min(+el.dataset.max, Math.max(+el.dataset.min, +el.value || +el.dataset.default))),

  toggleTask: el => {
    if (el.checked) {
      el.classList.add('pop');
      const row = el.closest('.task');
      if (row) row.classList.add('glow');
    }
    toggleTask(el.dataset.id);
  },
  toggleSub: el => {
    const chip = el.closest('.chip') || el;   // a chip in the list, or the small diamond in the compact view
    chip.classList.toggle('on', el.checked);
    if (el.checked) chip.classList.add('pop');
    toggleSubTask(el.dataset.id, el.dataset.sub);
  },
  counterUp: el => changeCounter(el.dataset.id, 1),
  counterDown: el => changeCounter(el.dataset.id, -1),
  addTask,
  deleteTask: el => { if (confirmed(el, 'Delete?')) deleteTask(el.dataset.id); },
  editTask: el => { findTask(el.dataset.id)[el.dataset.field] = el.value; saveTasks(); },
  editTarget: el => { findTask(el.dataset.id).mx = Math.max(0, +el.value || 0); saveTasks(); },
  editSub: el => { findTask(el.dataset.id).sub.find(s => s.id === el.dataset.sub).t = el.value; saveTasks(); },
  deleteSub: el => { const t = findTask(el.dataset.id); t.sub = t.sub.filter(s => s.id !== el.dataset.sub); saveTasks(); render(); },
  addSub: el => {
    const title = el.value.trim();
    if (!title) return;
    findTask(el.dataset.id).sub.push({id: 's' + Date.now(), t: title, s: ''});
    saveTasks();
    render();
  },

  setWaveplate,
  setCrystal,
  setSubscriptionDays,
  renewSubscription,
  editValue: el => { editingValue = el.dataset.kind; render(); },
  toggleSubscriptionEditor: () => { editingSubscription = !editingSubscription; render(); },

  addBanner,
  editBanner: el => { editingBanner = el.dataset.id; render(); },
  saveBanner: el => saveBanner(el.dataset.id),
  cancelBanner: () => { editingBanner = null; render(); },
  deleteBanner: el => { if (confirmed(el, 'Delete?')) deleteBanner(el.dataset.id); },

  openPicker,
  closePicker,
  pickerMonth: el => pickerMonth(+el.dataset.step),
  pickerDay: el => pickerDay(+el.dataset.day),
  pickerToday,
  pickerOk,
  pickerTime: el => { el.value = pad2(Math.min(+el.dataset.max, +el.value || 0)); },
};

function runAction(el, name) {
  const action = ACTIONS[name];
  if (action) action(el);
}

document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (el) runAction(el, el.dataset.act);
});
document.addEventListener('change', e => {
  const el = e.target.closest('[data-change]');
  if (el) runAction(el, el.dataset.change);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && picker) {
    closePicker();
    return;
  }
  if (e.key === 'Escape' && editingValue) {
    cancelInlineEdit();
    return;
  }
  const typing = e.target.matches && e.target.matches('input:not([type=checkbox]),select,textarea');
  if (!typing && !e.ctrlKey && !e.altKey && !e.metaKey && ['1', '2', '3', '4'].includes(e.key)) {   // 1-4: tabs
    const wasMini = st.set.mini;
    openTab(Object.keys(CATEGORIES)[+e.key - 1]);
    if (wasMini) fit(true);
    return;
  }
  if (e.ctrlKey && !e.altKey && (e.key === 'n' || e.key === 'N')) {   // Ctrl+N: new task in the open list
    e.preventDefault();
    if (st.ui || st.set.mini || st.tab === 'b') {
      const wasMini = st.set.mini;
      openTab(st.tab === 'b' ? 'd' : st.tab);
      if (wasMini) fit(true);
    }
    const field = $('new-task');
    if (field) field.focus();
    return;
  }
  if (e.key !== 'Enter') return;
  const el = e.target.closest('[data-enter]');
  if (!el) return;
  e.preventDefault();
  runAction(el, el.dataset.enter);
});
document.addEventListener('input', e => {
  if (e.target.matches('[data-digits]')) e.target.value = e.target.value.replace(/[^0-9]/g, '');
});
document.addEventListener('toggle', e => {
  if (e.target.id === 'completed') showCompleted = e.target.open;
  fit();
}, true);

// The overlay window normally refuses keyboard focus; text fields need it while they are focused.
document.addEventListener('focusin', e => {
  if (st.set.top && e.target.matches('input[type=text],input:not([type])')) api('typing', 1);
});
document.addEventListener('focusout', e => {
  if (e.target.matches('.inline-edit') && editingValue && e.target.isConnected) runAction(e.target, e.target.dataset.enter);
  if (e.target.matches('input')) api('typing', 0);
});

// =============================================================== drag and drop (tasks and banners)

document.addEventListener('pointerdown', e => {
  if (e.button !== 0) return;
  if (e.target.closest('#titlebar') && !e.target.closest('button')) {
    api('start_drag');   // the window itself is moved by Python
    return;
  }
  const row = e.target.closest('[data-drag]');
  if (!row || e.target.closest('button,summary,select,input:not([type=checkbox])')) return;
  drag = {kind: row.dataset.drag, id: row.dataset.id, startY: e.clientY, active: false, row, before: null};
});

document.addEventListener('pointermove', e => {
  if (!drag) return;
  if (!drag.active) {
    if (Math.abs(e.clientY - drag.startY) < 6) return;   // a click, not a drag (yet)
    drag.active = true;
    drag.row.classList.add('lifted');
    document.body.classList.add('dragging-row');
  }
  drag.row.style.transform = `translateY(${e.clientY - drag.startY}px)`;
  const rows = [...document.querySelectorAll(`[data-drag="${drag.kind}"]`)].filter(r => r !== drag.row);
  rows.forEach(r => r.classList.remove('drop-before', 'drop-after'));
  drag.before = rows.find(r => { const box = r.getBoundingClientRect(); return e.clientY < box.top + box.height / 2; }) || null;
  if (drag.before) drag.before.classList.add('drop-before');
  else if (rows.length) rows[rows.length - 1].classList.add('drop-after');
});

function endDrag() {
  if (!drag) return;
  const d = drag;
  drag = null;
  document.body.classList.remove('dragging-row');
  document.querySelectorAll('.drop-before,.drop-after').forEach(r => r.classList.remove('drop-before', 'drop-after'));
  d.row.classList.remove('lifted');
  d.row.style.transform = '';
  if (!d.active) return;
  dragEndedAt = Date.now();
  const list = d.kind === 't' ? tasks : st.banners;
  const [moved] = list.splice(list.findIndex(x => x.id === d.id), 1);
  if (d.before) {
    list.splice(list.findIndex(x => x.id === d.before.dataset.id), 0, moved);
  } else {   // dropped below the last row: after the last item of the same category
    let last = -1;
    list.forEach((x, i) => { if (d.kind === 'b' || x.c === moved.c) last = i; });
    list.splice(last + 1, 0, moved);
  }
  if (d.kind === 't') saveTasks();
  else save();
  render();
}
document.addEventListener('pointerup', endDrag);
document.addEventListener('pointercancel', endDrag);
// The click that ends a drag must not also tick the checkbox under the cursor.
document.addEventListener('click', e => {
  if (Date.now() - dragEndedAt < 200) {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);

// =============================================================== loading, migrations, start

// Brings saved data from older versions up to date.
function migrate(hadTasks) {
  const from = st.defV || 1;
  if (hadTasks && from < DEFAULTS_VERSION) {
    const retired = ['nest_fg', 'nest_hc', 'nest_tw', 'nest_thc', 'nest_tv'];   // v5: nests became one group
    if (from < 4) retired.push('nests', 'wp', 'crystal', 'shop', 'wshop', 'mshop', 'mcard');
    tasks = tasks.filter(t => !retired.includes(t.id));
    for (const def of DEFAULT_TASKS) {   // add defaults introduced after the user's version
      if (def.v <= from || tasks.some(t => t.id === def.id)) continue;
      const at = tasks.map(t => t.c).lastIndexOf(def.c);
      tasks.splice(at < 0 ? tasks.length : at + 1, 0, clone(def));
    }
    for (const t of tasks) {   // refresh old default texts the user never changed
      const def = DEFAULT_TASKS.find(x => x.id === t.id);
      if (!def) continue;
      if (def.mx && t.mx == null) t.mx = def.mx;
      if (t.id === 'pod' && t.s === 'Reset on Monday') t.s = def.s;
      if (t.id === 'dream' && /resets every Monday/.test(t.s || '')) t.s = def.s;
    }
    saveTasks();
  }
  st.defV = DEFAULTS_VERSION;
  if (st.custom && st.custom.length) {   // before 1.0 custom tasks were kept in progress.json
    st.custom.forEach(x => tasks.push({c: x.c, id: x.id, t: x.t, s: ''}));
    saveTasks();
  }
  delete st.custom;
  st.banners = st.banners || [];
  if (!Array.isArray(st.fullDays)) {   // 1.3.0: rebuild this week's overview from the current streak
    st.fullDays = [];
    for (let i = 0; i < Math.min(st.streak || 0, 60); i++) st.fullDays.push(st.lastFull - i);
  }
  st.banners.forEach(b => { if (b.id === 'b1' && b.n === 'Hsin banner') b.n = 'Hsin'; });
}

function loadState(progressText, tasksText) {
  st = freshState();
  try {
    const saved = JSON.parse(progressText || '{}');
    if (saved && saved.done) Object.assign(st, saved);
  } catch (e) {
    api('log_js', 'progress could not be read: ' + e.message);
  }
  st.set = {...DEFAULT_SETTINGS, ...st.set};
  if (!progressText) st.ui = 1;   // first start: show the settings
  updateResetShift();
  let list = null;
  try { list = JSON.parse(tasksText || 'null'); } catch (e) { api('log_js', 'tasks could not be read: ' + e.message); }
  tasks = Array.isArray(list) ? list : DEFAULT_TASKS.map(clone);
  if (!Array.isArray(list)) saveTasks();
  migrate(Array.isArray(list));
}

// tasks.json was edited in a text editor while the app was running.
function reloadEditedTasks() {
  api('tasks_changed').then(text => {
    if (!text) return;
    try {
      const list = JSON.parse(text);
      if (!Array.isArray(list)) return;
      tasks = list;
      updateStreak();
      saveTasks();
      render();
    } catch (e) {
      // half-saved or invalid: try again on the next focus
    }
  });
}

function boot(progressText, tasksText) {
  if (booted) return;
  booted = true;
  $('app-icon').src = IMAGES.app;
  loadState(progressText, tasksText);
  save();
  render();
  setInterval(tick, 1000);
  setInterval(checkForUpdate, UPDATE_CHECK_EVERY);
  document.addEventListener('visibilitychange', () => tick());
  window.addEventListener('focus', () => { tick(); reloadEditedTasks(); });
  window.addEventListener('beforeunload', () => save());
  applyRuntimeSettings();
  checkForUpdate();
  api('take_notices').then(list => (list || []).forEach(text => showNotice(text, 'warn')));
  api('ready');
}

// Never start with empty data just because Python did not answer: that would overwrite the saved files.
function loadApp(attempt = 0) {
  Promise.all([api('load'), api('load_tasks')]).then(([progressText, tasksText]) => {
    if (progressText !== null && tasksText !== null) {
      boot(progressText, tasksText);
    } else if (attempt < 5) {
      setTimeout(() => loadApp(attempt + 1), 1000);
    } else {
      api('log_js', 'could not load the saved data');
    }
  });
}

if (window.pywebview && pywebview.api) loadApp();
else window.addEventListener('pywebviewready', () => loadApp());
</script></body></html>
"""

HTML = HTML_TEMPLATE.replace("__APP_VERSION__", APP_VERSION)

if __name__ == "__main__":
    main()
