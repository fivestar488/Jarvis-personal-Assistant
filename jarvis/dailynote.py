"""Daily notes: "capture: call the bank about the card" adds a timestamped line to today's Markdown file in a folder
you own (Documents/Jarvis Daily Notes by default), one file per day, ready to open in Obsidian or any editor. The
folder is inside Documents, so "ask my files" finds them too. "What's in today's note?" reads it back.
"""
import datetime as dt
import os
import re
from pathlib import Path

from . import config
from .tools import S, tool


def folder():
    return Path(os.path.expandvars(os.path.expanduser(config.DAILY_NOTES_FOLDER)))


def _file(day):
    return folder() / f"{day:%Y-%m-%d}.md"


def add(text):
    text = " ".join(str(text).split()).strip()
    if not text:
        return "What should I write down, sir?"
    now = dt.datetime.now()
    path = _file(now.date())
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8") as f:
        if new:
            f.write(f"# {now:%A} {now.day} {now:%B %Y}\n\n")
        f.write(f"- {now:%H:%M} {text[:1].upper()}{text[1:]}\n")
    return "Captured, sir."


def read(day=None):
    day = day or dt.date.today()
    path = _file(day)
    when = "today's" if day == dt.date.today() else "yesterday's" if day == dt.date.today() - dt.timedelta(days=1) \
        else f"the {day:%d %B}"
    if not path.exists():
        return f"There's nothing in {when} note yet, sir."
    lines = [re.sub(r"^- (\d\d:\d\d) ", r"\1, ", l.strip()) for l in path.read_text(encoding="utf-8").splitlines()
             if l.startswith("- ")]
    if not lines:
        return f"{when.capitalize()} note is empty, sir."
    more = f" That's the last 8 of {len(lines)}." if len(lines) > 8 else ""
    return f"In {when} note: " + " ".join(f"{l.rstrip('.')}." for l in lines[-8:]) + more


@tool("Daily notes in Markdown (one file per day in his notes folder, Obsidian-friendly): 'add' a quick line "
      "('capture: ...', 'add to my daily note ...') or 'read' a day's note (date YYYY-MM-DD, default today).",
      {"action": {"type": "string", "enum": ["add", "read"]}, "text": S("For add: what to write down"),
       "date": S("For read: YYYY-MM-DD")})
def daily_note(action="add", text="", date=""):
    if action == "read":
        try:
            return read(dt.date.fromisoformat(date) if date else None)
        except ValueError:
            return read()
    return add(text)
