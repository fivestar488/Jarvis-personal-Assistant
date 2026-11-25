"""Flashcard tutor with spaced repetition, by voice.

"Teach me Spanish" / "make flashcards on the French Revolution" -> Jarvis writes a deck of cards.
"Quiz me on my notes" -> a deck from your saved notes.
"Quiz me" / "quiz me on Spanish" -> a short spoken quiz: he asks, you answer out loud, he marks it. Cards you
know come back less often (1, 3, 7, 14, 30 days); ones you miss come back tomorrow. "Stop the quiz" ends it.
"""
import datetime as dt
import difflib
import json
import re
import urllib.request

from . import config, privacy
from .tools import S, tool

DECKS_FILE = config.DATA_DIR / "flashcards.json"
GAPS = [1, 3, 7, 14, 30, 60]  # days until a card comes back, by how many times in a row it was right
QUIZ_LENGTH = 5
SCHEMA = {"type": "object", "properties": {"cards": {"type": "array", "items": {
    "type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
    "required": ["q", "a"], "additionalProperties": False}}}, "required": ["cards"], "additionalProperties": False}
PROMPT = ("Write {n} flashcards for a spoken quiz on: {topic}. q: a short question Jarvis can read aloud. a: the "
          "answer in 1 to 4 words, easy to say out loud (no lists, no punctuation tricks). Start simple. {extra}")

session = None  # {"deck", "queue": [card ids], "current", "right", "asked"} while a quiz runs


def _load():
    try:
        return json.loads(DECKS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(decks):
    DECKS_FILE.write_text(json.dumps(decks, indent=1, ensure_ascii=False), encoding="utf-8")


def _generate(topic, source_text=""):
    import anthropic
    from . import local_brain, spend
    extra = ("Base every card only on these notes:\n" + source_text[:6000]) if source_text else ""
    prompt = PROMPT.format(n=10, topic=topic, extra=extra)
    local = config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))
    if not local:
        try:
            r = anthropic.Anthropic().messages.create(
                model=config.HELPER_MODEL, max_tokens=2000,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": prompt}])
            spend.record(r.model or config.HELPER_MODEL, r.usage, "tutor")
            return json.loads(next((b.text for b in r.content if b.type == "text"), "{}")).get("cards", [])
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            if isinstance(e, (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    body = {"model": config.LOCAL_MODEL, "stream": False, "format": SCHEMA, "options": {"num_predict": 600, "temperature": 0.3},
            "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m", "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(json.load(r)["message"]["content"]).get("cards", [])
    finally:
        local_brain.prompt_disturbed()


def _deck_name(topic):
    return " ".join(re.sub(r"^(the|a|an)\s+", "", topic.lower().strip(" .?!")).split())[:40] or "general"


def make_deck(topic, from_notes=False):
    source = ""
    if from_notes:
        if not config.NOTES_FILE.exists():
            return "You haven't saved any notes yet, sir."
        source = privacy.redact(config.NOTES_FILE.read_text(encoding="utf-8"))
        topic = "my notes"
    try:
        cards = _generate(topic, source)
    except Exception as e:
        return f"I couldn't write the cards, sir: {e}"
    cards = [c for c in cards if c.get("q") and c.get("a")][:15]
    if not cards:
        return "I couldn't come up with any cards for that, sir."
    decks, name = _load(), _deck_name(topic)
    today = dt.date.today().isoformat()
    deck = decks.setdefault(name, [])
    known = {c["q"].lower() for c in deck}
    for c in cards:
        if c["q"].lower() not in known:
            deck.append({"q": c["q"].strip(), "a": c["a"].strip(), "streak": 0, "due": today})
    _save(decks)
    return f"{len(cards)} cards on {name} are ready, sir. Say 'quiz me on {name}' whenever you like."


def due_count():
    today = dt.date.today().isoformat()
    return sum(1 for deck in _load().values() for c in deck if c["due"] <= today)


def start_quiz(topic=""):
    global session
    decks = _load()
    if not decks:
        return "You have no flashcards yet, sir. Say 'teach me Spanish', or 'quiz me on my notes'."
    name = _deck_name(topic) if topic else None
    if name and name not in decks:
        match = difflib.get_close_matches(name, decks, n=1, cutoff=0.5)
        if not match:
            return make_deck(topic) + " " + start_quiz(topic) if topic else "No deck by that name, sir."
        name = match[0]
    today = dt.date.today().isoformat()
    pool = [(n, i) for n, deck in decks.items() if not name or n == name for i, c in enumerate(deck) if c["due"] <= today]
    if not pool:
        nxt = min((c["due"] for n, deck in decks.items() if not name or n == name for c in deck), default=None)
        return f"Nothing due today, sir. The next cards come up on {nxt}." if nxt else "That deck is empty, sir."
    session = {"queue": pool[:QUIZ_LENGTH], "right": 0, "asked": 0}
    return f"Quiz time, sir: {len(session['queue'])} cards. " + _ask()


def _ask():
    n, i = session["queue"][0]
    return f"Question {session['asked'] + 1}: {_load()[n][i]['q']}"


def _norm(s):
    return " ".join(re.sub(r"[^a-z0-9áéíóúñüàèìòùçâêîôûäëïöß ]", " ", s.lower()).split())


def answer(text):
    """His answer during a quiz. Returns what to say."""
    global session
    decks = _load()
    n, i = session["queue"].pop(0)
    card = decks[n][i]
    said, right_answer = _norm(text), _norm(card["a"])
    correct = bool(said) and (right_answer in said or difflib.SequenceMatcher(None, said, right_answer).ratio() >= 0.8)
    card["streak"] = card["streak"] + 1 if correct else 0
    card["due"] = (dt.date.today() + dt.timedelta(days=GAPS[min(card["streak"], len(GAPS) - 1)] if correct else 1)).isoformat()
    _save(decks)
    session["asked"] += 1
    session["right"] += correct
    reply = "Correct." if correct else f"Not quite, sir: it's {card['a']}."
    if session["queue"]:
        return f"{reply} {_ask()}"
    right, asked = session["right"], session["asked"]
    session = None
    verdict = " A perfect score, sir." if right == asked else " Not bad at all." if right >= asked / 2 else " We'll go again tomorrow."
    return f"{reply} That's the quiz: {right} out of {asked}.{verdict}"


def stop():
    global session
    if not session:
        return "There's no quiz running, sir."
    score = f"{session['right']} out of {session['asked']}"
    session = None
    return f"Quiz stopped: {score} so far."


@tool("Flashcard tutor: make a deck ('teach me Spanish', 'flashcards on X', from_notes for 'quiz me on my notes'), "
      "start a spoken quiz ('quiz me', 'quiz me on Spanish'), or say how many cards are due.",
      {"action": {"type": "string", "enum": ["make", "quiz", "due"]}, "topic": S("The subject"),
       "from_notes": {"type": "boolean"}}, ["action"])
def flashcards(action, topic="", from_notes=False):
    if action == "make":
        return make_deck(topic, from_notes)
    if action == "quiz":
        return start_quiz(topic)
    n = due_count()
    return f"{n} flashcard{'s' if n != 1 else ''} due today, sir." if n else "No flashcards due today, sir."
