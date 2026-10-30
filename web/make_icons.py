"""Draws the JARVIS app icons (arc reactor, suit colours) as PNGs for the phone app. Run once:
    python web/make_icons.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent
GOLD, CORE, BG = (255, 194, 61), (63, 200, 255), (26, 4, 3)


def reactor(size, padding):
    s = size * 4  # draw big, then shrink, for smooth edges
    img = Image.new("RGBA", (s, s), BG + (255,))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d, g = ImageDraw.Draw(img), ImageDraw.Draw(glow)
    c = s / 2
    r = (s / 2) * (1 - padding)

    def ring(draw, radius, width, colour, dash=None, gap=0):
        box = [c - radius, c - radius, c + radius, c + radius]
        if not dash:
            draw.ellipse(box, outline=colour, width=int(width))
            return
        a = 0
        while a < 360:
            draw.arc(box, a, a + dash, fill=colour, width=int(width))
            a += dash + gap

    ring(g, r * 0.95, r * 0.06, GOLD + (160,), 64, 26)
    ring(d, r * 0.95, r * 0.035, GOLD, 64, 26)
    ring(d, r * 0.72, r * 0.15, (150, 105, 30), 26, 10)  # coils (solid, darker gold)
    ring(d, r * 0.55, r * 0.035, GOLD)
    tri = [(c + r * 0.47 * math.cos(math.radians(a)), c + r * 0.47 * math.sin(math.radians(a))) for a in (-90, 30, 150)]
    d.line(tri + [tri[0]], fill=GOLD, width=int(r * 0.04), joint="curve")
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(s * 0.02)))

    # Blue arc-reactor core: a soft blue glow fading to a white-hot centre.
    core = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    cd.ellipse([c - r * 0.40, c - r * 0.40, c + r * 0.40, c + r * 0.40], fill=CORE + (150,))
    cd.ellipse([c - r * 0.24, c - r * 0.24, c + r * 0.24, c + r * 0.24], fill=(150, 225, 255, 255))
    cd.ellipse([c - r * 0.12, c - r * 0.12, c + r * 0.12, c + r * 0.12], fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, core.filter(ImageFilter.GaussianBlur(s * 0.03)))
    return img.convert("RGB").resize((size, size), Image.LANCZOS)


for size in (192, 512):
    reactor(size, 0.12).save(OUT / f"icon-{size}.png")
    reactor(size, 0.30).save(OUT / f"icon-maskable-{size}.png")  # extra margin: Android crops these into circles
reactor(180, 0.12).convert("RGB").save(OUT / "apple-touch-icon.png")
print("icons written to", OUT)
