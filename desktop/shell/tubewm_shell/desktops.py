"""tube-desktops: desktops that come and go by themselves (Wayfire).

There is always one spare desktop at the end of the bar, shown as "+". Open
something there and it becomes a desktop, named after what you opened: a
browser makes "web", an editor "code", a second browser desktop "web 2".
Leave a desktop empty and it goes away. Right-click a name to rename it,
keep it even when empty, move it, or close it. Renamed desktops are kept.

Each desktop is a column of Wayfire's workspace grid. A small daemon watches
Wayfire and keeps the columns packed to the left; the bar reads one line per
desktop from $XDG_RUNTIME_DIR/tubewm-desktops.bar.

    tube-desktops daemon          keep things tidy (started with Wayfire)
    tube-desktops go N            switch to desktop N (from 1)
    tube-desktops new             go to the spare desktop
    tube-desktops rename N NAME   rename (and keep) desktop N
    tube-desktops keep N          keep desktop N even when empty (again: let go)
    tube-desktops move N left|right
    tube-desktops close N         close desktop N; its windows move next door
    tube-desktops menu N          the right-click menu for desktop N
    tube-desktops list            print the desktops
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time

from . import wm

COLUMNS = 10
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
KEPT_FILE = os.path.join(CONFIG, "tubewm", "desktops.json")
STATE_FILE = os.path.join(RUNTIME, "tubewm-desktops.json")
BAR_FILE = os.path.join(RUNTIME, "tubewm-desktops.bar")
LOCK_FILE = os.path.join(RUNTIME, "tubewm-desktops.lock")
WAYBAR_SIGNAL = 8

# freedesktop categories, most specific first, to a desktop name.
CATEGORY_NAMES = [
    ("WebBrowser", "web"), ("Email", "mail"), ("InstantMessaging", "chat"), ("Chat", "chat"),
    ("IDE", "code"), ("TextEditor", "code"), ("Development", "code"),
    ("TerminalEmulator", "terminal"), ("FileManager", "files"),
    ("Music", "music"), ("Audio", "music"), ("Video", "video"), ("AudioVideo", "media"),
    ("Game", "play"), ("Photography", "photos"), ("Graphics", "art"),
    ("Office", "work"), ("Settings", "settings"), ("System", "system"),
]


def clean(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())[:20]


# ── state ──────────────────────────────────────────────────────────────────
# A desktop is {"name": str or None, "kept": bool}. None means "not named
# yet": the spare you just went to, waiting for its first window.

def _read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def load():
    state = _read(STATE_FILE, None)
    if not isinstance(state, list) or not state:
        kept = _read(KEPT_FILE, [])
        state = [{"name": clean(d.get("name")) or None, "kept": True}
                 for d in kept if isinstance(d, dict)][:COLUMNS]
    return state or [{"name": "home", "kept": False}]


def save(state):
    _write(STATE_FILE, state)
    _write(KEPT_FILE, [{"name": d["name"]} for d in state if d.get("kept") and d.get("name")])


@contextlib.contextmanager
def locked():
    os.makedirs(RUNTIME, exist_ok=True)
    with open(LOCK_FILE, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def names():
    return [d.get("name") or "new" for d in load()]


# ── naming ─────────────────────────────────────────────────────────────────

def _app_name(app_id):
    """A short name for a window's app, from its .desktop categories."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError):
        return clean(app_id) or "desktop"
    low = (app_id or "").lower()
    info = None
    for cand in (app_id + ".desktop", low + ".desktop"):
        try:
            info = Gio.DesktopAppInfo.new(cand)
        except TypeError:
            info = None
        if info:
            break
    if info is None:
        for i in Gio.AppInfo.get_all():
            did = (i.get_id() or "").lower().removesuffix(".desktop")
            wm_class = (i.get_startup_wm_class() or "").lower() if hasattr(i, "get_startup_wm_class") else ""
            if low and (did == low or did.endswith("." + low) or wm_class == low):
                info = i
                break
    if info is not None:
        cats = (info.get_categories() or "").split(";")
        for cat, name in CATEGORY_NAMES:
            if cat in cats:
                return name
        return clean(info.get_name()) or clean(app_id) or "desktop"
    return clean(app_id.split(".")[-1]) or "desktop"


