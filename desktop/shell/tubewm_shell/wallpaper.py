"""tube-wallpaper: minimal wallpapers drawn from the accent colour.

Each style is drawn with cairo at the size of your largest display, saved to
~/.cache/tubewm/wallpaper.png and set for every output through
~/.config/sway/config.d/50-tubewm-wallpaper.conf. tube-accent redraws it
when the accent changes, so the wallpaper always matches.
"""

import argparse
import math
import os
import random
import subprocess
import sys

from . import common

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

STATE = os.path.join(common.CONFIG, "tubewm", "wallpaper")
OFF = os.path.join(common.CONFIG, "tubewm", "wallpaper-off")
SNIPPET = os.path.join(common.CONFIG, "sway", "config.d", "50-tubewm-wallpaper.conf")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(common.HOME, ".cache")), "tubewm")
OUT = os.path.join(CACHE, "wallpaper.png")


def rgb(hex_):
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def tone(pal, amount):
    """The accent pushed towards black (amount > 0) or white (amount < 0)."""
    if amount >= 0:
        return rgb(common.mix(pal["ACCENT"], "#000000", amount))
    return rgb(common.mix(pal["ACCENT"], "#FFFFFF", -amount))


# Every style draws into a w x h context. Keep them calm: big flat shapes,
# few colours, nothing busy behind your windows.

def obsidian(cr, w, h, pal):
    cr.set_source_rgb(*rgb(pal["SHELL"]))
    cr.paint()


def accent(cr, w, h, pal):
    cr.set_source_rgb(*tone(pal, 0.0))
    cr.paint()


def fade(cr, w, h, pal):
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, *tone(pal, 0.05))
    g.add_color_stop_rgb(0.55, *tone(pal, 0.55))
    g.add_color_stop_rgb(1, *tone(pal, 0.82))
    cr.set_source(g)
    cr.paint()


def deep(cr, w, h, pal):
    cr.set_source_rgb(*tone(pal, 0.72))
    cr.paint()
    g = cairo.RadialGradient(w * 0.85, h * 0.1, 0, w * 0.85, h * 0.1, max(w, h) * 0.9)
    g.add_color_stop_rgba(0, *tone(pal, 0.35), 0.9)
    g.add_color_stop_rgba(1, *tone(pal, 0.72), 0)
    cr.set_source(g)
    cr.paint()


def bands(cr, w, h, pal):
    cr.set_source_rgb(*tone(pal, 0.78))
    cr.paint()
    shades = [0.62, 0.45, 0.28, 0.1]
    step = w * 0.17
    for i, amount in enumerate(shades):
        x = w * 0.42 + i * step
        cr.set_source_rgb(*tone(pal, amount))
        cr.move_to(x, h)
        cr.line_to(x + h * 0.55, 0)
        cr.line_to(w + h, 0)
        cr.line_to(w + h, h)
        cr.close_path()
        cr.fill()


