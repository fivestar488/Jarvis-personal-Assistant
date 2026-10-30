"""Live data for the HUD and for Jarvis: your location, weather (Open-Meteo, free, no key) and news headlines (RSS)."""
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from . import config

HEADERS = {"User-Agent": "Mozilla/5.0 (JARVIS personal assistant)"}
WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers", 81: "Showers",
    82: "Violent showers", 85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Severe thunderstorm",
}

_cache = {}
_lock = threading.Lock()


def _get(url, as_json=True):
    req = urllib.request.Request(url, headers=HEADERS)
    data = urllib.request.urlopen(req, timeout=15).read()
    return json.loads(data) if as_json else data


def _cached(key, seconds, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < seconds:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def geocode(place):
    found = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(place)).get("results")
    if not found:
        raise ValueError(f"Couldn't find a place called '{place}'.")
    r = found[0]
    return {"name": ", ".join(x for x in (r["name"], r.get("admin1"), r.get("country_code")) if x),
            "lat": r["latitude"], "lon": r["longitude"]}


def location():
    """Home location: JARVIS_LOCATION from .env, otherwise a best guess from your internet connection."""
    def fetch():
        if config.LOCATION:
            return geocode(config.LOCATION)
        ip = _get("https://ipapi.co/json/")
        return {"name": f"{ip['city']}, {ip.get('region_code') or ip.get('country_code')}",
                "lat": ip["latitude"], "lon": ip["longitude"]}
    return _cached("location", 6 * 3600, fetch)


def weather(place=None):
    loc = geocode(place) if place else location()
    imperial = config.WEATHER_UNITS == "imperial"

    def fetch():
        q = {
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto", "forecast_days": 4,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit" if imperial else "celsius",
            "wind_speed_unit": "mph" if imperial else "kmh",
        }
        w = _get("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q))
        c, d = w["current"], w["daily"]
        return {
            "location": loc,
            "units": {"temp": "°F" if imperial else "°C", "wind": "mph" if imperial else "km/h"},
            "current": {
                "temp": round(c["temperature_2m"]), "feels": round(c["apparent_temperature"]),
                "humidity": c["relative_humidity_2m"], "wind": round(c["wind_speed_10m"]),
                "code": c["weather_code"], "text": WMO.get(c["weather_code"], "Unknown"), "is_day": c["is_day"],
            },
            "daily": [
                {"date": d["time"][i], "code": d["weather_code"][i], "text": WMO.get(d["weather_code"][i], ""),
                 "high": round(d["temperature_2m_max"][i]), "low": round(d["temperature_2m_min"][i]),
                 "rain": d["precipitation_probability_max"][i]}
                for i in range(len(d["time"]))
            ],
        }
    return _cached(f"weather:{loc['lat']:.2f},{loc['lon']:.2f}", 600, fetch)


# Opinion pieces, live blogs and media items aren't straight news, so they're left out of the ticker.
NOT_NEWS = re.compile(
    r"^(opinion|analysis|comment|editorial|letters?|watch|video|live|listen|podcast|quiz|in pictures|photos)\b"
    r"|\|\s*opinion|\bopinion:|\blive updates\b|\blive:", re.I)
PER_SOURCE = 5


def _tag(el):
    return el.tag.rsplit("}", 1)[-1]  # strip XML namespaces (some feeds use RDF/Atom-style tags)


def _child(el, name):
    return next(((c.text or "").strip() for c in el if _tag(c) == name), "")


def _fetch_source(name, url):
    try:
        root = ET.fromstring(_get(url, as_json=False))
    except Exception:
        return []
    items = []
    for item in (e for e in root.iter() if _tag(e) in ("item", "entry")):  # RSS uses <item>, Atom uses <entry>
        title = _child(item, "title")
        title = re.sub(r"\s+-\s+(Reuters|AP News|The Associated Press)$", "", title)  # Google News adds " - Source"
        link = _child(item, "link") or next((c.get("href", "") for c in item if _tag(c) == "link"), "")
        if title and not NOT_NEWS.search(title):
            items.append({"title": title, "link": link, "source": name})
        if len(items) >= PER_SOURCE:
            break
    return items


def _same_story(a, b):
    wa, wb = (set(re.findall(r"[a-z]{4,}", t.lower())) for t in (a, b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def headlines(limit=48):
    """Top stories from several reliable outlets, interleaved so no single outlet dominates."""
    def fetch():
        with ThreadPoolExecutor(max_workers=12) as pool:  # fetch every outlet at once
            per_source = list(pool.map(lambda feed: _fetch_source(*feed), config.NEWS_FEEDS))
        mixed = []
        for round_ in range(PER_SOURCE):
            for items in per_source:
                if round_ < len(items) and not any(_same_story(items[round_]["title"], m["title"]) for m in mixed):
                    mixed.append(items[round_])
        return mixed
    return _cached("news", 600, fetch)[:limit]
