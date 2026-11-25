"""'Leave now' nudges: for calendar events with an address, Jarvis works out the travel time and tells you when to
set off: ten minutes before you need to leave, and again when it's time.

Free and keyless: addresses are found with OpenStreetMap's Nominatim, and drive times come from the public OSRM
router (walking and cycling from the FOSSGIS routers). Neither is guaranteed, so if a router doesn't answer, Jarvis
estimates from the straight-line distance. Online meetings (Zoom, Teams, Meet, links) are skipped.
Home is JARVIS_HOME_ADDRESS, or your rough location from your internet connection if that's blank.
"""
import datetime as dt
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config, notify
from .tools import tool

GEOCACHE = config.DATA_DIR / "geocache.json"
UA = {"User-Agent": "JARVIS-desktop-assistant/1.0 (open-source personal assistant)"}
ROUTERS = {"driving": "https://router.project-osrm.org/route/v1/driving/",
           "walking": "https://routing.openstreetmap.de/routed-foot/route/v1/driving/",
           "cycling": "https://routing.openstreetmap.de/routed-bike/route/v1/driving/"}
SPEED_KMH = {"driving": 40, "walking": 4.8, "cycling": 15}  # for the straight-line estimate
VERB = {"driving": "drive", "walking": "walk", "cycling": "ride"}
ONLINE = re.compile(r"https?://|zoom|teams|meet\.google|google meet|webex|skype|online|virtual|\bcall\b|phone|"
                    r"discord|slack|whereby|^tbd$|^tba$", re.I)
LOOK_AHEAD_HOURS = 4

_geo_lock = threading.Lock()
_last_geo = [0.0]
_routes = {}   # (event id, location) -> (minutes, how)
_nudged = {}   # event id -> set of nudges given ("soon", "now", "late")


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def geocode(place):
    """An address -> (lat, lon), cached on this PC. Nominatim asks for at most one request a second."""
    key = " ".join(place.lower().split())
    try:
        cache = json.loads(GEOCACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return tuple(cache[key]) if cache[key] else None
    with _geo_lock:
        wait = 1.1 - (time.monotonic() - _last_geo[0])
        if wait > 0:
            time.sleep(wait)
        _last_geo[0] = time.monotonic()
        found = _get("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(place))
    spot = (float(found[0]["lat"]), float(found[0]["lon"])) if found else None
    cache[key] = spot
    GEOCACHE.write_text(json.dumps(cache), encoding="utf-8")
    return spot


def home():
    if config.HOME_ADDRESS:
        spot = geocode(config.HOME_ADDRESS)
        if spot:
            return spot
    from . import feeds
    loc = feeds.location()
    return loc["lat"], loc["lon"]


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def travel_minutes(a, b, mode=None):
    """(minutes, 'route' or 'estimate') from a to b."""
    mode = mode if mode in ROUTERS else config.TRAVEL_MODE if config.TRAVEL_MODE in ROUTERS else "driving"
    try:
        r = _get(f"{ROUTERS[mode]}{a[1]},{a[0]};{b[1]},{b[0]}?overview=false")
        if r.get("code") == "Ok" and r.get("routes"):
            return max(1, round(r["routes"][0]["duration"] / 60)), "route"
    except Exception:
        pass
    return max(1, round(_km(a, b) * 1.35 / SPEED_KMH[mode] * 60)), "estimate"


def _events():
    from . import google_tools
    now = dt.datetime.now().astimezone()
    out = []
    for e in google_tools.list_events(now, now + dt.timedelta(hours=LOOK_AHEAD_HOURS)):
        loc = (e.get("location") or "").strip()
        if e["all_day"] or not loc or ONLINE.search(loc):
            continue
        start = dt.datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone()
        if start > now:
            out.append((e, start, loc))
    return out


def plan(event, start, loc):
    """(leave_at, minutes, how) for one event, or None if the address can't be found."""
    key = (event["id"], loc)
    if key not in _routes:
        spot = geocode(loc)
        if not spot:
            _routes[key] = None
        else:
            _routes[key] = travel_minutes(home(), spot)
    if not _routes[key]:
        return None
    minutes, how = _routes[key]
    return start - dt.timedelta(minutes=minutes + config.LEAVE_BUFFER_MINUTES), minutes, how


def _place(loc):
    return loc.split(",")[0].strip()[:60]


def _trip(minutes, how):
    mode = config.TRAVEL_MODE if config.TRAVEL_MODE in VERB else "driving"
    about = "about " if how == "estimate" else ""
    return f"{about}{minutes} minute{'s' if minutes != 1 else ''}' {VERB[mode]}"


def check():
    """Give any nudges that are due."""
    now = dt.datetime.now().astimezone()
    for event, start, loc in _events():
        try:
            p = plan(event, start, loc)
        except Exception:
            continue
        if not p:
            continue
        leave_at, minutes, how = p
        given = _nudged.setdefault(event["id"], set())
        title = event["title"]
        if now >= leave_at and "now" not in given and "late" not in given:
            late = now - leave_at > dt.timedelta(minutes=15)
            given.add("late" if late else "now")
            given.add("soon")
            if late:
                text = (f"{config.USER_NAME.capitalize()}, you're cutting it fine for {title} at {start:%H:%M}: it's "
                        f"{_trip(minutes, how)} to {_place(loc)}.")
            else:
                text = (f"Time to leave for {title}, {config.USER_NAME}. It's {_trip(minutes, how)} to {_place(loc)}; "
                        f"you'll arrive around {now + dt.timedelta(minutes=minutes):%H:%M}.")
            notify.alert("Leave now", text, level="caution")
        elif now >= leave_at - dt.timedelta(minutes=10) and not given:
            given.add("soon")
            notify.alert("Leave soon", f"{config.USER_NAME.capitalize()}, you'll need to leave for {title} in about "
                                       f"{max(1, round((leave_at - now).total_seconds() / 60))} minutes. It's "
                                       f"{_trip(minutes, how)} to {_place(loc)}.", level="note")


def leave_advice():
    """'When should I leave?' for the next event with an address today."""
    from . import google_tools
    if not google_tools.connected():
        return "Your calendar isn't connected, sir."
    events = _events()
    if not events:
        return f"Nothing with an address in the next {LOOK_AHEAD_HOURS} hours, sir."
    event, start, loc = events[0]
    try:
        p = plan(event, start, loc)
    except Exception as e:
        return f"I couldn't work out the journey to {_place(loc)}: {e}"
    if not p:
        return f"I couldn't find {loc} on the map, sir."
    leave_at, minutes, how = p
    now = dt.datetime.now().astimezone()
    if leave_at <= now:
        return f"You should leave now for {event['title']}, sir. It's {_trip(minutes, how)} to {_place(loc)}."
    return (f"Leave by {leave_at:%H:%M} for {event['title']} at {start:%H:%M}, sir: {_trip(minutes, how)} to "
            f"{_place(loc)}, plus {config.LEAVE_BUFFER_MINUTES} minutes to spare.")


def start():
    if not config.LEAVE_NUDGES:
        return

    def loop():
        from . import google_tools
        time.sleep(90)
        while True:
            try:
                if google_tools.connected():
                    check()
            except Exception:
                pass
            time.sleep(180)
    threading.Thread(target=loop, daemon=True, name="commute").start()


@tool("When he needs to leave for his next calendar event that has an address (travel time from home by his "
      "travel mode, plus a buffer). He also gets 'leave now' nudges automatically.")
def when_to_leave():
    return leave_advice()
