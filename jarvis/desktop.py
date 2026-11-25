"""The desktop as a set: mood mode and window tiling.

- "Mood mode" / "movie mode": Windows goes dark, the screen dims, the HUD switches to its blue look, and music
  starts if JARVIS_MOOD_MUSIC is set. "Mood mode off" puts everything back the way it was.
- "Put Chrome on the left and Spotify on the right", "maximise Word": windows arranged by voice.
"""
import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import winreg

from . import config, tools
from .tools import S, tool

MOOD_FILE = config.DATA_DIR / "mood-before.json"
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
user32 = ctypes.windll.user32


# ---------- mood mode ----------

def _theme():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as k:
        return {n: winreg.QueryValueEx(k, n)[0] for n in ("AppsUseLightTheme", "SystemUsesLightTheme")}


def _set_theme(values):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for n, v in values.items():
            winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, int(v))
    # Tell open windows the theme changed (WM_SETTINGCHANGE, "ImmersiveColorSet")
    user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "ImmersiveColorSet", 0x0002, 300, None)


def _ps(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                          timeout=20).stdout.strip()


def _brightness():
    """Laptop screen brightness (0-100), or None on a desktop monitor that doesn't support it."""
    out = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction SilentlyContinue "
              "| Select-Object -First 1).CurrentBrightness")
    return int(out) if out.isdigit() else None


def _set_brightness(level):
    _ps(f"Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue | "
        f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={int(level)}}} | Out-Null")


def _hud(event):
    return bool(tools.ui and hasattr(tools.ui, "hud") and tools.ui.hud(event))


def mood(on):
    if on:
        if MOOD_FILE.exists():
            return "Mood mode is already on, sir."
        before = {"theme": _theme(), "brightness": _brightness()}
        MOOD_FILE.write_text(json.dumps(before), encoding="utf-8")
        _set_theme({"AppsUseLightTheme": 0, "SystemUsesLightTheme": 0})
        if before["brightness"] is not None:
            _set_brightness(min(before["brightness"], 35))
        _hud({"type": "mood", "on": True})
        music = ""
        if config.MOOD_MUSIC and "spotify_play" in tools.TOOLS:
            content, is_error = tools.run("spotify_play", {"query": config.MOOD_MUSIC})
            music = " And a little music." if not is_error else ""
        return "Mood mode, sir. Lights down." + music
    if not MOOD_FILE.exists():
        return "Mood mode isn't on, sir."
    before = json.loads(MOOD_FILE.read_text(encoding="utf-8"))
    _set_theme(before["theme"])
    if before.get("brightness") is not None:
        _set_brightness(before["brightness"])
    MOOD_FILE.unlink(missing_ok=True)
    _hud({"type": "mood", "on": False})
    return "Mood mode off. Lights back up, sir."


@tool("Mood mode on or off: Windows dark mode, dimmed screen, the HUD's blue look, and music if set up. Off puts "
      "everything back. 'mood mode', 'movie mode', 'lights down'.", {"on": {"type": "boolean"}}, ["on"])
def mood_mode(on):
    return mood(on)


# ---------- window tiling ----------

def _windows():
    """Visible top-level windows with a title: [(hwnd, title, process name)]."""
    import psutil
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def check(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # skip owned pop-ups (GW_OWNER)
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                title = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, title, n + 1)
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    proc = psutil.Process(pid.value).name().lower().replace(".exe", "")
                except Exception:
                    proc = ""
                if title.value not in ("Program Manager", "Settings"):
                    found.append((hwnd, title.value, proc))
        return True

    user32.EnumWindows(check, 0)
    return found


def _find(app, windows):
    a = app.lower().strip()
    a_squash = a.replace(" ", "")
    for hwnd, title, proc in windows:  # the program's name first ("chrome"), then the window title
        if a_squash and (a_squash in proc or proc and proc in a_squash):
            return hwnd, title
    for hwnd, title, proc in windows:
        if a in title.lower():
            return hwnd, title
    return None, None


SPOTS = {  # (left, top, width, height) as fractions of the screen's work area
    "left": (0, 0, .5, 1), "right": (.5, 0, .5, 1), "top": (0, 0, 1, .5), "bottom": (0, .5, 1, .5),
    "top left": (0, 0, .5, .5), "top right": (.5, 0, .5, .5), "bottom left": (0, .5, .5, .5),
    "bottom right": (.5, .5, .5, .5), "full": (0, 0, 1, 1), "center": (.15, .1, .7, .8),
}


def tile(placements):
    """placements: [{"app": "chrome", "position": "left"}, ...]. Returns what to say."""
    try:
        old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # real pixels on scaled screens
    except AttributeError:
        old = None
    try:
        area = wt.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA: screen minus taskbar
        W, H = area.right - area.left, area.bottom - area.top
        windows = _windows()
        done, missing = [], []
        for p in placements:
            app = str(p.get("app", "")).strip()
            pos = " ".join(str(p.get("position", "left")).lower().replace("-", " ").split())
            pos = {"maximise": "full", "maximize": "full", "fullscreen": "full", "middle": "center",
                   "centre": "center", "left half": "left", "right half": "right"}.get(pos, pos)
            hwnd, title = _find(app, windows)
            if not hwnd:
                missing.append(app)
                continue
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE: un-minimise / un-maximise first
            if pos == "full":
                user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            else:
                x, y, w, h = SPOTS.get(pos, SPOTS["left"])
                user32.SetWindowPos(hwnd, 0, area.left + int(x * W), area.top + int(y * H), int(w * W), int(h * H),
                                    0x0040)  # SWP_SHOWWINDOW
            user32.SetForegroundWindow(hwnd)
            done.append(f"{app} {'maximised' if pos == 'full' else 'on the ' + pos}")
    finally:
        if old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    text = ("Done, sir: " + ", ".join(done) + ".") if done else ""
    if missing:
        text += f" I couldn't find an open window for {', '.join(missing)}."
    return text.strip() or "There was nothing to arrange."


@tool("Arrange open windows on the screen: left/right/top/bottom half, a quarter (top left...), centre, or full "
      "(maximise). 'put Chrome on the left and Spotify on the right', 'maximise Word'.",
      {"placements": {"type": "array", "items": {"type": "object", "properties": {
          "app": S("App or window name, e.g. 'chrome'"),
          "position": {"type": "string", "enum": list(SPOTS) + ["maximise"]}}, "required": ["app", "position"]}}},
      ["placements"])
def tile_windows(placements):
    return tile(placements)
