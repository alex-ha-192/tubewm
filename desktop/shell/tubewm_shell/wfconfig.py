"""tube-wayfire-config: write ~/.config/wayfire.ini from tubewm's template.

The template (desktop/wayfire/wayfire.ini.in) is filled in with the palette
and the keyboard layout, and ~/.config/tubewm/wayfire.ini, if it exists, is
merged on top. Wayfire notices the new file and reloads it by itself.
tube-render runs this; so can you.
"""

import argparse
import configparser
import os
import re
import sys

from . import common

KEYBOARD = os.path.join(common.CONFIG, "tubewm", "keyboard")
USER_INI = os.path.join(common.CONFIG, "tubewm", "wayfire.ini")
WAYFIRE_INI = os.path.join(common.CONFIG, "wayfire.ini")
TEMPLATE = os.path.normpath(os.path.join(common.SHELL_DIR, "..", "wayfire", "wayfire.ini.in"))

# Desktops are columns of Wayfire's workspace grid. The grid is always ten
# wide; tube-desktops shows only the ones in use, plus a spare.
COLUMNS = 10
# Empty means "what the system uses": the session launcher exports
# XKB_DEFAULT_* from the same file, and libxkbcommon falls back to those.
KEYBOARD_DEFAULT = {"layout": "", "variant": "", "options": ""}


def keyboard():
    kb = dict(KEYBOARD_DEFAULT)
    try:
        with open(KEYBOARD) as fh:
            for line in fh:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip().lower()
                    k = k[len("xkb_"):] if k.startswith("xkb_") else k  # XKB_LAYOUT=gb
                    kb[k] = v.strip().strip("'\"")
    except OSError:
        pass
    return kb


# ── wayfire.ini ────────────────────────────────────────────────────────────

def _rgba(hex_, alpha=1.0):
    h = hex_.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return "%.3f %.3f %.3f %.2f" % (r, g, b, alpha)


def _desktop_bindings():
    lines = []
    for i in range(1, COLUMNS + 1):
        key = "KEY_%d" % (i % 10)
        lines.append("binding_%d = <super> %s" % (i, key))
        lines.append("with_win_%d = <super> <shift> %s" % (i, key))
    return "\n".join(lines)


DRM = "/sys/class/drm"


def _edid_cm(path):
    """The panel's width in cm, from its EDID, or None."""
    try:
        with open(path, "rb") as fh:
            edid = fh.read(128)
    except OSError:
        return None
    return edid[21] if len(edid) >= 22 and edid[21] else None


def scale_for(width_px, width_cm=None):
    """How much to scale a built-in screen so things are a comfortable size.

    About 96 dots per inch at arm's length is what everything is drawn for.
    A Framework 13 with the 2.8K screen (2880 px across 28.5 cm, ~256 dpi)
    gets 2; the 2256 x 1504 screen (~200 dpi) gets 1.5.
    """
    if width_cm:
        dpi = width_px / (width_cm / 2.54)
        if dpi >= 230:
            return 2
        if dpi >= 170:
            return 1.5
        if dpi >= 140:
            return 1.25
        return 1
    return 2 if width_px >= 2560 else 1


def outputs(drm=DRM):
    """[output:NAME] sections giving built-in high-density screens a scale.
    Plug-in monitors are left at 1 (set yours in ~/.config/tubewm/wayfire.ini)."""
    sections = []
    try:
        names = sorted(os.listdir(drm))
    except OSError:
        return ""
    for card in names:
        m = re.match(r"card\d+-((?:eDP|LVDS|DSI)-.+)$", card)
        if not m:
            continue
        try:
            with open(os.path.join(drm, card, "modes")) as fh:
                first = fh.readline().strip()
        except OSError:
            continue
        size = re.match(r"(\d+)x(\d+)", first)
        if not size:
            continue
        scale = scale_for(int(size.group(1)), _edid_cm(os.path.join(drm, card, "edid")))
        if scale != 1:
            sections.append("[output:%s]\nscale = %g\n" % (m.group(1), scale))
    return "\n".join(sections)


def build(pal=None):
    """The text of wayfire.ini: the template, filled in, with the user's own
    ~/.config/tubewm/wayfire.ini merged on top."""
    pal = pal or common.load_palette()
    kb = keyboard()
    values = {
        "COLUMNS": str(COLUMNS),
        "DESKTOP_BINDINGS": _desktop_bindings(),
        "OUTPUTS": outputs(),
        "XKB_LAYOUT": kb.get("layout", ""),
        "XKB_VARIANT": kb.get("variant", ""),
        "XKB_OPTIONS": kb.get("options", ""),
    }
    for key, hex_ in pal.items():
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hex_)):
            values[key + "_RGBA"] = _rgba(hex_)
            for a in (40, 90):
                values["%s_A%d" % (key, a)] = _rgba(hex_, a / 100)
    with open(TEMPLATE) as fh:
        text = fh.read()
    text = re.sub(r"@([A-Z0-9_]+)@", lambda m: values.get(m.group(1), m.group(0)), text)
    missing = re.findall(r"@([A-Z0-9_]+)@", text)
    if missing:
        raise SystemExit("tube-wayfire-config: template has unknown fields: %s" % ", ".join(sorted(set(missing))))
    return _merge_user(text)


def _merge_user(text):
    if not os.path.exists(USER_INI):
        return _header() + text
    user = configparser.ConfigParser(interpolation=None, strict=False, comment_prefixes=("#",),
                                     inline_comment_prefixes=None)
    user.optionxform = str
    try:
        user.read(USER_INI)
    except configparser.Error as err:
        print("tube-wayfire-config: ignoring %s: %s" % (USER_INI, err), file=sys.stderr)
        return _header() + text
    out, section, done = [], None, set()

    def flush_rest(sec):
        if sec and user.has_section(sec):
            for k, v in user[sec].items():
                if (sec, k) not in done:
                    out.append("%s = %s" % (k, v))
                    done.add((sec, k))

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"\[(.+)\]\s*$", line)
        if m:
            flush_rest(section)
            section = m.group(1)
            out.append(line)
            i += 1
            continue
        m = re.match(r"([A-Za-z0-9_]+)\s*=", line)
        if m and section and user.has_section(section) and m.group(1) in user[section]:
            key = m.group(1)
            out.append("%s = %s  # from %s" % (key, user[section][key], "~/.config/tubewm/wayfire.ini")
                       if "\n" not in user[section][key] else "%s = %s" % (key, user[section][key]))
            done.add((section, key))
            while lines[i].rstrip().endswith("\\") and i + 1 < len(lines):  # skip continued lines
                i += 1
            i += 1
            continue
        out.append(line)
        i += 1
    flush_rest(section)
    for sec in user.sections():
        if not any(re.fullmatch(r"\[%s\]\s*" % re.escape(sec), l) for l in lines):
            out.append("")
            out.append("[%s]" % sec)
            for k, v in user[sec].items():
                out.append("%s = %s" % (k, v))
    return _header() + "\n".join(out) + "\n"


def _header():
    return ("# Written by tube-render from tubewm's wayfire.ini.in. Don't edit this file:\n"
            "# put your own settings in ~/.config/tubewm/wayfire.ini and run tube-render.\n\n")


def render(quiet=True):
    text = build()
    try:
        with open(WAYFIRE_INI) as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    tmp = WAYFIRE_INI + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, WAYFIRE_INI)  # Wayfire notices and reloads
    if not quiet:
        print("tube-wayfire-config: wrote %s" % WAYFIRE_INI)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-wayfire-config", description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", "-q", action="store_true")
    a = parser.parse_args(argv)
    render(quiet=a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
