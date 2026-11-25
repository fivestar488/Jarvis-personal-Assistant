"""Standing orders: commands Jarvis runs by himself when something happens.

  "Every weekday at 8, initiate focus protocol"     (time: every day / weekdays / weekends / a day of the week)
  "When my battery drops below 20 percent, low power mode"
  "When I open Steam, game mode on"                  (an app starting)
  "List my standing orders" / "cancel standing order 2" / "cancel all standing orders"

The checks are free (no AI); when one fires, its command runs exactly as if you'd said it.
"""
import datetime as dt
import json
import re
import threading
import time
import uuid

from . import config
from .tools import S, tool

ORDERS_FILE = config.DATA_DIR / "standing-orders.json"
DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
run_command = None  # set by the server: run_command(text) runs it like a spoken command


def _load():
    try:
        return json.loads(ORDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(orders):
    ORDERS_FILE.write_text(json.dumps(orders, indent=1, ensure_ascii=False), encoding="utf-8")


def _hhmm(h, m, ampm):
    h, m = int(h), int(m or 0)
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def parse(text):
    """'every weekday at 8 am run focus mode' -> an order dict, or None."""
    t = " ".join(text.lower().replace(",", " ").split())
    m = re.fullmatch(r"(?:every (day|weekday|weekend|morning|evening|night|monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
                     r"|on (weekdays|weekends|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays|sundays)|(daily|weekdays|weekends))"
                     r" at (\d{1,2})(?:[:.](\d{2}))? ?(am|pm)? (?:then )?(.+)", t)
    if m:
        when = (m.group(1) or m.group(2) or m.group(3)).rstrip("s")
        days = {"day": "daily", "daily": "daily", "morning": "daily", "evening": "daily", "night": "daily",
                "weekday": "weekdays", "weekend": "weekends"}.get(when, when)
        return {"trigger": {"type": "time", "days": days, "at": _hhmm(m.group(4), m.group(5), m.group(6))},
                "command": m.group(7).strip()}
    m = re.fullmatch(r"when(?:ever)? (?:my |the )?battery (?:drops|goes|falls|gets|is) (?:below|under|to) (\d{1,2})(?: ?%| percent)? (?:then )?(.+)", t)
    if m:
        return {"trigger": {"type": "battery", "below": int(m.group(1))}, "command": m.group(2).strip()}
    m = re.fullmatch(r"when(?:ever)? i (?:open|start|launch|run) ([a-z0-9 .+-]{2,30}?) (?:then )?((?:turn|switch|start|run|initiate|engage|set|play|pause|mute|low|game|do not|mood|lights|open|close|captions|stop).+)", t)
    if m:
        return {"trigger": {"type": "app", "name": m.group(1).strip().replace(" ", "")}, "command": m.group(2).strip()}
    return None


def describe(o):
    tr = o["trigger"]
    if tr["type"] == "time":
        days = {"daily": "every day", "weekdays": "every weekday", "weekends": "every weekend day"}.get(tr["days"], f"every {tr['days'].title()}")
        return f"{days} at {tr['at']}: {o['command']}"
    if tr["type"] == "battery":
        return f"when the battery drops below {tr['below']} percent: {o['command']}"
    return f"when you open {tr['name']}: {o['command']}"


def add(text):
    o = parse(text)
    if not o:
        return None
    o["id"] = uuid.uuid4().hex[:6]
    orders = _load()
    orders.append(o)
    _save(orders)
    return f"Standing order logged, sir: {describe(o)}."


def listing():
    orders = _load()
    if not orders:
        return "No standing orders, sir. Try 'every weekday at 8, initiate focus protocol'."
    return "Standing orders: " + "; ".join(f"{i}. {describe(o)}" for i, o in enumerate(orders, 1)) + "."


def cancel(which):
    orders = _load()
    if which == "all":
        _save([])
        return f"All {len(orders)} standing orders cancelled, sir."
    try:
        o = orders.pop(int(which) - 1)
    except (ValueError, IndexError):
        return f"There's no standing order {which}. {listing()}"
    _save(orders)
    return f"Cancelled: {describe(o)}."


def _fire(o):
    if run_command:
        threading.Thread(target=run_command, args=(o["command"],), daemon=True).start()


def start():
    def loop():
        import psutil
        fired_today, below, running = {}, {}, None
        while True:
            time.sleep(30)
            try:
                orders = _load()
                if not orders:
                    continue
                now = dt.datetime.now()
                today = now.date().isoformat()
                procs = {p.info["name"].lower().replace(".exe", "") for p in psutil.process_iter(["name"]) if p.info["name"]}
                b = psutil.sensors_battery()
                for o in orders:
                    tr = o["trigger"]
                    if tr["type"] == "time":
                        wd = now.weekday()
                        day_ok = (tr["days"] == "daily" or (tr["days"] == "weekdays" and wd < 5) or
                                  (tr["days"] == "weekends" and wd >= 5) or DAYS.get(tr["days"]) == wd)
                        h, m = map(int, tr["at"].split(":"))
                        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                        if day_ok and 0 <= (now - target).total_seconds() < 180 and fired_today.get(o["id"]) != today:
                            fired_today[o["id"]] = today
                            _fire(o)
                    elif tr["type"] == "battery" and b and not b.power_plugged:
                        low = b.percent < tr["below"]
                        if low and not below.get(o["id"]):
                            _fire(o)
                        below[o["id"]] = low
                    elif tr["type"] == "battery":
                        below[o["id"]] = False
                    elif tr["type"] == "app" and running is not None:
                        name = tr["name"]
                        now_on = any(name in p for p in procs)
                        was_on = any(name in p for p in running)
                        if now_on and not was_on:
                            _fire(o)
                running = procs
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="standing-orders").start()


@tool("Standing orders: commands Jarvis runs by himself on a schedule ('every weekday at 8 initiate focus protocol'), "
      "when the battery drops below a level, or when an app opens ('when I open Steam game mode on'). "
      "action add (order = his whole sentence), list, or cancel (which = a number or 'all').",
      {"action": {"type": "string", "enum": ["add", "list", "cancel"]}, "order": S("For add: the order in his words"),
       "which": S("For cancel: its number, or 'all'")}, ["action"])
def standing_orders(action, order="", which=""):
    if action == "add":
        return add(order) or ("I couldn't work out the trigger, sir. Try: 'every weekday at 8, initiate focus protocol', "
                              "'when my battery drops below 20 percent, low power mode', or 'when I open Steam, game mode on'.")
    if action == "cancel":
        return cancel(which or "all")
    return listing()
