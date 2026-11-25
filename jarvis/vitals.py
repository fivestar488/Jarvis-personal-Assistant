"""The PC as the suit: status reports, diagnostic sweeps and warnings that escalate, film style.

- "Status report" / "damage report": power, processors, memory, storage, uplink, AI core, budget, comms and
  security, each rated nominal / caution / warning / critical. The HUD's reactor turns amber or red to match.
- "Run a sweep" / "run diagnostics": the same, shown phase by phase on the HUD with a progress readout.
- Always on in the background: battery, internet, disk and processor warnings, with the odds
  ("At this rate you have about 40 minutes, sir"), each said once per level, not over and over.
"""
import shutil
import socket
import threading
import time
import uuid

from . import config, tools
from .tools import tool

RANK = {"nominal": 0, "note": 1, "caution": 2, "warning": 3, "critical": 4}


def _hud(event):
    return bool(tools.ui and hasattr(tools.ui, "hud") and tools.ui.hud(event))


# ---------- progress readouts (also used by protocols and file indexing) ----------

class Progress:
    """A named multi-step task shown on the HUD: phases, a percentage, and the result of each phase."""

    def __init__(self, title, steps):
        self.id, self.title, self.steps = uuid.uuid4().hex[:8], title, list(steps)
        _hud({"type": "progress", "id": self.id, "title": title, "steps": self.steps, "current": -1})

    def step(self, i, detail="", level="nominal"):
        _hud({"type": "progress", "id": self.id, "title": self.title, "steps": self.steps, "current": i,
              "detail": detail, "level": level, "pct": round(100 * (i + 1) / max(1, len(self.steps)))})

    def done(self, summary="", level="nominal"):
        _hud({"type": "progress", "id": self.id, "title": self.title, "steps": self.steps, "current": len(self.steps),
              "pct": 100, "done": True, "detail": summary, "level": level})


# ---------- the checks ----------

def _minutes(m):
    m = int(m)
    if m < 60:
        return f"{m} minute{'s' if m != 1 else ''}"
    h, r = divmod(m, 60)
    return f"{h} hour{'s' if h != 1 else ''}" + (f" {r} minutes" if r >= 5 else "")


def _online():
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 443), timeout=2).close()
            return True
        except OSError:
            continue
    return False


def check_power():
    import psutil
    b = psutil.sensors_battery()
    if b is None:
        return ("Power", "nominal", "mains power")
    pct = round(b.percent)
    if b.power_plugged:
        return ("Power", "nominal", f"{pct} percent and charging" if pct < 100 else "fully charged")
    left = b.secsleft if b.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else None
    odds = f", about {_minutes(left / 60)} left" if left and left > 0 else ""
    level = "critical" if pct <= 7 else "warning" if pct <= 15 else "caution" if pct <= 25 else "nominal"
    return ("Power", level, f"{pct} percent on battery{odds}")


def check_processors():
    import psutil
    load = psutil.cpu_percent(interval=0.6)
    level = "warning" if load >= 95 else "caution" if load >= 80 else "nominal"
    return ("Processors", level, f"{round(load)} percent load")


def check_memory():
    import psutil
    vm = psutil.virtual_memory()
    level = "warning" if vm.percent >= 94 else "caution" if vm.percent >= 86 else "nominal"
    return ("Memory", level, f"{round(vm.percent)} percent in use, {vm.available / 2**30:.1f} gigabytes free")


def check_storage():
    free = shutil.disk_usage("C:\\").free / 2**30
    level = "critical" if free < 1 else "warning" if free < 3 else "caution" if free < 10 else "nominal"
    return ("Storage", level, f"{free:.1f} gigabytes free")


def check_uplink():
    return ("Uplink", "nominal", "online") if _online() else ("Uplink", "warning", "no internet connection")


def check_ai():
    from . import local_brain, spend
    if config.BRAIN == "local":
        return ("AI core", "note", "offline systems only, by your settings")
    if config.BRAIN == "auto" and (local_brain.claude_resting() or local_brain.OFFLINE_FLAG.exists()):
        return ("AI core", "caution", "running on offline systems: no API credit")
    if spend.over_budget():
        return ("AI core", "caution", "today's budget is spent, so I'm on the cheapest model")
    return ("AI core", "nominal", f"online, {config.MODEL.replace('claude-', 'Claude ').replace('-', ' ')}")


def check_budget():
    from . import spend
    s = spend.summary()
    if not s["budget"]:
        return ("Budget", "nominal", f"${s['today']:.2f} spent today, no daily limit")
    used = s["today"] / s["budget"]
    level = "warning" if used >= 1 else "caution" if used >= 0.8 else "nominal"
    return ("Budget", level, f"${s['today']:.2f} of ${s['budget']:.2f} today")


def check_comms():
    from . import google_tools
    return ("Comms", "nominal", "Gmail and Calendar linked") if google_tools.connected() \
        else ("Comms", "caution", "Gmail and Calendar aren't connected")


