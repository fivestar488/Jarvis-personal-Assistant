"""Settings, loaded from the .env file next to jarvis.py."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"
NOTES_FILE = DATA_DIR / "notes.md"
LOG_FILE = DATA_DIR / "history.log"

PORT = int(os.getenv("JARVIS_PORT", "8765"))
HOTKEY = os.getenv("JARVIS_HOTKEY", "ctrl+alt+j")  # summons the HUD and starts listening, from any app
NETWORK_CHECK_SECONDS = 5  # how often Jarvis checks whether the phone link changed (new Wi-Fi etc.)
OWNER_NAME = os.getenv("JARVIS_OWNER", "Jake Young")
USER_NAME = os.getenv("JARVIS_USER_NAME", "sir")  # how Jarvis addresses you
THINKING_PHRASE = os.getenv("JARVIS_THINKING_PHRASE", "Thinking...")
MODEL = os.getenv("JARVIS_MODEL", "claude-opus-5-5")
# low = snappy replies, which suits a voice assistant. Raise to medium/high for harder tasks.
EFFORT = os.getenv("JARVIS_EFFORT", "low")

WAKE_WORDS = [w.strip().lower() for w in os.getenv("JARVIS_WAKE_WORDS", "jarvis,jervis,javis,jarvas,travis").split(",")]
VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
VOICE_RATE = os.getenv("JARVIS_VOICE_RATE", "+5%")     # speed, e.g. -5% or +10%
VOICE_PITCH = os.getenv("JARVIS_VOICE_PITCH", "+0Hz")  # e.g. -3Hz for deeper
WHISPER_MODEL = os.getenv("JARVIS_WHISPER_MODEL", "base.en")
LOCATION = os.getenv("JARVIS_LOCATION", "")  # e.g. "Manchester". Blank = detect from your internet connection
WEATHER_UNITS = os.getenv("JARVIS_WEATHER_UNITS", "metric")  # or "imperial"
# News ticker sources: a balanced mix of wire services and public broadcasters from several countries.
# Override in .env as JARVIS_NEWS_FEEDS=Name=url,Name=url
_GOOGLE_NEWS = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
DEFAULT_NEWS_FEEDS = [
    ("Reuters", _GOOGLE_NEWS + "site:reuters.com+when:1d"),
    ("AP", _GOOGLE_NEWS + "site:apnews.com+when:1d"),
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("DW", "https://rss.dw.com/rdf/rss-en-all"),
    ("PBS NewsHour", "https://www.pbs.org/newshour/feeds/rss/headlines"),
    ("Euronews", "https://www.euronews.com/rss?level=theme&name=news"),
    ("The Hill", "https://thehill.com/news/feed/"),
    # Tech
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("Wired", "https://www.wired.com/feed/rss"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
]
NEWS_FEEDS = [
    tuple(part.strip() for part in entry.split("=", 1))
    for entry in os.getenv("JARVIS_NEWS_FEEDS", "").split(",") if "=" in entry
] or DEFAULT_NEWS_FEEDS
CAMERA_INDEX = int(os.getenv("JARVIS_CAMERA_INDEX", "0"))

# Seconds Jarvis keeps listening for a follow-up after answering, without needing the wake word again.
FOLLOW_UP_SECONDS = float(os.getenv("JARVIS_FOLLOW_UP_SECONDS", "6"))
