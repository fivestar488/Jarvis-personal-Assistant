"""Desk scanner, like Tony Stark's workbench: a webcam pointed down at a mat or desk. Put something on it and
Jarvis works out what it is, tells you about it, and shows the scan as a hologram on the HUD.

- "Scan this" / "what's on the mat?": one scan now.
- "Start the scanner": watch mode. Jarvis watches the mat and scans by himself whenever something new is put
  down and held still for a moment (hands moving over it don't count).

Camera: JARVIS_DESK_CAMERA in .env (a camera number), or "auto": a second webcam if one is plugged in, otherwise
the laptop's own. Seeing needs Claude, or in free mode a small vision model (JARVIS_LOCAL_VISION_MODEL, default
moondream: `ollama pull moondream`).
"""
import base64
import json
import threading
import time
import urllib.request

from . import config, tools
from .tools import S, tool

SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "what": {"type": "string"},
        "details": {"type": "array", "items": {
            "type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
            "required": ["label", "value"], "additionalProperties": False}},
        "tip": {"type": "string"},
        "box": {"type": "array", "items": {"type": "integer"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["name", "what", "details", "tip", "box", "confidence"], "additionalProperties": False,
}
SCAN_PROMPT = (
    "You are JARVIS's workbench scanner. The photo is from a camera looking down at {owner}'s desk or mat. Identify "
    "the main object placed on it; ignore the mat itself, hands, and cables at the edges. "
    "name: what it is, as specific as you can tell (brand or model only if clearly visible). "
    "what: one or two short spoken sentences on what it is and what it's for. "
    "details: 3 to 5 useful facts with short labels (for example how it works, typical price, material, specs, "
    "care or safety). tip: one practical tip or interesting fact. Plain text, no markdown. "
    "box: where the object is in the photo as [left, top, right, bottom], each 0 to 1000 of the width or height "
    "([] if nothing's there). confidence: how sure you are what it is. "
    "If the surface is empty or the photo is too unclear, set name to 'Nothing recognised' and say so in what.")

_camera_index = None
_cam_lock = threading.Lock()


def camera_index():
    """Which camera looks at the desk."""
    global _camera_index
    if _camera_index is None:
        if config.DESK_CAMERA.isdigit():
            _camera_index = int(config.DESK_CAMERA)
        else:  # auto: the first extra camera that works, else the main one
            import cv2
            try:  # (missing cameras make OpenCV print warnings)
                cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
            except AttributeError:
                pass
            _camera_index = config.CAMERA_INDEX
            for i in (1, 2, 3):
                if i == config.CAMERA_INDEX:
                    continue
                cam = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                ok = cam.isOpened() and cam.read()[0]
                cam.release()
                if ok:
                    _camera_index = i
                    break
    return _camera_index


def _open():
    import cv2
    cam = cv2.VideoCapture(camera_index(), cv2.CAP_DSHOW)
    if not cam.isOpened():
        cam.release()
        raise RuntimeError("Couldn't open the desk camera. Is it plugged in, or in use by another app "
                           "(hand control in the HUD uses the laptop camera)?")
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cam


def _jpeg(frame, width=1024):
    import cv2
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, int(h * width / w)))
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tobytes()


def capture():
    """One photo of the desk, as JPEG bytes."""
    from . import security
    if _watch_frame is not None and watching():
        return _jpeg(_watch_frame)  # watch mode already has the camera open
    if security.running() and security.latest_frame is not None and camera_index() == config.CAMERA_INDEX:
        return _jpeg(security.latest_frame)
    with _cam_lock:
        cam = _open()
        try:
            ok, frame = False, None
            for _ in range(8):  # the first frames are dark while the camera adjusts its exposure
                ok, frame = cam.read()
            if not ok:
                raise RuntimeError("The desk camera didn't return an image.")
        finally:
            cam.release()
    return _jpeg(frame)


# ---------- working out what it is ----------

def _use_local():
    from . import local_brain, spend
    return config.BRAIN == "local" or (config.BRAIN == "auto" and (local_brain.claude_resting() or spend.over_budget()))


def _ask_claude(jpeg, question):
    import anthropic
    from . import spend
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(jpeg).decode()}},
               {"type": "text", "text": f"He asks: {question}" if question else "What is this?"}]
    response = anthropic.Anthropic().messages.create(
        model=config.HELPER_MODEL, max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCAN_SCHEMA}},
        system=SCAN_PROMPT.format(owner=config.OWNER_NAME),
        messages=[{"role": "user", "content": content}])
    spend.record(response.model or config.HELPER_MODEL, response.usage, "desk scanner")
    return json.loads(next((b.text for b in response.content if b.type == "text"), "{}"))


def _ask_local(jpeg, question):
    """The free vision model on this PC. Small models describe well but don't do structured answers reliably,
    so it's asked two short plain questions."""
    from . import local_brain

    def ask(prompt, tokens):
        body = {"model": config.LOCAL_VISION_MODEL, "stream": False, "keep_alive": "10m",
                "options": {"num_predict": tokens, "temperature": 0.2},
                "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(jpeg).decode()]}]}
        req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["message"]["content"].strip()
    try:
        name = ask("What is the main object in this picture? Answer with just its name, a few words.", 16)
        what = ask(question or "Describe this object in two short sentences: what it is and what it's used for.", 90)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"My offline eyes aren't installed yet. Run: ollama pull {config.LOCAL_VISION_MODEL}")
        raise
    finally:
        local_brain.prompt_disturbed()  # the chat model may have been swapped out of memory
    name = name.strip(" .\"'\n").split("\n")[0][:60] or "Something"
    return {"name": name[:1].upper() + name[1:], "what": what, "details": [], "tip": "", "box": [], "confidence": "low"}