def _unique(name, taken):
    if name not in taken:
        return name
    n = 2
    while "%s %d" % (name, n) in taken:
        n += 1
    return "%s %d" % (name, n)


# ── the tidy-up ────────────────────────────────────────────────────────────

def _instant(fn):
    """Run fn with workspace switches unanimated, so repacking the columns
    doesn't slide the screen about."""
    old = None
    try:
        old = wm._wf("wayfire/get-config-option", {"option": "vswitch/duration"}).get("value")
    except (OSError, wm.WayfireError, AttributeError):
        pass
    wm._try(lambda: wm._wf("wayfire/set-config-options", {"vswitch/duration": "0"}))
    try:
        fn()
    finally:
        wm._try(lambda: wm._wf("wayfire/set-config-options", {"vswitch/duration": old or "320ms circle"}))


def _move_column(windows, src, dst):
    for w in windows:
        if w.get("workspace") == src:
            wm._try(lambda w=w: wm._wf("vswitch/send-view", {"x": dst, "y": 0, "view-id": w["id"]}))


def reconcile(state=None, write=True):
    """Bring the list of desktops in line with where the windows are.

    New columns with windows become desktops, unnamed ones get a name from
    their first window, and empty desktops you are not on (and haven't kept)
    are removed, the ones to their right shifting left to close the gap."""
    state = state if state is not None else load()
    wins = wm.windows()
    cur = wm.current_pivot()
    used = {}
    for w in wins:
        used.setdefault(min(w.get("workspace", 0), COLUMNS - 1), []).append(w)
    want = max([len(state), cur + 1] + [c + 1 for c in used])
    while len(state) < want:
        state.append({"name": None, "kept": False})

    taken = {d["name"] for d in state if d.get("name")}
    for i, d in enumerate(state):
        if not d.get("name") and used.get(i):
            first = sorted(used[i], key=lambda w: w.get("id", 0))[0]
            d["name"] = _unique(_app_name(first.get("app_id", "")), taken)
            taken.add(d["name"])

    gone = [i for i, d in enumerate(state)
            if not used.get(i) and not d.get("kept") and i != cur]
    if len(gone) == len(state):
        gone = gone[1:]
    if gone:
        def repack():
            nonlocal cur
            for i in reversed(gone):
                ws = wm.windows()
                for col in range(i + 1, len(state)):
                    _move_column(ws, col, col - 1)
                state.pop(i)
                if cur > i:
                    cur -= 1
            wm.go_to_pivot(cur)
        if any(i < cur for i in gone):
            _instant(repack)
        else:
            repack()
    if write:
        save(state)
        write_bar(state, cur)
    return state


def write_bar(state, cur):
    lines = []
    for i in range(COLUMNS):
        if i < len(state):
            d = state[i]
            name = d.get("name") or "new"
            cls = ["current"] if i == cur else []
            if d.get("kept"):
                cls.append("kept")
            if not d.get("name"):
                cls.append("empty")
            lines.append(json.dumps({"text": name, "class": cls,
                                     "tooltip": "%s · right-click for more" % name}))
        else:
            lines.append(json.dumps({"text": ""}))
    spare = len(state) < COLUMNS and state[-1].get("name") is not None
    lines.append(json.dumps({"text": "+" if spare else "", "tooltip": "a new desktop"}))
    text = "\n".join(lines) + "\n"
    try:
        with open(BAR_FILE) as fh:
            if fh.read() == text:
                return
    except OSError:
        pass
    with open(BAR_FILE + ".tmp", "w") as fh:
        fh.write(text)
    os.replace(BAR_FILE + ".tmp", BAR_FILE)
    subprocess.run(["pkill", "-RTMIN+%d" % WAYBAR_SIGNAL, "-x", "waybar"], check=False)


