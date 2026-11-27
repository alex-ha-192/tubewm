"""tube-desktops: desktops that come and go by themselves (Wayfire).

There is always one spare desktop at the end of the bar, shown as "+". Open
something there and it becomes a desktop, named after what you opened: a
browser makes "web", an editor "code", a second browser desktop "web 2".
Leave a desktop empty and it goes away. Right-click a name to rename it,
keep it even when empty, move it, or close it. Renamed desktops are kept.

Windows share a desktop without covering each other. A new window takes a
free half or quarter, or the desktop is retiled to make room, up to four;
a fifth gets a desktop of its own. Snap a window to half the screen and the
one you used before it takes the other half.

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
    tube-desktops menu N [X]      the right-click menu for desktop N (at X px)
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
import threading
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


# Windows this process has just moved to another column while repacking
# the desktops: id -> when. The daemon doesn't treat those as windows you
# moved (see _arrive).
SHIFTED = {}


def _move_column(windows, src, dst):
    for w in windows:
        if w.get("workspace") == src:
            SHIFTED[w["id"]] = time.monotonic()
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
          "wset-workspace-changed", "output-wset-changed", "view-wset-changed",
          "view-tiled"]


PLACE_AFTER = 0.15   # seconds after a window opens before it's placed
ARRIVE_AFTER = 0.5   # after one is moved to another desktop (the slide is 320 ms)
SETTLE_AFTER = 0.6   # and before checking it stayed there


def _later(delay, fn, *args):
    t = threading.Timer(delay, fn, args)
    t.daemon = True
    t.start()


def _place(win_id, arranged):
    try:
        plan = wm.place(win_id)
    except (OSError, wm.WayfireError, ValueError):
        return
    now = time.monotonic()
    for vid, _zone in plan:
        arranged[vid] = now
    if plan:
        _later(SETTLE_AFTER, _settle, plan, arranged)


def _fill(gone, arranged):
    try:
        plan = wm.fill_gap(gone)
    except (OSError, wm.WayfireError, ValueError):
        return
    now = time.monotonic()
    for vid, _zone in plan:
        arranged[vid] = now
    if plan:
        _later(SETTLE_AFTER, _settle, plan, arranged)


def _arrive(win_id, left_behind, gap, arranged):
    try:
        plan = wm.arrived(win_id, left_behind, gap)
    except (OSError, wm.WayfireError, ValueError):
        return
    now = time.monotonic()
    for vid, _zone in plan:
        arranged[vid] = now
    if plan:
        _later(SETTLE_AFTER, _settle, plan, arranged)


def _moved(ev, arranged, now):
    """A window went to another desktop. If you moved it (rather than us,
    repacking the desktops or making room), find it room there in a moment,
    once the slide is over."""
    view = ev.get("view") or {}
    vid = view.get("id")
    src = (ev.get("from") or {}).get("x")
    dst = (ev.get("to") or {}).get("x")
    if vid is None or src is None or src == dst or view.get("role") != "toplevel":
        return
    if now - SHIFTED.get(vid, -9) < 2 or now - arranged.get(vid, -9) < 2:
        return
    left_behind = {w["id"] for w in wm.windows()
                   if w.get("workspace") == src and w["id"] != vid}
    _later(ARRIVE_AFTER, _arrive, vid, left_behind, view.get("geometry"), arranged)


def _settle(plan, arranged):
    try:
        again = wm.settle(plan)
    except (OSError, wm.WayfireError, ValueError):
        return
    now = time.monotonic()
    for vid in again:
        arranged[vid] = now


def daemon():
    if not wm.WAYFIRE:
        sys.exit("tube-desktops: needs Wayfire (WAYFIRE_SOCKET is not set)")
    with locked():
        reconcile()
    while True:
        try:
            arranged = {}   # windows we just moved ourselves: id -> when
            for ev in wm.wf_watch(EVENTS):
                kind, view = ev.get("event"), ev.get("view") or {}
                now = time.monotonic()
                if kind == "view-tiled":
                    # Snapping one window to half the screen sends the one
                    # you used before it to the other half.
                    if now - arranged.get(view.get("id"), -9) < 2:
                        continue
                    # You tiled it yourself: if to a corner, it keeps
                    # that size when a window beside it closes.
                    wm.chose(view, ev.get("new-edges"))
                    if ev.get("new-edges") != ev.get("old-edges"):
                        wm.pair(dict(view, **{"tiled-edges": ev.get("new-edges")}))
                    continue
                if kind == "view-workspace-changed":
                    _moved(ev, arranged, now)
                if kind == "view-mapped" and view.get("id") is not None:
                    # A new window takes free space, or the desktop is
                    # retiled so nothing is covered. Wait a moment so the
                    # app has settled on its first size, then check again
                    # a little later in case it moved itself.
                    _later(PLACE_AFTER, _place, view["id"], arranged)
                if kind == "view-unmapped" and view.get("id") is not None \
                        and view.get("role") == "toplevel" and not view.get("minimized"):
                    # A window closed: the ones beside it grow into its
                    # space (two halves become one window filling the
                    # screen). Wait a moment so it has really gone from
                    # Wayfire's list.
                    _later(PLACE_AFTER, _fill, view, arranged)
                if kind == "view-unmapped" and view.get("id") is not None:
                    wm.CHOSEN.discard(view["id"])
                with locked():
                    reconcile()
        except (OSError, wm.WayfireError, ValueError):
            time.sleep(1)  # Wayfire restarting, or a config reload
            if not os.path.exists(os.environ.get("WAYFIRE_SOCKET", "")):
                return


# ── the right-click menu ───────────────────────────────────────────────────

def menu(i, x=None):
    from . import common  # GTK, only when a menu is shown
    from gi.repository import Gtk

    state = load()
    if not (0 <= i < len(state)):
        return
    d = state[i]
    common.apply_css()
    win, box = common.popup_window("desktop-menu", "left", x if x is not None else _label_x(state, i))

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

    item("let go when empty" if d.get("kept") else "keep", lambda: keep(i))
    rule()
    item("move left", lambda: move(i, "left"), i > 0)
    item("move right", lambda: move(i, "right"), i < len(state) - 1)
    rule()
    neighbour = state[i - 1 if i > 0 else 1].get("name") if len(state) > 1 else None
    item("close", lambda: close(i), len(state) > 1)
    if neighbour:
        hint = Gtk.Label(label="its windows move to %s" % neighbour, xalign=0)
        hint.get_style_context().add_class("tube-popup-hint")
        box.pack_start(hint, False, False, 0)

    win.show_all()
    entry.grab_focus()
    entry.select_region(0, -1)
    Gtk.main()


def _label_x(state, i):
    """Where desktop i's name starts on the bar, so the menu opens under it.
    Measured with the strip's own font: the start square takes 52 px, then
    each name is 20 px Open Sans Light with 11 px either side. (The strip
    passes the real position; this is for running it by hand.)"""
    try:
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        layout = PangoCairo.FontMap.get_default().create_context()
        lay = Pango.Layout.new(layout)
        lay.set_font_description(Pango.FontDescription.from_string("Open Sans Light 20px"))
        x = 52
        for d in state[:i]:
            lay.set_text(d.get("name") or "new", -1)
            x += lay.get_pixel_size()[0] + 22
        return x
    except (ImportError, ValueError):
        return 52 + 70 * i


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
        x = int(a.args[1]) if len(a.args) > 1 and a.args[1].lstrip("-").isdigit() else None
        menu(n(), x)
    else:
        for i, d in enumerate(load(), 1):
            print("%2d  %s%s" % (i, d.get("name") or "(new)", "  · kept" if d.get("kept") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
