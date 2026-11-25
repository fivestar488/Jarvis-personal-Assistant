"""Free, instant answers: simple requests answered in plain Python before Claude is called (no API cost, no wait).
The time and date, "how many days until Christmas", percentages and sums, unit conversions, timers, reminders
("remind me to call mum in 20 minutes / at 5 pm"), volume and pause/skip, "open <app>", the weather, the news,
"what's playing", "what are my reminders", "read my notes", "got it" for a repeating reminder, and saved routines
by name. The patterns are strict on purpose: anything that
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
    # "Capture: call the bank" -> today's daily note, word for word (before cleaning, so capitals and length survive)
    m = re.match(r"\s*(?:(?:hey |ok |okay )?jarvis[,.!]?\s+)?(?:capture|daily note|add to (?:my |the )?daily note|"
                 r"note for today)\s*[:,\-]?\s+(.{2,})$", text, re.I | re.S)
    if m:
        from . import dailynote
        return dailynote.add(m.group(1).strip())
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

    from . import tutor
    if tutor.session:  # a flashcard quiz is running: what he says is his answer
        if re.fullmatch(r"(?:stop|end|cancel|quit|finish)(?: the| this)? quiz|stop", t):
            return tutor.stop()
        return tutor.answer(t)
    reply = (_wave4(t) or _wave3(t) or _scanner(t) or _hologram(t) or _actions(t) or _modes(t) or _meeting(t)
             or _meals(t) or _credit(t) or _suit(t))
    if reply:
        return reply

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

    reply = _reminder(t, now)
    if reply:
        return reply

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
    if re.fullmatch(r"pause|pause (the |this )?(music|song)", t):
        tools.media_control("playpause")
        return "Paused."
    if re.fullmatch(r"resume|resume (the )?music|play|unpause", t):
        tools.media_control("playpause")
        return "Resuming."
    if re.fullmatch(r"next|skip|next (song|track)|skip (this |the )?(song|track)", t):
        tools.media_control("next")
        return "Skipping."
    if re.fullmatch(r"previous|previous (song|track)|go back a song|last song", t):
        tools.media_control("previous")
        return "Going back a song."

    # "Open Spotify": only when the app is actually found; otherwise Claude works out what was meant.
    m = re.fullmatch(r"(?:open|launch|start) (?:up )?(?:the )?([a-z0-9 ]{2,30}?)(?: app)?", t)
    if m and len(m.group(1).split()) <= 3:
        name = m.group(1)
        try:
            # "chrome" -> "Google Chrome", "word" -> "Microsoft Word": the name as whole words of a real app's name
            known = name in tools.APP_ALIASES or any(f" {name} " in f" {a.lower()} " for a in tools._get_start_apps())
        except Exception:
            known = False
        if known:  # an exact app name only: anything fuzzier goes to the AI
            reply = tools.open_application(name)
            if reply.startswith("Opened"):
                return reply

    if re.fullmatch(r"(whats|what is|hows|how is) the weather( like)?( today| now| outside| right now)?|weather|"
                    r"weather (today|now)|is it (cold|hot|raining|warm) (outside|today)", t):
        return _weather()

    if re.fullmatch(r"(whats|what is) (playing|this song|this track|the song)( called)?|what song is (this|playing)", t):
        playing = tools.TOOLS["spotify_now_playing"]["fn"]() if "spotify_now_playing" in tools.TOOLS else ""
        if " by " in playing:  # "Song by Artist (playing, 1:23 of 3:45)."
            return "That's " + re.sub(r"\s*\(.*\)\.?$", ".", playing)
    if re.fullmatch(r"(what are|whats|list|read|tell me) (my|all my|the) reminders|(do i have )?any reminders|my reminders", t):
        return _reminders(now)
    if re.fullmatch(r"(whats|what is) (the|in the) news( today)?|(the |todays )?(news|headlines)|"
                    r"(read|tell) me the (news|headlines)|(what are )?(the |todays )?top (stories|headlines)", t):
        from . import feeds
        titles = [h["title"] for h in feeds.headlines(3)]
        return ("Here are the top headlines. " + " ".join(f"{h.rstrip('.')}." for h in titles)) if titles else None
    if re.fullmatch(r"(read|show|tell me|what are|whats in) (me )?my notes|my notes", t):
        lines = [re.sub(r"^- \[[^\]]*\]\s*", "", l).strip() for l in tools.read_notes().splitlines()]
        lines = [l for l in lines if l and l != "No notes yet."]
        if not lines:
            return "You haven't saved any notes yet."
        more = f" Those are the latest 5 of {len(lines)}." if len(lines) > 5 else ""
        return "Your notes: " + " ".join(f"{l[:1].upper()}{l[1:].rstrip('.')}." for l in lines[-5:]) + more
    return None


def _modes(t):
    """Low Power Mode, pausing the mic, captions."""
    from . import captions, modes
    if re.fullmatch(r"(?:turn on |enable |activate |go to |go into |switch to )?(?:low power|battery saver|power saving)"
                    r"(?: mode)?(?: on)?|save (?:the )?battery", t):
        return modes.low_power(True)
    if re.fullmatch(r"(?:turn off |disable |exit |leave )(?:the )?(?:low power|battery saver|power saving)(?: mode)?|"
                    r"(?:low power|battery saver|power saving)(?: mode)? off|full power(?: mode)?", t):
        return modes.low_power(False)
    if re.fullmatch(r"(?:pause|stop|mute) (?:the )?(?:listening|microphone|mic)|stop listening(?: to me| to the room)?", t):
        return modes.pause_listening(True)
    if re.fullmatch(r"(?:resume|start|unmute|unpause) (?:the )?(?:listening|microphone|mic)|(?:start )?listen(?:ing)? again", t):
        return modes.pause_listening(False)
    if re.fullmatch(r"(?:turn on |show |enable )?(?:live )?(?:captions|subtitles)(?: on)?", t):
        return captions.set_enabled(True)
    if re.fullmatch(r"(?:turn off |hide |disable )(?:the )?(?:live )?(?:captions|subtitles)|(?:live )?(?:captions|subtitles) off", t):
        return captions.set_enabled(False)
    return None


SHAPE = r"(cube|box|block|sphere|ball|orb|cylinder|tube|pipe|cone|torus|donut|doughnut|ring|pyramid)"
STRETCH = r"(taller|shorter|wider|thinner|narrower|deeper|flatter|bigger|smaller|longer)"
FINISH_END = (r"(?: finishes| is done| is finished| completes| is complete| closes| exits| quits| ends| stops growing|"
              r" goes quiet| is idle)")


def _wave4(t):
    """Sculpting, the demo tour, the setup doctor, 'tell me when it finishes', parcels, subscriptions, when to
    leave, and reading the daily note."""
    from . import commute, dailynote, doctor, finish, hologram, packages, subscriptions, tour
    m = (re.fullmatch(rf"sculpt(?: me)?(?: a| an)? {SHAPE}", t)
         or re.fullmatch(rf"(?:make|build|start|open)(?: me)?(?: a| an)? {SHAPE} (?:hologram )?to sculpt", t))
    if m:
        return hologram.sculpt("new", m.group(1))
    if re.fullmatch(r"(?:open|start)(?: the)? (?:sculpting|sculpt|workshop)(?: bench| mode)?|lets sculpt|sculpt(?: something)?", t):
        return hologram.sculpt("new", "cube")
    if hologram.state["open"] and hologram.state["kind"] == "sculpt":
        m = re.fullmatch(rf"add (?:a |an |another )?{SHAPE}", t)
        if m:
            return hologram.sculpt("add", m.group(1))
        m = re.fullmatch(rf"(?:make (?:it|that|this)(?: piece)? )?(?:a (?:bit|little|lot) )?{STRETCH}", t)
        if m:
            return hologram.sculpt("stretch", m.group(1))
        m = re.fullmatch(r"move (?:it|that|this)(?: piece)? (up|down|left|right|forward|forwards|back|backwards)", t)
        if m:
            return hologram.sculpt("move", m.group(1).rstrip("s").replace("backward", "back"))
        m = re.fullmatch(r"(?:turn|rotate|spin|tilt|flip) (?:it|that|this)(?: piece)?(?: (left|right|over))?", t)
        if m:
            return hologram.sculpt("turn", m.group(1) or "right")
        if re.fullmatch(r"(?:remove|delete|lose) (?:it|that|this)(?: piece| part| one)?", t):
            return hologram.sculpt("remove")
        if re.fullmatch(r"next(?: piece| part| one)?|select the next(?: piece| part| one)?", t):
            return hologram.sculpt("next")
        m = re.fullmatch(rf"(?:select|pick|grab) the {SHAPE}", t)
        if m:
            return hologram.sculpt("select", hologram.shape_name(m.group(1)))
        if re.fullmatch(r"undo(?: that)?", t):
            return hologram.sculpt("undo")
    if re.fullmatch(r"(?:give (?:them|us|me|my friends?|him|her) )?(?:the |a )tour|(?:start |run )?(?:the )?demo(?: mode)?|"
                    r"show (?:them|my friends?|everyone) what you can do", t):
        return tour.start_tour()
    if re.fullmatch(r"(?:stop|end|cancel|skip) (?:the )?(?:tour|demo)", t):
        return tour.stop_tour()
    if re.fullmatch(r"(?:check|test) (?:my|the|your) setup|run (?:the )?(?:setup )?doctor|setup (?:check|doctor)|"
                    r"is everything (?:working|set up)", t):
        return doctor.spoken_summary()
    m = re.fullmatch(rf"(?:tell|let) me(?: know)? when (.+?){FINISH_END}", t)
    if m:
        return finish.request(m.group(1))
    if re.fullmatch(r"what are you (?:watching|waiting) for|what are you keeping an eye on", t):
        return finish.listing()
    if re.fullmatch(r"stop watching(?: everything| it| that)?", t):
        return finish.stop_all()
    if re.fullmatch(r"where(?:s| is| are) my (?:stuff|parcels?|packages?|orders?|deliver(?:y|ies))|"
                    r"(?:any|my) (?:deliveries|parcels|packages)(?: today)?|whats (?:coming|being delivered)(?: today)?", t):
        return packages.where()
    m = re.fullmatch(r"track my (.+)", t)
    if m:
        return packages.track(m.group(1))
    if re.fullmatch(r"what am i paying for|(?:list |show |what are )?my subscriptions|what subscriptions do i (?:have|pay for)|"
                    r"how much do i (?:pay|spend) on subscriptions", t):
        return subscriptions.listing()
    m = re.fullmatch(r"i (?:cancelled|canceled|stopped|ended) (?:my )?(.+?)(?: subscription| membership)?", t)
    if m and len(m.group(1).split()) <= 4 and subscriptions.has(m.group(1)):  # not "I cancelled my meeting"
        return subscriptions.remove(m.group(1))
    if re.fullmatch(r"when (?:should|do) i (?:need to )?leave(?: for .+)?|what time should i leave(?: for .+)?|"
                    r"how long (?:will it take |does it take )?to get to my next (?:meeting|event|appointment)", t):
        return commute.leave_advice()
    m = re.fullmatch(r"(?:whats in|read(?: me)?|show me) (?:my |the )?(todays|daily|yesterdays) note", t)
    if m:
        return dailynote.read(dt.date.today() - dt.timedelta(days=1) if m.group(1) == "yesterdays" else None)
    return None


LANGUAGES = (r"spanish|french|german|italian|japanese|chinese|mandarin|arabic|hebrew|portuguese|korean|russian|dutch|"
             r"greek|turkish|hindi|polish|swedish")


def _wave3(t):
    """Data holograms, situation board, simulations, trips, game mode, breaks, standing orders, the offline wake
    word, the status strip and the flashcard tutor."""
    from . import boards, captions, focus, planner, standing, trips, tutor, wakeword
    m = (re.fullmatch(r"(?:show|open|bring up|pull up)(?: me)? my (week|schedule|calendar|inbox|emails?|mail|spending|spend|"
                      r"costs?|calories|meals|food)(?: as a hologram| in 3d| hologram)?", t)
         or re.fullmatch(r"(?:show|open)(?: me)? (?:a |the )?(?:hologram|3d view|3d map) of my (week|schedule|calendar|inbox|"
                         r"emails?|mail|spending|spend|costs?|calories|meals|food)", t))
    if m:
        return boards.show(m.group(1))
    if re.fullmatch(r"(?:give me a |run a )?(?:situation|sit) ?(?:report|rep|board)|sitrep|threat (?:assessment|level|report)|any threats", t):
        return boards.situation()
    m = re.fullmatch(r"(?:run (?:a |the )?)?simulat(?:e|ion)(?: of| on| for)? (.{6,})", t)
    if m:
        return planner.simulate(m.group(1))
    if re.fullmatch(r"trip mode|show (?:me )?my (?:next )?(?:trip|flight)|when(?:s| is) my (?:next )?(?:flight|trip)", t):
        return trips.trip_mode()
    if re.fullmatch(r"(?:scan|search|check) my (?:email|emails|inbox|gmail|mail) for (?:trips|flights|travel|bookings)", t):
        return trips.scan()
    m = re.fullmatch(r"add a trip to (.+?) on (.+)", t)
    if m:
        day = _target_date(m.group(2), dt.date.today())
        return trips.add(m.group(1), day.isoformat()) if day else None
    if re.fullmatch(r"(?:turn on |enable |start )?(?:game mode|do not disturb|dnd)(?: on| mode)?", t):
        return focus.set_manual(True)
    if re.fullmatch(r"(?:turn off |disable |stop |end )(?:game mode|do not disturb|dnd)|(?:game mode|do not disturb|dnd) off", t):
        return focus.set_manual(False)
    if re.fullmatch(r"(?:turn on |enable |start )?(?:the )?(?:break|eye break) reminders(?: on)?", t):
        return focus.set_breaks(True)
    if re.fullmatch(r"(?:turn off |disable |stop )(?:the )?(?:break|eye break) reminders|(?:break|eye break) reminders off", t):
        return focus.set_breaks(False)
    if re.fullmatch(r"(?:list |show |what are )?(?:my )?standing orders", t):
        return standing.listing()
    m = re.fullmatch(r"(?:cancel|delete|remove) (?:standing order (\d+)|(all) (?:my )?standing orders)", t)
    if m:
        return standing.cancel(m.group(1) or "all")
    if re.match(r"(?:every|on|when|whenever|daily|weekdays|weekends) ", t):
        added = standing.add(t)
        if added:
            return added
    if re.fullmatch(r"(?:turn on |enable |start )?(?:the )?offline wake word(?: on)?", t):
        return wakeword.switch(True)
    if re.fullmatch(r"(?:turn off |disable |stop )(?:the )?offline wake word|offline wake word off", t):
        return wakeword.switch(False)
    if re.fullmatch(r"(?:turn on |show |enable )?(?:the )?status (?:strip|bar)(?: on)?", t):
        return captions.set_strip(True)
    if re.fullmatch(r"(?:turn off |hide |disable )(?:the )?status (?:strip|bar)|status (?:strip|bar) off", t):
        return captions.set_strip(False)
    m = (re.fullmatch(rf"teach me (?:some )?((?:basic )?(?:{LANGUAGES})(?: words| vocabulary| phrases)?)", t)
         or re.fullmatch(r"(?:make|create|write)(?: me)? (?:some )?flash ?cards (?:on|about|for) (.+)", t))
    if m:
        return tutor.make_deck(m.group(1))
    if re.fullmatch(r"quiz me on my notes|(?:make|create) flash ?cards (?:from|on) my notes", t):
        made = tutor.make_deck("my notes", from_notes=True)
        return made if not made.split()[0].isdigit() else made + " " + tutor.start_quiz("my notes")
    m = re.fullmatch(r"(?:quiz me|test me|start (?:a|the|my) quiz)(?: on (.+))?", t)
    if m:
        return tutor.start_quiz(m.group(1) or "")
    if re.fullmatch(r"how many (?:flash ?cards|cards) (?:are )?due(?: today)?", t):
        return tutor.flashcards("due")
    return None


POSITION = r"(left|right|top|bottom|top left|top right|bottom left|bottom right|middle|center|centre)"


def _suit(t):
    """The film-style commands: status report, sweeps, protocols, mood mode, windows, perimeter, journal, wrap-ups,
    clipboard history, the video pane."""
    from . import cliphistory, desktop, filesearch, journal, perimeter, protocols, vitals, wrap
    if re.fullmatch(r"(?:give me a |run a )?(?:status|damage|systems?|system status) report|status|systems check|"
                    r"how are (?:we|the systems|things) (?:doing|looking)", t):
        return vitals.status(False)
    if re.fullmatch(r"run (?:a |the )?(?:full )?(?:sweep|systems sweep|diagnostics?|diagnostic sweep)|diagnostics", t):
        return vitals.status(True)
    m = re.fullmatch(r"(?:initiate|engage|run|activate|execute|start|begin|commence)(?: the)? (.+?) protocol", t)
    if m:
        return protocols.run(m.group(1))
    if re.fullmatch(r"(?:mood|movie|theatre|theater) mode(?: on)?|lights down|set the mood", t):
        return desktop.mood(True)
    if re.fullmatch(r"(?:mood|movie|theatre|theater) mode off|lights up|(?:turn off|end|stop) (?:the )?(?:mood|movie) mode", t):
        return desktop.mood(False)
    m = re.fullmatch(rf"(?:put|move|snap) (.+?) (?:on |to )?(?:the )?{POSITION}(?: half| side)?"
                     rf"(?: and (.+?) (?:on |to )?(?:the )?{POSITION}(?: half| side)?)?", t)
    if m:
        placements = [{"app": m.group(1), "position": m.group(2)}]
        if m.group(3):
            placements.append({"app": m.group(3), "position": m.group(4)})
        return desktop.tile(placements)
    m = re.fullmatch(r"maximi[sz]e (.+)", t)
    if m:
        return desktop.tile([{"app": m.group(1), "position": "full"}])
    if re.fullmatch(r"perimeter(?: report| status| check)?|any intruders|(?:has|did) anyone (?:try to )?(?:log|sign) ?in", t):
        return perimeter.report()
    if re.fullmatch(r"index my (?:files|documents)|update (?:the |my )?file index", t):
        return filesearch.index_now()
    m = re.fullmatch(r"(?:search my (?:files|documents|notes) for|what do my (?:files|documents|notes) say about) (.+)", t)
    if m:
        return filesearch.ask(m.group(1))
    if re.fullmatch(r"(?:start|turn on|enable) (?:my |the )?(?:activity )?journal|(?:activity )?journal on", t):
        return journal.switch(True)
    if re.fullmatch(r"(?:stop|turn off|disable) (?:my |the )?(?:activity )?journal|(?:activity )?journal off", t):
        return journal.switch(False)
    if re.fullmatch(r"(?:delete|erase|clear) (?:my |the )?(?:activity )?journal", t):
        return journal.erase()
    m = re.fullmatch(r"what (?:was i|have i been) (?:doing|working on)(.*)|what did i (?:do|work on)(.*)", t)
    if m:
        return journal.summary((m.group(1) or m.group(2) or "today").strip() or "today")
    if re.fullmatch(r"(?:wrap up|summari[sz]e)(?: my| the)? day|end of (?:the )?day(?: report| wrap)?|day wrap|how was my day", t):
        return wrap.day_wrap()
    if re.fullmatch(r"(?:my |the )?(?:weekly review|week in review)|how was my week|review my week", t):
        return wrap.week_review()
    m = re.fullmatch(r"paste (?:what|the thing|the text) i copied(?: about| with| from)? ?(.*)", t)
    if m:
        return cliphistory.recall(m.group(1), paste=True)
    m = re.fullmatch(r"(?:get|bring) back (?:what|the thing) i copied(?: about| with| from)? ?(.*)", t)
    if m:
        return cliphistory.recall(m.group(1), paste=False)
    if re.fullmatch(r"what did i copy(?: earlier| recently| today)?|(?:my )?clipboard history", t):
        return cliphistory.listing()
    from . import hologram
    m = (re.fullmatch(r"(?:play|show)(?: me)? (?:the )?trailer (?:for|of) (.+)", t)
         or re.fullmatch(r"(?:play|show)(?: me)? (?:the )?(.+?) trailer", t))
    if m:
        return hologram.show_video(f"{m.group(1)} trailer")
    m = re.fullmatch(r"(?:play|show)(?: me)? (?:a |the )?video (?:of|about|on|showing) (.+)", t)
    if m:
        return hologram.show_video(m.group(1))
    if re.fullmatch(r"(?:close|stop|hide)(?: the)? video(?: pane)?", t):
        return hologram.show_video(close=True)
    return None


UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


def _credit(t):
    """'How much credit do I need for a month?', 'what's the minimum to start using Claude?'"""
    from . import credit
    money = r"(?:credit|credits|api credit|money|claude credit)"
    if re.fullmatch(rf"(?:whats |what is |how much is )?(?:the )?minimum(?: amount)?(?: of)?(?: {money})?"
                    rf"(?: i need| needed| to buy| i should buy)?(?: to (?:start|get started|begin)(?: using (?:claude|jarvis|it))?"
                    rf"(?: right now| now)?| to get (?:this|it|jarvis) (?:up and )?running)?", t) and "minimum" in t \
            or re.fullmatch(rf"how much {money} do i need to (?:start|get started|begin)(?: using claude| with claude)?(?: right now| now)?", t):
        return credit.minimum()
    m = re.fullmatch(rf"how much {money} (?:do i need|should i buy|will i need|do i have to buy|to buy)(?: to buy)?"
                     rf"(?: for| to last| to cover)? (?P<n>a|an|one|two|three|four|five|six|\d+)? ?(?P<unit>day|week|month|year)s?", t)
    if m:
        n = m.group("n")
        amount = int(n) if n and n.isdigit() else NUMBER_WORDS.get(n, 1) if n else 1
        return credit.estimate(amount * UNIT_DAYS[m.group("unit")])
    m = re.fullmatch(r"how much (?:will|would|does|is) (?:jarvis|it|claude|using claude|this) (?:cost|be)(?: me)?"
                     r"(?: per| a| each| for a| for one)? (?P<unit>day|week|month|year)", t)
    if m:
        return credit.estimate(UNIT_DAYS[m.group("unit")])
    return None


