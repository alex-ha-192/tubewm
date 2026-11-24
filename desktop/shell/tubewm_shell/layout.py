"""The start screen's tile layout: load, seed, save.

The layout you build in the start screen is kept in
~/.config/tubewm/start.json. The first time start runs it is seeded from
desktop/start/default.toml (or from an older ~/.config/tubewm/start.toml
with groups, whose tiles are flattened in order), keeping only app tiles
for apps that are installed.
"""

import json
import os
import sys

from . import common

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib  # type: ignore

LAYOUT_PATH = os.path.join(common.CONFIG, "tubewm", "start.json")
LEGACY_PATH = os.path.join(common.CONFIG, "tubewm", "start.toml")
DEFAULT_PATH = os.path.normpath(os.path.join(common.SHELL_DIR, "..", "start", "default.toml"))


def _read_toml(path):
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as err:
        print("tube-start: can't read %s: %s" % (path, err), file=sys.stderr)
        return None


def _seed():
    data = None
    if os.path.exists(LEGACY_PATH):
        data = _read_toml(LEGACY_PATH)
    if not data:
        data = _read_toml(DEFAULT_PATH) or {}
    tiles = list(data.get("tile", []))
    for group in data.get("group", []):  # older layout with named groups
        tiles.extend(group.get("tiles", []))
    kept, seen_apps = [], set()
    for t in tiles:
        t = dict(t)
        if t.get("type", "app") == "app":
            if not t.get("exec"):
                info = common.find_app(t.get("app"))
                if info is None:
                    continue
                t["app"] = (info.get_id() or t["app"]).removesuffix(".desktop")
            if t.get("app") in seen_apps:
                continue
            seen_apps.add(t.get("app"))
        kept.append(t)
    return {"title": data.get("start", {}).get("title", "start"), "tiles": kept}


def load():
    if os.path.exists(LAYOUT_PATH):
        try:
            with open(LAYOUT_PATH) as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("tiles"), list):
                data.setdefault("title", "start")
                return data
        except (OSError, ValueError) as err:
            print("tube-start: can't read %s (%s); starting from the defaults" % (LAYOUT_PATH, err),
                  file=sys.stderr)
    data = _seed()
    save(data)
    return data


def save(data):
    clean = {
        "title": data.get("title", "start"),
        "tiles": [{k: v for k, v in t.items() if not k.startswith("_")} for t in data["tiles"]],
    }
    os.makedirs(os.path.dirname(LAYOUT_PATH), exist_ok=True)
    tmp = LAYOUT_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(clean, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, LAYOUT_PATH)


def reset():
    try:
        os.remove(LAYOUT_PATH)
    except OSError:
        pass
