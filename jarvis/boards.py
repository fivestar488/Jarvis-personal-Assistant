"""Your real data as holograms, and a situation board with one threat level.

- "Show me my week": a 3D map of the next 7 days, each day bursting into its events.
- "Show me my inbox": unread emails grouped by sender (subjects only, secrets hidden).
- "Show me my spending" / "my calories": 3D bars for the last 14 days (API spend, or the meal log).
- "Situation report" / "threat assessment": weather, headlines and your next event, rated note / caution /
  warning / critical like every other alert, and shown as a panel.
"""
import datetime as dt
import re

from . import config, privacy, tools
from .tools import S, tool

SEVERE = re.compile(r"\b(earthquake|tsunami|missile|rocket|siren|air raid|terror|attack|shooting|explosion|evacuat\w*|"
                    r"wildfire|flood\w*|hurricane|cyclone|typhoon|tornado|blizzard|heatwave|heat wave|lockdown|outbreak)\b", re.I)
WMO_SEVERE = {95: "warning", 96: "warning", 99: "critical", 65: "caution", 67: "caution", 75: "caution", 82: "caution",
              86: "caution", 57: "caution", 66: "caution", 48: "caution"}
RANK = {"nominal": 0, "note": 1, "caution": 2, "warning": 3, "critical": 4}


def _send(event):
    from .hologram import _send as send
    return send(event)


def _week():
    from . import google_tools
    if not google_tools.connected():
        return None, "Your calendar isn't connected, sir. Run jarvis.bat --connect-google."
    start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    events = google_tools.list_events(start, start + dt.timedelta(days=7))
    days = []
    for i in range(7):
        day = (start + dt.timedelta(days=i)).date()
        todays = [e for e in events if e["start"][:10] == day.isoformat()]
        children = [{"name": e["title"].strip()[:40], "detail": "All day" if e["all_day"] else
                     f"{e['start'][11:16]} to {e['end'][11:16]}" + (f" at {e['location']}" if e["location"] else ""),
                     "children": []} for e in todays]
        label = "Today" if i == 0 else "Tomorrow" if i == 1 else f"{day:%A}"
        days.append({"name": f"{label} ({len(todays)})", "detail": f"{len(todays)} event{'s' if len(todays) != 1 else ''}",
                     "children": children})
    total = len(events)
    return {"name": "This week", "detail": f"{total} event{'s' if total != 1 else ''} in the next 7 days", "children": days}, \
        f"Your week, sir: {total} event{'s' if total != 1 else ''} over the next 7 days."


def _inbox():
    from . import google_tools
    if not google_tools.connected():
        return None, "Gmail isn't connected, sir. Run jarvis.bat --connect-google."
    gmail = google_tools._service("gmail", "v1")
    ids = [m["id"] for m in gmail.users().messages().list(userId="me", q="is:unread in:inbox", maxResults=25)
           .execute().get("messages", [])]
    senders = {}
    for i in ids:
        m = gmail.users().messages().get(userId="me", id=i, format="metadata", metadataHeaders=["From", "Subject"]).execute()
        h = {x["name"]: x["value"] for x in m["payload"].get("headers", [])}
        who = re.sub(r"\s*<.*?>", "", h.get("From", "Someone")).strip('" ') or "Someone"
        senders.setdefault(who[:30], []).append(privacy.redact(h.get("Subject", "(no subject)"))[:60])
    groups = sorted(senders.items(), key=lambda kv: -len(kv[1]))[:8]
    tree = {"name": f"Inbox ({len(ids)} unread)", "detail": "Grouped by sender. Pinch one to see its subjects.",
            "children": [{"name": who, "detail": f"{len(subs)} unread", "children": [
                {"name": s[:40], "detail": s, "children": []} for s in subs[:5]]} for who, subs in groups]}
    top = groups[0][0] if groups else ""
    return tree, (f"{len(ids)} unread, sir" + (f"; most of it from {top}." if top else ".")) if ids else "Inbox zero, sir."


def _bars(kind):
    today = dt.date.today()
    days = [today - dt.timedelta(days=13 - i) for i in range(14)]
    if kind == "spend":
        from . import spend
        data = spend._load()
        values = [round(data.get(d.isoformat(), {}).get("usd", 0), 3) for d in days]
        unit, title, said = "$", "API spend, 14 days", f"${sum(values):.2f} over the last two weeks, sir."
    else:
        from . import meals
        values = [meals.totals(d)["calories"] for d in days]
        unit, title, said = "kcal", "Calories, 14 days", (f"About {round(sum(values) / max(1, sum(1 for v in values if v)))} calories "
                                                          "a day on the days you logged, sir." if any(values) else
                                                          "No meals logged in the last two weeks, sir.")
    bars = [{"label": f"{d:%a %d}".upper(), "value": v} for d, v in zip(days, values)]
    return {"bars": bars, "unit": unit, "title": title}, said


