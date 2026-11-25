"""Meeting mode: Jarvis writes down what's said in a meeting, with times, and sums it up with action items.

"Start meeting" -> the HUD listens to everything (not just "Jarvis, ...") and sends it here line by line.
"Meeting summary" -> a quick recap so far. "End meeting" -> a summary with action items and decisions, saved in
data/meetings/, added to your notes and sent to your phone. "Jarvis, ..." commands still work during a meeting.
"""
import datetime as dt
import json
import re
import threading
import urllib.request

from . import config, privacy, tools
from .tools import tool

FOLDER = config.DATA_DIR / "meetings"
SUMMARY_PROMPT = (
    "You write meeting minutes for {owner} from a rough speech-to-text transcript of a meeting he was in. Lines "
    "start with the time since the start; recognition errors are likely and only what his microphone heard is "
    "there. Write plain text (no markdown symbols, no headings with #) in this order: a 2 to 4 sentence summary; "
    "then 'Action items:' with one line per item starting with '- ' (who does it, if said); then 'Decisions:' the "
    "same way, only if any were made. Don't invent anything that isn't in the transcript. Keep it short.")
RECAP_PROMPT = ("Recap this meeting transcript so far in 2 or 3 short spoken sentences for {owner}, including any "
                "action items so far. Plain text. Don't invent anything.")

_lock = threading.Lock()
meeting = None  # {"start": datetime, "lines": [(seconds, text)], "file": Path} while one is running


def active():
    return meeting is not None


def _hud(event):
    return bool(tools.ui and hasattr(tools.ui, "hud") and tools.ui.hud(event))


def start():
    global meeting
    if meeting:
        return "Meeting mode is already on."
    FOLDER.mkdir(exist_ok=True)
    now = dt.datetime.now()
    with _lock:
        meeting = {"start": now, "lines": [], "file": FOLDER / f"{now:%Y-%m-%d %H%M}.md"}
        meeting["file"].write_text(f"# Meeting {now:%A %d %B %Y, %H:%M}\n\n## Transcript\n", encoding="utf-8")
    if not _hud({"type": "meeting", "on": True}):
        meeting = None
        return "Meeting mode needs the HUD open, so I can listen. Start Jarvis with jarvis.bat."
    return ("Meeting mode on. I'll take notes of everything I hear. Say 'Jarvis, meeting summary' for a recap, "
            "or 'Jarvis, end meeting' when you're done.")


def add(text):
    """A line heard during the meeting (from the HUD)."""
    text = privacy.redact(" ".join(str(text).split()))
    if not meeting or not text:
        return
    with _lock:
        seconds = int((dt.datetime.now() - meeting["start"]).total_seconds())
        meeting["lines"].append((seconds, text))
        with open(meeting["file"], "a", encoding="utf-8") as f:
            f.write(f"[{_clock(seconds)}] {text}\n")


def _clock(seconds):
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _transcript(heard, max_words=None):
    lines = [f"[{_clock(s)}] {t}" for s, t in heard]
    if max_words:  # keep the end of a long meeting for a small model
        kept, words = [], 0
        for line in reversed(lines):
            words += len(line.split())
            if words > max_words:
                break
            kept.append(line)
        lines = list(reversed(kept))
    return "\n".join(lines)


def _write(system, transcript, max_tokens):
    """Claude, or the free local model in offline mode."""
    import anthropic
    from . import local_brain, spend
    local = config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))
    if not local:
        try:
            response = anthropic.Anthropic().messages.create(
                model=config.HELPER_MODEL, max_tokens=max_tokens, output_config={"effort": "low"},
                system=system, messages=[{"role": "user", "content": transcript}])
            spend.record(response.model or config.HELPER_MODEL, response.usage, "meeting minutes")
            return next((b.text for b in response.content if b.type == "text"), "").strip()
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            no_credit = isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e.message).lower()
            if no_credit or isinstance(e, (anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    body = {"model": config.LOCAL_MODEL, "stream": False, "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m",
            "options": {"num_predict": min(max_tokens, 400), "temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": transcript}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["message"]["content"].strip()
    finally:
        local_brain.prompt_disturbed()


def _tidy(text):
    """Small models add lead-ins ('Here's a recap for Jake:', 'Summary:'). Drop them."""
    lines = text.strip().splitlines()
    if len(lines) > 1 and lines[0].rstrip().endswith(":") and len(lines[0]) < 80:
        lines = lines[1:]
    text = "\n".join(lines).strip()
    return re.sub(r"^(summary|recap)\s*:\s*", "", text, flags=re.I)


def recap():
    if not meeting:
        return "There's no meeting running. Say 'start meeting' first."
    if not meeting["lines"]:
        return "I haven't heard anything yet in this meeting."
    small = 1500 if config.BRAIN == "local" else None  # a small local model reads the last part only
    return _tidy(_write(RECAP_PROMPT.format(owner=config.OWNER_NAME), _transcript(meeting["lines"], small), 600))


def end():
    global meeting
    if not meeting:
        return "There's no meeting running."
    with _lock:
        m, meeting = meeting, None
    _hud({"type": "meeting", "on": False})
    minutes_long = max(1, round((dt.datetime.now() - m["start"]).total_seconds() / 60))
    if not m["lines"]:
        m["file"].unlink(missing_ok=True)
        return "Meeting mode off. I didn't hear anything, so there are no notes."
    small = 1800 if config.BRAIN == "local" else None
    try:
        text = _tidy(_write(SUMMARY_PROMPT.format(owner=config.OWNER_NAME), _transcript(m["lines"], small), 2000))
    except Exception as e:
        return f"Meeting mode off. The transcript is saved in {m['file'].name}, but I couldn't summarise it: {e}"
    with open(m["file"], "a", encoding="utf-8") as f:
        f.write(f"\n## Minutes\n\n{text}\n")
    tools.save_note(f"Meeting {m['start']:%d %b %H:%M} ({minutes_long} min): " + " ".join(text.split())[:1500])
    try:
        from . import notify
        threading.Thread(target=notify.push, args=("Meeting notes", text[:900]), daemon=True).start()
    except Exception:
        pass
    actions = [line[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]
    summary = text.split("Action items:")[0].strip()
    spoken = f"Meeting mode off, after {minutes_long} minute{'s' if minutes_long != 1 else ''}. {summary}"
    if actions:
        spoken += f" There {'is one action item' if len(actions) == 1 else f'are {len(actions)} action items'}: " \
                  + "; ".join(actions[:5]) + "."
    return spoken + " The full minutes are in your notes and on your phone."


@tool("Meeting mode: start taking notes of a meeting (everything the HUD hears), give a recap so far, or end it "
      "with a summary and action items saved to notes. 'start meeting', 'meeting summary', 'end meeting'.",
      {"action": {"type": "string", "enum": ["start", "recap", "end"]}}, ["action"])
def meeting_mode(action):
    return {"start": start, "recap": recap, "end": end}[action]()
