"""Load the shared tubewm palette (palette/tubewm-colors.sh + palette/accents).

The palette is a POSIX shell file. We parse its plain ``KEY=#RRGGBB`` lines
rather than executing it, so loading never runs code, and reimplement its
accent precedence in :func:`load`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PALETTE_DIR = REPO_ROOT / "palette"

# KEY=VALUE where VALUE may start with '#' (a colour) but a later ' #' is a comment
_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=(#?[^\s#]+)")
_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def _read_assignments(path: Path) -> dict:
    """Plain ``KEY=VALUE`` lines only; anything with shell syntax is skipped."""
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m and "$" not in m.group(2):
            out[m.group(1)] = m.group(2).strip("\"'")
    return out


def accent_swatches(palette_dir: Path = PALETTE_DIR) -> dict:
    """``palette/accents``: one ``name #RRGGBB`` per line."""
    out = {}
    path = Path(palette_dir) / "accents"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            bits = line.split()
            if len(bits) >= 2 and not bits[0].startswith("#") and _HEX.match(bits[1]):
                out[bits[0].lower()] = "#" + bits[1].lstrip("#").upper()
    return out


def config_home(env) -> Path:
    return Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", "~")).expanduser() / ".config")


def load(palette_dir=None, env=None, accent=None) -> dict:
    """Return the palette with ``TUBEWM_ACCENT`` resolved.

    Accent precedence matches ``tubewm-colors.sh``: explicit ``accent``
    argument, then ``$TUBEWM_ACCENT``, then ``~/.config/tubewm/accent``,
    then ``TUBEWM_ACCENT_DEFAULT``.
    """
    env = os.environ if env is None else env
    palette_dir = Path(palette_dir or env.get("TUBEWM_PALETTE_DIR") or PALETTE_DIR)
    values = _read_assignments(palette_dir / "tubewm-colors.sh")
    swatches = accent_swatches(palette_dir)
    chosen = (
        accent
        or env.get("TUBEWM_ACCENT")
        or _read_assignments(config_home(env) / "tubewm" / "accent").get("TUBEWM_ACCENT")
        or values.get("TUBEWM_ACCENT_DEFAULT")
        or "#E3008C"
    )
    values["TUBEWM_ACCENT"] = resolve_accent(chosen, swatches)
    values["_swatches"] = swatches
    return values


def resolve_accent(value: str, swatches: dict) -> str:
    """Turn ``#RRGGBB``, ``RRGGBB`` or a swatch name (``cobalt``) into ``#RRGGBB``."""
    value = (value or "").strip()
    if _HEX.match(value):
        return "#" + value.lstrip("#").upper()
    if value.lower() in swatches:
        return swatches[value.lower()]
    names = ", ".join(sorted(swatches)) or "(palette/accents missing)"
    raise ValueError(f"unknown accent {value!r}; use #RRGGBB or one of: {names}")


def polarity(palette: dict, mode: str) -> dict:
    """Colour roles for ``dark`` or ``light``.

    The shared palette only defines what the desktop needs, so the light
    roles and status colours are derived here from those base values.
    """
    if mode not in ("dark", "light"):
        raise ValueError("mode must be 'dark' or 'light'")
    g = lambda k, d: palette.get(k, d).upper()
    sw = palette.get("_swatches", {})
    accent = palette["TUBEWM_ACCENT"]
    if mode == "dark":
        bg, fg = g("TUBEWM_BG", "#000000"), g("TUBEWM_FG", "#FFFFFF")
        roles = {
            "bg": bg,
            "shell": g("TUBEWM_SHELL", "#111111"),
            "surface": g("TUBEWM_SURFACE", "#1D1D1D"),
            "surface_alt": g("TUBEWM_SURFACE_HI", "#2B2B2B"),
            "fg": fg,
            "fg_subtle": g("TUBEWM_SUBTLE", "#8A8A8A"),
            "fg_disabled": g("TUBEWM_DIM", "#4A4A4A"),
        }
        roles["border"] = mix(roles["surface_alt"], roles["fg_disabled"], 0.4)
        # the palette's DIM (#4A4A4A) is a hairline grey; as text it needs 3:1
        roles["fg_disabled"] = readable(roles["fg_disabled"], roles["shell"], 3.0)
    else:
        bg, fg = "#FFFFFF", g("TUBEWM_LIGHT_FG", "#111111")
        light = g("TUBEWM_LIGHT_BG", "#F3F3F3")
        roles = {
            "bg": bg,
            "shell": light,
            "surface": light,
            "surface_alt": mix(light, fg, 0.08),
            "fg": fg,
            "fg_subtle": mix(fg, bg, 0.40),
            "fg_disabled": mix(fg, bg, 0.68),
        }
        roles["border"] = mix(light, fg, 0.18)
        roles["fg_disabled"] = readable(roles["fg_disabled"], roles["shell"], 3.0)
        roles["fg_subtle"] = readable(roles["fg_subtle"], roles["shell"], 4.5)
    roles["accent"] = accent
    roles["error"] = g("TUBEWM_URGENT", "#E81123")
    roles["warning"] = sw.get("amber", "#F0A30A")
    roles["success"] = sw.get("lime", "#8CBF26")
    roles["info"] = sw.get("cobalt", "#0078D7")
    roles["font_ui"] = palette.get("TUBEWM_FONT_UI", "Open Sans")
    roles["font_mono"] = palette.get("TUBEWM_FONT_MONO", "JetBrains Mono")
    return roles


# ---- small colour helpers -------------------------------------------------

def rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(r: float, g: float, b: float) -> str:
    c = lambda v: max(0, min(255, round(v)))
    return "#{:02X}{:02X}{:02X}".format(c(r), c(g), c(b))


def alpha(hex_: str, a: float) -> str:
    """``#RRGGBB`` + alpha (0..1) -> ``#RRGGBBAA``."""
    return hex_.upper()[:7] + "{:02X}".format(max(0, min(255, round(a * 255))))


def mix(a: str, b: str, t: float) -> str:
    """Linear mix: t=0 gives a, t=1 gives b."""
    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    return to_hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def luminance(hex_: str) -> float:
    def ch(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(hex_)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def on_color(bg: str) -> str:
    """Text colour for a solid accent fill.

    Metro puts white type on accent tiles, so white wins whenever it is
    legible at large/UI sizes (3:1); pale accents such as lime or amber get
    black instead.
    """
    return "#FFFFFF" if contrast(bg, "#FFFFFF") >= 3.0 else "#000000"


def readable(fg: str, bg: str, target: float = 4.5) -> str:
    """Nudge ``fg`` toward white/black until it reaches ``target`` contrast on ``bg``."""
    toward = "#FFFFFF" if luminance(bg) < 0.5 else "#000000"
    t = 0.0
    out = fg
    while contrast(out, bg) < target and t < 1.0:
        t += 0.05
        out = mix(fg, toward, t)
    return out
