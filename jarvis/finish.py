"""'Tell me when it finishes': Jarvis keeps an eye on something slow and speaks up when it's done.

- "Tell me when my download finishes": the newest download in progress (Chrome/Edge .crdownload, Firefox .part)
  until its partial file is gone and the finished file stops growing.
- "Tell me when Steam closes" / "when the render finishes": a running program, until it exits.
- "Tell me when the computer is idle" / "when the install is done": until the CPU has been quiet for a minute.
- "Tell me when the window says complete": until a window with that text in its title appears.
- "Tell me when report.mp4 stops growing": a file, until its size stays the same for 20 seconds.
Checks are free (no AI) and run every few seconds for up to 12 hours. "What are you watching for?" lists them,
"stop watching" cancels them.
"""
import itertools
import os
import re
import threading
import time
from pathlib import Path

import psutil

from . import config, notify
from .tools import S, tool

POLL_SECONDS = 3
MAX_HOURS = 12
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".opdownload")
IDLE_CPU, IDLE_SECONDS = 15, 60

_watches = {}  # id -> {"what", "cancel": Event}
_ids = itertools.count(1)


def _downloads():
    return Path(os.path.expanduser("~/Downloads"))


def _start(what, check, done_text):
    """check() -> True when finished. Runs in a background thread."""
    wid = next(_ids)
    cancel = threading.Event()
    _watches[wid] = {"what": what, "cancel": cancel}

    def run():
        deadline = time.monotonic() + MAX_HOURS * 3600
        try:
            while not cancel.wait(POLL_SECONDS):
                if time.monotonic() > deadline:
                    notify.alert("Still waiting", f"I've stopped watching {what}, {config.USER_NAME}: twelve hours "
                                                  "and it hadn't finished.", level="note")
                    return
                try:
                    if check():
                        notify.alert("Finished", done_text, level="caution")
                        return
                except Exception:
                    continue
        finally:
            _watches.pop(wid, None)

    threading.Thread(target=run, daemon=True, name=f"finish-{wid}").start()
    return wid


def _stable(path, seconds=20):
    """A function that's True once `path` exists and its size hasn't changed for `seconds`."""
    seen = {"size": -1, "since": time.monotonic()}

    def check():
        size = path.stat().st_size if path.exists() else -1
        now = time.monotonic()
        if size != seen["size"]:
            seen.update(size=size, since=now)
            return False
        return size >= 0 and now - seen["since"] >= seconds
    return check


