"""Meal log: "log this meal" photographs your plate (the desk camera, or the laptop's), estimates calories and
protein, carbs and fat, and keeps a daily total. "How many calories today?" gives the total, and the morning
greeting mentions yesterday's. Estimates from a photo are rough: a guide, not a measurement.
"""
import base64
import datetime as dt
import json
import threading
import urllib.request

from . import config, tools
from .tools import S, tool

LOG_FILE = config.DATA_DIR / "meals.json"
MEAL_SCHEMA = {
    "type": "object",
    "properties": {
        "meal": {"type": "string"}, "calories": {"type": "integer"}, "protein_g": {"type": "integer"},
        "carbs_g": {"type": "integer"}, "fat_g": {"type": "integer"}, "note": {"type": "string"},
    },
    "required": ["meal", "calories", "protein_g", "carbs_g", "fat_g", "note"], "additionalProperties": False,
}
MEAL_PROMPT = ("Estimate the nutrition of the food in this photo, as served (the whole visible portion). meal: a "
               "short name ('chicken salad with bread'). Numbers are your best estimate. note: one short sentence "
               "on what you assumed, or 'No food visible' if there's no food (then all numbers 0).")
_lock = threading.Lock()


def _load():
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _estimate(jpeg, note):
    from . import local_brain, scanner
    question = MEAL_PROMPT + (f" He says: {note}" if note else "")
    if not scanner._use_local():
        import anthropic
        from . import spend
        try:
            response = anthropic.Anthropic().messages.create(
                model=config.HELPER_MODEL, max_tokens=1000,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": MEAL_SCHEMA}},
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(jpeg).decode()}},
                    {"type": "text", "text": question}]}])
            spend.record(response.model or config.HELPER_MODEL, response.usage, "meal log")
            return json.loads(next((b.text for b in response.content if b.type == "text"), "{}"))
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            no_credit = isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e.message).lower()
            if no_credit or isinstance(e, (anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    # Free mode: the small vision model names the food, the chat model estimates the numbers
    name = note or scanner._ask_local(jpeg, "")["name"]
    body = {"model": config.LOCAL_MODEL, "stream": False, "format": MEAL_SCHEMA,
            "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m", "options": {"num_predict": 120, "temperature": 0.2},
            "messages": [{"role": "user", "content": f"Estimate typical nutrition for one serving of: {name}. "
                                                     "Give whole numbers. note: one short sentence."}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.loads(json.load(r)["message"]["content"])
    finally:
        local_brain.prompt_disturbed()
    result["meal"] = name
    return result


def totals(day):
    items = [m for m in _load() if m["time"][:10] == day.isoformat()]
    return {"meals": len(items), "calories": sum(m["calories"] for m in items),
            "protein_g": sum(m["protein_g"] for m in items)}


def log(note=""):
    """Photograph the meal, estimate it, add it to today's log. Returns what to say."""
    from . import hologram, scanner
    try:
        jpeg = scanner.capture()
    except Exception as e:
        return str(e)
    image = "data:image/jpeg;base64," + base64.b64encode(scanner._jpeg_small(jpeg)).decode()
    hologram._send({"action": "open", "kind": "scan", "subject": "Meal scan", "image": image})
    try:
        r = _estimate(jpeg, note)
    except Exception as e:
        message = str(e) if isinstance(e, RuntimeError) else f"I couldn't estimate that meal: {e}"
        hologram._send({"action": "scan_result", "result": {"name": "Scan failed", "what": message, "details": [], "tip": ""}})
        return message
    num = lambda k: max(0, int(r.get(k) or 0))
    meal = str(r.get("meal") or "Meal").strip()[:80]
    if num("calories") == 0:
        hologram._send({"action": "scan_result", "result": {"name": "Nothing recognised", "what": "I don't see any food.", "details": [], "tip": ""}})
        return "I don't see any food. Put the plate in front of the camera and try again."
    item = {"time": dt.datetime.now().isoformat(timespec="minutes"), "meal": meal, "calories": num("calories"),
            "protein_g": num("protein_g"), "carbs_g": num("carbs_g"), "fat_g": num("fat_g")}
    with _lock:
        LOG_FILE.write_text(json.dumps((_load() + [item])[-1000:], indent=1, ensure_ascii=False), encoding="utf-8")

    def take_back():
        with _lock:
            LOG_FILE.write_text(json.dumps([m for m in _load() if m != item], indent=1, ensure_ascii=False), encoding="utf-8")
    from . import undo
    undo.offer(f"Logged {meal}", take_back)
    today = totals(dt.date.today())
    hologram._send({"action": "scan_result", "result": {
        "name": meal, "what": f"About {item['calories']} calories. Today so far: {today['calories']} calories.",
        "details": [{"label": "Protein", "value": f"{item['protein_g']} g"}, {"label": "Carbs", "value": f"{item['carbs_g']} g"},
                    {"label": "Fat", "value": f"{item['fat_g']} g"}],
        "tip": str(r.get("note") or "")}})
    return (f"Logged {meal}: about {item['calories']} calories and {item['protein_g']} grams of protein. "
            f"Today so far: {today['calories']} calories and {today['protein_g']} grams of protein.")


def today_summary():
    t = totals(dt.date.today())
    if not t["meals"]:
        return "You haven't logged any meals today. Say 'log this meal' with your plate in front of the camera."
    return (f"Today you've logged {t['meals']} meal{'s' if t['meals'] != 1 else ''}: about {t['calories']} calories "
            f"and {t['protein_g']} grams of protein.")


def yesterday_line():
    """For the morning greeting. Empty if nothing was logged yesterday."""
    t = totals(dt.date.today() - dt.timedelta(days=1))
    return (f"Yesterday you logged about {t['calories']} calories and {t['protein_g']} grams of protein."
            if t["meals"] else "")


@tool("Log a meal: photographs the plate with the desk camera (or webcam), estimates calories and protein, carbs "
      "and fat, and adds it to today's total. 'log this meal', 'log my lunch'.",
      {"note": S("What it is, if he said (helps the estimate)")})
def log_meal(note=""):
    return log(note)


@tool("How many calories and how much protein he's logged today.")
def meals_today():
    return today_summary()
