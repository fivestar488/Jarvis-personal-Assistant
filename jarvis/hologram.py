"""Holograms on the HUD, like Tony Stark's workshop: 3D views you open by voice and control with your hands.

Three kinds (drawn by web/holo.js):
- panels: the weather, news, agenda, system, Spotify or reminders, blown up full-screen;
- objects: built-in 3D models (a globe, the solar system, an atom, DNA, a jet engine) you spin and pull apart;
- topics: anything else becomes a 3D map. Clap and the selected part bursts into its own parts, which the AI
  works out (expand() below).
Hand gestures are tracked by the browser from the webcam; no video leaves the PC.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

from . import config, tools
from .tools import S, tool

PANELS = {
    "weather": r"weather|forecast|atmospherics",
    "news": r"news|headlines?|stories",
    "agenda": r"agenda|calendar|schedule|meetings?|events?",
    "system": r"system|diagnostics|computer|pc|laptop|cpu|battery",
    "spotify": r"spotify|music|song|now playing|what'?s playing",
    "reminders": r"reminders?|alarms?|timers?",
}
OBJECTS = {
    "globe": r"globe|earth|world|planet earth",
    "solar system": r"solar system|planets",
    "atom": r"atoms?",
    "dna": r"dna|double helix|genes?",
    "jet engine": r"(jet |turbine |aircraft |plane )?engines?",
}
PARTS_SCHEMA = {
    "type": "object",
    "properties": {"parts": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "detail": {"type": "string"}},
        "required": ["name", "detail"], "additionalProperties": False}}},
    "required": ["parts"], "additionalProperties": False,
}
EXPAND_PROMPT = ("You break things down for a holographic display, like Tony Stark's workshop. Given a subject (and the "
                 "path that led to it), list its {n} most important parts, components or sub-topics. name: 1 to 3 "
                 "words. detail: one plain factual sentence of at most 15 words. No repeats of the subject itself.")

# What the HUD is showing right now (it tells us over the websocket), so "expand the turbine" knows there's one open
state = {"open": False, "kind": "", "subject": ""}


def classify(subject):
    """'the weather' -> ('panel', 'weather'), 'planet earth' -> ('object', 'globe'), else ('topic', subject)."""
    s = re.sub(r"^(the|a|an|my)\s+", "", subject.strip().lower()).strip(" .?!")
    for kind, table in (("panel", PANELS), ("object", OBJECTS)):
        for name, pattern in table.items():
            if re.fullmatch(rf"(?:{pattern})(?: panel| model| hologram)?", s):
                return kind, name
    return "topic", re.sub(r"^(the|a|an|my)\s+", "", subject.strip(), flags=re.I).strip(" .?!")


def _send(event):
    """Send a hologram event to the HUD. False when no HUD is open (e.g. the console-only voice mode)."""
    if not tools.ui or not hasattr(tools.ui, "hud"):
        return False
    return tools.ui.hud({"type": "holo", **event})


WORKSPACE_FILE = config.DATA_DIR / "holo-workspace.json"


def _workspace():
    try:
        return json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_spec(name, spec):
    """A hologram saved to the workspace (the HUD sends what it's showing, including expanded parts)."""
    name = " ".join(str(name or spec.get("subject") or "hologram").lower().split())[:60]
    ws = _workspace()
    ws[name] = spec
    WORKSPACE_FILE.write_text(json.dumps(ws, ensure_ascii=False)[:2_000_000], encoding="utf-8")
    return name


def workspace_list():
    names = list(_workspace())
    if not names:
        return "Your hologram workspace is empty, sir. Say 'save this hologram' while one is open."
    return ("In your workspace: " + ", ".join(names) + ". Say 'show me a hologram of' and the name to bring one back.")


def open_hologram(subject, parts=None):
    saved = _workspace().get(" ".join(subject.lower().split()).removeprefix("the ").removeprefix("my "))
    if saved:  # from the workspace, exactly as it was saved
        if not _send({"action": "open", **saved}):
            return "Holograms need the HUD. Start Jarvis with jarvis.bat and try again."
        return f"Restored {saved.get('subject', subject)} from your workspace, sir."
    kind, name = classify(subject)
    event = {"action": "open", "kind": kind, "subject": name}
    if kind == "topic" and parts:
        event["parts"] = [{"name": str(p.get("name", ""))[:40], "detail": str(p.get("detail", ""))[:160]}
                          for p in parts if isinstance(p, dict) and p.get("name")][:6]
    if not _send(event):
        return "Holograms need the HUD. Start Jarvis with jarvis.bat and try again."
    hint = {"panel": "Spread your hands to zoom, flick to close.",
            "object": "Clap or spread your hands to pull it apart, pinch and drag to turn it.",
            "topic": "Clap to expand a part, point and pinch to pick one."}[kind]
    return f"Hologram of the {name} is up. {hint}"


def control(action, target=""):
    if not _send({"action": action, "target": target}):
        return "Holograms need the HUD. Start Jarvis with jarvis.bat and try again."
    return {"close": "Hologram closed.", "expand": "Expanding.", "collapse": "Putting it back together.",
            "zoom_in": "Zooming in.", "zoom_out": "Zooming out.", "rotate": "Rotating.", "reset": "View reset.",
            "wireframe": "Wireframe view.", "xray": "X-ray view.", "solid": "Back to the normal view.",
            "color": f"Recoloured{' ' + target if target else ''}, sir.", "save": "Saved to your workspace, sir.",
            "throw": "Sent to your phone, sir.",
            "gestures_on": "Hand control is on. The camera light will stay on while it's running.",
            "gestures_off": "Hand control is off.", "restore": "Brought it back out of the bin, sir."}.get(action, "Done.")


@tool("Open a 3D hologram on the HUD that he controls with his hands (clap or spread hands to expand, pinch and "
      "drag to rotate, flick to dismiss). subject: a HUD panel (weather, news, agenda, system, spotify, reminders), "
      "a built-in 3D model (globe, solar system, atom, dna, jet engine), or any topic, which becomes an expandable "
      "3D map of its parts.",
      {"subject": S("What to show, e.g. 'weather', 'jet engine', 'how the stock market works'"),
       "parts": {"type": "array", "description": "For a topic: its 4-6 main parts, so the hologram opens instantly",
                 "items": {"type": "object", "properties": {"name": S("1-3 words"), "detail": S("One short sentence")},
                           "required": ["name", "detail"]}}},
      ["subject"])
def show_hologram(subject, parts=None):
    return open_hologram(subject, parts)


@tool("Change the hologram on the HUD: close it, expand (a named part, or the selected one), collapse it, zoom, "
      "rotate, reset the view, wireframe / x-ray / solid view, recolour it (target = a colour), save it to his "
      "workspace (target = a name), throw it to his phone, turn webcam hand control on/off, or restore (bring "
      "back the last picture or hologram he threw in the bin).",
      {"action": {"type": "string", "enum": ["close", "expand", "collapse", "zoom_in", "zoom_out", "rotate", "reset",
                                             "wireframe", "xray", "solid", "color", "save", "throw",
                                             "gestures_on", "gestures_off", "restore"]},
       "target": S("For expand: the part's name. For color: the colour. For save: a name for it.")},
      ["action"])
def hologram_control(action, target=""):
    return control(action, target)


# ---------- sculpting: simple shapes stretched and turned by hand ----------
SHAPES = ["cube", "sphere", "cylinder", "cone", "torus", "pyramid"]
SHAPE_WORDS = {"box": "cube", "block": "cube", "ball": "sphere", "orb": "sphere", "tube": "cylinder", "pipe": "cylinder",
               "donut": "torus", "doughnut": "torus", "ring": "torus"}
SCULPT_SAY = {"add": "Added a {target}.", "stretch": "Done.", "move": "Moved.", "turn": "Turned.",
              "remove": "Removed that piece.", "next": "Next piece.", "select": "Selected the {target}.",
              "undo": "Put it back how it was."}


def shape_name(word):
    w = (word or "").lower().strip().rstrip("s")
    return SHAPE_WORDS.get(w, w if w in SHAPES else "")


def sculpt(op, target=""):
    """op 'new' opens the sculpting bench with one shape; the others change the piece that's selected."""
    if op == "new":
        name = shape_name(target) or "cube"
        if not _send({"action": "open", "kind": "sculpt", "subject": "Sculpture", "shapes": [{"type": name}]}):
            return "Sculpting needs the HUD. Start Jarvis with jarvis.bat and try again."
        return (f"A {name} on the bench, {config.USER_NAME}. Pinch with both hands and pull to stretch it, pinch and "
                "drag to turn it. Say 'add a sphere' for another piece, and 'save it as' a name when you're done.")
    if op == "add":
        target = shape_name(target) or "cube"
    if not state["open"] or state["kind"] != "sculpt":
        return "There's no sculpture open, sir. Say 'sculpt a cube' to start one."
    if not _send({"action": "sculpt", "op": op, "target": target}):
        return "Sculpting needs the HUD."
    return SCULPT_SAY.get(op, "Done.").format(target=target)


@tool("The hologram sculpting bench: simple shapes (cube, sphere, cylinder, cone, torus, pyramid) he stretches with "
      "both hands. op 'new' (target = a shape) starts one; 'add' (target = shape) adds a piece; 'stretch' (target: "
      "taller, shorter, wider, thinner, deeper, flatter, bigger, smaller); 'move' (target: up, down, left, right, "
      "forward, back); 'turn' (target: left, right, over); 'remove' the selected piece; 'next' piece; 'select' "
      "(target = shape); 'undo'. Save it with hologram_control save.",
      {"op": {"type": "string", "enum": ["new", "add", "stretch", "move", "turn", "remove", "next", "select", "undo"]},
       "target": S("A shape, size word or direction")}, ["op"])
def sculpt_hologram(op, target=""):
    return sculpt(op, target)


@tool("List the holograms saved in his workspace.")
def hologram_workspace():
    return workspace_list()


def find_video(query):
    """The top YouTube result's video id for a search, or None."""
    import urllib.parse
    req = urllib.request.Request("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query),
                                 headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    ids = re.findall(r'"videoId":"([\w-]{11})"', html)
    return ids[0] if ids else None


@tool("Play a video in a floating pane on the HUD (the top YouTube result), e.g. 'play the trailer for X', "
      "'show me a video of how a jet engine works'. close=true closes the pane.",
      {"query": S("What to search YouTube for"), "close": {"type": "boolean"}})
def show_video(query="", close=False):
    if close:
        return "Video closed." if _send({"action": "video_close"}) else "There's no HUD open."
    try:
        vid = find_video(query)
    except Exception:
        vid = None
    if not vid:
        return f"I couldn't find a video for {query}, sir."
    if not _send({"action": "video", "id": vid, "title": query}):
        return "The video pane needs the HUD open. Start Jarvis with jarvis.bat."
    return f"On screen, sir: {query}."


# ---------- pictures on glass cards over the HUD (web/holo.js "IMAGES") ----------
IMG_UA = {"User-Agent": "JARVIS-desktop-assistant/1.0 (open-source personal assistant)"}
IMG_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _wiki_json(host, params):
    import urllib.parse
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({"format": "json", "formatversion": 2, **params})
    req = urllib.request.Request(url, headers=IMG_UA)
    return json.loads(urllib.request.urlopen(req, timeout=12).read().decode("utf-8"))


def find_web_images(query, count=1):
    """Pictures of a subject: the main photo of its best Wikipedia article first, then Wikimedia Commons photos.
    Free, no key, and the pictures are openly licensed."""
    found, seen = [], set()

    def add(src, title, credit):
        import urllib.parse
        # the same photo comes back at different sizes ("1280px-Name.jpg" and "Name.jpg"): compare the file name
        key = re.sub(r"^\d+px-", "", urllib.parse.unquote((src or "").split("?")[0].rsplit("/", 1)[-1])).lower()
        if src and key not in seen:
            seen.add(key)
            found.append({"src": src, "title": title, "credit": credit})

    try:
        data = _wiki_json("en.wikipedia.org", {"action": "query", "generator": "search", "gsrsearch": query,
                                               "gsrlimit": 4, "prop": "pageimages", "piprop": "thumbnail",
                                               "pithumbsize": 1280, "redirects": 1})
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
        for p in pages[:1]:  # the subject's own article; more pictures come from Commons
            add((p.get("thumbnail") or {}).get("source"), p.get("title", query), "Wikipedia")
    except Exception:
        pass
    if len(found) < count:
        try:
            data = _wiki_json("commons.wikimedia.org", {"action": "query", "generator": "search",
                                                        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
                                                        "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|mime",
                                                        "iiurlwidth": 1280})
            pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
            for p in pages:
                info = (p.get("imageinfo") or [{}])[0]
                if info.get("mime", "").startswith("image/") and len(found) < count:
                    add(info.get("thumburl") or info.get("url"), query, "Wikimedia Commons")
        except Exception:
            pass
    return found[:count]


def _picture_folders():
    home = Path.home()
    names = ["Pictures", "Desktop", "Downloads", "OneDrive/Pictures", "OneDrive/Desktop"]
    return [home / n for n in names if (home / n).is_dir()]


def find_local_image(name):
    """An image file by path, or by words in its name from Pictures, Desktop and Downloads."""
    p = Path(os.path.expandvars(os.path.expanduser(name.strip().strip('"'))))
    if p.is_file() and p.suffix.lower() in IMG_TYPES:
        return p
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in {"the", "a", "my", "picture", "photo", "image", "of"}]
    if not words:
        return None
    best, scanned = None, 0
    for folder in _picture_folders():
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                scanned += 1
                if scanned > 20000:
                    return best
                fp = Path(root) / f
                if fp.suffix.lower() not in IMG_TYPES or not all(w in f.lower() for w in words):
                    continue
                try:
                    attrs = getattr(fp.stat(), "st_file_attributes", 0)
                    if attrs & 0x400000 or attrs & 0x1000:  # OneDrive "online-only": don't download it
                        continue
                    if best is None or fp.stat().st_mtime > best.stat().st_mtime:
                        best = fp
                except OSError:
                    pass
    return best


def local_image_data(path):
    """A picture file shrunk to at most 1600px and packed into a data: URL, so it never needs serving from disk."""
    import base64
    import io
    from PIL import Image
    with Image.open(path) as im:
        im.thumbnail((1600, 1600))
        out = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P"):
            im.convert("RGBA").save(out, "PNG", optimize=True)
            mime = "image/png"
        else:
            im.convert("RGB").save(out, "JPEG", quality=86)
            mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(out.getvalue()).decode()


@tool("Show pictures on the HUD as floating glass cards he can grab, move, stretch, spotlight or throw away with his "
      "hands (or the mouse). Use this whenever he asks to see a picture, photo or image of something, e.g. 'show me a "
      "picture of the Eiffel Tower', 'show me 3 photos of red pandas', 'bring up the photo of my dog on my desktop'. "
      "query finds openly licensed photos online; file shows a picture from his PC (a path, or words from its file "
      "name); url shows one specific https image link. add=true keeps the pictures already up. close=true clears them.",
      {"query": S("What the picture is of"), "count": {"type": "integer", "description": "How many pictures (1-4)"},
       "file": S("A picture on his PC: a full path, or words from its file name"),
       "url": S("A direct https link to an image"), "add": {"type": "boolean"}, "close": {"type": "boolean"}})
def show_image(query="", count=1, file="", url="", add=False, close=False):
    if close:
        return "Pictures cleared." if _send({"action": "image_close"}) else "There's no HUD open."
    count = max(1, min(4, int(count or 1)))
    if file:
        path = find_local_image(file)
        if not path:
            return f"I couldn't find a picture called {file} in Pictures, Desktop or Downloads, sir."
        try:
            images = [{"src": local_image_data(path), "title": path.stem, "credit": path.parent.name}]
        except Exception as e:
            return f"I found {path.name} but couldn't open it: {e}"
    elif url:
        if not url.startswith("https://"):
            return "I can only show https image links."
        images = [{"src": url, "title": query, "credit": re.sub(r"^https://(www\.)?([^/]+).*", r"\2", url)}]
    else:
        if not query:
            return "What would you like a picture of?"
        try:
            images = find_web_images(query, count)
        except Exception:
            images = []
        if not images:
            return f"I couldn't find a picture of {query}, sir."
    if not _send({"action": "image", "images": images, "replace": not add}):
        return "Pictures need the HUD open. Start Jarvis with jarvis.bat."
    what = images[0]["title"] if file else (query or images[0]["title"])
    n = len(images)
    return f"On screen, sir: {n} pictures of {what}." if n > 1 else f"On screen, sir: {what}."


# ---------- the parts of a topic, for the "expand" step ----------

def _ask_claude(path, n):
    import anthropic
    from . import spend
    response = anthropic.Anthropic().messages.create(
        model=config.HELPER_MODEL,
        max_tokens=1500,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": PARTS_SCHEMA}},
        system=EXPAND_PROMPT.format(n="4 to 6"),
        messages=[{"role": "user", "content": " > ".join(path)}],
    )
    spend.record(response.model or config.HELPER_MODEL, response.usage, "holograms")
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    return json.loads(text).get("parts", [])


def _ask_local(path, n):
    """The free model on this PC. Ollama's structured output keeps even a small model to the JSON shape."""
    from . import local_brain
    body = {"model": config.LOCAL_MODEL, "stream": False, "format": PARTS_SCHEMA,
            "keep_alive": f"{local_brain.KEEP_LOADED_MINUTES}m", "options": {"num_predict": 260, "temperature": 0.3},
            "messages": [{"role": "system", "content": EXPAND_PROMPT.format(n=n)},
                         {"role": "user", "content": " > ".join(path)}]}
    req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            text = json.load(r)["message"]["content"]
    finally:
        local_brain.prompt_disturbed()  # the chat model's remembered prompt was replaced by this one
    return json.loads(text).get("parts", [])


def expand(path):
    """The parts of the last subject in `path` (e.g. ['jet engine', 'turbine']). Uses Claude, or the free local
    model when that's the mode (or Claude is out of credit / offline in auto mode)."""
    import anthropic
    from . import local_brain, spend
    path = [str(p)[:80] for p in path if str(p).strip()][-4:]
    if not path:
        return []
    local = config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))
    parts = None
    if not local:
        try:
            parts = _ask_claude(path, 5)
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            no_credit = isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e.message).lower()
            if no_credit or isinstance(e, (anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    if parts is None:
        parts = _ask_local(path, 4)
    seen, clean = {p.lower() for p in path}, []
    for p in parts:
        name = str(p.get("name", "")).strip()[:40]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            clean.append({"name": name, "detail": str(p.get("detail", "")).strip()[:160]})
    return clean[:6]


def panel_data(name):
    """Data for the Spotify, reminders and situation panels (the others use the HUD's own feeds)."""
    if name == "situation":
        from . import boards
        return {"items": boards.situation_items()}
    if name == "spotify":
        fn = tools.TOOLS.get("spotify_now_playing", {}).get("fn")
        return {"text": fn() if fn else "Spotify isn't set up."}
    if name == "reminders":
        items = sorted(tools._load_reminders(), key=lambda r: r["due"])
        return {"items": [{"due": r["due"], "message": r["message"], "important": bool(r.get("important"))}
                          for r in items]}
    return {}
