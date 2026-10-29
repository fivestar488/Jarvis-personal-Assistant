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


async def synthesize(text):
    """Text -> MP3 bytes in Jarvis's voice."""
    import edge_tts
    audio = bytearray()
    async for chunk in edge_tts.Communicate(speakable(text), config.VOICE, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


class Ears:
    def __init__(self):
        import speech_recognition as sr
        from faster_whisper import WhisperModel

        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.8          # seconds of silence that end a sentence
        self.recognizer.dynamic_energy_threshold = True
        self.mic = sr.Microphone(sample_rate=16000)
        with self.mic as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        # First run downloads the model (~150 MB for base.en).
        self.model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")

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
