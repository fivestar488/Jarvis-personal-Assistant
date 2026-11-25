"""Routines: "save a routine called focus mode: close Chrome, open Spotify and VS Code, volume down". Jarvis saves it
as a list of his own tool calls, and "Jarvis, focus mode" replays them later with no API call. Anything risky in a
routine (closing apps, running commands, sending email) still asks for permission each time it runs."""
import datetime as dt
import json

from . import config, tools
from .tools import S, tool

ROUTINES_FILE = config.DATA_DIR / "routines.json"
MAX_STEPS = 15
NOT_IN_ROUTINES = {"save_routine", "run_routine", "delete_routine", "list_routines"}


def _load():
    try:
        return json.loads(ROUTINES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def names():
    return list(_load())


def _summary(content):
    if isinstance(content, list):  # e.g. a screenshot: an image plus a note
        return " ".join(b.get("text", "[image]") for b in content if isinstance(b, dict))
    return str(content)


@tool("Save a named routine: a fixed list of your own tool calls to replay later with 'Jarvis, <name>' (no AI needed "
      "then). Use when the user says 'save a routine', 'create a shortcut', 'when I say X, do Y and Z'. Build the "
      "steps from your tools, with the exact arguments each needs. Saving again with the same name replaces it.",
      {"name": S("Short name to say, e.g. 'focus mode', 'start my day'"),
       "steps": {"type": "array", "description": "The tool calls, in order",
                 "items": {"type": "object", "required": ["tool", "args"], "properties": {
                     "tool": S("A tool name, e.g. close_application"),
                     "args": {"type": "object", "description": "That tool's arguments"}}}}},
      ["name", "steps"])
def save_routine(name, steps):
    name = " ".join(name.lower().split())
    if not name:
        return "Give the routine a name."
    if not steps or len(steps) > MAX_STEPS:
        return f"A routine needs between 1 and {MAX_STEPS} steps."
    for s in steps:
        if s.get("tool") not in tools.TOOLS or s["tool"] in NOT_IN_ROUTINES:
            return f"'{s.get('tool')}' isn't a tool I can put in a routine. Nothing was saved."
        if not isinstance(s.get("args", {}), dict):
            return "Each step's args must be an object. Nothing was saved."
    routines = _load()
    routines[name] = {"steps": [{"tool": s["tool"], "args": s.get("args", {})} for s in steps],
                      "saved": dt.datetime.now().isoformat(timespec="minutes")}
    ROUTINES_FILE.write_text(json.dumps(routines, indent=1, ensure_ascii=False), encoding="utf-8")
    listed = ", ".join(s["tool"].replace("_", " ") for s in steps)
    return f"Saved the routine \"{name}\" ({len(steps)} steps: {listed}). Say \"{name}\" to run it."


@tool("Run a saved routine by name.", {"name": S("The routine's name")}, ["name"])
def run_routine(name):
    routines = _load()
    key = " ".join(name.lower().split())
    if key not in routines:
        close = [n for n in routines if key in n or n in key]
        if len(close) != 1:
            return f"No routine called \"{name}\". Saved routines: {', '.join(routines) or 'none'}."
        key = close[0]
    from .vitals import Progress
    steps = routines[key]["steps"]
    progress = Progress(f"{key.upper()} PROTOCOL", [s["tool"].replace("_", " ").title() for s in steps])
    results, failed = [], 0
    for i, s in enumerate(steps):
        content, is_error = tools.run(s["tool"], s["args"])
        failed += bool(is_error)
        results.append(f"{s['tool'].replace('_', ' ')}: {'failed - ' if is_error else ''}{_summary(content)[:150]}")
        progress.step(i, _summary(content)[:80], "caution" if is_error else "nominal")
    progress.done("Complete." if not failed else f"{failed} step(s) failed.", "caution" if failed else "nominal")
    return f"Ran \"{key}\". " + " | ".join(results)


@tool("List the saved routines and their steps.")
def list_routines():
    routines = _load()
    if not routines:
        return "No routines saved yet."
    return "\n".join(f"{n}: " + ", then ".join(f"{s['tool']}({json.dumps(s['args'], ensure_ascii=False)})" for s in r["steps"])
                     for n, r in routines.items())


@tool("Delete a saved routine.", {"name": S("The routine's name")}, ["name"])
def delete_routine(name):
    key = " ".join(name.lower().split())
    if not key:
        return "Say which routine to delete. Nothing was deleted."
    routines = _load()
    if key not in routines:
        return f"No routine called \"{name}\"."
    del routines[key]
    ROUTINES_FILE.write_text(json.dumps(routines, indent=1, ensure_ascii=False), encoding="utf-8")
    return f"Deleted the routine \"{key}\"."
