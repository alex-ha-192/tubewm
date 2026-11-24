#!/usr/bin/env python3
"""Generate the tubewm Vivaldi themes and UI CSS from the shared palette.

    python3 apps/vivaldi/build.py [--accent NAME|#RRGGBB] [--out DIR]

Writes, under DIR (default apps/vivaldi/dist):

    themes/tubewm-metro-dark.zip    importable with Settings > Themes > Import
    themes/tubewm-metro-light.zip
    themes/*.json                   the same theme objects, unzipped
    css/tubewm-metro.css            UI modifications (see the file header)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import palette as P  # noqa: E402

NAMES = {"dark": "tubewm Metro Dark", "light": "tubewm Metro Light"}
# Stable ids, so re-installing replaces the theme instead of adding a copy.
IDS = {m: str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/alex-ha-192/tubewm#vivaldi-{m}"))
       for m in NAMES}


def theme(mode: str, pal: dict) -> dict:
    c = P.polarity(pal, mode)
    return {
        "id": IDS[mode],
        "name": NAMES[mode],
        "version": 1,
        "engineVersion": 1,
        # Vivaldi's five colours. "Accent" tints the tab bar / header, so it is
        # kept at the shell colour; the user accent goes on "Highlight", which
        # Vivaldi uses for focus, selection and the active-tab indicator.
        "colorBg": c["bg"],
        "colorFg": c["fg"],
        "colorHighlightBg": c["accent"],
        "colorAccentBg": c["shell"],
        "colorWindowBg": c["shell"],
        "accentFromPage": False,
        "accentOnWindow": False,
        "accentSaturationLimit": 1,
        "preferSystemAccent": False,
        "contrast": 0,
        "alpha": 1,
        "blur": 0,
        "dimBlurred": False,
        "radius": 0,
        "simpleScrollbar": True,
        "transparencyTabBar": False,
        "transparencyTabs": False,
        "backgroundImage": "",
        "backgroundPosition": "stretch",
        "url": "",
    }


def css(pal: dict) -> str:
    d, l = P.polarity(pal, "dark"), P.polarity(pal, "light")
    subs = {"ACCENT": d["accent"], "ON_ACCENT": P.on_color(d["accent"])}
    for k in ("bg", "shell", "surface", "surface_alt", "fg", "fg_subtle", "fg_disabled"):
        subs[k.upper()] = d[k]
        subs["L_" + k.upper()] = l[k]
    out = (HERE / "metro.css.in").read_text(encoding="utf-8")
    for k, v in subs.items():
        out = out.replace(f"@{k}@", v)
    if "@" in out.replace("@media", "").replace("@keyframes", ""):
        raise RuntimeError("metro.css.in has an unknown @PLACEHOLDER@")
    return out


def build(out: Path, accent: str | None = None) -> dict:
    pal = P.load(accent=accent)
    (out / "themes").mkdir(parents=True, exist_ok=True)
    (out / "css").mkdir(parents=True, exist_ok=True)
    written = {"accent": pal["TUBEWM_ACCENT"], "themes": {}}
    for mode in NAMES:
        t = theme(mode, pal)
        body = json.dumps(t, indent=2) + "\n"
        (out / "themes" / f"tubewm-metro-{mode}.json").write_text(body, encoding="utf-8")
        z = out / "themes" / f"tubewm-metro-{mode}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("settings.json", body)
        written["themes"][mode] = t
    (out / "css" / "tubewm-metro.css").write_text(css(pal), encoding="utf-8")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--accent", help="accent name from palette/accents, or #RRGGBB")
    ap.add_argument("--out", type=Path, default=HERE / "dist")
    args = ap.parse_args(argv)
    try:
        info = build(args.out, args.accent)
    except ValueError as e:
        print(f"build.py: {e}", file=sys.stderr)
        return 2
    print(f"{args.out} ({info['accent']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
