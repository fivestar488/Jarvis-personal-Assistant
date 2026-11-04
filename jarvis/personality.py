"""Personalities: change how Jarvis talks ("be concise", "sarcastic butler mode", "back to normal"). The choice is
saved, so it survives restarts."""
import json

from . import config
from .tools import S, tool

PERSONALITY_FILE = config.DATA_DIR / "personality.json"

PRESETS = {
    "jarvis": "",  # the default, described in the main system prompt
    "concise": "Be as brief as possible: the answer or the confirmation in a few words, no pleasantries, no wit.",
    "sarcastic": "Be a dry, sarcastic British butler: deadpan wit and gentle teasing in most replies, but still "
                 "genuinely helpful, and never sarcastic about anything serious, sad or urgent.",
    "warm": "Be warm, upbeat and encouraging, like a supportive friend, while staying efficient.",
    "formal": "Be impeccably formal, like a traditional English butler: proper, polite, no slang or jokes.",
}


def current():
    """(name, instruction) of the saved personality."""
    try:
        saved = json.loads(PERSONALITY_FILE.read_text(encoding="utf-8"))
        return saved["name"], saved["instruction"]
    except (FileNotFoundError, ValueError, KeyError):
        return "jarvis", ""


def prompt_line():
    """The line for the system prompt (empty for the default personality)."""
    name, instruction = current()
    return f"\nPersonality setting: {name}. {instruction} This overrides the tone described above.\n" if instruction else ""


@tool("Change how Jarvis talks, when the user asks for a different personality or tone (e.g. 'be concise', "
      "'sarcastic mode', 'be more formal', 'talk like a pirate', 'back to normal'). Saved, so it survives restarts.",
      {"style": {"type": "string", "enum": [*PRESETS, "custom"],
                 "description": "'jarvis' is the normal personality; 'custom' uses the description"},
       "description": S("For style 'custom': how to talk, in one sentence")},
      ["style"])
def set_personality(style, description=""):
    if style == "custom":
        if not description.strip():
            return "Describe the custom personality in a sentence."
        instruction = description.strip()
    else:
        instruction = PRESETS[style]
    PERSONALITY_FILE.write_text(json.dumps({"name": style, "instruction": instruction}), encoding="utf-8")
    if not instruction:
        return "Personality set back to normal Jarvis. From now on, talk in your usual way."
    return f"Personality set to {style}. From now on, in every reply: {instruction}"
