"""Offline "Hey Jarvis": a tiny wake-word detector that runs on this PC (no internet, nothing leaves the
computer). When it hears "Hey Jarvis", the HUD starts listening for your command, like pressing the hotkey.
Lighter and more private than always-on online speech recognition.

"Offline wake word on/off" (or JARVIS_WAKE_WORD=on). It uses the open-source openWakeWord "hey jarvis" models
(about 4 MB, downloaded into data/wakeword/ the first time), run directly with onnxruntime.
"""
import collections
import threading
import time
import urllib.request

import numpy as np

from . import config
from .tools import tool

FOLDER = config.DATA_DIR / "wakeword"
ON_FILE = config.DATA_DIR / "wakeword-on"
BASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
MODELS = ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx")
RATE, CHUNK = 16000, 1280            # 80 ms of audio per step
MEL_SAMPLES = 76 * 160 + 400         # enough audio for the 76 spectrogram frames one embedding needs
THRESHOLD = 0.5
on_wake = None                       # set by the server: what to do when it hears "Hey Jarvis"
_thread = None
_stop = threading.Event()


def _download():
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        path = FOLDER / name
        if not path.exists() or path.stat().st_size < 100_000:
            urllib.request.urlretrieve(BASE + name, path)


class Detector:
    """openWakeWord's pipeline: audio -> mel spectrogram -> speech embeddings -> "hey jarvis" score."""

    def __init__(self):
        import onnxruntime as ort
        _download()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # one core is plenty; leave the other for everything else
        load = lambda n: ort.InferenceSession(str(FOLDER / n), sess_options=opts, providers=["CPUExecutionProvider"])
        self.mel, self.emb, self.ww = (load(n) for n in MODELS)
        self.audio = np.zeros(MEL_SAMPLES, np.float32)
        self.embeddings = collections.deque(maxlen=16)

    def feed(self, chunk):
        """chunk: 1280 int16 samples. Returns the wake-word score (0 to 1)."""
        self.audio = np.concatenate([self.audio[len(chunk):], chunk.astype(np.float32)])
        spec = self.mel.run(None, {"input": self.audio[None, :]})[0].squeeze() / 10 + 2  # (frames, 32)
        window = spec[-76:]
        if window.shape[0] < 76:
            return 0.0
        e = self.emb.run(None, {"input_1": window[None, :, :, None].astype(np.float32)})[0].reshape(96)
        self.embeddings.append(e)
        if len(self.embeddings) < 16:
            return 0.0
        return float(self.ww.run(None, {"x.1": np.array(self.embeddings, np.float32)[None]})[0].squeeze())


def _listen():
    import pyaudio
    try:
        det = Detector()
    except Exception as e:
        print(f"  Offline wake word couldn't start: {e}")
        return
    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"  Offline wake word: no microphone ({e})")
        pa.terminate()
        return
    last = 0.0
    try:
        while not _stop.is_set():
            chunk = np.frombuffer(stream.read(CHUNK, exception_on_overflow=False), np.int16)
            if det.feed(chunk) >= THRESHOLD and time.time() - last > 2.5:
                last = time.time()
                det.embeddings.clear()  # don't trigger twice on the same words
                if on_wake:
                    on_wake()
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def enabled():
    return config.WAKE_WORD or ON_FILE.exists()


def start():
    global _thread
    if not enabled() or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_listen, daemon=True, name="wake-word")
    _thread.start()


def switch(on):
    if on:
        ON_FILE.touch()
        start()
        return ("Offline wake word on, sir. Say 'Hey Jarvis' and I'll listen; it runs on this PC only. You can turn "
                "off hands-free in the HUD to save the online speech service.")
    ON_FILE.unlink(missing_ok=True)
    _stop.set()
    return "Offline wake word off."


@tool("Turn the offline 'Hey Jarvis' wake word on or off (a tiny detector on this PC; when it hears 'Hey Jarvis' "
      "the HUD starts listening).", {"on": {"type": "boolean"}}, ["on"])
def offline_wake_word(on):
    return switch(on)
