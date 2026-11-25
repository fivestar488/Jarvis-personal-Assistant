"""'What was I doing?': an activity journal you switch on yourself ("start my journal" or JARVIS_JOURNAL=on).

Once a minute it notes which app and window you're in (just the name and title, never a screenshot) in
data/journal/, on this PC only, with secrets hidden. "What was I working on Tuesday afternoon?" or "what did I do
yesterday?" turns that into a short summary. "Stop my journal" turns it off; "delete my journal" erases it.
"""
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import re
import shutil
import threading
import time

from . import config, privacy
from .tools import S, tool

FOLDER = config.DATA_DIR / "journal"
ON_FILE = config.DATA_DIR / "journal-on"
_thread = None
_stop = threading.Event()


def enabled():
    return config.JOURNAL or ON_FILE.exists()


def _foreground():
    import psutil
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, title, n + 1)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name().replace(".exe", "")
    except Exception:
        app = "?"
    return app, title.value


def _idle_seconds():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000


def _loop():
    FOLDER.mkdir(exist_ok=True)
    while not _stop.wait(60):
        try:
            if _idle_seconds() > 300:  # away from the keyboard: nothing to note
                continue
            fg = _foreground()
            if not fg:
                continue
            now = dt.datetime.now()
            entry = {"t": now.strftime("%H:%M"), "app": fg[0], "title": privacy.redact(fg[1])[:150]}
            with open(FOLDER / f"{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def start():
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="journal")
    _thread.start()


def switch(on):
    if on:
        ON_FILE.touch()
        start()
        return ("Journal on, sir. Once a minute I'll note which app and window you're in, on this PC only. "
                "Ask me what you were doing any time, or say 'stop my journal'.")
    ON_FILE.unlink(missing_ok=True)
    _stop.set()
    return "Journal off. What's already noted stays until you say 'delete my journal'."


def erase():
    shutil.rmtree(FOLDER, ignore_errors=True)
    return "Journal deleted, sir."


# ---------- answering "what was I doing?" ----------

PARTS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 22), "night": (22, 29)}


def _day(text, today):
    t = text.lower()
    if "yesterday" in t:
        return today - dt.timedelta(days=1)
    for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        if name in t:
            back = (today.weekday() - i) % 7 or 7  # the last one, not today
            return today - dt.timedelta(days=0 if back == 7 and "today" in t else back)
    return today


def _clean_title(app, title):
    """'Inbox (3) - you@x.com - Gmail - Google Chrome' -> 'Inbox - Gmail'."""
    t = re.sub(r"\s*[-–—|]\s*(Google Chrome|Microsoft Edge|Opera|Firefox|Visual Studio Code|Brave)$", "", title)
    t = re.sub(r"\(\d+\)\s*", "", t)
    return t.strip() or app


def summary(when="today"):
    today = dt.date.today()
    day = _day(when, today)
    path = FOLDER / f"{day:%Y-%m-%d}.jsonl"
    if not path.exists():
        return ("Your journal is off, sir. Say 'start my journal' and I'll start keeping track." if not enabled()
                else f"I have nothing noted for {_say_day(day, today)}.")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    part = next((p for p in PARTS if p in when.lower()), None)
    if part:
        lo, hi = PARTS[part]
        rows = [r for r in rows if lo <= int(r["t"][:2]) + (24 if int(r["t"][:2]) < 5 else 0) < hi]
    if not rows:
        return f"Nothing noted for {_say_day(day, today)}{' ' + part if part else ''}, sir."
    apps, things = {}, {}
    for r in rows:
        apps[r["app"]] = apps.get(r["app"], 0) + 1
        key = _clean_title(r["app"], r["title"])
        things[key] = things.get(key, 0) + 1
    top_apps = ", ".join(f"{a} for {_mins(m)}" for a, m in sorted(apps.items(), key=lambda kv: -kv[1])[:3])
    top_things = "; ".join(k for k, _ in sorted(things.items(), key=lambda kv: -kv[1])[:4])
    span = f"from {rows[0]['t']} to {rows[-1]['t']}"
    return (f"{_say_day(day, today).capitalize()}{' ' + part if part else ''}, {span}, you were mostly in {top_apps}. "
            f"The main things: {top_things}.")


def _mins(m):
    return f"{m} minute{'s' if m != 1 else ''}" if m < 60 else f"{m / 60:.1f} hours"


def _say_day(day, today):
    return "today" if day == today else "yesterday" if day == today - dt.timedelta(days=1) else f"{day:%A}"


@tool("The activity journal (off unless he turns it on): 'what was I doing/working on <day> <morning/afternoon>', "
      "or turn it on/off or delete it. Notes the app and window title once a minute, on this PC only.",
      {"action": {"type": "string", "enum": ["summary", "on", "off", "delete"]},
       "when": S("For summary: e.g. 'today', 'yesterday afternoon', 'tuesday morning'")}, ["action"])
def activity_journal(action, when="today"):
    return {"summary": lambda: summary(when), "on": lambda: switch(True), "off": lambda: switch(False),
            "delete": erase}[action]()
