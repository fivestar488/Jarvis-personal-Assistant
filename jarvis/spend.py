"""API spend: what each Claude call cost, totals per day and month, and a daily budget.

Prices are Anthropic's list prices in dollars per million tokens (November 2026). Cache reads cost 0.1x the
input price, 5-minute cache writes 1.25x, and web searches $10 per 1,000. Your bill can differ slightly
(taxes, discounts); console.anthropic.com is the source of truth.

When today's spend reaches the daily budget, Jarvis keeps answering but switches to the cheapest model and
pauses background jobs until midnight.
"""
import datetime as dt
import json
import threading

from . import config
from .tools import tool

SPEND_FILE = config.DATA_DIR / "spend.json"

# (input, output) per million tokens. Matched by the longest prefix of the model id, so "claude-opus-5-5"
# isn't priced as "claude-opus-5".
PRICES = {
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4": (1.00, 5.00),
}
HAIKU_5_5_LONG = (0.50, 2.50)   # Haiku 5.5 prompts over 100K tokens use a second rate card
UNKNOWN = (10.00, 50.00)        # an id we don't know: assume the dearest, so the budget errs on the safe side
WEB_SEARCH = 10.00 / 1000

_lock = threading.Lock()


def _price(model, prompt_tokens):
    if model.startswith("claude-haiku-5-5") and prompt_tokens > 100_000:
        return HAIKU_5_5_LONG
    for prefix in sorted(PRICES, key=len, reverse=True):
        if model.startswith(prefix):
            return PRICES[prefix]
    return UNKNOWN


def cost(model, usage):
    """Dollars for one API response, from its usage block."""
    inp = getattr(usage, "input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    p_in, p_out = _price(model, inp + read + write)
    return (inp * p_in + read * p_in * 0.1 + write * p_in * 1.25 + out * p_out) / 1e6 + searches * WEB_SEARCH


def _load():
    try:
        return json.loads(SPEND_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def record(model, usage, source):
    """Add one response's cost to today's total, and warn about the budget when it's crossed."""
    usd = cost(model, usage)
    today = dt.date.today().isoformat()
    with _lock:
        data = _load()
        day = data.setdefault(today, {"usd": 0.0, "calls": 0, "by": {}, "alerted": 0})
        day["usd"] += usd
        day["calls"] += 1
        day["by"][source] = day["by"].get(source, 0.0) + usd
        level = 0
        if config.DAILY_BUDGET:
            level = 2 if day["usd"] >= config.DAILY_BUDGET else 1 if day["usd"] >= 0.8 * config.DAILY_BUDGET else 0
        alert = level > day.get("alerted", 0)
        if alert:
            day["alerted"] = level
        for old in sorted(data)[:-400]:  # keep about a year
            del data[old]
        SPEND_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        total = day["usd"]
    if alert:
        _warn(level, total)
    return usd


def _warn(level, total):
    from . import notify
    budget = config.DAILY_BUDGET
    if level == 1:
        notify.alert("API budget", f"Heads up, {config.USER_NAME}: I've used ${total:.2f} of today's ${budget:.2f} API budget.")
    else:
        plan = "pause the email watch" if config.MODEL == config.HELPER_MODEL else \
            "switch to my cheapest model and pause the email watch"
        notify.alert("API budget", f"Today's ${budget:.2f} API budget is used up. I'll {plan} until midnight, "
                                   "but I'll still answer you.")


def today():
    return _load().get(dt.date.today().isoformat(), {}).get("usd", 0.0)


def over_budget():
    return bool(config.DAILY_BUDGET) and today() >= config.DAILY_BUDGET


def current_model():
    """The model to use for the next request: the normal one, or the cheapest once today's budget is spent."""
    return config.HELPER_MODEL if over_budget() else config.MODEL


def summary():
    data, now = _load(), dt.date.today()
    month = sum(d["usd"] for k, d in data.items() if k.startswith(now.strftime("%Y-%m")))
    day = data.get(now.isoformat(), {})
    return {"today": round(day.get("usd", 0.0), 4), "month": round(month, 4), "calls_today": day.get("calls", 0),
            "budget": config.DAILY_BUDGET, "by_source_today": {k: round(v, 4) for k, v in day.get("by", {}).items()},
            "model": current_model()}


@tool("How much Jarvis has spent on the Claude API: today, this month, the daily budget, and what used it. "
      "Use when the user asks about cost, credit, spending or the budget.")
def api_spend():
    s = summary()
    budget = f" of the ${s['budget']:.2f} daily budget" if s["budget"] else " (no daily budget set)"
    parts = ", ".join(f"{k} ${v:.3f}" for k, v in s["by_source_today"].items()) or "nothing yet"
    return (f"Today: ${s['today']:.3f}{budget}, over {s['calls_today']} API calls ({parts}). "
            f"This month: ${s['month']:.2f}. Current model: {s['model']}. Prices are list prices; "
            "the exact bill is at console.anthropic.com.")
