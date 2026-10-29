"""Everything Jarvis can do on your PC. Each @tool function becomes a tool Claude can call.

To add a new skill: write a function, decorate it with @tool, return a string. That's it.
"""
import base64
import datetime as dt
import difflib
import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import config

TOOLS: dict[str, dict] = {}

# Set by the interface (text or voice) so tools can ask for permission and speak up later.
#   ui.confirm(question) -> bool      ui.announce(text) -> None
ui = None


def tool(description, properties=None, required=()):
    def wrap(fn):
        TOOLS[fn.__name__] = {
            "fn": fn,
            "schema": {
                "name": fn.__name__,
                "description": description,
                "input_schema": {"type": "object", "properties": properties or {}, "required": list(required)},
            },
        }
        return fn
    return wrap


def S(desc): return {"type": "string", "description": desc}
def I(desc): return {"type": "integer", "description": desc}
def B(desc): return {"type": "boolean", "description": desc}


def schemas():
    return [t["schema"] for t in TOOLS.values()]


def run(name, args):
    """Run a tool. Returns (content, is_error)."""
    if name not in TOOLS:
        return f"Unknown tool: {name}", True
    try:
        return TOOLS[name]["fn"](**args), False
    except Exception as e:  # report failures back to Claude so it can recover
        return f"{type(e).__name__}: {e}", True


def confirm(question):
    return ui.confirm(question) if ui else False


def _path(p):
    return Path(os.path.expandvars(os.path.expanduser(p))).resolve()


def _clip(text, limit=8000):
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated, {len(text) - limit} more characters]"


# ---------------------------------------------------------------- time

@tool("Get the current local date and time.")
def get_datetime():
    return dt.datetime.now().strftime("%A %d %B %Y, %H:%M:%S")


# ---------------------------------------------------------------- apps

APP_ALIASES = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe", "paint": "mspaint.exe",
    "command prompt": "cmd.exe", "cmd": "cmd.exe", "powershell": "powershell.exe", "terminal": "wt.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "task manager": "taskmgr.exe", "settings": "ms-settings:", "control panel": "control.exe",
    "snipping tool": "snippingtool.exe",
}
_start_apps = None


def _get_start_apps():
    """Every app in the Start menu (desktop and Store apps) as {name: AppID}."""
    global _start_apps
    if _start_apps is None:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        _start_apps = {a["Name"]: a["AppID"] for a in json.loads(out or "[]")}
    return _start_apps


@tool("Open/launch an application installed on this PC, e.g. 'spotify', 'chrome', 'notepad', 'discord', 'steam'.",
      {"name": S("Name of the app")}, ["name"])
def open_application(name):
    key = name.lower().strip()
    if key in APP_ALIASES:
        os.startfile(APP_ALIASES[key])
        return f"Opened {name}."
    apps = _get_start_apps()
    lowered = {n.lower(): n for n in apps}
    match = next((lowered[n] for n in lowered if n == key), None)
    match = match or next((lowered[n] for n in sorted(lowered, key=len) if key in n), None)
    if not match:
        close = difflib.get_close_matches(key, lowered.keys(), n=1, cutoff=0.6)
        match = lowered[close[0]] if close else None
    if not match:
        return f"Couldn't find an app called '{name}'. Similar apps: {difflib.get_close_matches(key, lowered.keys(), n=5, cutoff=0.3)}"
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{apps[match]}"])
    return f"Opened {match}."


@tool("Close a running application by name (e.g. 'chrome', 'spotify'). Unsaved work may be lost.",
      {"name": S("App or process name")}, ["name"])
def close_application(name):
    import psutil
    key = name.lower().replace(".exe", "").replace(" ", "")
    procs = [p for p in psutil.process_iter(["name"]) if p.info["name"] and key in p.info["name"].lower().replace(" ", "")]
    if not procs:
        return f"No running process matches '{name}'."
    names = sorted({p.info["name"] for p in procs})
    if not confirm(f"Close {', '.join(names)}?"):
        return "User declined."
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    return f"Closed {', '.join(names)}."


# ---------------------------------------------------------------- web

@tool("Open a URL or website in the default browser.", {"url": S("Full URL or domain, e.g. 'github.com'")}, ["url"])
def open_url(url):
    if not re.match(r"^[a-z]+://", url):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}."


@tool("Search Google in the browser for the user to look at. (For answering questions yourself, use web_search instead.)",
      {"query": S("Search terms")}, ["query"])