def check_security():
    from . import security
    return ("Security", "note", "security mode armed") if security.running() else ("Security", "nominal", "standing by")


CHECKS = [check_power, check_processors, check_memory, check_storage, check_uplink, check_ai, check_budget,
          check_comms, check_security]
PHASES = ["Power cells", "Processors", "Memory", "Storage", "Uplink", "AI core", "Budget", "Comms", "Security"]


def _run(check):
    try:
        return check()
    except Exception as e:
        return (check.__name__.replace("check_", "").title(), "caution", f"couldn't check ({type(e).__name__})")


def report(items):
    """The spoken status report: short when all is well, specific when it isn't."""
    worst = max((RANK[l] for _, l, _ in items), default=0)
    problems = [(n, l, d) for n, l, d in items if RANK[l] >= RANK["caution"]]
    power = next((d for n, _, d in items if n == "Power"), "")
    if not problems:
        return f"All systems nominal, sir. Power: {power}. Processors and memory are steady, and we're online."
    lead = {4: "We have a critical issue, sir.", 3: "Sir, a few things need your attention.",
            2: "Mostly nominal, sir, with a caveat or two."}[min(worst, 4) if worst >= 2 else 2]
    said = "; ".join(f"{n if n.startswith('AI') else n.lower()}, {d}"
                     for n, _, d in sorted(problems, key=lambda p: -RANK[p[1]]))
    return f"{lead} {said[:1].upper()}{said[1:]}. Everything else is nominal."


def status(sweep=False):
    """Run every check. With sweep=True, it's shown on the HUD phase by phase, like a diagnostic."""
    progress = Progress("SYSTEMS SWEEP", PHASES) if sweep else None
    items = []
    for i, check in enumerate(CHECKS):
        item = _run(check)
        items.append(item)
        if progress:
            progress.step(i, item[2], item[1])
            time.sleep(0.35)  # long enough to read each phase
    worst = max(items, key=lambda it: RANK[it[1]])[1]
    _hud({"type": "vitals", "level": worst, "items": [{"name": n, "level": l, "detail": d} for n, l, d in items]})
    text = report(items)
    if progress:
        progress.done("Sweep complete." if RANK[worst] < 2 else "Sweep complete: attention needed.", worst)
    return text


@tool("Status report / damage report on the PC, suit style: power and time left, processors, memory, storage, "
      "internet, AI core, budget, comms, security. sweep=true shows it on the HUD as a diagnostic sweep "
      "('run a sweep', 'run diagnostics').",
      {"sweep": {"type": "boolean"}})
def status_report(sweep=False):
    return status(sweep)


# ---------- background warnings ----------

_said = {}  # what was last warned about, so each level is said once


def _warn_once(key, level, title, message):
    if RANK.get(_said.get(key), -1) >= RANK[level]:
        return
    _said[key] = level
    from . import notify
    notify.alert(title, message, level=level)
    _hud({"type": "vitals", "level": level})


def _clear(key, message=None):
    if _said.pop(key, None) and message:
        from . import notify
        notify.alert("All clear", message, level="note", phone=False)


def _tick(state):
    import psutil
    b = psutil.sensors_battery()
    if b and not b.power_plugged:
        name, level, detail = check_power()
        if RANK[level] >= RANK["caution"]:
            words = {"caution": "Power is getting low, sir", "warning": "Sir, power is running low",
                     "critical": "Sir, we're about to lose power"}[level]
            plug = " I'd plug in now." if level != "caution" else ""
            _warn_once("power", level, "Battery", f"{words}: {detail}.{plug}")
    elif b and b.power_plugged:
        _clear("power")
    online = _online()
    if not online:
        state["offline_since"] = state.get("offline_since") or time.time()
        if time.time() - state["offline_since"] > 90:
            _warn_once("uplink", "caution", "Connection", "We've lost the internet connection, sir. "
                       "I'm on my offline systems until it's back.")
    else:
        if state.pop("offline_since", None):
            _clear("uplink", "We're back online, sir.")
    name, level, detail = check_storage()
    if RANK[level] >= RANK["caution"]:
        _warn_once("storage", level, "Storage", f"Storage is running short, sir: {detail}.")
    load = psutil.cpu_percent(interval=None)
    state["hot"] = state.get("hot", 0) + 1 if load >= 95 else 0
    if state["hot"] >= 3:  # three checks in a row at full load
        top = max(psutil.process_iter(["name", "cpu_percent"]), key=lambda p: p.info["cpu_percent"] or 0, default=None)
        who = f" {top.info['name']} is the main culprit." if top and top.info["name"] else ""
        _warn_once("cpu", "note", "Processors", f"The processors have been at full load for a few minutes, sir.{who}")
    elif state["hot"] == 0:
        _said.pop("cpu", None)


def start():
    def loop():
        import psutil
        psutil.cpu_percent(interval=None)  # first reading primes the counter
        state = {}
        while True:
            time.sleep(60)
            try:
                _tick(state)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="vitals").start()
