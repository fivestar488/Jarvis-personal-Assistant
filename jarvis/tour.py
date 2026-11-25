"""'Give them the tour': a narrated two-minute demo of the holograms, the workshop and the alerts, for showing Jarvis
to friends. Everything on screen is made-up sample data, so none of your email, calendar or spending shows.
'Stop the tour' ends it.
"""
import asyncio
import base64
import threading
import time

from . import config, tools
from .tools import tool

# (what Jarvis says, hologram events to send as he starts saying it, seconds to linger after he finishes)
STEPS = [
    ("Allow me to introduce myself. I'm JARVIS, a personal assistant that runs on this computer. Everything you're "
     "about to see uses sample data, so nothing private will appear.", [], 0.5),
    ("First, holograms. I can build a 3D model of almost anything, and you can turn it with your hands.",
     [{"action": "open", "kind": "object", "subject": "jet engine"}], 1.0),
    ("Clap, and it comes apart, each part labelled.", [{"action": "expand"}], 2.5),
    ("Any topic becomes a map. Pick a part, and it breaks down further.",
     [{"action": "open", "kind": "topic", "subject": "How a car works", "parts": [
         {"name": "Engine", "detail": "Burns fuel to turn the crankshaft."},
         {"name": "Transmission", "detail": "Gears that trade speed for pulling power."},
         {"name": "Brakes", "detail": "Pads squeeze discs to turn motion into heat."},
         {"name": "Steering", "detail": "Turns the front wheels through a rack and pinion."},
         {"name": "Battery", "detail": "Starts the engine and runs the electronics."}]}], 2.5),
    ("Your own data, in three dimensions. Here's a sample week of spending. The tallest bar is the day to worry about.",
     [{"action": "open", "kind": "data", "subject": "Sample spending", "unit": "$", "title": "A sample week",
       "bars": [{"label": "MON", "value": 12.4}, {"label": "TUE", "value": 8.1}, {"label": "WED", "value": 31.75},
                {"label": "THU", "value": 6.5}, {"label": "FRI", "value": 22.0}, {"label": "SAT", "value": 44.9},
                {"label": "SUN", "value": 9.3}]}], 2.0),
    ("Trip mode. A flight becomes an arc across the globe, with a countdown, the weather when you land, and a "
     "packing list.",
     [{"action": "open", "kind": "object", "subject": "globe",
       "arcs": [{"from": {"lat": 51.47, "lon": -0.45, "name": "London"},
                 "to": {"lat": 40.64, "lon": -73.78, "name": "New York"}, "label": "SAMPLE · 12 DEC"}]}], 2.5),
    ("And the workshop. Shapes you stretch with both hands, then save.",
     [{"action": "open", "kind": "sculpt", "subject": "Sculpture", "shapes": [{"type": "cylinder"}]}], 0.5),
    ("Add a piece, stretch it, and you have the start of something.",
     [{"action": "sculpt", "op": "add", "target": "sphere"}, {"action": "sculpt", "op": "stretch", "target": "taller"}],
     2.0),
    ("When something needs your attention, I'll say so, from a quiet note up to a red alert.",
     [{"action": "close"}], 0.3),
    ("", ["ALERT"], 6.5),
    ("I also look after email, the calendar, music, reminders, parcels, and the boring bits in between. Just ask. "
     "That concludes the tour.", [], 0),
]

_cancel = threading.Event()
_running = threading.Lock()


def _say(text):
    """Speak a line on the HUD and return roughly how long it takes."""
    from .voice import synthesize
    try:
        audio = asyncio.run(synthesize(text, tone=None))
    except Exception:
        audio = b""
    tools.ui.hud({"type": "reply", "text": text, "audio": base64.b64encode(audio).decode() if audio else None,
                  "origin": "tour"})
    # Edge's voices are 48 kbit/s MP3, so the length in bytes gives the length in seconds
    return len(audio) * 8 / 48000 if audio else len(text.split()) / 2.6


def _run():
    try:
        time.sleep(3.5)  # let "Certainly, here's the tour" finish
        for text, events, linger in STEPS:
            if _cancel.is_set():
                return
            for ev in events:
                if ev == "ALERT":
                    tools.ui.announce("Sample alert: the tour's demo reactor is running a little warm.", level="warning")
                else:
                    tools.ui.hud({"type": "holo", **ev})
            seconds = (_say(text) if text else 0) + linger
            if _cancel.wait(seconds):
                return
    finally:
        tools.ui.hud({"type": "holo", "action": "close"})
        _running.release()


def start_tour():
    if not tools.ui or not hasattr(tools.ui, "hud"):
        return "The tour needs the HUD. Start Jarvis with jarvis.bat."
    if not _running.acquire(blocking=False):
        return "The tour's already running, sir."
    _cancel.clear()
    threading.Thread(target=_run, daemon=True, name="tour").start()
    return f"Certainly, {config.USER_NAME}. Here's the tour."


def stop_tour():
    if not _running.locked():
        return "There's no tour running, sir."
    _cancel.set()
    return "Tour ended."


@tool("'Give them the tour' / demo mode: a narrated two-minute demo of the holograms, sculpting and alerts on made-up "
      "sample data (nothing private shows), for showing Jarvis to friends. stop=true ends it.",
      {"stop": {"type": "boolean"}})
def demo_tour(stop=False):
    return stop_tour() if stop else start_tour()