def google_search(query):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(query))
    return f"Opened Google results for '{query}'."


@tool("Play a song or video on YouTube: finds the top result and starts playing it in the browser.",
      {"query": S("What to play, e.g. 'back in black ac/dc'")}, ["query"])
def play_youtube(query):
    req = urllib.request.Request(
        "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    ids = re.findall(r'"videoId":"([\w-]{11})"', html)
    if not ids:
        webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        return "Couldn't pick a video, opened the search results instead."
    webbrowser.open(f"https://www.youtube.com/watch?v={ids[0]}")
    return f"Playing top YouTube result for '{query}'."


# ---------------------------------------------------------------- shell & files

@tool("Run a PowerShell command on this Windows PC and return its output. The user is asked to approve every command. "
      "Use for anything no other tool covers (system settings, installs, git, network info, etc).",
      {"command": S("PowerShell command"), "reason": S("One short sentence on what this does, shown to the user")},
      ["command", "reason"])
def run_powershell(command, reason):
    if not confirm(f"Run this command? ({reason})\n    {command}"):
        return "User declined to run the command."
    r = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=120)
    return _clip(f"exit code {r.returncode}\n{r.stdout}\n{r.stderr}".strip())


@tool("List files and folders in a directory. Supports ~ and environment variables.",
      {"path": S("Folder path, e.g. '~/Downloads'")}, ["path"])
def list_directory(path):
    p = _path(path)
    entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    lines = [f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries[:300]]
    return f"{p}\n" + "\n".join(lines) + (f"\n... and {len(entries) - 300} more" if len(entries) > 300 else "")


@tool("Read a text file.", {"path": S("File path")}, ["path"])
def read_file(path):
    return _clip(_path(path).read_text(encoding="utf-8", errors="replace"), 20000)


@tool("Write or append text to a file. Creates folders as needed. Asks the user before overwriting an existing file.",
      {"path": S("File path"), "content": S("Text to write"), "append": B("Append instead of overwrite")},
      ["path", "content"])
def write_file(path, content, append=False):
    p = _path(path)
    if p.exists() and not append and not confirm(f"Overwrite {p}?"):
        return "User declined."
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    return f"{'Appended to' if append else 'Wrote'} {p}."


@tool("Find files by name anywhere under a folder (defaults to the user's home folder).",
      {"pattern": S("Glob pattern, e.g. '*.pdf' or '*invoice*'"), "folder": S("Folder to search in")}, ["pattern"])
def find_files(pattern, folder="~"):
    results = []
    for p in _path(folder).rglob(pattern):
        if "AppData" in p.parts or any(part.startswith(".") for part in p.parts):
            continue
        results.append(str(p))
        if len(results) >= 50:
            break
    return "\n".join(results) or "No matches."


@tool("Open a file or folder with its default program (e.g. a PDF, a photo, a folder in Explorer).",
      {"path": S("File or folder path")}, ["path"])
def open_path(path):
    os.startfile(_path(path))
    return f"Opened {_path(path)}."


# ---------------------------------------------------------------- system

@tool("Get CPU, memory, disk and battery status of this PC.")
def system_status():
    import psutil
    lines = [
        f"CPU: {psutil.cpu_percent(interval=0.5)}%",
        f"RAM: {psutil.virtual_memory().percent}% used of {psutil.virtual_memory().total / 2**30:.1f} GB",
        f"Disk C: {psutil.disk_usage('C:/').percent}% used, {psutil.disk_usage('C:/').free / 2**30:.0f} GB free",
    ]
    battery = psutil.sensors_battery()
    if battery:
        lines.append(f"Battery: {battery.percent:.0f}% ({'charging' if battery.power_plugged else 'on battery'})")
    top = sorted(psutil.process_iter(["name", "memory_percent"]), key=lambda p: p.info["memory_percent"] or 0, reverse=True)[:5]
    lines.append("Top memory users: " + ", ".join(f"{p.info['name']} ({p.info['memory_percent']:.1f}%)" for p in top))
    return "\n".join(lines)


@tool("Control media and volume: play/pause, next/previous track, volume up/down, mute.",
      {"action": {"type": "string", "enum": ["playpause", "next", "previous", "volume_up", "volume_down", "mute"]},
       "times": I("How many presses, for volume (each is ~2%). Default 5.")},
      ["action"])
