"""Free, instant answers: simple requests answered in plain Python before Claude is called (no API cost, no wait).
The time and date, "how many days until Christmas", percentages and sums, unit conversions, timers, volume,
"got it" for a repeating reminder, and saved routines by name. The patterns are strict on purpose: anything that
doesn't match exactly ("what time is it in Tokyo") goes to Claude as usual."""
import ast
import datetime as dt
import operator
import re

from . import config

HOLIDAYS = {"christmas": (12, 25), "christmas day": (12, 25), "christmas eve": (12, 24), "new year": (1, 1),
            "new years": (1, 1), "new years day": (1, 1), "new years eve": (12, 31), "halloween": (10, 31),
            "valentines day": (2, 14), "valentines": (2, 14)}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})

# unit -> (dimension, value in the base unit). Temperatures are handled separately.
UNITS = {"km": ("len", 1000), "kilometer": ("len", 1000), "kilometre": ("len", 1000), "m": ("len", 1),
         "meter": ("len", 1), "metre": ("len", 1), "cm": ("len", .01), "centimeter": ("len", .01),
         "centimetre": ("len", .01), "mm": ("len", .001), "mile": ("len", 1609.344), "mi": ("len", 1609.344),
         "foot": ("len", .3048), "feet": ("len", .3048), "ft": ("len", .3048), "inch": ("len", .0254),
         "inches": ("len", .0254), "in": ("len", .0254), "yard": ("len", .9144),
         "kg": ("mass", 1), "kilogram": ("mass", 1), "kilo": ("mass", 1), "g": ("mass", .001), "gram": ("mass", .001),
         "pound": ("mass", .45359237), "lb": ("mass", .45359237), "lbs": ("mass", .45359237), "ounce": ("mass", .028349523),
         "oz": ("mass", .028349523), "stone": ("mass", 6.35029318),
         "liter": ("vol", 1), "litre": ("vol", 1), "l": ("vol", 1), "ml": ("vol", .001), "milliliter": ("vol", .001),
         "gallon": ("vol", 3.78541178), "gal": ("vol", 3.78541178), "cup": ("vol", .2365882365)}
TEMPS = {"c": "c", "celsius": "c", "centigrade": "c", "degrees celsius": "c", "f": "f", "fahrenheit": "f",
         "degrees fahrenheit": "f"}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
NUM = r"(-?\d[\d,]*(?:\.\d+)?)"