# ── actions ────────────────────────────────────────────────────────────────

def go(i):
    with locked():
        state = load()
        if 0 <= i < COLUMNS:
            wm.go_to_pivot(i)
            if i >= len(state):
                state.append({"name": None, "kept": False})
            reconcile(state)


def new():
    with locked():
        state = reconcile(write=False)
        if len(state) >= COLUMNS:
            return
        if state[-1].get("name") is not None:
            state.append({"name": None, "kept": False})
        wm.go_to_pivot(len(state) - 1)
        reconcile(state)


def rename(i, name):
    with locked():
        state = load()
        name = clean(name)
        if 0 <= i < len(state) and name:
            taken = {d["name"] for j, d in enumerate(state) if j != i and d.get("name")}
            state[i] = {"name": _unique(name, taken), "kept": True}
        reconcile(state)


def keep(i, value=None):
    with locked():
        state = load()
        if 0 <= i < len(state):
            d = state[i]
            d["kept"] = (not d.get("kept")) if value is None else value
            if d["kept"] and not d.get("name"):
                d["name"] = _unique("desktop", {x["name"] for x in state if x.get("name")})
        reconcile(state)


def move(i, direction):
    with locked():
        state = load()
        j = i - 1 if direction == "left" else i + 1
        if not (0 <= i < len(state) and 0 <= j < len(state)):
            return
        ws = wm.windows()
        a = [w for w in ws if w.get("workspace") == i]
        b = [w for w in ws if w.get("workspace") == j]
        _move_column(a, i, j)
        _move_column(b, j, i)
        state[i], state[j] = state[j], state[i]
        cur = wm.current_pivot()
        if cur in (i, j):
            wm.go_to_pivot(j if cur == i else i)
        reconcile(state)


def close(i):
    with locked():
        state = load()
        if not (0 <= i < len(state)) or len(state) == 1:
            return
        target = i - 1 if i > 0 else 1
        _move_column(wm.windows(), i, target)
        state[i]["kept"] = False
        if wm.current_pivot() == i:
            wm.go_to_pivot(target)
        reconcile(state)


# ── the daemon ─────────────────────────────────────────────────────────────

EVENTS = ["view-mapped", "view-unmapped", "view-workspace-changed",
          "wset-workspace-changed", "output-wset-changed", "view-wset-changed"]


def daemon():
    if not wm.WAYFIRE:
        sys.exit("tube-desktops: needs Wayfire (WAYFIRE_SOCKET is not set)")
    with locked():
        reconcile()
    while True:
        try:
            for _ev in wm.wf_watch(EVENTS):
                with locked():
                    reconcile()
        except (OSError, wm.WayfireError, ValueError):
            time.sleep(1)  # Wayfire restarting, or a config reload
            if not os.path.exists(os.environ.get("WAYFIRE_SOCKET", "")):
                return


# ── the right-click menu ───────────────────────────────────────────────────