def media_control(action, times=5):
    import pyautogui
    key = {"playpause": "playpause", "next": "nexttrack", "previous": "prevtrack",
           "volume_up": "volumeup", "volume_down": "volumedown", "mute": "volumemute"}[action]
    pyautogui.press(key, presses=times if action.startswith("volume") else 1)
    return f"Done: {action}."


@tool("Lock, sleep, restart or shut down the PC. Everything except lock asks the user first.",
      {"action": {"type": "string", "enum": ["lock", "sleep", "restart", "shutdown"]}}, ["action"])
def system_power(action):
    if action != "lock" and not confirm(f"Really {action} the computer?"):
        return "User declined."
    commands = {
        "lock": ["rundll32.exe", "user32.dll,LockWorkStation"],
        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        "restart": ["shutdown", "/r", "/t", "5"],
        "shutdown": ["shutdown", "/s", "/t", "5"],
    }
    subprocess.Popen(commands[action])
    return f"{action} started."


# ---------------------------------------------------------------- screen, keyboard, clipboard

@tool("Take a screenshot. With look=true you get to see the screen yourself, so use it whenever the user asks "
      "about what's on their screen or you need to see something to help.",
      {"look": B("Return the image so you can see it (default true)")})
def take_screenshot(look=True):
    from PIL import ImageGrab
    img = ImageGrab.grab(all_screens=False)
    folder = Path.home() / "Pictures" / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"screenshot_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    img.save(file)
    if not look:
        return f"Saved screenshot to {file}."
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return _image_result(buf.getvalue(), f"Screenshot saved to {file}.")


def _image_result(jpeg, note):
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
        {"type": "text", "text": note},
    ]


@tool("Look through the PC's webcam and see what's in front of it. Use when the user asks what you can see, "
      "what he's holding, how he looks, who's there, etc.")
def look_through_camera():
    import cv2
    cam = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
    try:
        if not cam.isOpened():
            return "Couldn't open the webcam. It may be in use by another app, or blocked in Windows privacy settings."
        ok, frame = False, None
        for _ in range(10):  # the first frames are dark while auto-exposure adjusts
            ok, frame = cam.read()
        if not ok:
            return "The webcam didn't return an image."
    finally:
        cam.release()
    h, w = frame.shape[:2]
    if w > 1280:
        frame = cv2.resize(frame, (1280, int(h * 1280 / w)))
    _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return _image_result(jpeg.tobytes(), "Webcam image captured just now.")


@tool("Type text into whatever window currently has focus, as if typed on the keyboard.",
      {"text": S("Text to type")}, ["text"])
def type_text(text):
    import pyautogui
    pyperclip_set(text)
    pyautogui.hotkey("ctrl", "v")  # pasting handles unicode and is much faster than typing each key
    return "Typed it."


@tool("Press a keyboard shortcut, e.g. 'ctrl+c', 'alt+tab', 'win+d', 'enter'.", {"keys": S("Keys joined with +")}, ["keys"])
def press_keys(keys):
    import pyautogui
    pyautogui.hotkey(*[k.strip().lower() for k in keys.split("+")])
    return f"Pressed {keys}."


def pyperclip_set(text):
    import pyperclip
    pyperclip.copy(text)


@tool("Read the text currently on the clipboard.")
def get_clipboard():
    import pyperclip
    return _clip(pyperclip.paste() or "(clipboard is empty)")


@tool("Copy text to the clipboard.", {"text": S("Text to copy")}, ["text"])
def set_clipboard(text):
    pyperclip_set(text)
    return "Copied to clipboard."


# ---------------------------------------------------------------- timers & reminders

REMINDERS_FILE = config.DATA_DIR / "reminders.json"
_reminder_lock = threading.Lock()
_started_at = dt.datetime.now()
_reminder_loop = None


def _load_reminders():
    if REMINDERS_FILE.exists():
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    return []


def _save_reminders(items):
    REMINDERS_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


@tool("Set a timer or reminder. Jarvis announces it out loud when it's due. Saved to disk, so it survives restarts. "
      "Give either seconds from now, or an exact time.",
      {"message": S("What to say, e.g. 'Your pizza is ready'"),
       "seconds": I("Delay from now in seconds"),
       "at": S("Exact local time: 'HH:MM' (next occurrence) or 'YYYY-MM-DDTHH:MM'")},
      ["message"])
