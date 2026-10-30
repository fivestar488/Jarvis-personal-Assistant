"""The startup greeting: time of day, the weather, and what's left on today's calendar."""
import datetime as dt

from . import config, feeds, google_tools


def _time(iso):
    """'2026-10-30T20:00:00+02:00' -> '8 PM', '09:30' -> '9:30 AM' (reads naturally out loud)."""
    return dt.datetime.fromisoformat(iso).astimezone().strftime("%I:%M %p").lstrip("0").replace(":00", "")


def greeting():
    now = dt.datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    lines = [f"Good {part}, {config.USER_NAME}. Jarvis online."]

    try:
        w = feeds.weather()
        c = w["current"]
        town = w["location"]["name"].split(",")[0]
        lines.append(f"It's {c['temp']} degrees and {c['text'].lower()} in {town}.")
    except Exception:
        pass  # no internet: skip the weather rather than fail the greeting

    if google_tools.connected():
        try:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            events = google_tools.list_events(start, start + dt.timedelta(days=1))
            upcoming = [e for e in events if not e["all_day"] and dt.datetime.fromisoformat(e["end"]).astimezone() > now.astimezone()]
            if not upcoming:
                lines.append("Your calendar is clear for the rest of today.")
            else:
                items = [f"{e['title'].strip()} at {_time(e['start'])}" for e in upcoming[:3]]
                listed = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
                more = f", plus {len(upcoming) - 3} more" if len(upcoming) > 3 else ""
                lines.append(f"You have {len(upcoming)} thing{'s' if len(upcoming) > 1 else ''} left today: {listed}{more}.")
        except Exception:
            pass

    lines.append("How can I help?")
    return " ".join(lines)