def _meals(t):
    """'Log this meal', 'log my lunch', 'how many calories today?'"""
    from . import meals
    m = re.fullmatch(r"log (?:this|my|the) (?:meal|food|plate|lunch|dinner|breakfast|snack)|log what im eating|"
                     r"log (?:this|my) (?:meal|lunch|dinner|breakfast|snack) (?:of |its |it is )?(?P<note>.+)", t)
    if m:
        return meals.log(m.groupdict().get("note") or "")
    if re.fullmatch(r"how many calories (?:have i (?:had|eaten)|did i (?:have|eat))(?: today)?|calories today|"
                    r"what have i eaten today|how much protein (?:have i had|today)(?: today)?|my (?:calories|meals) today", t):
        return meals.today_summary()
    return None


def _meeting(t):
    """Meeting mode: 'start meeting', 'meeting summary', 'end meeting'."""
    from . import minutes
    if re.fullmatch(r"(?:start|begin|open)(?: a| the| my)? meeting(?: mode| notes)?|meeting mode(?: on)?|"
                    r"take (?:the )?(?:meeting )?(?:notes|minutes)(?: for (?:this|the) meeting)?", t):
        return minutes.start()
    if not minutes.active():
        return None
    if re.fullmatch(r"(?:end|stop|finish|close)(?: the| this)? meeting(?: mode| notes)?|meeting mode off|"
                    r"(?:the )?meeting is over|were done(?: here)?", t):
        return minutes.end()
    if re.fullmatch(r"(?:meeting )?(?:summary|recap)(?: so far)?|summari[sz]e(?: the| this)? meeting(?: so far)?|"
                    r"recap(?: the| this)? meeting(?: so far)?|what have we (?:said|covered|agreed)(?: so far)?", t):
        return minutes.recap()
    return None


