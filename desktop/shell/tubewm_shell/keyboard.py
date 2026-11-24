"""tube-keyboard: one keyboard layout for the desktop, lock screen, login screen and consoles.

    tube-keyboard                 show the layout in use
    tube-keyboard set gb          use a layout (and optionally a variant: set gb extd)
    tube-keyboard system          also use it on the login screen and text consoles
    tube-keyboard list [words]    list layouts, optionally only those matching words

Your choice lives in ~/.config/tubewm/keyboard (XKB_LAYOUT=, XKB_VARIANT=).
Sway reads it through ~/.config/sway/config.d/10-tubewm-keyboard.conf, the
session launcher exports it as XKB_DEFAULT_*, and `system` hands it to
localectl, which sets both the login screen and the consoles.

This module deliberately needs nothing but the standard library: the
installer uses it before GTK is installed.
"""

import os
import re
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
STATE = os.path.join(CONFIG, "tubewm", "keyboard")
SWAY_SNIPPET = os.path.join(CONFIG, "sway", "config.d", "10-tubewm-keyboard.conf")
RULES = ("/usr/share/X11/xkb/rules/evdev.lst", "/usr/share/X11/xkb/rules/base.lst")

# Used when xkeyboard-config's list isn't installed.
FALLBACK = [
    ("us", "", "English (US)"), ("gb", "", "English (UK)"), ("ie", "", "Irish"),
    ("de", "", "German"), ("fr", "", "French"), ("es", "", "Spanish"),
    ("it", "", "Italian"), ("pt", "", "Portuguese"), ("br", "", "Portuguese (Brazil)"),
    ("nl", "", "Dutch"), ("be", "", "Belgian"), ("ch", "", "German (Switzerland)"),
    ("se", "", "Swedish"), ("no", "", "Norwegian"), ("dk", "", "Danish"),
    ("fi", "", "Finnish"), ("pl", "", "Polish"), ("cz", "", "Czech"),
    ("hu", "", "Hungarian"), ("ru", "", "Russian"), ("ua", "", "Ukrainian"),
    ("tr", "", "Turkish"), ("jp", "", "Japanese"), ("kr", "", "Korean"),
    ("us", "intl", "English (US, intl., with dead keys)"),
    ("us", "dvorak", "English (Dvorak)"), ("us", "colemak", "English (Colemak)"),
]


def layouts():
    """Every layout and variant as (layout, variant, description), layouts first."""
    for path in RULES:
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError:
            continue
        out, section = [], None
        for line in text.splitlines():
            if line.startswith("!"):
                section = line[1:].strip()
                continue
            line = line.strip()
            if not line:
                continue
            if section == "layout":
                code, _, desc = line.partition(" ")
                out.append((code, "", desc.strip()))
            elif section == "variant":
                m = re.match(r"(\S+)\s+(\S+):\s*(.*)", line)
                if m:
                    out.append((m.group(2), m.group(1), m.group(3).strip()))
        if out:
            return out
    return list(FALLBACK)


def describe(layout, variant=""):
    for code, var, desc in layouts():
        if code == layout and var == (variant or ""):
            return desc
    return layout + ("(%s)" % variant if variant else "")


def search(words, items=None):
    items = layouts() if items is None else items
    terms = words.lower().split()
    if not terms:
        return items
    def hit(item):
        hay = ("%s %s %s" % (item[2], item[0], item[1])).lower()
        return all(t in hay for t in terms)
    return [i for i in items if hit(i)]


