"""Credit planner: roughly how much Claude API credit to buy for a stretch of time, and the minimum to get going.

"How much credit do I need for a month?", "what's the minimum to start using Claude?". Once Jarvis has a few days
of real spending recorded (see spend.py), the estimate uses your own average. Before that it works it out from
the size of Jarvis's instructions and tools, the model's price, and typical use. Either way it's a rough guide:
console.anthropic.com shows the real balance and bill.
"""
import datetime as dt
import json

from . import config, spend
from .tools import I, tool

MIN_PURCHASE = 5  # dollars: the smallest credit purchase the Anthropic console accepts (check its billing page)
MARGIN = 1.25     # buy a quarter extra: some days are busier, and prices or habits change
PROFILES = {"light": 15, "typical": 40, "heavy": 120}  # spoken or typed commands a day


def _prompt_tokens():
    """How big Jarvis's standing prompt is (instructions + every tool's description), in tokens (approx.)."""
    from . import brain, tools
    chars = len(brain.build_system_prompt("hud")) + len(json.dumps(tools.schemas()))
    return int(chars / 3.6)


def _per_command(model):
    """Dollars for one average command with prompt caching, from the real prompt size."""
    p_in, p_out = spend._price(model, 20_000)
    prefix = _prompt_tokens()
    steps = 1.8           # most commands are one call; tool use adds a second or third
    fresh_in = 900        # the new message, recent history and tool results each step
    out = 220             # spoken replies are short
    cold = 0.35           # share of commands after a 5-minute pause, which re-write the cache (1.25x)
    cached_read = prefix * steps * (1 - cold) * p_in * 0.1
    cache_write = prefix * cold * p_in * 1.25 + prefix * (steps - 1) * cold * p_in * 0.1
    rest = (fresh_in * steps * p_in + out * steps * p_out)
    searches = 0.08 * spend.WEB_SEARCH * 1e6  # about 1 command in 12 searches the web
    return (cached_read + cache_write + rest + searches) / 1e6


def _background_per_day():
    """Email watch, suggestions, memory tidy, meeting briefs: all on the cheap helper model."""
    p_in, p_out = spend._price(config.HELPER_MODEL, 5_000)
    calls = []
    if config.EMAIL_WATCH:
        calls += [(1_800, 150)] * 12      # checks only call the AI when new mail arrives
    calls += [(3_500, 400)] * max(0, config.SUGGESTIONS_PER_DAY)
    if config.MEMORY_TIDY:
        calls += [(3_000, 600)]
    calls += [(2_000, 300)] * 3           # meeting briefs, holograms, scans now and then
    return sum(i * p_in + o * p_out for i, o in calls) / 1e6


def _history():
    """Average dollars per active day over the last 30 days, if there are at least 3 days of real use."""
    data = spend._load()
    since = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    days = [d["usd"] for k, d in data.items() if k >= since and d.get("usd", 0) > 0.001]
    return (sum(days) / len(days), len(days)) if len(days) >= 3 else (None, len(days))


def _money(usd):
    if usd == int(usd) and usd >= 1:
        return f"${int(usd):,}"
    return f"${usd:.2f}" if usd < 10 else f"${usd:,.0f}"


def _name(model):
    """'claude-haiku-5-5' -> 'Claude Haiku 5.5'."""
    parts = model.split("-")
    if len(parts) >= 3 and parts[0] == "claude":
        return f"Claude {parts[1].title()} {'.'.join(p for p in parts[2:] if p.isdigit())}".strip()
    return model


def _compare(days):
    """On Haiku, a line on what the step up (Sonnet 5.5) would cost, since that's the usual upgrade."""
    if not config.MODEL.startswith("claude-haiku"):
        return ""
    sonnet = PROFILES["typical"] * _per_command("claude-sonnet-5-5") * days + _background_per_day() * days
    return f" If you move up to Claude Sonnet 5.5 for smarter answers, typical use would be about {_money(sonnet)}."


def _restart_note():
    from . import local_brain
    if config.BRAIN == "local":
        return " You're set to offline only: change JARVIS_BRAIN to auto or claude in the .env file, then restart me."
    if config.BRAIN == "auto" and (local_brain.claude_resting() or local_brain.OFFLINE_FLAG.exists()):
        return " Add it, and I'll switch from offline mode back to Claude by myself within half an hour, or straight away if you restart me."
    return ""


def _buy(usd):
    """What to actually buy: the estimate plus a margin, rounded up to $5, never under the minimum."""
    return max(MIN_PURCHASE, int(-(-usd * MARGIN // 5) * 5))


def daily_cost(commands_per_day=None, model=None):
    model = model or config.MODEL
    real, _ = _history()
    if real is not None and not commands_per_day:
        return real
    n = commands_per_day or PROFILES["typical"]
    return n * _per_command(model) + _background_per_day()


def estimate(days=30, commands_per_day=None):
    days = max(1, min(int(days or 30), 3650))
    model = config.MODEL
    real, active = _history()
    period = _period(days)
    if real is not None and not commands_per_day:
        total = real * days
        return (f"Going by your own use over the last {active} active days, about {_money(real)} a day, "
                f"{period} would cost roughly {_money(total)}. I'd buy {_money(_buy(total))} to be safe. "
                f"That's on {_name(model)}; console.anthropic.com shows the exact balance.")
    if commands_per_day:
        total = daily_cost(commands_per_day) * days
        return (f"At about {commands_per_day} commands a day on {_name(model)}, {period} would cost roughly "
                f"{_money(total)}, background jobs included. I'd buy {_money(_buy(total))} to be safe.")
    light, typical, heavy = (daily_cost(PROFILES[k]) * days for k in ("light", "typical", "heavy"))
    return (f"Rough estimate for {period} on {_name(model)}: light use, about {PROFILES['light']} commands a day, "
            f"{_money(light)}; typical, about {PROFILES['typical']} a day, {_money(typical)}; heavy, about "
            f"{PROFILES['heavy']} a day, {_money(heavy)}. That includes background jobs like the email watch. "
            f"For typical use I'd buy {_money(_buy(typical))}.{_compare(days)} Once you've used me for a few days, "
            "I can base this on your real spending.")


def minimum():
    model = config.MODEL
    per_day = daily_cost()
    lasts = MIN_PURCHASE / per_day if per_day else 0
    span = (f"about {int(lasts)} days" if lasts < 60 else f"about {lasts / 30:.0f} months") if lasts >= 1 else "less than a day"
    return (f"The minimum to get started is {_money(MIN_PURCHASE)}, the smallest credit purchase on "
            f"console.anthropic.com, under Settings, Billing. On {_name(model)}, with typical use of around "
            f"{PROFILES['typical']} commands a day, that lasts {span}.{_restart_note()}")


def _period(days):
    if days % 365 == 0:
        n = days // 365
        return "a year" if n == 1 else f"{n} years"
    if days % 30 == 0:
        n = days // 30
        return "a month" if n == 1 else f"{n} months"
    if days % 7 == 0:
        n = days // 7
        return "a week" if n == 1 else f"{n} weeks"
    return "a day" if days == 1 else f"{days} days"


@tool("Estimate how much Claude API credit to buy for a period, or the minimum needed to start using Claude. "
      "Use for 'how much credit do I need for a month', 'how much will Jarvis cost per week', 'what's the "
      "minimum to get started'. days 0 = the minimum to get started.",
      {"days": I("Length of the period in days (30 for a month). 0 for the minimum to start."),
       "commands_per_day": I("Only if he said how much he'll use Jarvis")})
def credit_estimate(days=30, commands_per_day=None):
    return minimum() if not days else estimate(days, commands_per_day)