def menu(i):
    from . import common  # GTK, only when a menu is shown
    from gi.repository import Gdk, Gtk

    state = load()
    if not (0 <= i < len(state)):
        return
    d = state[i]
    common.apply_css()
    # A clear layer over the whole screen below the bar, so a click anywhere
    # outside the menu closes it; the menu itself sits under the name.
    win = common.make_layer_window("desktop-menu", transparent=True, layer="top")
    if common.GtkLayerShell is not None and common.GtkLayerShell.is_supported():
        common.GtkLayerShell.set_exclusive_zone(win, 0)
    catcher = Gtk.EventBox()
    catcher.connect("button-press-event", lambda *_: Gtk.main_quit())
    win.add(catcher)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.START,
                  valign=Gtk.Align.START, margin_start=_label_x(state, i))
    box.get_style_context().add_class("tube-popup")
    shield = Gtk.EventBox()  # clicks inside the menu don't reach the catcher
    shield.connect("button-press-event", lambda *_: True)
    shield.add(box)
    shield.set_halign(Gtk.Align.START)
    shield.set_valign(Gtk.Align.START)
    catcher.add(shield)

    entry = Gtk.Entry(text=d.get("name") or "")
    entry.set_placeholder_text("name this desktop")
    entry.get_style_context().add_class("tube-popup-entry")
    box.pack_start(entry, False, False, 0)

    def done(*_):
        Gtk.main_quit()

    def act(fn):
        def run(*_):
            win.hide()
            fn()
            done()
        return run

    entry.connect("activate", lambda e: act(lambda: rename(i, e.get_text()))())

    def item(text, fn, sensitive=True):
        b = Gtk.Button(label=text)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("tube-popup-item")
        b.get_child().set_xalign(0)
        b.set_sensitive(sensitive)
        b.connect("clicked", act(fn))
        box.pack_start(b, False, False, 0)

    def rule():
        sep = Gtk.Separator()
        sep.get_style_context().add_class("tube-popup-rule")
        box.pack_start(sep, False, False, 0)

    item("let go when empty" if d.get("kept") else "keep, even when empty", lambda: keep(i))
    rule()
    item("move left", lambda: move(i, "left"), i > 0)
    item("move right", lambda: move(i, "right"), i < len(state) - 1)
    rule()
    neighbour = state[i - 1 if i > 0 else 1].get("name") if len(state) > 1 else None
    item("close desktop", lambda: close(i), len(state) > 1)
    if neighbour:
        hint = Gtk.Label(label="its windows move to %s" % neighbour, xalign=0)
        hint.get_style_context().add_class("tube-popup-hint")
        box.pack_start(hint, False, False, 0)

    win.connect("key-press-event", lambda _w, ev: done() if ev.keyval == Gdk.KEY_Escape else False)
    win.show_all()
    entry.grab_focus()
    entry.select_region(0, -1)
    Gtk.main()


def _label_x(state, i):
    """Where desktop i's name starts on the bar, so the menu opens under it.
    Measured with the bar's own font: start tile 68 px, then each name at
    30 px Open Sans Light with 9 px either side."""
    try:
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        layout = PangoCairo.FontMap.get_default().create_context()
        lay = Pango.Layout.new(layout)
        lay.set_font_description(Pango.FontDescription.from_string("Open Sans Light 30px"))
        x = 68
        for d in state[:i]:
            lay.set_text(d.get("name") or "new", -1)
            x += lay.get_pixel_size()[0] + 18
        return x
    except (ImportError, ValueError):
        return 68 + 90 * i


# ── command line ───────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(prog="tube-desktops", description=__doc__.splitlines()[0])
    p.add_argument("action", nargs="?", default="list",
                   choices=["daemon", "go", "new", "rename", "keep", "move", "close", "menu", "list"])
    p.add_argument("args", nargs="*")
    a = p.parse_args(argv)

    def n():
        try:
            return int(a.args[0]) - 1
        except (IndexError, ValueError):
            p.error("%s needs a desktop number, counting from 1" % a.action)

    if a.action == "daemon":
        daemon()
    elif a.action == "go":
        go(n())
    elif a.action == "new":
        new()
    elif a.action == "rename":
        rename(n(), " ".join(a.args[1:]))
    elif a.action == "keep":
        keep(n())
    elif a.action == "move":
        move(n(), (a.args[1:] or ["right"])[0])
    elif a.action == "close":
        close(n())
    elif a.action == "menu":
        menu(n())
    else:
        for i, d in enumerate(load(), 1):
            print("%2d  %s%s" % (i, d.get("name") or "(new)", "  · kept" if d.get("kept") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
