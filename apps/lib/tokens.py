"""Flat colour tokens for app config templates, plus the template renderer.

Every app theme in apps/ is a text template with ``@NAME@`` placeholders.
:func:`tokens` turns the shared palette into those names, and :func:`render`
fills them in. Each colour token comes in four spellings, because config
formats disagree about how to write a colour:

    @ACCENT@        #E3008C
    @ACCENT.bare@   E3008C
    @ACCENT.argb@   #FFE3008C      (Qt palettes)
    @ACCENT.rgb@    227, 0, 140

The ANSI and syntax colours live here too, so the terminal and editor themes
(VSCode included) all agree.
"""

from __future__ import annotations

import re

import palette as P

ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


def ansi(c: dict, mode: str) -> list[str]:
    """The 16 terminal colours: 0-7 normal, 8-15 bright.

    Hues come from the accent swatch family and are nudged until they read on
    the canvas, so they stay legible whatever the polarity.
    """
    bg = c["bg"]
    hues = {"red": c["error"], "green": c["success"], "yellow": c["warning"], "blue": c["info"],
            "magenta": "#E3008C", "cyan": "#00A8A8"}
    toward = "#FFFFFF" if mode == "dark" else "#000000"
    normal, bright = [], []
    for name in ANSI_NAMES:
        if name in hues:
            base = P.readable(hues[name], bg, 3.5)
            normal.append(base)
            bright.append(P.mix(base, toward, 0.25))
        elif name == "black":
            normal.append("#000000" if mode == "dark" else "#111111")
            bright.append(c["fg_disabled"] if mode == "dark" else c["fg_subtle"])
        else:  # white
            normal.append("#D0D0D0" if mode == "dark" else "#C8C8C8")
            bright.append("#FFFFFF" if mode == "dark" else "#E8E8E8")
    return normal + bright


def syntax(c: dict, mode: str) -> dict:
    """Code colours: mostly monochrome, keywords in the accent.

    Every hue is pulled toward enough contrast with the canvas, so a dark
    accent (cobalt, brown) still reads on black.
    """
    bg = c["bg"]
    r = lambda h, t=4.5: P.readable(h, bg, t)
    return {
        "keyword": r(c["accent"]),
        "string": r("#8CBF26" if mode == "dark" else "#10893E"),
        "number": r("#F0A30A" if mode == "dark" else "#B85C00"),
        "type": r("#00A8A8" if mode == "dark" else "#00797A"),
        "func": c["fg"],
        "prop": r(P.mix(c["fg"], c["fg_subtle"], 0.35)),
        "punct": r(c["fg_subtle"]),
        "comment": r(c["fg_subtle"], 3.0),
        "escape": r("#F26B1D" if mode == "dark" else "#B5430A"),
        "error": r(c["error"]),
    }


def tokens(pal: dict, mode: str = "dark") -> dict:
    """Upper-case token name -> value, for one polarity."""
    c = P.polarity(pal, mode)
    t = {k.upper(): v for k, v in c.items() if isinstance(v, str) and v.startswith("#")}
    a = c["accent"]
    t.update(
        MODE=mode,
        FONT_UI=c["font_ui"],
        FONT_MONO=c["font_mono"],
        ON_ACCENT=P.on_color(a),
        # the accent where it is used as text on the canvas
        ACCENT_TEXT=P.readable(a, c["bg"], 4.5),
        # solid (alpha-free) blends for apps that cannot do transparency
        SELECTION=P.mix(c["bg"], a, 0.40 if mode == "dark" else 0.25),
        SELECTION_SOFT=P.mix(c["bg"], a, 0.20 if mode == "dark" else 0.12),
        ACCENT_HOVER=P.mix(a, "#FFFFFF" if mode == "dark" else "#000000", 0.15),
        LINE_HIGHLIGHT=P.mix(c["bg"], c["fg"], 0.05),
    )
    for i, hex_ in enumerate(ansi(c, mode)):
        t[f"ANSI{i}"] = hex_
    for k, v in syntax(c, mode).items():
        t[f"SYN_{k.upper()}"] = v
    return t


_PLACEHOLDER = re.compile(r"@([A-Z][A-Z0-9_]*)(?:\.(bare|argb|rgb))?@")


def render(text: str, toks: dict) -> str:
    """Fill ``@NAME@`` / ``@NAME.form@`` placeholders; unknown names are an error."""
    def sub(m):
        name, form = m.group(1), m.group(2)
        if name not in toks:
            raise KeyError(f"unknown template token @{name}@")
        val = toks[name]
        if form is None:
            return val
        if not val.startswith("#"):
            raise KeyError(f"@{name}.{form}@: {name} is not a colour")
        h = val[1:7].upper()
        if form == "bare":
            return h
        if form == "argb":
            return "#FF" + h
        r, g, b = P.rgb(val)
        return f"{r}, {g}, {b}"
    return _PLACEHOLDER.sub(sub, text)
