"""
Draws the panel's app icons (panel/static/icons/), for its home-screen app and the browser tab:
    python scripts/make_icons.py
A play mark on the Standard theme's accent, on its background. Drawn 4 times larger and scaled down, for smooth edges.
"maskable" fills the whole square and keeps the mark in the middle 60%: Android cuts it to its own shape (a circle,
a squircle), and nothing of the mark may be cut off.
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panel", "static", "icons")
BACKGROUND = (14, 15, 19)        # --bg, Standard theme
ACCENT_TOP = (176, 140, 255)     # --accent #a07cff, a little lighter
ACCENT_BOTTOM = (112, 76, 230)   # and a little darker: a soft fall of light from the top
MARK = (255, 255, 255)
SCALE = 4


def gradient(size):
    """The accent, top to bottom."""
    fill = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        fill.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(ACCENT_TOP, ACCENT_BOTTOM)))
    return fill.resize((size, size))


def draw(size, maskable):
    big = size * SCALE
    icon = Image.new("RGBA", (big, big), BACKGROUND + (255,) if maskable else (0, 0, 0, 0))
    # The tile: the whole icon as a rounded square, or within the middle (maskable's safe zone) as a circle.
    tile = Image.new("L", (big, big), 0)
    shape = ImageDraw.Draw(tile)
    if maskable:
        inset = round(big * 0.2)
        shape.ellipse((inset, inset, big - inset, big - inset), fill=255)
        box = (inset, big - inset)
    else:
        shape.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.22), fill=255)
        box = (0, big)
    icon.paste(gradient(big), (0, 0), tile)
    # The play mark, a triangle a touch right of centre (it looks centred so).
    low, high = box
    span = high - low
    cx, cy, r = low + span * 0.53, low + span * 0.5, span * 0.24
    ImageDraw.Draw(icon).polygon([(cx - r * 0.85, cy - r), (cx - r * 0.85, cy + r), (cx + r, cy)], fill=MARK)
    return icon.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size, maskable in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                                 ("maskable-512.png", 512, True), ("apple-touch-icon.png", 180, True),
                                 ("favicon-32.png", 32, False)):
        draw(size, maskable).save(os.path.join(OUT, name), optimize=True)
        print(os.path.join(OUT, name))


if __name__ == "__main__":
    main()