def set_reminder(message, seconds=None, at=None):
    now = dt.datetime.now()
    if at:
        if len(at) <= 5:
            hour, minute = map(int, at.split(":"))
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due <= now:
                due += dt.timedelta(days=1)
        else:
            due = dt.datetime.fromisoformat(at)
    elif seconds:
        due = now + dt.timedelta(seconds=seconds)
    else:
        return "Give either seconds or at."
    item = {"id": os.urandom(3).hex(), "due": due.isoformat(timespec="seconds"), "message": message}
    with _reminder_lock:
        _save_reminders(_load_reminders() + [item])
    return f"Reminder set for {due:%A %d %b at %H:%M:%S} (id {item['id']})."


@tool("List upcoming reminders.")
def list_reminders():
    items = sorted(_load_reminders(), key=lambda r: r["due"])
    return "\n".join(f"[{r['id']}] {r['due'].replace('T', ' ')} — {r['message']}" for r in items) or "No reminders set."


@tool("Cancel reminders by id, or by text contained in the message.", {"match": S("Reminder id or part of its message")}, ["match"])
def cancel_reminder(match):
    with _reminder_lock:
        items = _load_reminders()
        kept = [r for r in items if r["id"] != match and match.lower() not in r["message"].lower()]
        _save_reminders(kept)
    return f"Cancelled {len(items) - len(kept)} reminder(s)."


def start_reminders():
    """Background loop that announces due reminders, including any that came due while Jarvis was off."""
    global _reminder_loop
    if _reminder_loop:
        return

    def loop():
        while True:
            now = dt.datetime.now()
            with _reminder_lock:
                items = _load_reminders()
                due = [r for r in items if dt.datetime.fromisoformat(r["due"]) <= now]
                if due:
                    _save_reminders([r for r in items if r not in due])
            for r in due:
                when = dt.datetime.fromisoformat(r["due"])
                if ui and when < _started_at:
                    ui.announce(f"While I was offline you had a reminder for {when:%A at %H:%M}: {r['message']}")
                elif ui:
                    ui.announce(f"Reminder: {r['message']}")
            time.sleep(3)

    _reminder_loop = threading.Thread(target=loop, daemon=True)
    _reminder_loop.start()


# ---------------------------------------------------------------- weather & news

@tool("Current weather and 4-day forecast. Faster than web_search for weather. Defaults to the user's home location.",
      {"place": S("Optional city or place name")})
def get_weather(place=None):
    from . import feeds
    w = feeds.weather(place)
    c, u = w["current"], w["units"]
    lines = [f"{w['location']['name']}: {c['text']}, {c['temp']}{u['temp']} (feels like {c['feels']}{u['temp']}), "
             f"humidity {c['humidity']}%, wind {c['wind']} {u['wind']}."]
    for d in w["daily"]:
        lines.append(f"{d['date']}: {d['text']}, high {d['high']}{u['temp']}, low {d['low']}{u['temp']}, rain chance {d['rain']}%")
    return "\n".join(lines)


@tool("Today's top news headlines from the user's news feeds.")
def get_headlines():
    from . import feeds
    return "\n".join(f"- {h['title']} ({h['source']})" for h in feeds.headlines(15)) or "Couldn't load the news."


# ---------------------------------------------------------------- memory & notes

def load_memory():
    if config.MEMORY_FILE.exists():
        return json.loads(config.MEMORY_FILE.read_text(encoding="utf-8"))
    return []


def _save_memory(facts):
    config.MEMORY_FILE.write_text(json.dumps(facts, indent=2), encoding="utf-8")


@tool("Permanently remember a fact about the user or their preferences, kept across sessions. "
      "Use when the user says 'remember...' or shares something clearly worth remembering.",
      {"fact": S("The fact, written as a short sentence")}, ["fact"])
def remember(fact):
    facts = load_memory()
    facts.append(fact)
    _save_memory(facts)
    return "Remembered."


@tool("Forget remembered facts that contain the given text.", {"text": S("Text to match")}, ["text"])
def forget(text):
    facts = load_memory()
    kept = [f for f in facts if text.lower() not in f.lower()]
    _save_memory(kept)
    return f"Forgot {len(facts) - len(kept)} fact(s)."


@tool("Save a note to the user's notes file.", {"text": S("The note")}, ["text"])
def save_note(text):
    with open(config.NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(f"- [{dt.datetime.now():%Y-%m-%d %H:%M}] {text}\n")
    return "Note saved."


@tool("Read all of the user's saved notes.")
def read_notes():
    return config.NOTES_FILE.read_text(encoding="utf-8") if config.NOTES_FILE.exists() else "No notes yet."


from . import google_tools  # noqa: E402,F401  (registers the Gmail & Calendar tools)
