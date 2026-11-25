"""Undo: anything Jarvis adds for you (a calendar event, an email draft, a reminder, a note, a memory) can be taken
back for 10 minutes, by saying "undo that" or tapping UNDO in the HUD's activity log."""
import threading
import time
import uuid

from . import tools
from .tools import tool

UNDO_MINUTES = 10
_items = []  # newest last: {"id", "text", "fn", "until"}
_lock = threading.Lock()


def offer(text, fn):
    """Make an action undoable. text: what was done ("Added 'Gym' to your calendar"). fn: undoes it."""
    item = {"id": uuid.uuid4().hex[:8], "text": text, "fn": fn, "until": time.time() + UNDO_MINUTES * 60}
    with _lock:
        _items[:] = [i for i in _items if i["until"] > time.time()][-19:] + [item]
    if tools.ui and hasattr(tools.ui, "hud"):
        tools.ui.hud({"type": "undo_offer", "id": item["id"], "text": text, "seconds": UNDO_MINUTES * 60})
    return item["id"]


def undo(item_id=None):
    """Undo one action (the most recent if no id). Returns what to say."""
    with _lock:
        live = [i for i in _items if i["until"] > time.time()]
        item = next((i for i in live if i["id"] == item_id), None) if item_id else (live[-1] if live else None)
        if item:
            _items.remove(item)
    if not item:
        return "There's nothing to undo." if not item_id else "That can't be undone any more."
    if tools.ui and hasattr(tools.ui, "hud"):
        tools.ui.hud({"type": "undo_done", "id": item["id"]})
    try:
        item["fn"]()
    except Exception as e:
        return f"I couldn't undo that: {e}"
    return f"Undone: {item['text'][:1].lower()}{item['text'][1:]}."


@tool("Undo the last thing Jarvis added in the past 10 minutes (calendar event, email draft, reminder, note, "
      "memory). Use when he says 'undo that', 'take that back', 'cancel that'.")
def undo_last():
    return undo()
