"""Free mode: a small AI model running on this PC through Ollama (https://ollama.com), no API credit needed.

It's less capable than Claude and, on a laptop without a graphics card, slower. To keep it quick it gets a short
system prompt, a short history, and only the handful of tools that match the request (sending all ~60 tool
descriptions would take a laptop CPU minutes to read). It can't search the web or see the screen.

JARVIS_BRAIN in .env: claude (default), local (always this), or auto (Claude, switching to this one when the
credit runs out or the internet/API is down, and trying Claude again after a while).
"""
import json
import re
import time
import urllib.request

import anthropic

from . import config, personality, tools

# Which tools to offer, by words in the request. Kept small on purpose: a tiny model picks better from few tools.
# Most specific first: only the first MAX_TOOLS matches are offered.
TOOL_GROUPS = [
    (r"\bgot it\b|stop reminding", ["acknowledge_reminder"]),
    (r"(cancel|delete|remove).*remind", ["cancel_reminder", "list_reminders"]),
    (r"(what|which|list|any).*remind", ["list_reminders"]),
    (r"remind|alarm|wake me|don't let me forget", ["set_reminder"]),
    (r"what'?s playing|this song|like (this|the) song", ["spotify_now_playing", "spotify_like_current"]),
    (r"youtube|video", ["play_youtube"]),
    (r"pause|resume|skip|next song|previous|volume|louder|quieter|mute", ["media_control"]),
    (r"spotify|\bplay\b|song|music|playlist", ["spotify_play", "spotify_control"]),
    (r"\b(open|launch|start)\b", ["open_application", "open_url"]),
    (r"\b(close|quit|kill)\b", ["close_application"]),
    (r"weather|rain|temperature|forecast|umbrella|\bcold\b|\bhot\b|sunny", ["get_weather"]),
    (r"news|headline", ["get_headlines"]),
    (r"e-?mail|inbox|gmail|\bmail\b", ["gmail_search", "gmail_read", "gmail_draft"]),
    (r"calendar|meeting|schedule|agenda|appointment|event|\bbusy\b|\bfree\b", ["calendar_events", "calendar_create_event"]),
    (r"remember|don't forget that", ["remember"]),
    (r"\bforget\b", ["forget"]),
    (r"\bnotes?\b|jot", ["save_note", "read_notes"]),
    (r"\bfiles?\b|folder|download|document", ["find_files", "list_directory", "open_path"]),
    (r"google|search|look up", ["google_search"]),
    (r"battery|\bcpu\b|memory usage|disk space|ram\b", ["system_status"]),
    (r"\block\b|shut ?down|restart|reboot|go to sleep", ["system_power"]),
    (r"clipboard|copy", ["get_clipboard", "set_clipboard"]),
    (r"\btype\b", ["type_text"]),
    (r"routine", ["run_routine", "list_routines"]),
    (r"security|guard|watch the room", ["start_security_mode", "stop_security_mode", "security_status"]),
    (r"what time|what'?s the time|what date|what'?s the date|what day", ["get_datetime"]),
]
# Tools that answer with a short confirmation ("Opened spotify."). Jarvis says it as it is instead of asking the
# model to word a reply, which on a laptop CPU saves 5-10 seconds.
SAY_RESULT = {"set_reminder", "cancel_reminder", "acknowledge_reminder", "open_application", "close_application",
              "open_url", "open_path", "google_search", "play_youtube", "spotify_play", "spotify_control",
              "spotify_like_current", "media_control", "remember", "forget", "save_note", "set_clipboard",
              "type_text", "system_power", "start_security_mode", "stop_security_mode"}
MAX_TOOLS = 3           # every tool description costs a laptop CPU seconds to read
MEMORY_FACTS = 8
HISTORY_EXCHANGES = 3   # earlier exchanges sent back each time (each costs CPU time to re-read)
MAX_STEPS = 6
CLAUDE_RETRY_MINUTES = 30

_claude_rest_until = 0.0


def rest_claude():
    """Auto mode: Claude just failed (no credit, offline...), so use the local model for a while."""
    global _claude_rest_until
    _claude_rest_until = time.monotonic() + CLAUDE_RETRY_MINUTES * 60


def claude_resting():
    return time.monotonic() < _claude_rest_until


def pick_tools(text):
    low = text.lower()
    names = []
    for pattern, group in TOOL_GROUPS:
        if re.search(pattern, low):
            names += [n for n in group if n in tools.TOOLS and n not in names]
    return names[:MAX_TOOLS]


