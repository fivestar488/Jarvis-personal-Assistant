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
EMAIL_WATCH = os.getenv("JARVIS_EMAIL_WATCH", "on").lower() != "off"
EMAIL_WATCH_MINUTES = float(os.getenv("JARVIS_EMAIL_WATCH_MINUTES", "5"))
SPOTIFY_CLIENT_ID = os.getenv("JARVIS_SPOTIFY_CLIENT_ID", "")
OWNER_NAME = os.getenv("JARVIS_OWNER", "Jake Young")
USER_NAME = os.getenv("JARVIS_USER_NAME", "sir")  # how Jarvis addresses you
THINKING_PHRASE = os.getenv("JARVIS_THINKING_PHRASE", "Thinking...")
MODEL = os.getenv("JARVIS_MODEL", "claude-opus-5-5")
# low = snappy replies, which suits a voice assistant. Raise to medium/high for harder tasks.
EFFORT = os.getenv("JARVIS_EFFORT", "low")
# Background jobs (sorting new emails) always use the cheapest model, whatever MODEL is set to.
HELPER_MODEL = os.getenv("JARVIS_HELPER_MODEL") or "claude-haiku-5-5"
# Free mode with a model on this PC through Ollama (see jarvis/local_brain.py):
#   claude = always Claude; local = always the local model; auto = Claude, or the local model when Claude can't answer
BRAIN = (os.getenv("JARVIS_BRAIN") or "claude").strip().lower()
LOCAL_MODEL = os.getenv("JARVIS_LOCAL_MODEL") or "llama3.2:3b"
OLLAMA_URL = os.getenv("JARVIS_OLLAMA_URL") or "http://localhost:11434"
# Daily API budget in dollars: a warning at 80%, and at 100% the cheapest model and no background jobs until
# midnight (he still answers). 0 = no budget.
DAILY_BUDGET = float(os.getenv("JARVIS_DAILY_BUDGET") or 1.00)
# Minutes before each calendar event that Jarvis briefs you on it (0 = off).
MEETING_BRIEF_MINUTES = int(os.getenv("JARVIS_MEETING_BRIEF_MINUTES") or 10)
# Proactive suggestions (offered reminders you approve or dismiss): at most this many a day. 0 = off.
SUGGESTIONS_PER_DAY = int(os.getenv("JARVIS_SUGGESTIONS_PER_DAY") or 3)
# Nightly memory tidy-up (merges duplicate memories, replaces outdated ones). on/off
MEMORY_TIDY = os.getenv("JARVIS_MEMORY_TIDY", "on").lower() not in ("off", "false", "0", "no")
# Your private Telegram bot's token from @BotFather (blank = Telegram off). See "Telegram" in the README.
TELEGRAM_TOKEN = os.getenv("JARVIS_TELEGRAM_TOKEN", "").strip()
# After this long without a command, Jarvis starts a fresh conversation instead of re-sending the old one.
IDLE_RESET_MINUTES = int(os.getenv("JARVIS_IDLE_RESET_MINUTES") or 60)

WAKE_WORDS = [w.strip().lower() for w in os.getenv("JARVIS_WAKE_WORDS", "jarvis,jervis,javis,jarvas,travis").split(",")]
# Say one of these (with or without "Jarvis") and he powers up like in the films: welcome home, weather, agenda.
# They work in hands-free mode without saying "Jarvis" first. Punctuation and apostrophes don't matter.
ACTIVATION_PHRASES = [p.strip() for p in (
    os.getenv("JARVIS_ACTIVATION_PHRASES")
    or "wake up daddy's home,wake up daddy is home,wake up daddies home,daddy's home,daddy is home,wake up,i'm home,honey i'm home"
).split(",") if p.strip()]
# Music for the power-up (a clap, or a clap plus "Wake up, daddy's home"), played in the background in the HUD.
# Put an audio file you own at data/activation-song.mp3 (or .m4a/.wav/.ogg), or give a file path here; "off" = none.
ACTIVATION_SONG = os.getenv("JARVIS_ACTIVATION_SONG", "").strip()
SONG_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".ogg": "audio/ogg"}