def _clean(text):
    """'Hey Jarvis, what's the time?' -> 'whats the time'"""
    t = text.lower().replace("’", "'").replace("'", "")
    t = re.sub(r"[?!.,]+(\s|$)", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split()
    skip = set(config.WAKE_WORDS) | {"hey", "ok", "okay", "please"}
    while words and words[0] in skip:
        words.pop(0)
    while words and words[-1] in skip:
        words.pop()
    return " ".join(words)


def _num(s):
    return float(s.replace(",", ""))


def _fmt(x):
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _calc(expr):
    """Safely evaluate plain arithmetic (numbers and + - * / ^ only)."""
    expr = expr.replace("x", "*").replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    for word, sym in (("multiplied by", "*"), ("divided by", "/"), ("times", "*"), ("plus", "+"), ("minus", "-"),
                      ("over", "/"), ("to the power of", "**")):
        expr = expr.replace(word, sym)
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expr) or not re.search(r"\d\s*[-+*/]", expr):
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("too big")
            return OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
            return OPS[type(node.op)](ev(node.operand))
        raise ValueError("not arithmetic")

    try:
        return ev(ast.parse(expr, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
        return None


def _target_date(name, today):
    name = name.strip()
    if name in HOLIDAYS:
        month, day = HOLIDAYS[name]
    else:
        m = re.fullmatch(r"(?:the )?(\d{1,2})(?:st|nd|rd|th)? (?:of )?([a-z]+)|([a-z]+) (\d{1,2})(?:st|nd|rd|th)?", name)
        if not m:
            return None
        day, month_name = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if month_name not in MONTHS:
            return None
        month, day = MONTHS[month_name], int(day)
    try:
        target = dt.date(today.year, month, day)
    except ValueError:
        return None
    return target if target >= today else target.replace(year=today.year + 1)


def answer(text):
    """The free answer to `text`, or None to let Claude handle it."""
    t = _clean(text)
    if not t or len(t) > 80:
        return None
    now = dt.datetime.now()

    # Saved routines by name: "focus mode", "run focus mode"
    from . import routines
    for name in routines.names():
        if t in (name, f"run {name}", f"start {name}", f"do {name}", f"{name} please"):
            return routines.run_routine(name)

    # "Got it" for a repeating reminder (if none is repeating, let Claude reply normally)
    if re.fullmatch(r"(ok |okay |alright )?(got it|i got it|done|its done|i did it|stop reminding me|thanks i got it)", t):
        from . import tools
        if any(r.get("nag") for r in tools._load_reminders()):
            return tools.acknowledge_reminder()
        return None

    if re.fullmatch(r"(whats the time|what time is it|what is the time|the time|time)( now| right now)?", t):
        return f"It's {now:%I:%M %p}.".replace(" 0", " ")
    if re.fullmatch(r"(whats|what is) (the date|todays date|the date today)|what day is (it|it today|today)|whats today", t):
        return f"It's {now:%A}, {now.day} {now:%B %Y}."

    m = re.fullmatch(r"how many (days|weeks) (are there )?(until|till|til|to|before) (.+)", t)
    if m:
        target = _target_date(m.group(4), now.date())
        if target:
            days = (target - now.date()).days
            if days == 0:
                return f"It's today: {target:%A %d %B}."
            when = f"{days} day{'s' if days != 1 else ''}" if m.group(1) == "days" else f"{days / 7:.1f} weeks"
            name = m.group(4).title() if m.group(4) in HOLIDAYS else m.group(4)
            return f"{when} until {name}, on {target:%A %d %B %Y}."

    m = re.fullmatch(rf"(?:whats|what is|calculate)? ?{NUM} ?(?:%|percent) of {NUM}", t)
    if m:
        return f"{_fmt(_num(m.group(1)) * _num(m.group(2)) / 100)}."

    m = re.fullmatch(r"(?:whats|what is|calculate) (.+)", t)
    if m:
        value = _calc(m.group(1))
        if value is not None:
            return f"{_fmt(value)}."

    m = re.fullmatch(rf"(?:convert )?{NUM} ?([a-z ]+?) (?:to|in|into) ([a-z ]+)", t)
    if m:
        value, a_said, b_said = _num(m.group(1)), m.group(2).strip(), m.group(3).strip()
        unit = lambda w: w if w in UNITS or w in TEMPS else w[:-1] if w.endswith("s") else w  # "miles" -> "mile"
        a, b = unit(a_said), unit(b_said)
        if a in TEMPS and b in TEMPS and TEMPS[a] != TEMPS[b]:
            out = value * 9 / 5 + 32 if TEMPS[a] == "c" else (value - 32) * 5 / 9
            return f"{_fmt(value)}°{TEMPS[a].upper()} is {_fmt(round(out, 1))}°{TEMPS[b].upper()}."
        if a in UNITS and b in UNITS and UNITS[a][0] == UNITS[b][0]:
            out = round(value * UNITS[a][1] / UNITS[b][1], 2)
            abbreviations = {"km", "m", "cm", "mm", "mi", "ft", "in", "kg", "g", "lb", "lbs", "oz", "l", "ml", "gal"}
            plural = lambda u, n: u if n == 1 or u in abbreviations or u.endswith("s") or u in ("feet", "inches", "stone") else u + "s"
            return f"{_fmt(value)} {plural(a, value)} is {_fmt(out)} {plural(b, out)}."

    m = (re.fullmatch(r"(?:set )?(?:a )?timer (?:for )?(\d+) (second|minute|hour)s?", t)
         or re.fullmatch(r"(?:set )?(?:a |an )?(\d+) (second|minute|hour) timer", t))
    if m:
        from . import tools
        n, unit = int(m.group(1)), m.group(2)
        tools.set_reminder("Your timer is done.", seconds=n * {"second": 1, "minute": 60, "hour": 3600}[unit])
        return f"Timer set for {n} {unit}{'s' if n != 1 else ''}."

    from . import tools
    if re.fullmatch(r"(turn )?(the )?volume up|louder|turn it up", t):
        return tools.media_control("volume_up")
    if re.fullmatch(r"(turn )?(the )?volume down|quieter|turn it down", t):
        return tools.media_control("volume_down")
    if t in ("mute", "unmute", "mute the volume", "unmute the volume"):
        return tools.media_control("mute")
    m = re.fullmatch(r"(?:set )?(?:the )?volume (?:to )?(\d{1,3})(?: percent| %)?", t)
    if m:
        level = max(0, min(100, int(m.group(1))))
        import pyautogui
        pyautogui.press("volumedown", presses=50)       # to zero (each press is 2%)
        pyautogui.press("volumeup", presses=round(level / 2))
        return f"Volume set to about {level}%."
    return None
