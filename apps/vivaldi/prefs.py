#!/usr/bin/env python3
"""Add or remove the tubewm themes in a Vivaldi profile's Preferences file.

    python3 prefs.py apply  PREFERENCES BUILD_DIR [--light] [--css-dir DIR]
    python3 prefs.py remove PREFERENCES

Only run this while Vivaldi is closed: the browser rewrites Preferences from
memory on exit and would undo the change. install.sh checks that for you.

What it touches, all under the top-level "vivaldi" key:
    themes.user                     our two themes, replaced by id
    themes.current                  the active theme id
    appearance.css_ui_mods_directory  the folder holding tubewm-metro.css
The previous values of themes.current and the CSS folder are kept in
"tubewm_previous" next to them so remove can put them back. A timestamped
backup of Preferences is written before any change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build import IDS  # noqa: E402

PREV = "tubewm_previous"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("vivaldi"), dict):
        raise SystemExit(f"prefs.py: {path} does not look like a Vivaldi profile (no 'vivaldi' key); not touched")
    return data


def _save(path: Path, data: dict) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak, n = path.with_name(f"{path.name}.tubewm-{stamp}.bak"), 1
    while bak.exists():
        n += 1
        bak = path.with_name(f"{path.name}.tubewm-{stamp}-{n}.bak")
    shutil.copy2(path, bak)
    tmp = path.with_name(path.name + ".tubewm-tmp")
    # Chromium writes Preferences compact, without a trailing newline.
    tmp.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    print(f"backup: {bak}", file=sys.stderr)


def apply(path: Path, build_dir: Path, light: bool, css_dir: str | None) -> None:
    data = _load(path)
    v = data["vivaldi"]
    themes = v.setdefault("themes", {})
    ours = set(IDS.values())
    prev = v.setdefault(PREV, {})

    user = [t for t in themes.get("user", []) if not (isinstance(t, dict) and t.get("id") in ours)]
    for mode in ("dark", "light"):
        user.append(json.loads((build_dir / "themes" / f"tubewm-metro-{mode}.json").read_text(encoding="utf-8")))
    themes["user"] = user

    if themes.get("current") not in ours:
        prev.setdefault("current", themes.get("current"))
    themes["current"] = IDS["light" if light else "dark"]

    if css_dir:
        appearance = v.setdefault("appearance", {})
        if "css_ui_mods_directory" not in prev and appearance.get("css_ui_mods_directory") != css_dir:
            prev["css_ui_mods_directory"] = appearance.get("css_ui_mods_directory")
        appearance["css_ui_mods_directory"] = css_dir
    _save(path, data)


def remove(path: Path) -> None:
    data = _load(path)
    v = data["vivaldi"]
    ours = set(IDS.values())
    prev = v.pop(PREV, {}) or {}
    themes = v.get("themes", {})
    if "user" in themes:
        themes["user"] = [t for t in themes["user"] if not (isinstance(t, dict) and t.get("id") in ours)]
    if themes.get("current") in ours:
        if prev.get("current"):
            themes["current"] = prev["current"]
        else:
            themes.pop("current", None)
    appearance = v.get("appearance", {})
    if "css_ui_mods_directory" in prev:
        if prev["css_ui_mods_directory"]:
            appearance["css_ui_mods_directory"] = prev["css_ui_mods_directory"]
        else:
            appearance.pop("css_ui_mods_directory", None)
    _save(path, data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("op", choices=("apply", "remove"))
    ap.add_argument("preferences", type=Path)
    ap.add_argument("build_dir", type=Path, nargs="?")
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--css-dir")
    a = ap.parse_args(argv)
    if a.op == "apply":
        if not a.build_dir:
            ap.error("apply needs BUILD_DIR")
        apply(a.preferences, a.build_dir, a.light, a.css_dir)
    else:
        remove(a.preferences)
    return 0


if __name__ == "__main__":
    sys.exit(main())