def analyze(jpeg, question=""):
    import anthropic
    from . import local_brain
    if not _use_local():
        try:
            return _ask_claude(jpeg, question)
        except anthropic.APIError as e:
            if config.BRAIN != "auto" or not local_brain.available():
                raise
            no_credit = isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e.message).lower()
            if no_credit or isinstance(e, (anthropic.AuthenticationError, anthropic.APIConnectionError)):
                local_brain.rest_claude()
    return _ask_local(jpeg, question)


def _spoken(result):
    name = result.get("name") or "Something"
    if name.lower().startswith("nothing"):
        return result.get("what") or "I don't see anything on the mat."
    what = result.get("what", "").strip()
    what = what[:1].upper() + what[1:]
    return what if name.lower() in what.lower() else f"That's {_article(name)}. {what}".strip()


def _article(name):
    """'Coffee mug' -> 'a coffee mug', 'Raspberry Pi 4' -> 'a Raspberry Pi 4', 'Scissors' -> 'scissors'."""
    if name[1:] == name[1:].lower():
        name = name[:1].lower() + name[1:]
    low = name.lower()
    if low.split()[0] in ("a", "an", "the", "some") or (low.endswith("s") and not low.endswith("ss")):
        return name
    first = name.split()[0]
    if len(first) > 1 and first.isupper():  # an acronym is said letter by letter: "a USB cable", "an HDMI cable"
        return ("an " if first[0] in "AEFHILMNORSX" else "a ") + name
    return ("an " if low[:1] in "aeiou" else "a ") + name


def scan(question=""):
    """Photograph the desk, show it on the HUD as a scan hologram, work out what's there. Returns what to say."""
    from . import hologram
    try:
        jpeg = capture()
    except Exception as e:
        return str(e)
    image = "data:image/jpeg;base64," + base64.b64encode(_jpeg_small(jpeg)).decode()
    hologram._send({"action": "open", "kind": "scan", "subject": "Scanning", "image": image})
    try:
        result = analyze(jpeg, question)
    except Exception as e:
        message = str(e) if isinstance(e, RuntimeError) else f"I couldn't analyse it: {e}"
        hologram._send({"action": "scan_result", "result": {"name": "Scan failed", "what": message, "details": [], "tip": ""}})
        return message
    hologram._send({"action": "scan_result", "result": result})
    return _spoken(result)


def _jpeg_small(jpeg):
    """A lighter copy of the photo for the HUD."""
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    return _jpeg(frame, 720)


# ---------- watch mode: scan by itself when something is put down ----------

_watch_thread = None
_watch_stop = threading.Event()
_watch_frame = None


def watching():
    return bool(_watch_thread and _watch_thread.is_alive())


def _small(frame):
    import cv2
    g = cv2.cvtColor(cv2.resize(frame, (96, 72)), cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0)


def _changed(a, b):
    """Fraction of the picture that differs noticeably between two small grey frames."""
    import cv2
    return float((cv2.absdiff(a, b) > 28).mean())


def _watch():
    global _watch_frame
    try:
        cam = _open()
    except Exception as e:
        _announce(str(e))
        return
    try:
        for _ in range(15):  # let the brightness settle
            cam.read()
        ok, frame = cam.read()
        if not ok:
            _announce("The desk camera didn't return an image.")
            return
        empty = _small(frame)  # the mat as it is now (assumed clear)
        last, scanned, still_since = empty, None, time.time()
        while not _watch_stop.is_set():
            ok, frame = cam.read()
            if not ok:
                time.sleep(0.5)
                continue
            _watch_frame = frame
            now_small = _small(frame)
            moving = _changed(now_small, last) > 0.01
            last = now_small
            if moving:
                still_since = time.time()
            elif time.time() - still_since > 1.2:  # held still for a moment
                if _changed(now_small, empty) < 0.02:
                    scanned = None  # the mat is clear again
                    empty = now_small  # (follows slow changes in the light)
                elif scanned is None or _changed(now_small, scanned) > 0.04:
                    scanned = now_small  # something new is lying there
                    _announce(scan())
            time.sleep(0.15)
    finally:
        _watch_frame = None
        cam.release()


def _announce(text):
    if tools.ui:
        tools.ui.announce(text)


def _load_local_vision():
    body = json.dumps({"model": config.LOCAL_VISION_MODEL, "prompt": "", "keep_alive": "30m"}).encode()
    try:
        req = urllib.request.Request(config.OLLAMA_URL.rstrip("/") + "/api/generate", body,
                                     {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=300).read()
    except Exception:
        pass


def start_watching():
    global _watch_thread
    if watching():
        return "The desk scanner is already watching."
    _watch_stop.clear()
    _watch_thread = threading.Thread(target=_watch, daemon=True, name="desk-scanner")
    _watch_thread.start()
    if _use_local():  # load the offline eyes now: the first scan would otherwise wait ~1 minute for them
        threading.Thread(target=_load_local_vision, daemon=True).start()
    return "Desk scanner on. Clear the mat for a second, then put something down and hold still."


def stop_watching():
    if not watching():
        return "The desk scanner isn't running."
    _watch_stop.set()
    return "Desk scanner off."


@tool("Scan the desk: photograph the mat or desk under the desk camera (a webcam pointing down), identify the "
      "object on it and get details. Use when he asks what's on the desk/mat/table, to scan or analyse something "
      "he's put down. Also shows the scan as a hologram on the HUD.",
      {"question": S("His question about it, if any (e.g. 'is this ripe?', 'how much is this worth?')")})
def scan_desk(question=""):
    return scan(question)


@tool("Turn the desk scanner's watch mode on or off: Jarvis watches the mat and scans anything newly put down.",
      {"on": {"type": "boolean"}}, ["on"])
def desk_scanner_mode(on):
    return start_watching() if on else stop_watching()
