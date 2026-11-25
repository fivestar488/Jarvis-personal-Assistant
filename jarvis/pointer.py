"""Point and ask: put the mouse on something and say "what's this?" or "read that". Jarvis looks at a close-up of
what's under the pointer (with a ring drawn on the exact spot) plus the whole screen for context."""
import base64
import io

from . import config
from .tools import S, tool


def _shots():
    import pyautogui
    from PIL import ImageDraw
    x, y = pyautogui.position()
    full = pyautogui.screenshot()
    W, H = full.size
    sw, sh = pyautogui.size()  # the pointer is in screen units; the screenshot may be in real pixels
    px, py = int(x * W / sw), int(y * H / sh)
    box = (max(0, px - 450), max(0, py - 300), min(W, px + 450), min(H, py + 300))
    crop = full.crop(box).convert("RGB")
    d = ImageDraw.Draw(crop)
    cx, cy = px - box[0], py - box[1]
    for r, w in ((28, 4), (34, 2)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 40, 40), width=w)
    small = full.convert("RGB")
    small.thumbnail((1280, 1280))

    def jpeg(img):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        return buf.getvalue()
    return jpeg(crop), jpeg(small)


@tool("Point and ask: see what's under his mouse pointer (a close-up with a red ring on the spot, plus the whole "
      "screen). Use when he says 'what's this', 'what's that', 'read this', 'explain this' about something he's "
      "pointing at with the mouse.",
      {"question": S("His question about it, if any")})
def whats_this(question=""):
    crop, screen = _shots()
    from . import scanner
    if scanner._use_local():  # offline: the small vision model describes the close-up
        try:
            return "What's under the pointer: " + scanner._ask_local(crop, question or "What is inside the red circle? Read any text.")["what"]
        except Exception as e:
            return f"I couldn't look at it offline: {e}"
    b64 = lambda b: base64.b64encode(b).decode()
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(crop)}},
        {"type": "text", "text": "Close-up of what he's pointing at: the red ring marks the exact spot of his mouse pointer."},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(screen)}},
        {"type": "text", "text": "His whole screen, for context." + (f" He asks: {question}" if question else "")},
    ]