def _actions(t):
    """'Undo that', 'block an hour for the report'."""
    if re.fullmatch(r"undo(?: that| it| the last thing| last| please)?|take (?:that|it) back", t):
        from . import undo
        return undo.undo()
    m = (re.fullmatch(rf"(?:block|book|reserve)(?: out)?(?: some)? time (?:for|to) (?P<task>.+?)"
                      rf"(?: for {AMOUNT} (?P<unit>hour|minute)s?)?", t)
         or re.fullmatch(rf"(?:block|book|reserve)(?: out)? {AMOUNT} (?P<unit>hour|minute)s? (?:for|to) (?P<task>.+)", t)
         or re.fullmatch(r"time ?block (?P<task>.+)", t))
    if m:
        from . import google_tools
        if not google_tools.connected():
            return None  # let the AI explain how to connect Google
        n = m.groupdict().get("n")
        amount = 0.5 if n == "half an" else NUMBER_WORDS.get(n, None) if n and not n.isdigit() else int(n) if n else 1
        minutes = amount * (60 if (m.groupdict().get("unit") or "hour") == "hour" else 1)
        try:
            return google_tools.block_time(m.group("task"), int(minutes))
        except google_tools.NotConnected as e:
            return str(e)
    return None


SURFACE = r"(?:the|my) (?:mat|desk|table|workbench|bench)"