def activation_song_file():
    """The activation song's file on this PC, or None."""
    if ACTIVATION_SONG.lower() in ("off", "none", "no"):
        return None
    candidates = [Path(os.path.expandvars(os.path.expanduser(ACTIVATION_SONG)))] if ACTIVATION_SONG else \
        [DATA_DIR / f"activation-song{ext}" for ext in SONG_TYPES]
    return next((p for p in candidates if p.is_file() and p.suffix.lower() in SONG_TYPES), None)


# In the HUD, a spoken power-up phrase only counts once you clap (so the TV can't wake him). Typed ones don't need it.
CLAP_TO_WAKE = os.getenv("JARVIS_CLAP_TO_WAKE", "on").lower() not in ("off", "false", "0", "no")
VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
VOICE_RATE = os.getenv("JARVIS_VOICE_RATE", "+5%")     # speed, e.g. -5% or +10%
VOICE_PITCH = os.getenv("JARVIS_VOICE_PITCH", "+0Hz")  # e.g. -3Hz for deeper
WHISPER_MODEL = os.getenv("JARVIS_WHISPER_MODEL", "base.en")
# The HUD's own speech recognition (when the browser's isn't available) favours speed: tiny.en is ~3x faster.
HUD_WHISPER_MODEL = os.getenv("JARVIS_HUD_WHISPER_MODEL", "tiny.en")
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
# Desk scanner: a webcam pointed down at a mat. "auto" = a second camera if one is plugged in, else the main one.
DESK_CAMERA = (os.getenv("JARVIS_DESK_CAMERA") or "auto").strip().lower()
# Free offline mode's eyes for the desk scanner (a small vision model through Ollama)
LOCAL_VISION_MODEL = os.getenv("JARVIS_LOCAL_VISION_MODEL") or "moondream"

# Hide card numbers, passwords and keys before they reach the AI, memory or logs (see jarvis/privacy.py)
REDACT = (os.getenv("JARVIS_REDACT") or "on").strip().lower() != "off"
# Dictate anywhere: press this, speak, press it again, and the text is typed into the app you're in (blank = off)
DICTATE_HOTKEY = os.getenv("JARVIS_DICTATE_HOTKEY", "ctrl+alt+d").strip()
# Live captions: what Jarvis says shown at the bottom of the screen, over every app (also "captions on/off")
CAPTIONS = (os.getenv("JARVIS_CAPTIONS") or "off").strip().lower() == "on"
# "Open House" protocol: the apps it opens, comma-separated
OPEN_HOUSE = os.getenv("JARVIS_OPEN_HOUSE", "spotify, chrome")
# Mood mode: a Spotify search to play when it starts (blank = no music)
MOOD_MUSIC = os.getenv("JARVIS_MOOD_MUSIC", "")
# "What was I doing?" journal: notes the window you're in once a minute, kept only on this PC. Off unless you say so.
JOURNAL = (os.getenv("JARVIS_JOURNAL") or "off").strip().lower() == "on"
# Ask my files: folders to search (comma-separated). Default: Documents and Desktop.
FILE_FOLDERS = [p.strip() for p in (os.getenv("JARVIS_FILE_FOLDERS") or "~/Documents,~/Desktop").split(",") if p.strip()]
# Clipboard history ("paste what I copied about the flights"): kept in memory only, never saved
CLIPBOARD_HISTORY = (os.getenv("JARVIS_CLIPBOARD_HISTORY") or "on").strip().lower() != "off"
# End-of-day wrap-up time (HH:MM, blank = off) and the Sunday weekly review
DAY_WRAP = os.getenv("JARVIS_DAY_WRAP", "21:30").strip()
# Perimeter alerts: failed Windows sign-ins and new devices on your home Wi-Fi
PERIMETER = (os.getenv("JARVIS_PERIMETER") or "on").strip().lower() != "off"
# Offline "Hey Jarvis" wake word (a tiny detector on this PC). Also "offline wake word on/off".
WAKE_WORD = (os.getenv("JARVIS_WAKE_WORD") or "off").strip().lower() == "on"
# Always-visible status strip in the corner of the screen (also "status strip on/off")
STATUS_STRIP = (os.getenv("JARVIS_STATUS_STRIP") or "off").strip().lower() == "on"

# Seconds Jarvis keeps listening for a follow-up after answering, without needing the wake word again.
FOLLOW_UP_SECONDS = float(os.getenv("JARVIS_FOLLOW_UP_SECONDS", "6"))
