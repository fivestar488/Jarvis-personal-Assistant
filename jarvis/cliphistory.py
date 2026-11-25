"""Clipboard history: "paste what I copied about the flights", "what did I copy earlier?".

Jarvis remembers the last 40 things you copied (text only), in memory only: never saved to disk, gone when Jarvis
closes. Secrets (cards, passwords, keys) are never kept. JARVIS_CLIPBOARD_HISTORY=off turns it off.
"""
import re
import threading
import time

from . import config, privacy
from .tools import S, tool

KEEP = 40
_items = []  # newest last: (time, text)
_lock = threading.Lock()


def _loop():
    import pyperclip
    last = None
    while True:
        time.sleep(1.5)
        try:
            text = pyperclip.paste()
        except Exception:
            continue
        if not text or text == last or len(text) > 20000:
            continue
        last = text
        if privacy.redact(text) != text:  # it had a secret in it: don't keep it at all
            continue
        with _lock:
            _items[:] = [i for i in _items if i[1] != text][-(KEEP - 1):] + [(time.time(), text)]


def start():
    if config.CLIPBOARD_HISTORY:
        threading.Thread(target=_loop, daemon=True, name="clipboard-history").start()


def find(about=""):
    """The best match for some words, or the latest if none given."""
    with _lock:
        items = list(_items)
    if not items:
        return None
    if not about.strip():
        return items[-1][1]
    words = [w for w in re.findall(r"[a-z0-9]{3,}", about.lower()) if w not in {"the", "that", "about", "copied", "copy"}]
    if not words:
        return items[-1][1]
    scored = [(sum(w in text.lower() for w in words), i, text) for i, (_, text) in enumerate(items)]
    best = max(scored)
    return best[2] if best[0] else None


def recall(about="", paste=True):
    text = find(about)
    if text is None:
        return "I don't have anything like that in your clipboard history, sir." if about else "Your clipboard history is empty."
    import pyperclip
    pyperclip.copy(text)
    preview = " ".join(text.split())[:80]
    if paste:
        import pyautogui
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        return f"Pasted: {preview}{'...' if len(text) > 80 else ''}"
    return f"It's back on your clipboard: {preview}{'...' if len(text) > 80 else ''}"


def listing():
    with _lock:
        items = list(_items)[-5:]
    if not items:
        return "Your clipboard history is empty."
    return "Recently copied: " + "; ".join(f"\"{' '.join(t.split())[:50]}\"" for _, t in reversed(items))


@tool("Clipboard history: find something he copied earlier by what it was about, and paste it (or just put it "
      "back on the clipboard). 'paste what I copied about the flights'. No 'about' = list the recent ones.",
      {"about": S("Words from what he copied"), "paste": {"type": "boolean", "description": "Paste it now (default true)"}})
def clipboard_history(about="", paste=True):
    return recall(about, paste) if about else listing()