def _scanner(t):
    """The desk scanner: 'scan this', 'what's on the mat?', 'start the scanner'..."""
    from . import scanner
    if re.fullmatch(rf"scan(?: this| that| it)?(?: (?:on|from) {SURFACE})?(?: for me)?|scan {SURFACE}|"
                    rf"(?:whats|what is) (?:this |that )?on {SURFACE}|"
                    rf"(?:what is|whats|identify|analy[sz]e) (?:this|that) (?:on|from) {SURFACE}", t):
        return scanner.scan()
    if re.fullmatch(r"(?:start|turn on|enable|activate)(?: the)? (?:desk )?scanner(?: mode)?|"
                    r"(?:desk )?scanner(?: mode)? on|workbench mode(?: on)?", t):
        return scanner.start_watching()
    if re.fullmatch(r"(?:stop|turn off|disable|deactivate)(?: the)? (?:desk )?scanner(?: mode)?|"
                    r"(?:desk )?scanner(?: mode)? off|workbench mode off", t):
        return scanner.stop_watching()
    return None


HOLO = r"(?:hologram|holo|3d model|3d view|3d map|3d breakdown)"


def _hologram(t):
    """'Show me a hologram of a jet engine', 'expand the weather', 'close the hologram', 'expand the turbine'..."""
    from . import hologram
    m = (re.fullmatch(rf"(?:show|open|bring up|display|pull up|give|make|build)(?: me| us)? (?:a |an |the )?{HOLO}"
                      rf"(?: of| for| on)? (.+)", t)
         or re.fullmatch(rf"(?:show|open|bring up|display|pull up)(?: me)? (.+?) (?:as a |in a |in )?(?:{HOLO}|3d)", t)
         or re.fullmatch(r"(?:expand|blow up|enlarge) (?:the |my )?(weather|news|agenda|calendar|system|"
                         r"spotify|music|reminders)(?: panel)?", t))
    if m and m.group(1) not in ("it", "that", "this", "the", "a", "an"):
        return hologram.open_hologram(m.group(1))
    if re.fullmatch(rf"(?:close|hide|dismiss|clear|remove|get rid of|lose) (?:the |that |this )?{HOLO}s?", t):
        return hologram.control("close")
    if re.fullmatch(r"(?:turn on|enable|start|activate) (?:the )?(?:hand|gesture)s? (?:control|tracking|mode)|"
                    r"(?:hand|gesture) (?:control|tracking|mode) on", t):
        return hologram.control("gestures_on")
    if re.fullmatch(r"(?:turn off|disable|stop|deactivate) (?:the )?(?:hand|gesture)s? (?:control|tracking|mode)|"
                    r"(?:hand|gesture) (?:control|tracking|mode) off", t):
        return hologram.control("gestures_off")
    if re.fullmatch(r"(?:show|open|list)(?: me)? (?:my )?(?:hologram )?workspace|whats in my (?:hologram )?workspace", t):
        return hologram.workspace_list()
    if not hologram.state["open"]:
        return None
    # While a hologram is open
    if re.fullmatch(r"(?:show (?:me )?(?:the )?)?wire ?frame(?: mode| view)?", t):
        return hologram.control("wireframe")
    if re.fullmatch(r"(?:show (?:me )?(?:the )?)?x ?ray(?: mode| view| it)?|x ?ray it", t):
        return hologram.control("xray")
    if re.fullmatch(r"(?:solid|normal)(?: mode| view)?|back to (?:the )?normal(?: view)?", t):
        return hologram.control("solid")
    m = re.fullmatch(r"(?:colou?r|make|turn|paint) it (red|blue|green|gold|white|purple|orange|cyan|yellow|pink)", t)
    if m:
        return hologram.control("color", m.group(1))
    m = re.fullmatch(r"(?:save|pin|keep) (?:this|it|the hologram)(?: hologram)?(?: to (?:my )?workspace)?(?: as (.+))?", t)
    if m:
        return hologram.control("save", m.group(1) or "")
    if re.fullmatch(r"(?:throw|send|flick|toss) (?:it|this|the hologram|that) to (?:my )?phone", t):
        return hologram.control("throw")
    if re.fullmatch(r"(?:close|dismiss|hide) it|(?:thats|that will be|that is) all", t):
        return hologram.control("close")
    if re.fullmatch(r"(?:expand|explode|open up|break down|pull apart)(?: it| that| this| more| further)?", t):
        return hologram.control("expand")
    m = re.fullmatch(r"(?:expand|explode|open up|break down)(?: on)? (?:the |a |an )?(.+)", t)
    if m:
        return hologram.control("expand", m.group(1))
    if re.fullmatch(r"collapse(?: it)?|put it (?:back )?together|reassemble(?: it)?", t):
        return hologram.control("collapse")
    if re.fullmatch(r"zoom in|closer|bigger", t):
        return hologram.control("zoom_in")
    if re.fullmatch(r"zoom out|further|smaller", t):
        return hologram.control("zoom_out")
    if re.fullmatch(r"(?:rotate|spin|turn)(?: it| that)?(?: around)?", t):
        return hologram.control("rotate")
    if re.fullmatch(r"reset(?: the)? view|cent(?:er|re) it", t):
        return hologram.control("reset")
    return None


