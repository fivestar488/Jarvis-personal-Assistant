"""The startup greeting (time of day, the weather, what's left on today's calendar), and the
"Wake up, daddy's home" activation that gives the same briefing on demand."""
import datetime as dt
import re

from . import config, feeds, google_tools


def _time(iso):
    """'2026-10-30T20:00:00+02:00' -> '8 PM', '09:30' -> '9:30 AM' (reads naturally out loud)."""
    return dt.datetime.fromisoformat(iso).astimezone().strftime("%I:%M %p").lstrip("0").replace(":00", "")


def _plain(text):
    """'Jarvis, wake up! Daddy's home.' -> 'wake up daddys home' (no punctuation, no wake word)."""
    words = re.sub(r"[^a-z ]", " ", text.lower().replace("'", "").replace("’", "")).split()
    skip = set(config.WAKE_WORDS) | {"hey", "ok", "okay"}
    while words and words[0] in skip:
        words.pop(0)
    while words and words[-1] in skip:
        words.pop()
    return " ".join(words)


def is_activation(text):
    """True for "Wake up, daddy's home" and the other power-up phrases (config.ACTIVATION_PHRASES)."""
    return _plain(text) in {_plain(p) for p in config.ACTIVATION_PHRASES}


def welcome_home():
    """The reply to "Wake up, daddy's home": the line from the film, then the weather and agenda."""
    return greeting(f"Welcome home, {config.USER_NAME}. All systems are online.")


def greeting(opening=None):
    now = dt.datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    lines = [opening or f"Good {part}, {config.USER_NAME}. Jarvis online."]

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
