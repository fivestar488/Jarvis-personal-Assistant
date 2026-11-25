"""End-of-day wrap-up and the Sunday weekly review, built from what Jarvis already knows (free: no AI call).

Every evening at JARVIS_DAY_WRAP (default 21:30) Jarvis sums up the day: meetings, reminders still to come,
notes, meals, meetings minuted, API spend, and tomorrow's first event. On Sundays it's the whole week instead.
"Wrap up my day" / "weekly review" any time.
"""
import datetime as dt
import json
import threading
import time

from . import config, tools
from .tools import tool

STATE_FILE = config.DATA_DIR / "wrap-state.json"


def _events(start, end):
    from . import google_tools
    if not google_tools.connected():
        return None
    try:
        return [e for e in google_tools.list_events(start, end) if not e["all_day"]]
    except Exception:
        return None


def _notes_between(start, end):
    if not config.NOTES_FILE.exists():
        return 0
    n = 0
    for line in config.NOTES_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("- [") and start.strftime("%Y-%m-%d") <= line[3:13] <= end.strftime("%Y-%m-%d"):
            n += 1
    return n


def _spend_between(start, end):
    from . import spend
    data = spend._load()
    days = [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    return sum(data.get(d, {}).get("usd", 0) for d in days)


def _meetings_between(start, end):
    from . import minutes
    if not minutes.FOLDER.exists():
        return 0
    return sum(1 for p in minutes.FOLDER.glob("*.md") if start.isoformat() <= p.name[:10] <= end.isoformat())


def day_wrap(day=None):
    from . import meals
    day = day or dt.date.today()
    start = dt.datetime.combine(day, dt.time())
    parts = [f"Here's your day, {config.USER_NAME}."]
    events = _events(start, start + dt.timedelta(days=1))
    if events is not None:
        parts.append(f"You had {len(events)} event{'s' if len(events) != 1 else ''} on the calendar." if events
                     else "Nothing was on the calendar.")
    m = _meetings_between(day, day)
    if m:
        parts.append(f"I minuted {m} meeting{'s' if m != 1 else ''}; the notes are saved.")
    n = _notes_between(day, day)
    if n:
        parts.append(f"You saved {n} note{'s' if n != 1 else ''}.")
    t = meals.totals(day)
    if t["meals"]:
        parts.append(f"Food: about {t['calories']} calories and {t['protein_g']} grams of protein.")
    usd = _spend_between(day, day)
    if usd >= 0.01:
        parts.append(f"I cost ${usd:.2f} in API credit today.")
    upcoming = sorted(tools._load_reminders(), key=lambda r: r["due"])
    tomorrow = day + dt.timedelta(days=1)
    soon = [r for r in upcoming if r["due"][:10] <= tomorrow.isoformat()]
    if soon:
        parts.append(f"{len(soon)} reminder{'s' if len(soon) != 1 else ''} coming up, starting with {soon[0]['message'].rstrip('.')}.")
    nxt = _events(dt.datetime.combine(tomorrow, dt.time()), dt.datetime.combine(tomorrow, dt.time()) + dt.timedelta(days=1))
    if nxt:
        first = nxt[0]
        when = dt.datetime.fromisoformat(first["start"]).strftime("%H:%M")
        parts.append(f"Tomorrow starts with {first['title'].strip()} at {when}.")
    elif nxt is not None:
        parts.append("Tomorrow's calendar is clear.")
    if len(parts) == 1:
        parts.append("A quiet one: nothing logged today.")
    return " ".join(parts) + " Good night, sir." if dt.datetime.now().hour >= 20 else " ".join(parts)


def week_review(end=None):
    from . import meals
    end = end or dt.date.today()
    start = end - dt.timedelta(days=6)
    parts = [f"Your week in review, {config.USER_NAME}."]
    events = _events(dt.datetime.combine(start, dt.time()), dt.datetime.combine(end, dt.time()) + dt.timedelta(days=1))
    if events is not None:
        parts.append(f"{len(events)} calendar events this week.")
    m = _meetings_between(start, end)
    if m:
        parts.append(f"{m} meeting{'s' if m != 1 else ''} minuted.")
    n = _notes_between(start, end)
    if n:
        parts.append(f"{n} note{'s' if n != 1 else ''} saved.")
    logged = [meals.totals(start + dt.timedelta(days=i)) for i in range(7)]
    days_logged = [t for t in logged if t["meals"]]
    if days_logged:
        avg = sum(t["calories"] for t in days_logged) / len(days_logged)
        parts.append(f"You logged food on {len(days_logged)} day{'s' if len(days_logged) != 1 else ''}, about "
                     f"{round(avg)} calories a day on average.")
    usd = _spend_between(start, end)
    parts.append(f"API spend for the week: ${usd:.2f}." if usd >= 0.01 else "No API spend this week.")
    nxt = _events(dt.datetime.combine(end + dt.timedelta(days=1), dt.time()),
                  dt.datetime.combine(end + dt.timedelta(days=8), dt.time()))
    if nxt:
        parts.append(f"Next week you have {len(nxt)} event{'s' if len(nxt) != 1 else ''}, starting with "
                     f"{nxt[0]['title'].strip()} on {dt.datetime.fromisoformat(nxt[0]['start']):%A}.")
    return " ".join(parts)


@tool("End-of-day wrap-up (meetings, notes, meals, spend, reminders, tomorrow's first event) or the weekly review.",
      {"weekly": {"type": "boolean", "description": "true for the weekly review"}})
def wrap_up(weekly=False):
    return week_review() if weekly else day_wrap()


def start():
    if not config.DAY_WRAP:
        return
    try:
        hour, minute = map(int, config.DAY_WRAP.split(":"))
    except ValueError:
        return

    def loop():
        while True:
            time.sleep(60)
            now = dt.datetime.now()
            try:
                done = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
            except ValueError:
                done = {}
            if (now.hour, now.minute) >= (hour, minute) and done.get("last") != now.date().isoformat():
                done["last"] = now.date().isoformat()
                STATE_FILE.write_text(json.dumps(done))
                text = week_review() if now.weekday() == 6 else day_wrap()
                from . import notify
                notify.alert("Weekly review" if now.weekday() == 6 else "Day wrap-up", text, level="note", phone=True)
    threading.Thread(target=loop, daemon=True, name="day-wrap").start()