def show(what):
    """Open a data hologram: week, inbox, spend or calories."""
    w = what.lower()
    try:
        if "week" in w or "calendar" in w or "schedule" in w:
            tree, said = _week()
            event = {"kind": "topic", "subject": "This week", "tree": tree} if tree else None
        elif "inbox" in w or "mail" in w:
            tree, said = _inbox()
            event = {"kind": "topic", "subject": "Inbox", "tree": tree} if tree else None
        elif "calor" in w or "food" in w or "meal" in w or "eat" in w:
            data, said = _bars("calories")
            event = {"kind": "data", "subject": data["title"], **data}
        else:
            data, said = _bars("spend")
            event = {"kind": "data", "subject": data["title"], **data}
    except Exception as e:
        return f"I couldn't build that view, sir: {e}"
    if event and not _send({"action": "open", **event}):
        return "Holograms need the HUD. Start Jarvis with jarvis.bat."
    return said


@tool("Show his real data as a 3D hologram on the HUD: 'week' (next 7 days of calendar), 'inbox' (unread email by "
      "sender), 'spend' (API spend, 14 days) or 'calories' (meal log, 14 days). 'show me my week'.",
      {"what": {"type": "string", "enum": ["week", "inbox", "spend", "calories"]}}, ["what"])
def show_my_data(what):
    return show(what)


# ---------- situation board ----------

def situation_items():
    from . import feeds
    items = []
    try:
        w = feeds.weather()
        u = w["units"]["temp"]
        for i, d in enumerate(w["daily"][:2]):
            when = "today" if i == 0 else "tomorrow"
            level = WMO_SEVERE.get(d["code"], "nominal")
            hot, cold = (35, -5) if u == "°C" else (95, 23)
            if d["high"] >= hot or d["low"] <= cold:
                level = max(level, "caution", key=lambda l: RANK[l])
            rain = d.get("rain") or 0
            if rain >= 70 and RANK[level] < 2:
                level = "caution"
            items.append({"name": f"Weather {when}", "level": level,
                          "detail": f"{d['text']}, {d['low']}{u} to {d['high']}{u}, {rain}% chance of rain"})
    except Exception:
        items.append({"name": "Weather", "level": "note", "detail": "No weather data right now"})
    try:
        place = feeds.location()["name"].split(",")[0].lower()
        heads = feeds.headlines(30)
        hot = [h for h in heads if SEVERE.search(h["title"])]
        local = [h for h in hot if place and place in h["title"].lower()]
        level = "warning" if local else "caution" if len(hot) >= 3 else "note" if hot else "nominal"
        items.append({"name": "News", "level": level, "detail": (local or hot)[0]["title"][:120] if hot else "Nothing alarming in the headlines"})
    except Exception:
        items.append({"name": "News", "level": "note", "detail": "No headlines right now"})
    try:
        from . import google_tools
        if google_tools.connected():
            now = dt.datetime.now()
            nxt = next((e for e in google_tools.list_events(now, now + dt.timedelta(days=1)) if not e["all_day"]
                        and dt.datetime.fromisoformat(e["start"]).replace(tzinfo=None) > now), None)
            if nxt:
                mins = int((dt.datetime.fromisoformat(nxt["start"]).replace(tzinfo=None) - now).total_seconds() // 60)
                items.append({"name": "Next event", "level": "caution" if mins <= 15 else "nominal",
                              "detail": f"{nxt['title'].strip()} in {mins} minutes" if mins < 120 else
                              f"{nxt['title'].strip()} at {nxt['start'][11:16]}"})
    except Exception:
        pass
    return items


def situation():
    items = situation_items()
    worst = max((i["level"] for i in items), key=lambda l: RANK[l], default="nominal")
    _send({"action": "open", "kind": "panel", "subject": "situation"})
    problems = [i for i in items if RANK[i["level"]] >= 2]
    lead = {"nominal": "Situation nominal, sir.", "note": "Situation nominal, sir.", "caution": "Threat level: caution, sir.",
            "warning": "Threat level: warning, sir.", "critical": "Threat level critical, sir."}[worst]
    said = "; ".join(f"{i['name'].lower()}: {i['detail']}" for i in (problems or items[:2]))
    return f"{lead} {said[:1].upper()}{said[1:]}."


@tool("Situation report / threat assessment: weather today and tomorrow, alarming headlines (especially local ones) "
      "and his next event, rated nominal, caution, warning or critical, shown as a HUD panel.")
def situation_report():
    return situation()
