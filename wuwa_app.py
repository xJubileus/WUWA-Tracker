import os, sys, ctypes, traceback, threading, time, subprocess
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

    def do_update(self, url, digest=""):
        try:
            if not str(url).startswith("https://github.com/xJubileus/WUWA-Tracker/releases/download/"):
                return "invalid address"
            import urllib.request, hashlib, tempfile
            path = os.path.join(tempfile.gettempdir(), "WUWA-Tracker-Update.exe")
            req = urllib.request.Request(url, headers={"User-Agent": "WUWA-Tracker"})
            sha = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as f:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
            if str(digest).startswith("sha256:") and sha.hexdigest() != str(digest)[7:].lower():
                os.remove(path)
                return "checksum mismatch"
            subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1"],
                             creationflags=0x00000008 | 0x08000000, close_fds=True)
            threading.Timer(1.5, lambda: os._exit(0)).start()
            return "ok"
        except Exception:
            log(traceback.format_exc())
            return "download error"

    def open_url(self, url):
        try:
            if str(url).startswith("https://github.com/xJubileus/WUWA-Tracker"):
                os.startfile(url)
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
            if getattr(sys, "frozen", False) or "__compiled__" in globals():
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

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>WUWA Tracker</title><style>
:root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px);--bg:#f4f5f8;--card:#fff;--tx:#1b1e27;--mu:#6b7285;--ac:#4f6bed;--bd:#e1e4ec;--ok:#2e9e6b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#12141b;--card:#1b1e29;--tx:#e8eaf2;--mu:#8b92a8;--ac:#7f95ff;--bd:#2b3042;--ok:#4cc790}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#12141b;--card:#1b1e29;--tx:#e8eaf2;--mu:#8b92a8;--ac:#7f95ff;--bd:#2b3042;--ok:#4cc790}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
*{box-sizing:border-box}
html,body{height:100%;background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--tx);font:13px/1.3 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow-y:auto;scrollbar-width:none;-ms-overflow-style:none}
body::-webkit-scrollbar,*::-webkit-scrollbar{display:none;width:0;height:0}
main{max-width:640px;margin:0 auto;padding:8px}
h1{font-size:15px;margin:0 0 6px}
.tabs{display:flex;gap:4px;margin-bottom:6px}
.tab{flex:1 1 auto;white-space:nowrap;padding:6px 2px;border:1px solid var(--bd);background:var(--card);color:var(--tx);border-radius:8px;font-size:13px;cursor:pointer}
.tab small{display:block;font-size:10px;opacity:.75;line-height:1.2;margin-top:1px}
.tab.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.info{display:flex;justify-content:space-between;font-size:12px;color:var(--mu);margin:4px 2px;font-variant-numeric:tabular-nums}
.bar{height:4px;background:var(--bd);border-radius:4px;overflow:hidden;margin-bottom:6px}
.bar i{display:block;height:100%;background:var(--ok);transition:width .3s}
.item{display:flex;gap:8px;align-items:center;background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:5px 8px;margin-bottom:4px;cursor:pointer}
.item input{width:16px;height:16px;margin:0;accent-color:var(--ok);flex:none}
.item b{display:block;font-weight:600;font-size:13px}
.item span{display:block;color:var(--mu);font-size:11px;line-height:1.25;margin-top:1px}
.item .x{margin-left:auto;background:none;border:0;color:var(--mu);font-size:14px;cursor:pointer;padding:0 2px}
.done{opacity:.6}
.done b{text-decoration:line-through}
details{margin-top:6px}
summary{color:var(--mu);cursor:pointer;font-size:12px;margin-bottom:4px}
.add{display:flex;gap:4px;margin-top:6px}
.add input{flex:1;min-width:0;padding:5px 8px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx);font-size:12px}
.add button{padding:5px 12px;border-radius:8px;border:0;background:var(--ac);color:#fff;cursor:pointer;font-size:14px}
.empty{text-align:center;padding:14px 4px;color:var(--ok);font-weight:600}

.tab{padding:4px 2px}.tab small{font-size:9px}.tab.g{flex:0 0 30px;font-size:14px}
.sp{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:6px 8px;margin-bottom:6px;font-size:12px;display:flex;flex-direction:column;gap:5px}
.sp label{display:flex;gap:6px;align-items:center}.sp .r{display:flex;gap:6px}
.sp button,.add button.s{padding:3px 8px;border-radius:6px;border:1px solid var(--bd);background:var(--card);color:var(--tx);cursor:pointer;font-size:12px}
input.n{width:42px;padding:2px 4px;border-radius:6px;border:1px solid var(--bd);background:var(--bg);color:var(--tx);font-size:12px}
.wp{display:flex;gap:4px;align-items:center;font-size:12px;margin-bottom:6px;font-variant-numeric:tabular-nums}.wp span{flex:1}
.wp input{width:52px}.wp button{padding:3px 8px;border-radius:6px;border:0;background:var(--ac);color:#fff;cursor:pointer;font-size:12px}
.bn{align-items:stretch}.bn>div{flex:1}.bt{display:flex;justify-content:space-between;gap:6px}.mu{color:var(--mu);font-size:11px}
.bc{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums;margin:2px 0}.bn .bar{margin:3px 0 0;height:4px}.end{opacity:.5}
.ed{flex-direction:column;align-items:stretch;gap:3px;cursor:default}.item.ed input{width:100%;height:auto;padding:3px 6px;border-radius:6px;border:1px solid var(--bd);background:var(--bg);color:var(--tx);font-size:12px;min-width:0}
.ed .x{align-self:flex-end}.add.wrap{display:grid;grid-template-columns:1fr 1fr;gap:6px}.add.wrap label{font-size:11px;color:var(--mu);display:flex;flex-direction:column;gap:2px;min-width:0}.add.wrap input{width:100%;height:30px;min-width:0;padding:4px 8px;font-size:12px}.add.wrap button{height:30px;align-self:end;width:100%}.tl{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 2px;max-width:150px}.tabs.nat .tab:not(.g){flex:0 0 auto}.tab{padding-left:6px;padding-right:6px}.ic{width:16px;height:16px;flex:none}

.item{user-select:none;-webkit-user-select:none}.item[data-dg="b"]{cursor:grab}
.dragging{opacity:.92;position:relative;z-index:5;pointer-events:none;box-shadow:0 6px 16px rgba(0,0,0,.35)}
.ovt{box-shadow:0 -3px 0 0 var(--ac)}.ovb{box-shadow:0 3px 0 0 var(--ac)}body.dnd{cursor:grabbing;user-select:none}
.bn>div:first-child{flex:1}.bn>div:last-child.bb{flex:none}.bb{display:flex;gap:2px;align-items:flex-start}.bb .x{margin-left:0!important}
.item.bed{display:block;cursor:default}.add.wrap button.c{background:var(--card);color:var(--tx);border:1px solid var(--bd)}
.dt{cursor:pointer}main.dpo{min-height:340px}
.dpb{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:20;padding:8px}
.dpc{background:var(--card);border:1px solid var(--bd);border-radius:16px;padding:12px;width:100%;max-width:300px;box-shadow:0 12px 32px rgba(0,0,0,.45)}
.dph{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;font-weight:600;font-size:13px}
.dph button{width:28px;height:28px;border-radius:50%;border:1px solid var(--bd);background:var(--bg);color:var(--tx);cursor:pointer;font-size:15px;line-height:1}
.dpw,.dpg{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center}.dpw span{font-size:10px;color:var(--mu);padding-bottom:2px}
.dpg button{height:28px;border:0;border-radius:9px;background:none;color:var(--tx);cursor:pointer;font-size:12px}
.dpg button:hover{background:var(--bg)}.dpg button.sel{background:var(--ac);color:#fff}.dpg button.td{outline:1px solid var(--ac)}
.dpt{display:flex;align-items:center;gap:4px;margin-top:10px;font-size:12px}.dpt .sp2{flex:1}
.dpt input{width:34px;text-align:center;padding:5px 2px;border-radius:9px;border:1px solid var(--bd);background:var(--bg);color:var(--tx);font-size:12px}
.dpt button{padding:5px 11px;border-radius:9px;border:1px solid var(--bd);background:var(--bg);color:var(--tx);cursor:pointer;font-size:12px}.dpt button.ok{background:var(--ac);color:#fff;border-color:var(--ac)}
#tb{display:flex;align-items:center;gap:6px;height:28px;margin:-8px -8px 6px;padding:0 4px 0 8px;border-bottom:1px solid var(--bd);background:var(--card);font-size:12px;user-select:none;-webkit-user-select:none}
body{border:1px solid var(--bd)}
#tb img{width:16px;height:16px;border-radius:3px}#tb .t{flex:1;font-weight:600}
#tb button{width:34px;height:22px;border:0;border-radius:6px;background:none;color:var(--tx);cursor:pointer;font-size:13px;line-height:1}
#tb button:hover{background:var(--bg)}#tb .cl:hover{background:#d9434f;color:#fff}
.ctn{flex:none;min-width:34px;text-align:center;font-weight:700;font-size:12px;background:var(--bg);border:1px solid var(--bd);border-radius:8px;padding:3px 6px;font-variant-numeric:tabular-nums}
.upd{background:var(--ac);color:#fff;border-radius:8px;padding:5px 8px;margin-bottom:6px;font-size:12px;cursor:pointer}
.sp select{background:var(--bg);color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:2px 4px;font-size:12px}
.mcr{flex-wrap:wrap}.mcr span{flex:1 1 100%}.mcr input.dt{width:100px;height:24px;padding:2px 6px;font-size:11px}.mcr .x{margin-left:auto;font-size:12px}.warn{color:#e5a33d}.bad{color:#e05555}
</style></head><body><main>
<div id="tb" onpointerdown="tbDown(event)"><img id="tbi" alt=""><span class="t">WUWA Tracker</span><button onclick="api('minimize')">&#8211;</button><button class="cl" onclick="api('close')">&#10005;</button></div>
<div id="upd"></div><div class="tabs" id="tabs"></div><div id="set"></div>
<div class="info"><span id="cd"></span><span id="cnt"></span></div>
<div class="bar" id="bar"><i id="pb" style="width:0"></i></div>
<div id="wp"></div><div id="list"></div><div class="add" id="add"></div><div id="dp"></div>
</main><script>
const $=i=>document.getElementById(i);
const CATS={d:['Daily','every day'],w:['Weekly','every Monday'],m:['Monthly','1st of month'],b:['Banners','limited']};
const DEF=[
['d','daily','Daily Activity (Guidebook)','Complete daily tasks, reach 100 activity and claim the Astrite'],
['d','podcast','Pioneer Podcast daily tasks','Battle pass XP, claim the rewards'],
['d','resp','Open-world gathering / Echo farming','Reset respawns materials and enemies'],
['d','nest_fg','Nightmare Nest: Fallen Grave','Dream of the Lost · Havoc Warrior, Glacio Predator, Tambourinist · up to 36 per day, no Waveplate',4],
['d','nest_hc','Nightmare Nest: Honami City','Thread of Severed Fate · Tick Tack, Dwarf Cassowary, Roseshroom · up to 36 per day, no Waveplate',4],
['d','nest_tw','Nightmare Nest: The Wastelands','Crown of Valor · Electro Predator, Aero Predator, Violet-Feathered Heron · up to 36 per day, no Waveplate',4],
['d','nest_thc',"Nightmare Nest: Three Heroes' Crest","Flamewing's Shadow · Baby Roseshroom, Baby Viridblaze Saurian, Viridblaze Saurian · up to 36 per day, no Waveplate",4],
['d','nest_tv','Nightmare Nest: Tideline Verge','Law of Harmony · Gulpuff, Chirpuff, Cyan-Feathered Heron · up to 36 per day, no Waveplate',4],
['w','boss','3 Weekly Challenge boss rewards','3 rewards per week, 60 Waveplates each: Forte materials and Echoes',1,3],
['w','pod','Pioneer Podcast weekly tasks','Reset on Monday'],
['w','ww','Whimpering Wastes','Weekly reset, challenges give Astrite (check current status after each patch)'],
['w','toa','Tower of Adversity: Stable/Experimental Zone','Uses Vigor, crests = Astrite. Check the current cycle'],
['w','echo','Use boosted Echo drop chances','Weekly allowance, see how many are left in the Data Bank'],
['w','holo','Tactical Hologram challenges','If there is a new or uncleared stage'],
['w','dream','Fantasies of the Thousand Gateways','Dreamscape Mode: recurring 13-stage combat challenge, resets every Monday',2],
['m','hazard','Tower of Adversity: Hazard Zone','Cycle may change (14 days or 1 month), check the current dates'],
['m','events','Version events and battle pass season','Check which event or BP level ends soon']
].map(x=>({c:x[0],id:x[1],t:x[2],s:x[3],v:x[4]||1,mx:x[5]||0}));
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const SRV={EU:['Europe',1],AM:['America',-5],AS:['Asia',8],SEA:['SEA',8],HMT:['HMT',8]},SD={top:0,auto:0,rem:1,remH:3,edit:0,op:55,srv:'EU',wpn:1,wpm:15,upd:1},VER='1.2.0';
let SO=3*36e5,UPD=null;const OFF=()=>SRV[st.set.srv||'EU'][1],UT=()=>'UTC'+(OFF()<0?'':'+')+OFF(),setSO=()=>{SO=(4-OFF())*36e5},cmp=(a,b)=>{const x=a.split('.').map(Number),y=b.split('.').map(Number);for(let i=0;i<3;i++)if((x[i]||0)!==(y[i]||0))return(x[i]||0)-(y[i]||0);return 0};
const ICON='data:image/png;base64,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';
function tbDown(e){if(e.target.closest('button'))return;api('start_drag')}
const CRI='data:image/png;base64,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';
const WPI='data:image/png;base64,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';
let st={done:{},tab:'d',set:{...SD},cnt:{},mc:null,mcN:-1,wp:null,streak:0,lastFull:-1,prev:null,remDay:-1,banners:null,ui:0},tasks=[],cur={},nxStr='';
const api=(f,...a)=>{try{return Promise.resolve(pywebview.api[f](...a)).catch(()=>null)}catch(e){return Promise.resolve(null)}};
const save=()=>api('save',JSON.stringify(st));
const saveT=()=>api('save_tasks',JSON.stringify(tasks));
function keys(){const sh=Date.now()-SO,dk=Math.floor(sh/864e5),sd=new Date(sh),wk=Math.floor((dk+3)/7);
 return{d:dk,w:wk,m:sd.getUTCFullYear()*12+sd.getUTCMonth(),next:{d:(dk+1)*864e5+SO,w:((wk+1)*7-3)*864e5+SO,m:Date.UTC(sd.getUTCFullYear(),sd.getUTCMonth()+1,1)+SO}}}
const p2=n=>String(n).padStart(2,'0');
function fmt(ms){let s=Math.max(0,Math.floor(ms/1000)),d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return(d?d+'d ':'')+h+'h '+p2(m)+'m '+p2(s%60)+'s'}
const loc=t=>new Date(t).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
function wpNow(){if(!st.wp)return null;const n=Date.now(),e=n-st.wp.ts,v=st.wp.v,c0=st.wp.c||0,full=v>=240?st.wp.ts:st.wp.ts+(240-v)*36e4,c=Math.min(480,c0+Math.max(0,Math.floor((n-full)/72e4)));return{v:v>=240?v:Math.min(240,v+Math.floor(e/36e4)),left:Math.max(0,full-n),c,cleft:c>=480?0:Math.max(0,full+(480-c0)*72e4-n)}}
function wpText(){const w=wpNow();if(!w)return'Waveplate: type your current value →';let t=w.v+'/240 · '+(w.left?'full in '+fmt(w.left):'FULL, regen is wasted!');
 if(w.left){const r=keys().next.d-Date.now(),over=w.v+r/36e4-240;if(over>0)t+=' · spend ≥'+Math.ceil(over)+' before reset'}return t}
function updClick(){if(!UPD||UPD.busy)return;if(!UPD.a){api('open_url',UPD.u);return}UPD.busy=1;UPD.msg='Downloading update… the app will restart';render();api('do_update',UPD.a,UPD.d).then(r=>{if(r!=='ok'){UPD.busy=0;UPD.a='';UPD.msg='Update failed ('+esc(r)+'), click to open the download page';render()}})}
function crText(){const w=wpNow();if(!w)return'Waveplate Crystal: type your current value →';return w.c+'/480 · '+(w.c>=480?'FULL, overflow is wasted!':(w.left?'starts when Waveplate is full · ':'')+'full in '+fmt(w.cleft))}
const mcLeft=()=>st.mc?st.mc.end-Date.now():null;
function mcText(){const l=mcLeft();if(l===null)return'Lunite Subscription: not set, enter days left or the purchase date';if(l<=0)return'Lunite Subscription: expired, renew?';return'Lunite Subscription: '+Math.floor(l/864e5)+'d '+p2(Math.floor(l%864e5/36e5))+'h left (ends '+loc(st.mc.end)+')'}
function mcUpd(){const l=mcLeft(),e=$('mct');e.textContent=mcText();e.className=l!==null&&l<=0?'bad':l!==null&&l<=3*864e5?'warn':''}
function tick(f){const k=keys();if(!f&&(k.d!==cur.d||k.w!==cur.w||k.m!==cur.m)){render();return}
 if(st.tab==='b')document.querySelectorAll('.bn').forEach(el=>{const c=el.querySelector('.bc'),s=+c.dataset.s,e=+c.dataset.e,n=Date.now();c.textContent=n<s?'starts in '+fmt(s-n):n>=e?'Ended':fmt(e-n);el.querySelector('i').style.width=Math.max(0,Math.min(100,(n-s)/(e-s)*100))+'%'});
 else{$('cd').textContent='Resets in '+fmt(k.next[st.tab]-Date.now())+' ('+nxStr+')';if($('wpt'))$('wpt').textContent=wpText();if($('crt'))$('crt').textContent=crText();if($('mct'))mcUpd()}
 {const l=mcLeft();if(st.set.rem&&l!==null&&l>0&&l<=3*864e5&&st.mcN!==k.d){st.mcN=k.d;save();api('notify','WUWA Tracker','Lunite Subscription ends in '+Math.ceil(l/864e5)+' day(s)')}}
 {const w=wpNow();if(st.set.wpn&&w&&w.left>0&&w.left<=st.set.wpm*6e4&&st.wpFor!==st.wp.ts){st.wpFor=st.wp.ts;save();api('notify','WUWA Tracker','Waveplate full in '+Math.ceil(w.left/6e4)+' min ('+w.v+'/240)')}}
 if(st.set.rem&&st.remDay!==k.d&&k.next.d-Date.now()<=st.set.remH*36e5){const n=tasks.filter(t=>t.c==='d'&&!isDn(t)).length;if(n){st.remDay=k.d;save();api('notify','WUWA Tracker',n+' daily task(s) left. Reset in '+fmt(k.next.d-Date.now()))}}}
const cv=t=>{const o=st.cnt[t.id];return o&&o.k===keys()[t.c]?o.v:0},isDn=t=>t.mx>0?cv(t)>=t.mx:st.done[t.id]===keys()[t.c];
function inc(id,d){const t=tasks.find(x=>x.id===id);st.cnt[id]={k:keys()[t.c],v:Math.max(0,Math.min(t.mx,cv(t)+d))};chk();save();render()}
function chk(){const k=keys(),ds=tasks.filter(t=>t.c==='d');if(!ds.length)return;const full=ds.every(isDn);
 if(full&&st.lastFull!==k.d){st.prev={s:st.streak||0,l:st.lastFull};st.streak=(st.lastFull===k.d-1?st.streak:0)+1;st.lastFull=k.d}
 else if(!full&&st.lastFull===k.d&&st.prev){st.streak=st.prev.s;st.lastFull=st.prev.l;st.prev=null}}
function settings(){const s=st.set,ck=(k,l)=>`<label><input type="checkbox" ${s[k]?'checked':''} onchange="sw('${k}',this.checked)"> ${l}</label>`,
 nu=(k,lo,hi,d)=>`<input class="n" type="text" inputmode="numeric" maxlength="3" value="${s[k]}" oninput="this.value=this.value.replace(/[^0-9]/g,'')" onchange="sw('${k}',Math.min(${hi},Math.max(${lo},+this.value||${d})))">`;
 return'<div class="sp">'+`<label>Server <select onchange="sw('srv',this.value)">${Object.keys(SRV).map(k=>`<option value="${k}" ${(s.srv||'EU')===k?'selected':''}>${SRV[k][0]} (UTC${SRV[k][1]<0?'':'+'}${SRV[k][1]})</option>`).join('')}</select></label>`+
 ck('top','Always on top <span class="mu">(see-through; hold ALT to use it)</span>')+(s.top?`<label>Opacity ${nu('op',20,100,55)} %</label>`:'')+ck('auto','Start with Windows')+
 `<label><input type="checkbox" ${s.rem?'checked':''} onchange="sw('rem',this.checked)"> Task reminder ${nu('remH',1,23,3)} h before reset</label>`+
 `<label><input type="checkbox" ${s.wpn?'checked':''} onchange="sw('wpn',this.checked)"> Waveplate alert ${nu('wpm',5,60,15)} min before full</label>`+ck('upd','Check for updates (GitHub)')+ck('edit','Edit tasks')+
 (s.edit?`<div class="r"><button onclick="defs()">Restore defaults</button><button onclick="api('open_tasks')">Open tasks file</button></div>`:'')+`<span class="mu">v${VER}</span></div>`}
function sw(k,v){st.set[k]=typeof v==='boolean'?(v?1:0):v;if(k==='top'||k==='op')api('set_on_top',st.set.top,st.set.op||55);if(k==='rem')st.remDay=-1;if(k==='srv'){setSO();st.done={};st.cnt={}}
 if(k==='auto')api('set_autostart',st.set.auto).then(r=>{if(r!==null){st.set.auto=r?1:0;save();render()}});
 save();render()}
const bsort=()=>(st.banners||[]).slice().sort((a,b)=>(a.e<Date.now())-(b.e<Date.now()));
let beid=null;
function render(){const k=keys(),c=st.tab,B=c==='b',ed=st.set.edit;cur=k;
 $('tabs').innerHTML=Object.keys(CATS).map(x=>`<button class="tab ${x==c?'on':''}" onclick="st.tab='${x}';save();render()"><span class="tl">${x==='b'&&bsort().length?esc(bsort()[0].n):CATS[x][0]}</span><small>${CATS[x][1]}</small></button>`).join('')+'<button class="tab g '+(st.ui?'on':'')+'" onclick="st.ui=st.ui?0:1;render()">⚙</button>';
 $('set').innerHTML=st.ui?settings():'';
 $('upd').innerHTML=UPD?`<div class="upd" onclick="updClick()">${UPD.msg||'Update '+esc(UPD.v)+' available – click to install'}</div>`:'';
 $('bar').style.display=B?'none':'';
 if(B){$('cd').textContent='Times are server time ('+UT()+'), shown in your local time';$('cnt').textContent='';$('wp').innerHTML='';
  const bs=bsort();
  $('list').innerHTML=bs.map(b=>b.id===beid?`<div class="item bed"><div class="add wrap" style="margin:0"><label>Banner name<input id="en" value="${esc(b.n)}"></label><label>Start (server)${dtf('es',tv(b.s))}</label><label>End (server)${dtf('ee',tv(b.e))}</label><div style="display:flex;gap:6px;align-self:end"><button onclick="saveB('${b.id}')">Save</button><button class="c" onclick="beid=null;render()">Cancel</button></div></div></div>`:`<div class="item bn ${b.e<Date.now()?'end':''}" data-dg="b" data-id="${b.id}" onpointerdown="dstart(event,'b','${b.id}')"><div><div class="bt"><b>${esc(b.n)}</b><span class="mu">ends ${loc(b.e)}</span></div><div class="bc" data-s="${b.s}" data-e="${b.e}"></div><div class="bar"><i></i></div></div><div class="bb"><button class="x" onclick="beid='${b.id}';render()">✎</button><button class="x" onclick="delB('${b.id}')">✕</button></div></div>`).join('')||'<div class="empty">No banners yet</div>';
  $('add').className='add wrap';$('add').innerHTML=`<label>Banner name<input id="bn" placeholder="e.g. Hsin"></label><label>Start (server)${dtf('bs','')}</label><label>End (server)${dtf('be','')}</label><button onclick="addB()">+</button>`;tick(true);return}
 const all=tasks.filter(t=>t.c==c),isD=isDn,todo=all.filter(x=>!isD(x)),dn=all.filter(isD);
 nxStr=loc(k.next[c]);const sv=st.lastFull>=k.d-1?st.streak:0;
 $('cnt').textContent=(c==='d'&&sv?'🔥'+sv+' · ':'')+dn.length+' / '+all.length+' done';
 $('pb').style.width=(all.length?dn.length/all.length*100:0)+'%';
 $('wp').innerHTML=c==='d'?wpRows():c==='m'?mcRow():'';
 const da=(i,d)=>d?'':`data-dg="t" data-id="${i.id}" onpointerdown="dstart(event,'t','${i.id}')"`,body=i=>`<div><b>${esc(i.t)}</b><span>${esc(i.s)}</span></div>`,
 row=(i,d)=>i.mx>0?`<div class="item ${d?'done':''}" ${da(i,d)} title="${esc(i.s)}" onclick="inc('${i.id}',1)" style="cursor:pointer"><span class="ctn">${cv(i)}/${i.mx}</span>${body(i)}<button class="x" onclick="event.stopPropagation();inc('${i.id}',-1)">−</button></div>`:`<label class="item ${d?'done':''}" ${da(i,d)} title="${esc(i.s)}"><input type="checkbox" ${d?'checked':''} onchange="tg('${i.id}')">${body(i)}</label>`;
 const erow=i=>`<div class="item ed"><input value="${esc(i.t)}" onchange="ed('${i.id}','t',this.value)"><input value="${esc(i.s||'')}" placeholder="description" onchange="ed('${i.id}','s',this.value)"><div style="display:flex;gap:6px;align-items:center;justify-content:space-between"><span class="mu">Counter target (0 = checkbox)</span><input class="n" value="${i.mx||0}" onchange="ed('${i.id}','mx',Math.max(0,+this.value.replace(/[^0-9]/g,'')||0))"><button class="x" onclick="del('${i.id}')">✕ delete</button></div></div>`;
 $('list').innerHTML=ed?all.map(erow).join(''):(todo.length?todo.map(i=>row(i,0)).join(''):'<div class="empty">🎉 All done, ready for the reset!</div>')+(dn.length?`<details><summary>Completed (${dn.length}) – open to undo</summary>${dn.map(i=>row(i,1)).join('')}</details>`:'');
 $('add').className='add';$('add').innerHTML='<input id="ni" placeholder="Add task…" onkeydown="if(event.key===\'Enter\')add()"><button onclick="add()">+</button>';tick(true)}
function tg(id){const t=tasks.find(x=>x.id===id),k=keys()[t.c];st.done[id]=st.done[id]===k?null:k;chk();save();setTimeout(render,250)}
function ed(id,f,v){tasks.find(x=>x.id===id)[f]=v;saveT()}
function del(id){tasks=tasks.filter(x=>x.id!==id);saveT();chk();save();render()}
function defs(){tasks=DEF.map(x=>({...x}));saveT();render()}
function add(){const v=$('ni').value.trim();if(!v)return;tasks.push({c:st.tab,id:'c'+Date.now(),t:v,s:''});saveT();render()}
const ni=(id,mx,fn)=>`<input class="n" id="${id}" type="text" inputmode="numeric" maxlength="${mx}" placeholder="now" oninput="this.value=this.value.replace(/[^0-9]/g,'')" onkeydown="if(event.key==='Enter')${fn}()">`,
 wpRows=()=>`<div class="wp"><img class="ic" src="${WPI}"><span id="wpt"></span>${ni('wpi',3,'setWp')}</div><div class="wp"><img class="ic" src="${CRI}"><span id="crt"></span>${ni('cri',3,'setCr')}</div>`,
 mcRow=()=>`<div class="wp mcr"><span id="mct"></span>${ni('mcd',2,'setMc').replace('placeholder="now"','placeholder="days left"')}<input class="dt" id="mcb" readonly placeholder="bought on" data-cb="mcDate" onclick="dpOpen('mcb')"><button class="x" title="Renewed: add 30 days" onclick="mcPlus()">+30d</button></div>`;
function setWp(){const v=parseInt($('wpi').value);if(isNaN(v)||v<0)return;const w=wpNow();st.wp={v,ts:Date.now(),c:w?w.c:0};save();render()}
function setCr(){const v=parseInt($('cri').value);if(isNaN(v)||v<0)return;const w=wpNow();st.wp={v:w?w.v:240,ts:Date.now(),c:Math.min(480,v)};save();render()}
function setMc(){const d=parseInt($('mcd').value);if(isNaN(d)||d<0)return;st.mc={end:keys().next.d+(d-1)*864e5};save();render()}
function mcDate(v){const ms=pd(v);if(!ms)return;st.mc={end:ms+30*864e5};save();render()}
function mcPlus(){st.mc={end:Math.max(st.mc?st.mc.end:0,Date.now())+30*864e5};save();render()}
const pd=v=>{if(!v)return null;const[d,t]=v.split('T'),[y,m,dd]=d.split('-').map(Number),[h,mi]=t.split(':').map(Number);return Date.UTC(y,m-1,dd,h-OFF(),mi)};
const tv=ms=>new Date(ms+OFF()*36e5).toISOString().slice(0,16);
const fv=v=>v.slice(8,10)+'/'+v.slice(5,7)+'/'+v.slice(0,4)+' '+v.slice(11,16);
const dtf=(id,v)=>`<input class="dt" id="${id}" readonly placeholder="dd/mm/yyyy --:--" data-v="${v||''}" value="${v?fv(v):''}" onclick="dpOpen('${id}')">`;
function addB(){const n=$('bn').value.trim(),e=pd($('be').dataset.v);if(!n||!e)return;st.banners.push({id:'b'+Date.now(),n,s:pd($('bs').dataset.v)||Date.now(),e});save();render()}
function saveB(id){const n=$('en').value.trim(),e=pd($('ee').dataset.v);if(!n||!e)return;const b=st.banners.find(x=>x.id===id);b.n=n;b.e=e;b.s=pd($('es').dataset.v)||b.s;beid=null;save();render()}
function delB(id){st.banners=st.banners.filter(b=>b.id!==id);save();render()}
let dp=null;const MN=['January','February','March','April','May','June','July','August','September','October','November','December'];
function dpOpen(id){const v=$(id).dataset.v,n=new Date(Date.now()+OFF()*36e5);let y=n.getUTCFullYear(),m=n.getUTCMonth(),d=n.getUTCDate(),h=n.getUTCHours(),mi=n.getUTCMinutes();
 if(v){y=+v.slice(0,4);m=+v.slice(5,7)-1;d=+v.slice(8,10);h=+v.slice(11,13);mi=+v.slice(14,16)}
 dp={id,vy:y,vm:m,sy:y,sm:m,sd:d,h,mi};dpR()}
function dpR(){const o=$('dp'),mn=document.querySelector('main');if(!dp){o.innerHTML='';mn.classList.remove('dpo');fit();return}
 mn.classList.add('dpo');const f=(new Date(dp.vy,dp.vm,1).getDay()+6)%7,dim=new Date(dp.vy,dp.vm+1,0).getDate(),tn=new Date(Date.now()+OFF()*36e5);let g='';
 for(let i=0;i<f;i++)g+='<span></span>';
 for(let d=1;d<=dim;d++){const sel=dp.sy===dp.vy&&dp.sm===dp.vm&&dp.sd===d,td=tn.getUTCFullYear()===dp.vy&&tn.getUTCMonth()===dp.vm&&tn.getUTCDate()===d;g+=`<button class="${sel?'sel':''} ${td?'td':''}" onclick="dpD(${d})">${d}</button>`}
 const ti=(id,val,mx)=>`<input id="${id}" value="${p2(val)}" maxlength="2" inputmode="numeric" oninput="this.value=this.value.replace(/[^0-9]/g,'')" onchange="this.value=p2(Math.min(${mx},+this.value||0))">`;
 o.innerHTML=`<div class="dpb" onclick="dp=null;dpR()"><div class="dpc" onclick="event.stopPropagation()"><div class="dph"><button onclick="dpM(-1)">‹</button><span>${MN[dp.vm]} ${dp.vy}</span><button onclick="dpM(1)">›</button></div><div class="dpw">${['Mo','Tu','We','Th','Fr','Sa','Su'].map(x=>'<span>'+x+'</span>').join('')}</div><div class="dpg">${g}</div><div class="dpt">${ti('dh',dp.h,23)}:${ti('dm',dp.mi,59)}<span class="sp2"></span><button onclick="dpT()">Today</button><button class="ok" onclick="dpOK()">OK</button></div></div></div>`;fit()}
function dpTime(){dp.h=Math.min(23,+$('dh').value||0);dp.mi=Math.min(59,+$('dm').value||0)}
function dpM(n){dpTime();dp.vm+=n;if(dp.vm<0){dp.vm=11;dp.vy--}if(dp.vm>11){dp.vm=0;dp.vy++}dpR()}
function dpD(d){dpTime();dp.sy=dp.vy;dp.sm=dp.vm;dp.sd=d;dpR()}
function dpT(){const n=new Date(Date.now()+OFF()*36e5);dp.vy=dp.sy=n.getUTCFullYear();dp.vm=dp.sm=n.getUTCMonth();dp.sd=n.getUTCDate();dp.h=n.getUTCHours();dp.mi=n.getUTCMinutes();dpR()}
function dpOK(){dpTime();const v=`${dp.sy}-${p2(dp.sm+1)}-${p2(dp.sd)}T${p2(dp.h)}:${p2(dp.mi)}`,el=$(dp.id);if(el){el.dataset.v=v;el.value=fv(v)}dp=null;dpR();if(el&&el.dataset.cb&&window[el.dataset.cb])window[el.dataset.cb](v)}
let dg=null,dgT=0;
function dstart(e,k,id){if(e.button!==0||e.target.closest('button,summary,input:not([type=checkbox])'))return;dg={k,id,y:e.clientY,on:0,el:e.currentTarget,t:null}}
document.addEventListener('pointermove',e=>{if(!dg)return;
 if(!dg.on){if(Math.abs(e.clientY-dg.y)<6)return;dg.on=1;dg.el.classList.add('dragging');document.body.classList.add('dnd')}
 dg.el.style.transform='translateY('+(e.clientY-dg.y)+'px)';
 const rows=[...document.querySelectorAll('[data-dg="'+dg.k+'"]')].filter(x=>x!==dg.el);rows.forEach(x=>x.classList.remove('ovt','ovb'));
 dg.t=rows.find(r=>{const b=r.getBoundingClientRect();return e.clientY<b.top+b.height/2})||null;
 if(dg.t)dg.t.classList.add('ovt');else if(rows.length)rows[rows.length-1].classList.add('ovb')});
function dend(){if(!dg)return;const d=dg;dg=null;document.body.classList.remove('dnd');document.querySelectorAll('.ovt,.ovb').forEach(x=>x.classList.remove('ovt','ovb'));
 d.el.classList.remove('dragging');d.el.style.transform='';if(!d.on)return;dgT=Date.now();
 const arr=d.k==='t'?tasks:st.banners,i=arr.findIndex(x=>x.id===d.id),it=arr.splice(i,1)[0];
 if(d.t){arr.splice(arr.findIndex(x=>x.id===d.t.dataset.id),0,it)}else{let j=-1;arr.forEach((x,n)=>{if(d.k==='b'||x.c===it.c)j=n});arr.splice(j+1,0,it)}
 if(d.k==='t')saveT();else save();render()}
document.addEventListener('pointerup',dend);document.addEventListener('pointercancel',dend);
document.addEventListener('click',e=>{if(Date.now()-dgT<200){e.preventDefault();e.stopPropagation()}},true);
let fitT=0;function fit(){clearTimeout(fitT);fitT=setTimeout(()=>{try{if(pywebview.api.fit){const m=document.querySelector('main'),t=$('tabs');t.classList.add('nat');let nw=2+16+4*(t.children.length-1);[...t.children].forEach(c=>nw+=c.getBoundingClientRect().width);t.classList.remove('nat');const q=pywebview.api.fit(Math.ceil(m.getBoundingClientRect().height)+2,window.innerHeight,Math.ceil(nw),window.innerWidth);if(q&&q.catch)q.catch(()=>{})}}catch(e){}},60)}
const _render=render;render=function(){_render();fit()};document.addEventListener('toggle',fit,true);
let booted=0;
function boot(a,b){if(booted)return;booted=1;
 try{const o=JSON.parse(a||'{}');if(o.done)st=Object.assign(st,o);st.set=Object.assign({},SD,st.set)}catch(e){}
 if(!a)st.ui=1;setSO();
 try{const t=JSON.parse(b||'null');if(Array.isArray(t))tasks=t}catch(e){}
 if(!b){tasks=DEF.map(x=>({...x}));saveT()}
 {const dv=st.defV||1;if(b&&dv<4){tasks=tasks.filter(t=>!['nests','wp','crystal','shop','wshop','mshop','mcard'].includes(t.id));DEF.filter(x=>x.v>dv&&!tasks.some(t=>t.id===x.id)).forEach(x=>{const ix=tasks.map(t=>t.c).lastIndexOf(x.c);tasks.splice(ix<0?tasks.length:ix+1,0,{...x})});tasks.forEach(t=>{const d=DEF.find(x=>x.id===t.id);if(d&&d.mx&&t.mx==null)t.mx=d.mx});saveT()}st.defV=4}
 if(st.custom&&st.custom.length){st.custom.forEach(x=>tasks.push({c:x.c,id:x.id,t:x.t,s:''}));delete st.custom;saveT()}
 (st.banners||[]).forEach(b=>{if(b.id==='b1'&&b.n==='Hsin banner')b.n='Hsin'});
 if(!st.banners){st.banners=[{id:'b1',n:'Hsin',s:Date.UTC(2026,8,30,3,0),e:Date.UTC(2026,9,22,8,59)}]}
 save();render();setInterval(tick,1000);
 document.addEventListener('visibilitychange',()=>tick());window.addEventListener('focus',()=>tick());window.addEventListener('beforeunload',()=>save());
 {document.addEventListener('focusin',e=>{if(st.set.top&&e.target.matches&&e.target.matches('input[type=text],input:not([type])'))api('typing',1)});document.addEventListener('focusout',e=>{if(e.target.matches&&e.target.matches('input'))api('typing',0)});$('tbi').src=ICON;if(st.set.upd)fetch('https://api.github.com/repos/xJubileus/WUWA-Tracker/releases/latest').then(x=>x.json()).then(j=>{const v=String(j.tag_name||'').replace(/^v/,'');if(v&&cmp(v,VER)>0){const as=(j.assets||[]).find(x=>/Setup\.exe$/i.test(x.name||''));UPD={v,u:String(j.html_url),a:as?String(as.browser_download_url):'',d:as?String(as.digest||''):''};render()}}).catch(()=>{});if(st.set.top)api('set_on_top',1,st.set.op||55);api('get_autostart').then(v=>{if(v!==null&&(v?1:0)!==st.set.auto){st.set.auto=v?1:0;save();render()}});}}
const loadApp=()=>Promise.all([pywebview.api.load(),pywebview.api.load_tasks()]).then(r=>boot(r[0]==='{}'?'':r[0],r[1])).catch(()=>boot('',''));
window.pywebview&&pywebview.api?loadApp():window.addEventListener('pywebviewready',loadApp);
</script></body></html>
"""

if __name__ == "__main__":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WuWaTracker.App")
    except Exception:
        pass
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    os.makedirs(DATA_DIR, exist_ok=True)
    icon = os.path.join(base_dir(), "wuwa.ico")
    WINDOW = webview.create_window(TITLE, html=HTML, js_api=Api(), width=360, height=640,
                                   min_size=(300, 150), background_color=bg_color(),
                                   frameless=True, easy_drag=False)
    WINDOW.events.shown += set_icon
    webview.start(icon=icon, private_mode=False, storage_path=os.path.join(DATA_DIR, "webview"))
