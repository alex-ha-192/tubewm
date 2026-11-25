"""marks: the strip's sound and battery marks, drawn for their level.

The other marks in the strip are fixed line icons (templates/waybar/icons).
These two show how much: the speaker sends out one, two or three waves as
the volume goes up (the ones it doesn't reach stay, dimmed, so the mark
keeps its size), and the battery fills from the left. Below a fifth the
battery turns the accent colour, as it always has.

Each mark is a small SVG on the same 24-unit square and 1.8-unit line as
the icon set. No GTK here, so this can be used (and tested) anywhere.
"""

import time

STROKE = 1.8
LOW = 20          # percent: the battery turns the accent colour below this
WAVES = 3

# The speaker and its waves, all about the point (10, 12).
SPEAKER = "M2 9h3.5l4.5-4v14l-4.5-4H2z"
# (radius, x, y above centre) of each wave, at 45 degrees either side.
_WAVES = ((4.0, 12.83, 2.83), (7.5, 15.30, 5.30), (11.0, 17.78, 7.78))

# The battery: an outline with a nub, and the room inside it to fill.
BODY = (2, 7, 17, 10)                 # x, y, w, h of the outline
NUB = "M21.5 10.5v3"
FILL_X, FILL_Y, FILL_W, FILL_H = 4.5, 9.5, 12.0, 5.0
BOLT = "M11.5 8.5l-3 4h4l-3 4"


def _svg(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
            'fill="none" stroke-width="%s" stroke-linejoin="miter">%s</svg>' % (STROKE, body))


def _clamp(pct):
    try:
        return max(0, min(100, int(round(float(pct)))))
    except (TypeError, ValueError):
        return 0


def waves(level):
    """How many of the three waves a volume of `level` percent lights:
    one up to a third, two up to two thirds, three above (none at 0)."""
    level = _clamp(level)
    if level == 0:
        return 0
    return min(WAVES, (level * WAVES + 99) // 100)


def volume_svg(level, muted, pal):
    """The speaker for this volume; muted (or at 0) it is crossed out."""
    fg = pal.get("FG", "#FFFFFF")
    dim = pal.get("DIM", "#656565")
    parts = ['<path d="%s" stroke="%s"/>' % (SPEAKER, fg)]
    if muted or _clamp(level) == 0:
        parts.append('<path d="M14.5 9.5l5 5M19.5 9.5l-5 5" stroke="%s"/>' % fg)
        return _svg("".join(parts))
    lit = waves(level)
    for i, (r, x, dy) in enumerate(_WAVES):
        parts.append('<path d="M%.2f %.2fa%.1f %.1f 0 0 1 0 %.2f" stroke="%s"/>'
                     % (x, 12 - dy, r, r, 2 * dy, fg if i < lit else dim))
    return _svg("".join(parts))


def battery_fill(pct):
    """Width of the fill inside the battery for `pct` percent: never quite
    empty while there's any charge, so 3% still shows a sliver."""
    pct = _clamp(pct)
    if pct == 0:
        return 0.0
    return round(max(2.0, FILL_W * pct / 100.0), 2)


def battery_svg(pct, charging, pal):
    """The battery, filled to its charge. Charging, the fill is dimmed and
    a bolt sits over it; low and not charging, it's in the accent."""
    pct = _clamp(pct)
    low = pct < LOW and not charging
    line = pal.get("ACCENT_LIGHT", "#FF66C4") if low else pal.get("FG", "#FFFFFF")
    fill = pal.get("SUBTLE", "#8A8A8A") if charging else line
    x, y, w, h = BODY
    parts = ['<rect x="%s" y="%s" width="%s" height="%s" stroke="%s"/>' % (x, y, w, h, line),
             '<path d="%s" stroke="%s"/>' % (NUB, line)]
    width = battery_fill(pct)
    if width:
        parts.append('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" stroke="none"/>'
                     % (FILL_X, FILL_Y, width, FILL_H, fill))
    if charging:
        parts.append('<path d="%s" stroke="%s" stroke-linejoin="round"/>' % (BOLT, line))
    return _svg("".join(parts))


def battery_key(pct, charging):
    """The battery mark changes in 12 steps (one per unit of fill), so cache
    by step rather than by percent."""
    return ("battery", int(round(battery_fill(pct) * 2)), _clamp(pct) < LOW, bool(charging))


def volume_key(level, muted):
    return ("volume", -1 if muted or _clamp(level) == 0 else waves(level))


def date_text(when=None):
    """The date beside the time, lowercase like the rest of the strip:
    'wed 25 nov'."""
    t = time.localtime(when) if when is not None else time.localtime()
    return ("%s %d %s" % (time.strftime("%a", t), t.tm_mday, time.strftime("%b", t))).lower()