def horizon(cr, w, h, pal):
    cr.set_source_rgb(*tone(pal, 0.68))
    cr.paint()
    cr.set_source_rgb(*tone(pal, 0.8))
    cr.rectangle(0, h * 0.62, w, h * 0.38)
    cr.fill()
    cr.set_source_rgb(*tone(pal, 0.0))
    cr.rectangle(0, h * 0.62 - max(2, h // 360), w * 0.38, max(2, h // 360))
    cr.fill()


def squares(cr, w, h, pal):
    cr.set_source_rgb(*rgb(pal["SURFACE"]))
    cr.paint()
    unit = max(4, round(h / 27))
    gap = max(1, unit // 7)
    rnd = random.Random(7)  # same pattern every time
    cols, rows = w // (unit + gap) + 1, h // (unit + gap) + 1
    for c in range(cols):
        for r in range(rows):
            # Density rises toward the bottom-right corner.
            d = math.hypot((cols - c) / cols, (rows - r) / rows) / math.sqrt(2)
            p = max(0.0, 0.85 - d * 1.35)
            if rnd.random() < p:
                amount = 0.15 + rnd.random() * 0.6
                cr.set_source_rgb(*tone(pal, amount))
                cr.rectangle(c * (unit + gap), r * (unit + gap), unit, unit)
                cr.fill()


def word(cr, w, h, pal, text=None):
    cr.set_source_rgb(*tone(pal, 0.74))
    cr.paint()
    text = text or os.environ.get("TUBE_WALLPAPER_WORD") or "tube"
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription.from_string("Open Sans Light")
    desc.set_absolute_size(h * 0.62 * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    _ink, logical = layout.get_pixel_extents()
    cr.set_source_rgb(*tone(pal, 0.6))
    # Cropped off the bottom-right edge, like a header too big for the screen.
    cr.move_to(w - logical.width * 0.86, h - logical.height * 0.78)
    PangoCairo.show_layout(cr, layout)


STYLES = {
    "obsidian": (obsidian, "flat near-black, the classic"),
    "accent": (accent, "the accent colour, edge to edge"),
    "fade": (fade, "accent fading diagonally into the dark"),
    "deep": (deep, "a dark accent tone with a soft glow top right"),
    "bands": (bands, "flat diagonal bands in accent tints"),
    "horizon": (horizon, "two calm halves and a thin accent line"),
    "squares": (squares, "scattered tiles gathering in one corner"),
    "word": (word, "one huge cropped word in light type"),
}
DEFAULT = "fade"


def render(style, w, h, path=None, pal=None):
    pal = pal or common.load_palette()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, int(w), int(h))
    cr = cairo.Context(surf)
    STYLES.get(style, STYLES[DEFAULT])[0](cr, w, h, pal)
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp.png"
        surf.write_to_png(tmp)
        os.replace(tmp, path)
    return surf


def current():
    try:
        with open(STATE) as fh:
            name = fh.read().strip()
            return name if name in STYLES else DEFAULT
    except OSError:
        return None


def biggest_output():
    import json
    try:
        outs = json.loads(common.sh("swaymsg -r -t get_outputs") or "[]")
        sizes = [(o["current_mode"]["width"], o["current_mode"]["height"])
                 for o in outs if o.get("active") and o.get("current_mode")]
        if sizes:
            return max(sizes, key=lambda s: s[0] * s[1])
    except (ValueError, KeyError, TypeError):
        pass
    return 2560, 1440


def apply(style, reload=True):
    if style not in STYLES:
        raise SystemExit("tube-wallpaper: no style called %r (try: tube-wallpaper list)" % style)
    w, h = biggest_output()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        fh.write(style + "\n")
    if os.path.exists(OFF):
        os.remove(OFF)
    render(style, w, h, OUT)
    os.makedirs(os.path.dirname(SNIPPET), exist_ok=True)
    with open(SNIPPET, "w") as fh:
        fh.write("# Written by tube-wallpaper. Remove this file to go back to the plain backdrop.\n")
        fh.write('output * bg "%s" fill\n' % OUT)
    if os.environ.get("SWAYSOCK") and common.have("swaymsg"):
        # Set it straight away; a full reload isn't needed.
        subprocess.run(["swaymsg", "-q", "output", "*", "bg", OUT, "fill"], check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-wallpaper",
                                     description="Minimal wallpapers drawn from the accent colour.")
    parser.add_argument("style", nargs="?", help="a style name, 'list', 'off', or 'refresh'")
    parser.add_argument("--preview", metavar="DIR",
                        help="write a small PNG of every style into DIR and exit")
    args = parser.parse_args(argv)

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        for name in STYLES:
            render(name, 640, 360, os.path.join(args.preview, name + ".png"))
        print("wrote %d previews to %s" % (len(STYLES), args.preview))
        return 0
    if args.style in (None, "list"):
        cur = current()
        for name, (_fn, blurb) in STYLES.items():
            print("%s %-9s %s" % ("*" if name == cur else " ", name, blurb))
        return 0
    if args.style == "off":
        for p in (STATE, SNIPPET):
            try:
                os.remove(p)
            except OSError:
                pass
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
        if os.environ.get("SWAYSOCK"):
            subprocess.run(["swaymsg", "-q", "reload"], check=False)
        return 0
    if args.style == "refresh":
        cur = current()
        if cur:
            apply(cur)
        return 0
    apply(args.style)
    return 0


if __name__ == "__main__":
    sys.exit(main())