def _reminders(now):
    from . import tools
    items = sorted(tools._load_reminders(), key=lambda r: r["due"])
    if not items:
        return "You have no reminders set."

    def when(due):
        d = dt.datetime.fromisoformat(due)
        day = ("today" if d.date() == now.date() else "tomorrow" if d.date() == now.date() + dt.timedelta(days=1)
               else f"on {d:%A} {d.day} {d:%B}")
        return f"{d:%I:%M %p}".lstrip("0") + f" {day}"
    said = [f"{r['message'].rstrip('.')} at {when(r['due'])}" for r in items[:5]]
    count = f"{len(items)} reminder{'s' if len(items) != 1 else ''}"
    return f"You have {count}: " + "; ".join(said) + "." + (" And more after that." if len(items) > 5 else "")


NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45}
SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
AMOUNT = r"(?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty five|half an)"


def _your(task):
    """'call my mum' -> 'call your mum' (for the spoken confirmation)."""
    swap = {"my": "your", "me": "you", "myself": "yourself", "i": "you", "im": "youre", "ive": "youve"}
    return " ".join(swap.get(w, w) for w in task.split())


def _reminder(t, now):
    """'remind me to call mum in 20 minutes', 'remind me in an hour to stretch', 'remind me to leave at 5:30 pm'."""
    from . import tools
    m = (re.fullmatch(rf"remind me (?:to )?(?P<task>.+?) in {AMOUNT} (?P<unit>second|minute|hour|day)s?", t)
         or re.fullmatch(rf"remind me in {AMOUNT} (?P<unit>second|minute|hour|day)s? (?:to )?(?P<task>.+)", t))
    if m:
        amount, unit = m.group("n"), m.group("unit")
        if amount == "half an":
            seconds = SECONDS[unit] // 2
        else:
            seconds = (int(amount) if amount.isdigit() else NUMBER_WORDS[amount]) * SECONDS[unit]
        if not seconds:
            return None
        task = m.group("task")
        tools.set_reminder(task[0].upper() + task[1:] + ".", seconds=seconds)
        due = now + dt.timedelta(seconds=seconds)
        if seconds >= 3600:
            when = f"at {due:%H:%M}" + ("" if due.date() == now.date() else f" on {due:%A}")
        elif seconds >= 60:
            when = f"in {seconds // 60} minute{'s' if seconds // 60 != 1 else ''}"
        else:
            when = f"in {seconds} second{'s' if seconds != 1 else ''}"
        return f"Okay, I'll remind you to {_your(task)} {when}."
    m = re.fullmatch(r"remind me (?:to )?(?P<task>.+?) at (?P<h>\d{1,2})(?::(?P<min>\d{2}))? ?(?P<ampm>am|pm|a\.?m|p\.?m)?", t)
    if m:
        hour, minute, ampm = int(m.group("h")), int(m.group("min") or 0), (m.group("ampm") or "").replace(".", "")
        if hour > 23 or minute > 59 or (ampm and not 1 <= hour <= 12):
            return None
        if ampm:
            hour = hour % 12 + (12 if ampm == "pm" else 0)
            candidates = [hour]
        else:
            candidates = [hour, hour + 12] if 1 <= hour <= 11 else [hour]  # "at 5": whichever 5 o'clock comes next
        def next_at(h):
            due = now.replace(hour=h % 24, minute=minute, second=0, microsecond=0)
            return due if due > now else due + dt.timedelta(days=1)
        due = min(next_at(h) for h in candidates)
        task = m.group("task")
        tools.set_reminder(task[0].upper() + task[1:] + ".", at=due.strftime("%Y-%m-%dT%H:%M"))
        day = "" if due.date() == now.date() else " tomorrow"
        return f"Okay, I'll remind you to {_your(task)} at {due:%H:%M}{day}."
    return None


def _weather():
    from . import feeds
    try:
        w = feeds.weather(None)
    except Exception:
        return None  # let the AI try (and explain)
    c, u, today = w["current"], w["units"], (w.get("daily") or [{}])[0]
    reply = f"It's {c['text'].lower()} and {c['temp']}{u['temp']} in {w['location']['name'].split(',')[0]}"
    if today.get("high") is not None:
        reply += f", with a high of {today['high']}{u['temp']} today"
    if today.get("rain"):
        reply += f" and a {today['rain']}% chance of rain"
    return reply + "."
