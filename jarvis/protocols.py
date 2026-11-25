"""Protocols, film style: named sequences Jarvis runs step by step, with a progress readout on the HUD.

- "Initiate Open House protocol": opens your usual apps (JARVIS_OPEN_HOUSE in .env), one by one.
- "Initiate Clean Slate protocol": after you approve it, minimises every window, clears the clipboard and locks
  the PC, with a countdown.
- "Initiate <name> protocol" also runs any routine you've saved ("focus mode" -> "focus protocol").
"""
import ctypes
import time

from . import config, tools
from .tools import S, tool
from .vitals import Progress

OPEN_HOUSE_APPS = [a.strip() for a in (config.OPEN_HOUSE or "").split(",") if a.strip()]


def open_house():
    apps = OPEN_HOUSE_APPS
    if not apps:
        return "Open House has no apps set yet, sir. Add them to JARVIS_OPEN_HOUSE in the .env file."
    p = Progress("OPEN HOUSE PROTOCOL", ["Waking systems"] + [a.title() for a in apps] + ["Ready"])
    p.step(0, "Bringing everything online")
    time.sleep(0.6)
    opened, failed = [], []
    for i, app in enumerate(apps, start=1):
        content, is_error = tools.run("open_application", {"name": app})
        ok = not is_error and str(content).startswith("Opened")
        (opened if ok else failed).append(app)
        p.step(i, str(content)[:80], "nominal" if ok else "caution")
        time.sleep(0.4)
    p.done("All systems online." if not failed else f"{len(failed)} didn't open.", "nominal" if not failed else "caution")
    text = f"Open House protocol complete, sir. {', '.join(a.title() for a in opened) or 'Nothing'} online."
    return text + (f" I couldn't open {', '.join(failed)}." if failed else "")


def clean_slate():
    if not tools.confirm("Clean Slate protocol: minimise every window, clear the clipboard and lock the PC?"):
        return "Clean Slate protocol cancelled, sir."
    p = Progress("CLEAN SLATE PROTOCOL", ["Minimising windows", "Clearing clipboard", "Locking in 3", "2", "1"])
    import pyautogui
    import pyperclip
    pyautogui.hotkey("win", "d")
    p.step(0, "Windows minimised")
    try:
        pyperclip.copy("")
    except Exception:
        pass
    p.step(1, "Clipboard cleared")
    for i in (2, 3, 4):
        time.sleep(1)
        p.step(i, "Locking")
    time.sleep(1)
    p.done("Locked.")
    ctypes.windll.user32.LockWorkStation()
    return "Clean Slate protocol complete, sir. Your screen is locked."


BUILT_IN = {"open house": open_house, "clean slate": clean_slate}


def run(name):
    key = " ".join(name.lower().replace("protocol", "").split())
    if key in BUILT_IN:
        return BUILT_IN[key]()
    from . import routines
    saved = routines.names()
    match = next((n for n in saved if n == key or n.replace(" mode", "") == key or key in n), None)
    if not match:
        known = ", ".join(sorted(set(BUILT_IN) | set(saved)))
        return f"I don't have a {name} protocol, sir. Available protocols: {known}."
    return routines.run_routine(match)


@tool("Run a named protocol, film style, with a step-by-step readout on the HUD: 'open house' (opens his usual apps), "
      "'clean slate' (minimise all, clear clipboard, lock; asks first), or any saved routine by name. "
      "Use for 'initiate X protocol', 'engage X protocol'.",
      {"name": S("The protocol's name, e.g. 'open house'")}, ["name"])
def run_protocol(name):
    return run(name)
