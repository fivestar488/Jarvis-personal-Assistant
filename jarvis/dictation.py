"""Dictate anywhere: press the dictation hotkey (JARVIS_DICTATE_HOTKEY, default Ctrl+Alt+D) in any app, speak,
press it again, and what you said is typed where your cursor is (an email, a document, a chat). A high beep means
it's listening, a low one that it stopped. It stops by itself after 2 minutes.

Speech is turned into text on this PC (Whisper). The text is tidied up: filler words out, capitals and full
stops in; with API credit, a cheap Claude pass also fixes punctuation and misheard words.
"""
import re
import threading
import time
import winsound

from . import config

RATE = 16000
MAX_SECONDS = 120
FILLERS = re.compile(r"\b(?:um+|uh+|erm+|er|ah+|hmm+|mm+)\b[,.]?\s*", re.I)
POLISH_PROMPT = ("Clean up this dictated text: fix punctuation, capitalisation and obviously misheard words, and "
                 "remove filler words and false starts. Keep the meaning, wording and language; don't add anything "
                 "or answer it. Reply with only the cleaned text.")

_recording = None  # {"frames": [...], "stop": Event, "thread": Thread} while recording
_lock = threading.Lock()


def _beep(freq, ms):
    threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


def _status(text):
    from . import tools
    if tools.ui and hasattr(tools.ui, "hud"):
        tools.ui.hud({"type": "status", "text": text})


def _record(state):
    import pyaudio
    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=1024)
    except Exception as e:
        state["error"] = f"Couldn't open the microphone: {e}"
        pa.terminate()
        return
    started = time.time()
    try:
        while not state["stop"].is_set() and time.time() - started < MAX_SECONDS:
            state["frames"].append(stream.read(1024, exception_on_overflow=False))
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    if not state["stop"].is_set():  # ran out of time: finish as if the hotkey was pressed
        threading.Thread(target=toggle, daemon=True).start()


def clean(text):
    """Free tidy-up: no 'um's, a capital at the start, a full stop at the end."""
    text = FILLERS.sub("", text)
    text = re.sub(r"\s+([,.!?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()
    if text:
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?…":
            text += "."
    return text


def _polish(text):
    """A cheap Claude pass, only when Claude is in use and there's enough to be worth it."""
    from . import local_brain, spend
    if len(text.split()) < 8 or config.BRAIN == "local" or local_brain.claude_resting() or spend.over_budget():
        return text
    try:
        import anthropic
        response = anthropic.Anthropic().messages.create(
            model=config.HELPER_MODEL, max_tokens=2000, output_config={"effort": "low"},
            system=POLISH_PROMPT, messages=[{"role": "user", "content": text}])
        spend.record(response.model or config.HELPER_MODEL, response.usage, "dictation")
        polished = next((b.text for b in response.content if b.type == "text"), "").strip()
        # Guard against it answering instead of cleaning: the result should be about as long as what was said
        return polished if polished and 0.5 < len(polished) / len(text) < 1.6 else text
    except Exception:
        return text


def _paste(text):
    """Type it where the cursor is (pasting handles any characters), then put the clipboard back."""
    import pyautogui
    import pyperclip
    try:
        old = pyperclip.paste()
    except Exception:
        old = None
    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)
    if old is not None:
        try:
            pyperclip.copy(old)
        except Exception:
            pass


def _finish(state):
    state["thread"].join(timeout=3)
    if state.get("error"):
        _status(f"Dictation: {state['error']}")
        return
    audio = b"".join(state["frames"])
    if len(audio) < RATE * 2 * 0.4:  # under half a second: nothing said
        _status("Dictation: didn't hear anything.")
        return
    import numpy as np
    from .voice import whisper
    samples = np.frombuffer(audio, np.int16).astype(np.float32) / 32768
    segments, _ = whisper(config.WHISPER_MODEL).transcribe(samples, language="en", beam_size=1, vad_filter=True)
    text = clean(" ".join(s.text.strip() for s in segments))
    if not text:
        _status("Dictation: didn't catch any words.")
        return
    text = _polish(text)
    _paste(text)
    _status(f"Dictated: {text[:80]}{'...' if len(text) > 80 else ''}")


def toggle():
    """The hotkey: start listening, or stop and type what was said."""
    global _recording
    with _lock:
        if _recording is None:
            state = {"frames": [], "stop": threading.Event()}
            state["thread"] = threading.Thread(target=_record, args=(state,), daemon=True)
            _recording = state
            state["thread"].start()
            from .voice import whisper  # load the speech model while you talk (it's kept after the first time)
            threading.Thread(target=whisper, args=(config.WHISPER_MODEL,), daemon=True).start()
            _beep(1200, 90)
            _status("Dictating... press the hotkey again when you're done.")
            return
        state, _recording = _recording, None
        state["stop"].set()
    _beep(700, 90)
    threading.Thread(target=_finish, args=(state,), daemon=True).start()


def start_hotkey(on_error):
    if not config.DICTATE_HOTKEY:
        return
    from . import hotkey
    hotkey.start(config.DICTATE_HOTKEY, toggle, on_error, ident=2, setting="JARVIS_DICTATE_HOTKEY")