def _short_schema(name):
    """The tool's schema with only the first sentence of its description: quicker for a laptop to read."""
    schema = dict(tools.TOOLS[name]["schema"])
    schema["description"] = re.split(r"(?<=[.!?])\s", schema["description"], maxsplit=1)[0]
    return schema


UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400}


def _clean_args(name, args):
    """Small models fill in tool arguments sloppily (e.g. at='20 minutes'). Fix the usual slips."""
    args = dict(args or {})
    if name == "set_reminder":
        at, secs = str(args.get("at") or ""), args.get("seconds")
        try:
            secs = int(float(secs)) if secs not in (None, "") else None
        except (TypeError, ValueError):
            secs = None
        if at and not re.fullmatch(r"\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", at.strip()):
            m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(second|sec|minute|min|hour|hr|day)", at.lower())
            if m and not secs:
                secs = int(float(m.group(1)) * UNITS[m.group(2)])
            args.pop("at")
        if secs:
            args["seconds"] = secs
            args.pop("at", None)
        else:
            args.pop("seconds", None)
    return args


def available():
    """Is Ollama running with the configured model downloaded?"""
    try:
        with urllib.request.urlopen(config.OLLAMA_URL.rstrip("/") + "/api/tags", timeout=2) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return False
    want = config.LOCAL_MODEL if ":" in config.LOCAL_MODEL else config.LOCAL_MODEL + ":latest"
    return want in models


def warm_up():
    """Load the model into memory now (and keep it there for an hour) so the first question isn't slow."""
    body = json.dumps({"model": config.LOCAL_MODEL, "prompt": "", "keep_alive": "60m"}).encode()
    try:
        req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/generate", body,
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=120).read()
    except Exception:
        pass


def _system():
    facts = tools.load_memory()[-MEMORY_FACTS:]
    memory = "\n".join(f"- {f}" for f in facts) or "(nothing yet)"
    return (f"You are JARVIS, {config.OWNER_NAME}'s personal assistant: calm, capable, quietly witty. "
            f"Call him \"{config.USER_NAME}\" now and then. {personality.prompt_line()}\n"
            "Your replies are read aloud: answer in one to three short plain sentences, no markdown, no lists. "
            "When a tool can do what he asks, call it. Tool results are real, live data: answer from them. "
            "Without a tool you can't browse the web or see the screen; if a question needs that, say so briefly. "
            "Don't make up facts.\n"
            f"Things you remember about him:\n{memory}")


class LocalBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(base_url=config.OLLAMA_URL, api_key="ollama", timeout=300, max_retries=0)
        self.history = []  # plain text only: [{"role": "user"/"assistant", "content": str}, ...]

    def reset(self):
        self.history = []

    def ask(self, text, on_text=None, on_status=None):
        chosen = pick_tools(text)
        schemas = [_short_schema(n) for n in chosen]
        messages = self.history[-HISTORY_EXCHANGES * 2:] + [{"role": "user", "content": text}]
        reply = ""
        for _ in range(MAX_STEPS):
            request = dict(model=config.LOCAL_MODEL, max_tokens=400, system=_system(), messages=messages)
            if schemas:
                request["tools"] = schemas
            if on_text:
                with self.client.messages.stream(**request) as stream:
                    for piece in stream.text_stream:
                        on_text(piece)
                    response = stream.get_final_message()
                on_text(None)
            else:
                response = self.client.messages.create(**request)
            reply = "".join(b.text for b in response.content if b.type == "text").strip()
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                break
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content
                                                              if b.type in ("text", "tool_use")]})
            results = []
            for block in calls:
                if block.name not in chosen:  # small models sometimes invent tools
                    content, is_error = f"Unknown tool: {block.name}", True
                else:
                    if on_status:
                        on_status(f"{block.name}(local)")
                    content, is_error = tools.run(block.name, _clean_args(block.name, block.input))
                if not isinstance(content, str):  # images etc.: a local text model can't use them
                    content = "Done (the result was an image, which offline mode can't look at)."
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})
            if all(b.name in SAY_RESULT for b in calls) and not any(r["is_error"] for r in results):
                reply = " ".join(re.sub(r"\s*\(id \w+\)", "", r["content"]) for r in results)
                if on_text:
                    on_text(reply)
                    on_text(None)
                break
        reply = reply or "Done."
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        self.history = self.history[-HISTORY_EXCHANGES * 2:]
        return reply
