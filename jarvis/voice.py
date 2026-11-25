"""Ears (microphone -> text, using Whisper locally) and mouth (text -> speech, using Microsoft Edge neural voices)."""
import asyncio
import os
import re
import tempfile
import threading

from . import config


def speakable(text):
    """Strip markdown and links so the voice doesn't read out symbols."""
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceSplitter:
    """Collects streamed reply text and hands back each complete sentence, so the first one can be spoken while
    the rest is still being written. Very short pieces wait for more ("Okay." on its own sounds clipped)."""
    END = re.compile(r"(?<=[.!?…])[\"')\]]?\s+|\n\s*\n")
    # The first piece may also end at a natural pause (comma, colon, dash), so he starts talking sooner
    PAUSE = re.compile(r"(?<=[,;:—–])\s+")
    MIN_CHARS = 20
    MIN_FIRST_PAUSE_CHARS = 30

    def __init__(self, emit):
        self.emit, self.buf, self.started = emit, "", False

    def feed(self, text):
        self.buf += text
        while True:
            m = next((m for m in self.END.finditer(self.buf) if m.start() >= self.MIN_CHARS), None)
            if not m and not self.started:
                m = next((m for m in self.PAUSE.finditer(self.buf) if m.start() >= self.MIN_FIRST_PAUSE_CHARS), None)
            if not m:
                return
            sentence, self.buf = self.buf[:m.end()].strip(), self.buf[m.end():]
            if speakable(sentence):
                self.started = True
                self.emit(sentence)

    def flush(self):
        rest, self.buf = self.buf.strip(), ""
        if speakable(rest):
            self.emit(rest)


_spoken_cache = {}  # short phrases he says often ("Paused.", "Done.") -> their audio, so they play instantly

# A voice that fits the moment. The free Edge voices don't take speaking styles (whispering, cheerful), so each tone
# is a change of speed (%), volume (%) and pitch (Hz) on top of your JARVIS_VOICE_RATE / _PITCH.
TONES = {
    "night": (-6, -35, -2),   # late at night: slower and much quieter
    "alert": (12, 0, 1),      # warnings: brisk
    "warm": (-3, 0, 2),       # good news: a touch slower and brighter
}
GOOD_NEWS = re.compile(r"\b(congratulations|good news|great news|well done|happy birthday|splendid|excellent news|"
                       r"you did it|nicely done|delivered)\b", re.I)


def tone_for(text, level=None):
    """Which tone to use: an alert's level, else the time of day, else the words themselves. None = normal."""
    if not config.VOICE_TONE:
        return None
    import datetime as dt
    if level in ("warning", "critical"):
        return "alert"
    hour = dt.datetime.now().hour
    if hour >= 23 or hour < 6:
        return "night"
    if GOOD_NEWS.search(text or ""):
        return "warm"
    return None


def _shift(base, delta, unit):
    m = re.fullmatch(r"([+-]?\d+)" + unit, (base or f"+0{unit}").strip())
    value = (int(m.group(1)) if m else 0) + delta
    return f"{value:+d}{unit}"


async def synthesize(text, tone="auto", level=None):
    """Text -> MP3 bytes in Jarvis's voice. tone: 'auto' (see tone_for), None, or a name from TONES."""
    import edge_tts
    if tone == "auto":
        tone = tone_for(text, level)
    rate_d, volume_d, pitch_d = TONES.get(tone, (0, 0, 0))
    rate, volume = _shift(config.VOICE_RATE, rate_d, "%"), _shift("+0%", volume_d, "%")
    pitch = _shift(config.VOICE_PITCH, pitch_d, "Hz")
    key = (speakable(text), config.VOICE, rate, volume, pitch)
    if key in _spoken_cache:
        return _spoken_cache[key]
    audio = bytearray()
    async for chunk in edge_tts.Communicate(key[0], config.VOICE, rate=rate, volume=volume, pitch=pitch).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    audio = bytes(audio)
    if len(key[0]) <= 40 and audio:
        if len(_spoken_cache) > 200:
            _spoken_cache.pop(next(iter(_spoken_cache)))
        _spoken_cache[key] = audio
    return audio


_whisper = {}
_whisper_lock = threading.Lock()


def whisper(name=None):
    """A Whisper model, loaded once. First use downloads it (~75 MB for tiny.en, ~150 MB for base.en)."""
    name = name or config.HUD_WHISPER_MODEL
    with _whisper_lock:
        if name not in _whisper:
            from faster_whisper import WhisperModel
            _whisper[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _whisper[name]


def warm_whisper():
    """Load the HUD's model and run it once, so your first command isn't the slow one."""
    import numpy as np
    segments, _ = whisper().transcribe(np.zeros(16000, np.float32), language="en", vad_filter=True)
    list(segments)


def transcribe_pcm(pcm):
    """16 kHz mono 16-bit PCM bytes (what the HUD sends) -> text. Empty if it was just noise."""
    import numpy as np
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    if len(audio) < 16000 * 0.3:
        return ""
    segments, _ = whisper().transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                       initial_prompt="A conversation with Jarvis.", condition_on_previous_text=False)
    # Whisper "hears" words like "Thank you." in background noise; drop segments it isn't sure contain speech.
    return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()


class Ears:
    def __init__(self):
        import speech_recognition as sr

        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.8          # seconds of silence that end a sentence
        self.recognizer.dynamic_energy_threshold = True
        self.mic = sr.Microphone(sample_rate=16000)
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        self.model = whisper(config.WHISPER_MODEL)

    def listen(self, timeout=None, phrase_limit=15):
        """Wait for speech and return the transcript, or None if nobody spoke within `timeout` seconds."""
        with self.mic as source:
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except self.sr.WaitTimeoutError:
                return None
        import numpy as np
        samples = np.frombuffer(audio.get_raw_data(convert_rate=16000, convert_width=2), np.int16).astype(np.float32) / 32768
        segments, _ = self.model.transcribe(samples, language="en", beam_size=1, vad_filter=True)
        text = " ".join(s.text for s in segments).strip()
        return text or None


class Mouth:
    def __init__(self):
        self.lock = threading.Lock()  # reminders can fire from another thread; don't talk over ourselves
        self.engine = None
        try:
            import pygame
            pygame.mixer.init()
            self.pygame = pygame
        except Exception:
            self.pygame = None

    def say(self, text):
        if not text:
            return
        with self.lock:
            try:
                self._say_edge(text)
            except Exception:
                self._say_offline(text)  # no internet, or edge-tts failed

    def _say_edge(self, text):
        if not self.pygame:
            raise RuntimeError("pygame unavailable")
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(asyncio.run(synthesize(text)))
            music = self.pygame.mixer.music
            music.load(path)
            music.play()
            while music.get_busy():
                self.pygame.time.wait(50)
            music.unload()
        finally:
            os.remove(path)

    def _say_offline(self, text):
        import pyttsx3
        if self.engine is None:
            self.engine = pyttsx3.init()
        self.engine.say(speakable(text))
        self.engine.runAndWait()
