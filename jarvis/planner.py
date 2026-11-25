"""'Run the simulation': what-if planning, film style. "Simulate my week if I take Friday off", "run a simulation
on buying a PS5". Jarvis lays the idea against your calendar, reminders and spending, shows the run as a progress
readout, and answers with the odds."""
import datetime as dt
import json
import time
import urllib.request

from . import config, privacy, tools
from .tools import S, tool

PROMPT = ("You are JARVIS running a quick what-if simulation for {owner}. Using only the facts given (his calendar, "
          "reminders and recent spending) plus common sense, assess the scenario. Reply in 3 to 5 short spoken "
          "sentences: start with 'Simulation complete.', give the likely outcome with rough odds as a percentage, "
          "name the main conflict or risk (a specific event, deadline or cost if there is one), and end with a "
          "recommendation. Dry wit is fine. Plain text, no lists or markdown.")


def _facts():
    lines = []
    now = dt.datetime.now()
    try:
        from . import google_tools
        if google_tools.connected():
            evs = google_tools.list_events(now.replace(hour=0, minute=0), now + dt.timedelta(days=14))
            lines.append("Calendar (next 14 days): " + ("; ".join(
                f"{dt.datetime.fromisoformat(e['start']).strftime('%a %d %b %H:%M') if not e['all_day'] else e['start'] + ' all day'} "
                f"{e['title'].strip()}" for e in evs[:40]) or "nothing scheduled"))
    except Exception:
        pass
    rem = sorted(tools._load_reminders(), key=lambda r: r["due"])[:15]
    if rem:
        lines.append("Reminders: " + "; ".join(f"{r['due'][:16].replace('T', ' ')} {r['message']}" for r in rem))
    try:
        from . import spend
        s = spend.summary()
        lines.append(f"API spend this month: ${s['month']:.2f}, daily budget ${s['budget'] or 0:.2f}")
    except Exception:
        pass
    lines.append(f"Now: {now:%A %d %B %Y, %H:%M}")
    return privacy.redact("\n".join(lines))


def _ask(scenario, facts):
    import anthropic
    from . import local_brain, spend
    system = PROMPT.format(owner=config.OWNER_NAME)
    content = f"Scenario: {scenario}\n\nFacts:\n{facts}"
    local = config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))
    if not local:
        try:
            r = anthropic.Anthropic().messages.create(model=config.HELPER_MODEL, max_tokens=700, output_config={"effort": "low"},
                                                      system=system, messages=[{"role": "user", "content": content}])
            spend.record(r.model or config.HELPER_MODEL, r.usage, "simulation")
            return next((b.text for b in r.content if b.type == "text"), "").strip()
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            if isinstance(e, (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    body = {"model": config.LOCAL_MODEL, "stream": False, "options": {"num_predict": 180, "temperature": 0.4},
            "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content[:5000]}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["message"]["content"].strip()
    finally:
        local_brain.prompt_disturbed()


def simulate(scenario):
    from .vitals import Progress
    p = Progress("RUNNING SIMULATION", ["Loading calendar", "Loading commitments", "Modelling outcomes", "Computing odds"])
    p.step(0, scenario[:60])
    facts = _facts()
    time.sleep(0.4)
    p.step(1, "Reminders and budget")
    time.sleep(0.4)
    p.step(2, "Running scenarios")
    try:
        answer = _ask(scenario, facts)
    except Exception as e:
        p.done("Simulation failed.", "caution")
        return f"The simulation failed, sir: {e}"
    p.step(3, "Done")
    p.done("Simulation complete.")
    return answer if answer.lower().startswith("simulation") else "Simulation complete. " + answer


@tool("'Run the simulation': a what-if plan against his calendar, reminders and spending, answered with odds and a "
      "recommendation. 'simulate my week if I take Friday off', 'run a simulation on buying a PS5'.",
      {"scenario": S("The what-if, in his words")}, ["scenario"])
def run_simulation(scenario):
    return simulate(scenario)