def watch_download():
    folder = _downloads()
    if not folder.is_dir():
        return "I can't find your Downloads folder, sir."
    partials = sorted((p for p in folder.iterdir() if p.suffix.lower() in PARTIAL),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    if partials:
        part = partials[0]
        final = part.with_suffix("")
        unnamed = final.name.lower().startswith("unconfirmed")  # Chrome picks the real name only at the end
        name = "your download" if unnamed else final.name
        stable = _stable(final, 5)
        _start(f"the download of {name}", lambda: not part.exists() and (unnamed or stable()),
               f"Your download has finished, {config.USER_NAME}" + ("." if unnamed else f": {name}."))
        return f"Watching the download of {name}, {config.USER_NAME}. I'll tell you when it's done."
    # No partial file: maybe a browser that writes the final name straight away. Watch the newest recent file.
    recent = [p for p in folder.iterdir() if p.is_file() and time.time() - p.stat().st_mtime < 120]
    if not recent:
        return "I don't see a download in progress, sir. Start it first, then ask me again."
    newest = max(recent, key=lambda p: p.stat().st_mtime)
    _start(f"the download of {newest.name}", _stable(newest), f"Your download has finished, {config.USER_NAME}: {newest.name}.")
    return f"Watching {newest.name}, {config.USER_NAME}. I'll tell you when it stops growing."


def _find_processes(name):
    want = re.sub(r"\.exe$", "", name.lower().strip())
    found = []
    for p in psutil.process_iter(["name", "pid"]):
        n = (p.info["name"] or "").lower().removesuffix(".exe")
        if n and (n == want or (len(want) >= 3 and want in n)):
            found.append(p.info["pid"])
    return found


def watch_program(name):
    pids = _find_processes(name)
    if not pids:
        return f"I don't see {name} running, sir."
    _start(name, lambda: not any(psutil.pid_exists(pid) for pid in pids),
           f"{name.strip().title()} has finished, {config.USER_NAME}.")
    return f"Watching {name}, {config.USER_NAME}. I'll tell you the moment it closes."


def watch_idle(what="the computer"):
    quiet = {"since": None}

    def check():
        busy = psutil.cpu_percent(interval=None)
        now = time.monotonic()
        if busy > IDLE_CPU:
            quiet["since"] = None
            return False
        quiet["since"] = quiet["since"] or now
        return now - quiet["since"] >= IDLE_SECONDS
    psutil.cpu_percent(interval=None)  # the first reading is meaningless
    _start(what, check, f"Things have gone quiet, {config.USER_NAME}: {what} looks finished.")
    return f"Watching {what}, {config.USER_NAME}. I'll tell you once the processor has been quiet for a minute."


def _window_titles():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                titles.append(buf.value)
        return True
    user32.EnumWindows(each, 0)
    return titles


def watch_window(text):
    want = text.lower().strip()
    _start(f"a window saying {text}", lambda: any(want in t.lower() for t in _window_titles()),
           f"A window just said {text}, {config.USER_NAME}.")
    return f"Watching for a window that says {text}, {config.USER_NAME}."


def watch_file(name):
    path = Path(os.path.expandvars(os.path.expanduser(name)))
    if not path.is_absolute():
        candidates = [d / name for d in (_downloads(), Path.home() / "Desktop", Path.home() / "Documents",
                                         Path.home() / "Videos")]
        path = next((c for c in candidates if c.exists()), candidates[0])
    if not path.exists():
        return f"I can't find {name}, sir."
    _start(path.name, _stable(path), f"{path.name} has stopped growing, {config.USER_NAME}. It looks finished.")
    return f"Watching {path.name}, {config.USER_NAME}. I'll tell you when it stops growing."


IDLE_WORDS = r"(?:the )?(?:computer|pc|laptop|install(?:ation|er)?|update|render|export|build|backup|scan|compile|copy)"


def request(thing):
    """Work out what to watch from plain words ("my download", "steam", "the render"...)."""
    t = re.sub(r"^(?:my|the)\s+", "", thing.lower().strip(" .?!"))
    t = re.sub(r"\s+(?:finishes|is done|is finished|completes|ends|closes|exits|quits|stops|is complete|is idle|"
               r"goes quiet|stops growing|has finished)$", "", t)
    if re.fullmatch(r"downloads?|(?:the )?file download|.*\bdownload(?:ing)?\b.*", t):
        return watch_download()
    m = re.fullmatch(r"(?:a |the )?window (?:says|shows|titled|called) (.+)", t)
    if m:
        return watch_window(m.group(1))
    if re.search(r"\.\w{2,4}$", t) or "\\" in t or "/" in t:
        return watch_file(thing.strip())
    if _find_processes(t):
        return watch_program(t)
    if re.fullmatch(IDLE_WORDS + r"|.*\b(?:install|update|render|export|build|backup|copy)\w*\b.*|it|this|that", t):
        return watch_idle(f"the {t}" if t not in ("it", "this", "that") else "that")
    return (f"I'm not sure what to watch for {thing}, sir. Try a program's name, 'my download', "
            "or 'the window says complete'.")


def listing():
    if not _watches:
        return "I'm not watching anything at the moment, sir."
    return "Watching: " + "; ".join(w["what"] for w in _watches.values()) + "."


def stop_all():
    n = len(_watches)
    for w in list(_watches.values()):
        w["cancel"].set()
    _watches.clear()
    return f"Stopped watching {n} thing{'s' if n != 1 else ''}, sir." if n else "I wasn't watching anything, sir."


@tool("'Tell me when it finishes': watch something slow and speak up when it's done, free (no AI). what: a program "
      "name ('steam', 'blender'), 'my download', 'the install'/'the render' (waits for the CPU to go quiet), "
      "'window says <text>', or a file name (waits until it stops growing). action 'list' or 'stop' instead.",
      {"what": S("What to watch"), "action": {"type": "string", "enum": ["watch", "list", "stop"]}})
def tell_me_when(what="", action="watch"):
    if action == "list":
        return listing()
    if action == "stop":
        return stop_all()
    return request(what) if what else "What should I watch, sir?"
