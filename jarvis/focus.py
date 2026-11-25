"""Game mode and break nudges.

- Game mode: while a full-screen game or a video call (Zoom, Teams, Meet in a browser tab...) has the screen, or
  after "game mode on" / "do not disturb", Jarvis holds every alert except critical ones and gives you a short
  recap when it ends.
- Break nudges ("break reminders on"): after 20 minutes of active use, a 20-20-20 eye break (look at something
  20 feet away for 20 seconds); every 90 minutes, water. Paused during game mode and when you're away.
"""
import ctypes
import ctypes.wintypes as wt
import threading
import time

from . import config, tools
from .tools import tool

CALL_APPS = {"zoom", "teams", "ms-teams", "webex", "webexmta", "skype", "slack"}
CALL_TITLES = ("meet - ", "google meet", "zoom meeting", "| microsoft teams", "huddle")
NOT_GAMES = {"explorer", "msedge", "chrome", "firefox", "opera", "brave", "code", "searchhost", "textinputhost",
             "applicationframehost", "shellexperiencehost", "lockapp", "vlc", "wmplayer", "mpc-hc64"}
BREAKS_FILE = config.DATA_DIR / "breaks-on"
user32 = ctypes.windll.user32

_state = {"manual": None, "auto": False, "reason": "", "held": [], "since": None}
_lock = threading.Lock()


def quiet():
    """Should alerts be held right now?"""
    return _state["manual"] if _state["manual"] is not None else _state["auto"]


def hold(title, message, level):
    with _lock:
        _state["held"].append((time.strftime("%H:%M"), title, message, level))


def _foreground():
    import psutil
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, title, n + 1)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        proc = psutil.Process(pid.value).name().lower().replace(".exe", "")
    except Exception:
        proc = ""
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    mon = user32.MonitorFromWindow(hwnd, 2)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    mi = MONITORINFO(ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    m = mi.rcMonitor
    full = rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom
    return proc, title.value, full


def detect():
    """(busy, reason): a full-screen game or a video call has the screen."""
    try:
        old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        old = None
    try:
        fg = _foreground()
    finally:
        if old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    if not fg:
        return False, ""
    proc, title, full = fg
    low = title.lower()
    if proc in CALL_APPS or any(t in low for t in CALL_TITLES):
        return True, "a call"
    if full and proc and proc not in NOT_GAMES and "j.a.r.v.i.s" not in low:
        return True, title or proc
    return False, ""


def _recap():
    with _lock:
        held, _state["held"] = _state["held"], []
    if not held:
        return
    from . import notify
    said = "; ".join(f"{m.rstrip('.')}" for _, _, m, _ in held[:4])
    more = f" And {len(held) - 4} more in the comms log." if len(held) > 4 else ""
    notify.alert("While you were busy", f"Welcome back, sir. While you were busy: {said}.{more}", level="note", phone=False)


def set_manual(on):
    was = quiet()
    _state["manual"] = True if on else None
    if was and not quiet():
        _recap()
    return ("Game mode on, sir. I'll hold everything but critical alerts." if on else
            "Game mode off." + (" Here's what I held." if was and _state["held"] else ""))


@tool("Game mode / do not disturb on or off: holds every alert except critical ones, with a recap afterwards. "
      "It also switches on by itself during full-screen games and video calls.", {"on": {"type": "boolean"}}, ["on"])
def game_mode(on):
    return set_manual(on)


# ---------- break nudges ----------

def breaks_on():
    return BREAKS_FILE.exists()


def set_breaks(on):
    BREAKS_FILE.touch() if on else BREAKS_FILE.unlink(missing_ok=True)
    return ("Break reminders on, sir: an eye break every 20 minutes of screen time, water every 90."
            if on else "Break reminders off.")


@tool("Break reminders on or off: a 20-20-20 eye break every 20 minutes of active screen use, water every 90.",
      {"on": {"type": "boolean"}}, ["on"])
def break_reminders(on):
    return set_breaks(on)


def _idle_seconds():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO))
    user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


def start():
    def loop():
        active, eyes_at, water_at = 0, 20 * 60, 90 * 60
        while True:
            time.sleep(10)
            try:
                busy, reason = detect()
                was = quiet()
                _state["auto"], _state["reason"] = busy, reason
                if was and not quiet():
                    _recap()
                if _idle_seconds() > 300:  # away: start counting again when he's back
                    active, eyes_at, water_at = 0, 20 * 60, 90 * 60
                    continue
                active += 10
                if breaks_on() and not quiet() and tools.ui:
                    from . import notify
                    if active >= eyes_at:
                        eyes_at = active + 20 * 60
                        notify.alert("Eye break", "Twenty-twenty-twenty, sir: look at something twenty feet away for "
                                     "twenty seconds.", level="note", phone=False)
                    if active >= water_at:
                        water_at = active + 90 * 60
                        notify.alert("Water", "Ninety minutes at the screen, sir. A glass of water wouldn't go amiss.",
                                     level="note", phone=False)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="focus").start()
