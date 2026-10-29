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

OWNER_NAME = os.getenv("JARVIS_OWNER", "Jake Young")
USER_NAME = os.getenv("JARVIS_USER_NAME", "sir")  # how Jarvis addresses you
THINKING_PHRASE = os.getenv("JARVIS_THINKING_PHRASE", "Thinking...")
MODEL = os.getenv("JARVIS_MODEL", "claude-opus-5-5")
# low = snappy replies, which suits a voice assistant. Raise to medium/high for harder tasks.
EFFORT = os.getenv("JARVIS_EFFORT", "low")

WAKE_WORDS = [w.strip().lower() for w in os.getenv("JARVIS_WAKE_WORDS", "jarvis,jervis,javis,jarvas,travis").split(",")]
VOICE = os.getenv("JARVIS_VOICE", "en-GB-RyanNeural")
WHISPER_MODEL = os.getenv("JARVIS_WHISPER_MODEL", "base.en")
# Seconds Jarvis keeps listening for a follow-up after answering, without needing the wake word again.
FOLLOW_UP_SECONDS = float(os.getenv("JARVIS_FOLLOW_UP_SECONDS", "6"))