def _read_kv(path):
    vals = {}
    try:
        with open(path) as fh:
            for line in fh:
                key, sep, value = line.strip().partition("=")
                if sep:
                    vals[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return vals


def load():
    """The saved choice as (layout, variant), or None."""
    vals = _read_kv(STATE)
    if vals.get("XKB_LAYOUT"):
        return vals["XKB_LAYOUT"], vals.get("XKB_VARIANT", "")
    return None


def system():
    """What the login screen uses, from localectl, as (layout, variant) or None."""
    if not shutil.which("localectl"):
        return None
    try:
        out = subprocess.run(["localectl", "status"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    vals = {}
    for line in out.splitlines():
        key, _, value = line.strip().partition(":")
        vals[key.strip()] = value.strip()
    layout = vals.get("X11 Layout", "").split(",")[0]
    if not layout or layout == "n/a":
        return None
    return layout, vals.get("X11 Variant", "").split(",")[0]


def _from_language():
    lang = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    m = re.match(r"([a-z]{2,3})_([A-Z]{2})", lang)
    if not m:
        return None
    language, region = m.group(1), m.group(2).lower()
    if language == "en":
        return ("gb", "") if region == "gb" else ("ie", "") if region == "ie" else ("us", "")
    codes = {code for code, var, _ in layouts() if not var}
    if region in codes:
        return region, ""
    if language in codes:
        return language, ""
    return None


def guess():
    """The best starting choice: saved, else the login screen's unless it is
    only the stock US default, else what the system language suggests."""
    saved = load()
    if saved:
        return saved
    sysk = system()
    if sysk and sysk[0] != "us":
        return sysk
    return _from_language() or sysk or ("us", "")


def save(layout, variant=""):
    """Use a layout for the desktop and lock screen, now and from next login."""
    variant = variant or ""
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        fh.write("# Written by tube-keyboard. Change it with: tube-keyboard set LAYOUT [VARIANT]\n")
        fh.write("XKB_LAYOUT=%s\nXKB_VARIANT=%s\n" % (layout, variant))
    os.makedirs(os.path.dirname(SWAY_SNIPPET), exist_ok=True)
    with open(SWAY_SNIPPET, "w") as fh:
        fh.write("# Written by tube-keyboard (%s). Change it with tube-keyboard.\n"
                 % describe(layout, variant))
        fh.write("input type:keyboard {\n    xkb_layout %s\n    xkb_variant \"%s\"\n}\n"
                 % (layout, variant))
    if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
        subprocess.run(["swaymsg", "-q", "input type:keyboard xkb_layout %s" % layout],
                       capture_output=True)
        subprocess.run(["swaymsg", "-q", 'input type:keyboard xkb_variant "%s"' % variant],
                       capture_output=True)


def system_command(layout, variant=""):
    """The command that sets the login screen and the consoles (needs root).
    localectl also converts the layout to the nearest console keymap."""
    return ["localectl", "set-x11-keymap", layout, "", variant or ""]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args.pop(0) if args else "show"
    if cmd in ("-h", "--help", "help"):
        print(__doc__.split("\n\n")[0].split(":", 1)[1].strip())
        print(__doc__.split("\n\n")[1])
        return 0
    if cmd == "show":
        cur = load() or guess()
        print("%s  (%s)" % (describe(*cur), " ".join(filter(None, cur))))
        sysk = system()
        if sysk and sysk != cur:
            print("login screen: %s  (run 'tube-keyboard system' to match)" % describe(*sysk))
        return 0
    if cmd == "list":
        for code, var, desc in search(" ".join(args)):
            print("%-8s %-14s %s" % (code, var, desc))
        return 0
    if cmd == "set":
        if not args:
            print("tube-keyboard: set needs a layout, e.g. tube-keyboard set gb", file=sys.stderr)
            return 2
        layout, variant = args[0], (args[1] if len(args) > 1 else "")
        if not any(c == layout and v == variant for c, v, _ in layouts()):
            print("tube-keyboard: no layout '%s%s' (try: tube-keyboard list %s)"
                  % (layout, " " + variant if variant else "", layout), file=sys.stderr)
            return 1
        save(layout, variant)
        print("keyboard is now %s" % describe(layout, variant))
        return 0
    if cmd == "system":
        cur = load() or guess()
        run = system_command(*cur)
        if os.geteuid() != 0 and shutil.which("sudo"):
            run = ["sudo"] + run
        print("setting the login screen and consoles to %s" % describe(*cur))
        return subprocess.call(run)
    print("tube-keyboard: unknown command '%s' (try --help)" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
