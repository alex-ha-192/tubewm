"""The glance: live tiles in start's right-hand column, arranged by you.

Tiles sit on a four-column grid as wide as the column. Drag a tile to move it
(the others make room for it), drag its bottom-right corner to resize it,
and right-click it for its sizes, colour, settings and remove. "add a tile"
opens the library of every kind of tile there is.

Clicking a tile opens its applet in place of the tiles, with the things you
would want to do: the music tile has the controls, the calendar tile the week
ahead, the sound tile the volume and which speakers and microphone to use.
The back arrow or Escape goes back to the tiles.

The tiles you have are kept in ~/.config/tubewm/glance.json.
"""

import datetime
import json
import os
import random
import sys
import threading
import time
import urllib.parse

from . import applets, common, glyphs, tiles, wm

from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

COLS = 4
GAP = 8
MAX_ROWS = 6
# Names for the shapes in the right-click menu; any width and height works.
SHAPES = [("small", (1, 1)), ("medium", (2, 2)), ("long", (4, 1)), ("wide", (4, 2)),
          ("tall", (2, 4)), ("large", (4, 4))]
OLD_SIZES = dict(SHAPES)
DRAG_SLOP = 6        # px the pointer moves before a press becomes a drag
SLIDE_MS = 180       # tiles gliding to their new place
PATH = os.path.join(common.CONFIG, "tubewm", "glance.json")
WEATHER_CACHE = os.path.join(common.RUNTIME, "tubewm-weather")
WEATHER_EVERY = 1800  # seconds

DEFAULT = [
    {"type": "music", "w": 4, "h": 2, "color": "accent"},
    {"type": "calendar", "w": 2, "h": 2},
    {"type": "weather", "w": 2, "h": 2},
    {"type": "notifications", "w": 2, "h": 1},
    {"type": "battery", "w": 1, "h": 1},
    {"type": "sound", "w": 1, "h": 1},
]


# ── what the tiles show ────────────────────────────────────────────────────
#
# Each reader runs on a worker thread and returns a face: a dict with any of
#   label  the small heading           big    the one thing to read
#   sub    a line under it             more   [(left, right)] rows for large tiles
#   value  what a small tile shows     glyph  what a small tile shows otherwise
#   image  a picture to fill the tile

def now_playing():
    """(status, title, artist, where) of whatever is playing, or None."""
    if not common.have("playerctl"):
        return None
    fmt = "{{status}}\t{{title}}\t{{artist}}\t{{duration(position)}}\t{{duration(mpris:length)}}"
    parts = common.sh(["playerctl", "metadata", "--format", fmt]).split("\t")
    if len(parts) == 5 and parts[0] in ("Playing", "Paused") and parts[1]:
        where = "%s of %s" % (parts[3], parts[4]) if parts[3] and parts[4] else ""
        return parts[0].lower(), parts[1], parts[2], where
    return None


def agenda(days=7):
    """[(day, time, title, place)] from khal for the coming days, or None
    when there is no khal. day is "" for today."""
    if not common.have("khal"):
        return None
    out = common.sh(["khal", "list", "today", "%dd" % days,
                     "--format", "{start-time}\t{title}\t{location}",
                     "--day-format", "@@{name}"], timeout=5)
    events, day = [], ""
    for line in out.splitlines():
        if line.startswith("@@"):
            name = line[2:].strip().lower()
            day = "" if name == "today" else name
            continue
        when, _t, rest = line.partition("\t")
        what, _t, where = rest.partition("\t")
        if what.strip():
            events.append((day, when.strip() or "all day", what.strip(), where.strip()))
    return events


def weather(location="", allow_fetch=True):
    """(temperature, conditions) from wttr.in, remembered for half an hour."""
    location = (location or os.environ.get("TUBEWM_WEATHER", "")).strip()
    try:
        with open(WEATHER_CACHE) as fh:
            cached = json.load(fh)
        if cached.get("where", "") != location:
            cached = {}
        elif time.time() - cached.get("at", 0) < WEATHER_EVERY:
            return cached.get("temp"), cached.get("cond")
    except (OSError, ValueError):
        cached = {}
    if not allow_fetch or not common.have("curl"):
        return cached.get("temp"), cached.get("cond")
    out = common.sh(["curl", "-fsS", "--max-time", "8",
                     "https://wttr.in/%s?format=%%t%%09%%C&m" % urllib.parse.quote(location)], timeout=10)
    parts = out.split("\t")
    if len(parts) == 2 and "unknown" not in out.lower() and "<" not in out:
        temp, cond = parts[0].replace("+", "").strip(), parts[1].strip().lower()
        try:
            with open(WEATHER_CACHE, "w") as fh:
                json.dump({"at": time.time(), "where": location, "temp": temp, "cond": cond}, fh)
        except OSError:
            pass
        return temp, cond
    return cached.get("temp"), cached.get("cond")


def _music(spec, state):
    p = now_playing()
    if not p:
        return {"label": "music", "big": "nothing playing", "glyph": "music"}
    status, title, artist, where = p
    return {"label": "now playing" if status == "playing" else "paused", "big": title,
            "sub": " · ".join(x for x in (artist, where) if x), "glyph": "pause" if status == "playing" else "play"}


def _calendar(spec, state):
    today = datetime.date.today()
    events = agenda(days=7) or []
    todays = [e for e in events if not e[0]]
    face = {"value": str(today.day)}
    if todays:
        _day, when, what, _where = todays[0]
        face.update(label="next", big=when, sub=what)
    else:
        face.update(label="today", big=str(today.day), sub=today.strftime("%A %B").lower())
    rest = events[1:] if todays else events
    face["more"] = [(day or when, what) for day, when, what, _w in rest[:4]]
    return face


def _weather(spec, state):
    temp, cond = weather(spec.get("location", ""))
    if not temp:
        return {"label": "weather", "big": "…", "sub": "no forecast yet", "glyph": "weather"}
    return {"label": "weather", "big": temp, "sub": cond, "value": temp}


def _notifications(spec, state):
    items = applets.notification_history() if common.have("makoctl") else []
    n = len(items)
    latest = items[-1] if items else None
    sub = "all caught up"
    if latest:
        sub = " · ".join(x for x in ((latest.get("app") or "").lower(), latest.get("summary")) if x)
    return {"label": "notifications", "big": str(n), "sub": sub, "value": str(min(n, 99)),
            "more": [((i.get("app") or "").lower(), i.get("summary", "")) for i in items[-5:-1][::-1]]}


def _battery(spec, state):
    pct, status, left = applets.battery_info()
    if pct is None:
        return {"label": "battery", "big": "plugged in", "sub": "no battery", "glyph": "battery"}
    words = {"discharging": "on battery", "charging": "charging", "fully-charged": "fully charged",
             "pending-charge": "plugged in, not charging"}.get(status.lower(), status.lower())
    return {"label": "battery", "big": "%d%%" % pct, "sub": left or words, "value": "%d%%" % pct}


def _audio(kind):
    """[(name, description, is_default)] of outputs or inputs."""
    if hasattr(applets, "audio_devices"):
        return applets.audio_devices(kind)
    return applets.sinks() if kind == "output" else []


def _sound(spec, state):
    v, muted = applets.volume()
    device = next((d for _n, d, default in _audio("output") if default), "")
    big = "muted" if muted else ("%d%%" % v if v is not None else "…")
    return {"label": "volume", "big": big, "sub": device.lower(), "value": big}


def _network(spec, state):
    name, addr = tiles._network()
    return {"label": "network", "big": name or "offline", "sub": addr, "glyph": "network",
            "caption": name or "offline"}


def _clock(spec, state):
    now = datetime.datetime.now()
    return {"big": now.strftime("%H:%M"), "sub": now.strftime("%A %-d %B").lower(),
            "value": now.strftime("%H:%M"), "caption": now.strftime("%A").lower()}


def _system(spec, state):
    cur = tiles._cpu_times()
    prev, state["cpu"] = state.get("cpu"), cur
    pct = 0
    if cur and prev and cur[0] > prev[0]:
        pct = round(100 * (1 - (cur[1] - prev[1]) / (cur[0] - prev[0])))
    mem = tiles._meminfo()
    up = ""
    try:
        with open("/proc/uptime") as fh:
            secs = int(float(fh.read().split()[0]))
        hours = secs // 3600
        up = "up %d %s" % (hours, "hour" if hours == 1 else "hours") if hours else \
            "up %d minutes" % (secs // 60)
    except (OSError, ValueError):
        pass
    sub = " · ".join(x for x in ("memory %s%% used" % mem if mem is not None else "", up) if x)
    return {"label": "processor", "big": "%d%% busy" % pct, "sub": sub, "value": "%d%%" % pct}


def _storage(spec, state):
    try:
        st = os.statvfs(os.path.expanduser(spec.get("path") or "/"))
    except OSError:
        return {"label": "storage", "big": "…", "glyph": "disk"}
    total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    used = 100 - round(100 * free / total) if total else 0
    return {"label": "storage", "big": "%d%% full" % used,
            "sub": "%s free of %s" % (applets._size(free), applets._size(total)), "value": "%d%%" % used,
            "caption": "storage used"}


def _photos(spec, state):
    folder = os.path.expanduser(spec.get("folder") or "~/Pictures")
    if state.get("folder") != folder:
        found = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found += [os.path.join(root, f) for f in files if f.lower().endswith(tiles.IMAGE_EXT)]
            if len(found) > 2000:
                break
        state.update(folder=folder, found=found)
    found = state.get("found") or []
    if not found:
        return {"label": "photos", "big": "no pictures", "sub": folder.replace(common.HOME, "~"),
                "glyph": "photo"}
    return {"label": "photos", "image": random.choice(found), "glyph": "photo"}


def _recent(spec, state):
    files = tiles._recent_files(6)
    if not files:
        return {"label": "recent files", "big": "nothing yet", "glyph": "recent"}
    return {"label": "recent files", "big": os.path.basename(files[0]),
            "sub": os.path.dirname(files[0]).replace(common.HOME, "~"), "glyph": "recent",
            "more": [(os.path.basename(p), "") for p in files[1:5]]}


# App names for the windows tile. Its reader runs on a thread, and Gio's
# list of installed apps must only be read on the main loop: reading it from
# a thread while start reads it too (or while it reloads after an install)
# can leave start stuck on a lock for good, deaf to the Windows key. So the
# thread only looks names up here, and the main loop fills them in.
_names = {}


def _app_display(app_id):
    if not app_id:
        return ""
    if app_id not in _names:
        _names[app_id] = None
        GLib.idle_add(_learn_name, app_id)
    return _names.get(app_id) or app_id


def _learn_name(app_id):
    info = common.find_app(app_id)
    _names[app_id] = (info.get_display_name() if info else "") or app_id
    return False


def _windows(spec, state):
    try:
        wins = wm.windows()
    except Exception:  # noqa: BLE001 - no compositor to ask
        wins = []
    names = [_app_display(w.get("app_id") or "").lower() for w in wins]
    return {"label": "open windows", "big": str(len(wins)), "sub": ", ".join(n for n in names if n),
            "value": str(len(wins))}


def _note(spec, state):
    lines = [ln for ln in (spec.get("text") or "").splitlines() if ln.strip()]
    if not lines:
        return {"label": "note", "big": "click to write", "glyph": "note"}
    return {"label": "note", "big": lines[0], "sub": lines[1] if len(lines) > 1 else "",
            "more": [(ln, "") for ln in lines[2:6]], "glyph": "note"}


def _command(spec, state):
    cmd = spec.get("command") or ""
    if not cmd:
        return {"label": "command", "big": "no command yet", "glyph": "terminal"}
    out = common.sh(["sh", "-c", cmd], timeout=10)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return {"label": spec.get("label") or cmd, "big": lines[0] if lines else "no output",
            "sub": lines[1] if len(lines) > 1 else "", "more": [(ln, "") for ln in lines[2:6]],
            "value": lines[0][:5] if lines and len(lines[0]) <= 5 else None, "glyph": "terminal"}


def _shortcut(spec, state):
    name, glyph, _cmd = tiles.ACTIONS.get(spec.get("action"), tiles.ACTIONS["lock"])
    return {"label": "", "big": name, "glyph": glyph, "caption": name}


# ── the detail views ───────────────────────────────────────────────────────

class Agenda(applets.Applet):
    """The calendar tile's applet: the week ahead, then the month."""
    title = "calendar"

    def build(self):
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.list, False, False, 0)
        row = Gtk.Box(spacing=8)
        app = _calendar_app()
        if app:
            row.pack_start(applets.button("new event", lambda: self.open(app), "glance-primary"), False, False, 0)
            row.pack_start(applets.button("open %s" % _app_name(app), lambda: self.open(app)), False, False, 0)
        self.pack_start(row, False, False, 6)
        self.pack_start(applets.Calendar(), False, False, 12)

    def open(self, app):
        common.launch_app(app)
        self.done()

    def update(self):
        applets.clear(self.list)
        events = agenda(days=7)
        if events is None:
            self.list.pack_start(applets.label("your events show up here once khal is set up",
                                               "applet-dim", wrap=True), False, False, 0)
        elif not events:
            self.list.pack_start(applets.label("nothing in the next seven days", "applet-dim"),
                                 False, False, 0)
        day = None
        for d, when, what, where in events or []:
            if d != day:
                day = d
                self.list.pack_start(applets.section(d or "today"), False, False, 4)
            row = Gtk.Box(spacing=14)
            t = applets.label(when, "glance-when")
            t.set_valign(Gtk.Align.START)
            row.pack_start(t, False, False, 0)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(applets.label(what, "applet-strong", wrap=True), False, False, 0)
            if where:
                box.pack_start(applets.label(where, "applet-dim", wrap=True), False, False, 0)
            row.pack_start(box, True, True, 0)
            self.list.pack_start(row, False, False, 0)
        self.list.show_all()


def _calendar_app():
    for app_id in ("org.gnome.Calendar", "gnome-calendar", "org.kde.merkuro.calendar", "khal"):
        info = common.find_app(app_id)
        if info:
            return info
    return None


def _app_name(info):
    return (info.get_display_name() or "calendar").lower()


class Sound(applets.Volume):
    """Volume, and which speakers and which microphone to use."""

    def build(self):
        v, _muted = applets.volume()
        line = Gtk.Box(spacing=10)
        self.mute = applets.button(glyph="sound", cb=self.toggle_mute, tooltip="mute", size=22)
        line.pack_start(self.mute, False, False, 0)
        line.pack_start(applets.slider(v or 0, applets.set_volume, hi=150 if (v or 0) > 100 else 100),
                        True, True, 0)
        self.pct = applets.label("", "applet-strong")
        line.pack_start(self.pct, False, False, 0)
        self.pack_start(line, False, False, 0)
        for kind, heading in (("output", "play sound through"), ("input", "listen with")):
            devices = _audio(kind)
            if not devices:
                continue
            self.pack_start(applets.section(heading), False, False, 4)
            first = None
            for name, desc, default in devices:
                rb = Gtk.RadioButton.new_with_label_from_widget(first, desc.lower())
                first = first or rb
                rb.get_style_context().add_class("applet-radio")
                rb.set_active(default)
                rb.connect("toggled", lambda b, k=kind, n=name: b.get_active() and _set_audio(k, n))
                self.pack_start(rb, False, False, 0)
        if common.have("pavucontrol"):
            self.pack_start(applets.button("more sound settings", lambda: (applets.spawn("pavucontrol"),
                                                                           self.done()), glyph="settings"),
                            False, False, 6)


def _set_audio(kind, name):
    if hasattr(applets, "set_audio_device"):
        applets.set_audio_device(kind, name)
    else:
        applets.run(["pactl", "set-default-" + ("sink" if kind == "output" else "source"), name])


class NoteEditor(applets.Applet):
    """The note tile's applet: the note itself, to write in."""
    title = "note"

    def __init__(self, spec, on_change):
        self.spec, self.on_change = spec, on_change
        super().__init__()

    def build(self):
        self.text = Gtk.TextView()
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.get_style_context().add_class("glance-note")
        self.text.set_size_request(-1, 220)
        buf = self.text.get_buffer()
        buf.set_text(self.spec.get("text") or "")
        buf.connect("changed", lambda b: self.on_change(b.get_text(b.get_start_iter(), b.get_end_iter(), False)))
        self.pack_start(self.text, False, False, 0)
        self.pack_start(applets.label("it is saved as you type", "applet-dim"), False, False, 0)
        GLib.idle_add(lambda: self.text.grab_focus() and False)


# ── the library ────────────────────────────────────────────────────────────

class Kind:
    def __init__(self, name, title, blurb, glyph, read, least=(1, 1), most=(COLS, MAX_ROWS), default=(2, 2),
                 every=30, applet=None, params=()):
        self.name, self.title, self.blurb, self.glyph = name, title, blurb, glyph
        self.read, self.least, self.most, self.default, self.every = read, least, most, default, every
        self.applet = applet        # spec -> Applet, or None to run the tile's action
        self.params = tuple(params)  # (key, what to ask, default, [choices])


KINDS = {k.name: k for k in [
    Kind("music", "now playing", "what is playing, with the controls", "music", _music,
         default=(4, 2), every=2, applet=lambda s: applets.Music()),
    Kind("calendar", "calendar", "your next event, and the week ahead when you click", "calendar",
         _calendar, every=60, applet=lambda s: Agenda()),
    Kind("weather", "weather", "the temperature and the sky where you are", "weather", _weather,
         every=300, applet=lambda s: applets.Weather(s.get("location", "")),
         params=(("location", "place (leave empty to guess from your connection)", ""),)),
    Kind("notifications", "notifications", "how many you have, and the latest", "bell", _notifications,
         default=(2, 1), every=5,
         applet=lambda s: applets.Notifications()),
    Kind("battery", "battery", "charge left, power mode and brightness", "battery", _battery,
         default=(1, 1), every=30, applet=lambda s: applets.Power()),
    Kind("sound", "sound", "the volume, and which speakers and microphone", "sound", _sound,
         default=(1, 1), every=3, applet=lambda s: Sound()),
    Kind("network", "network", "what you are connected to, and the networks nearby", "network",
         _network, default=(1, 1), every=15, applet=lambda s: applets.Network()),
    Kind("clock", "clock", "the time and date, and the month", "clock", _clock, default=(4, 2),
         every=5, applet=lambda s: applets.Clock()),
    Kind("system", "system", "how busy the processor and memory are", "system", _system,
         every=3, applet=lambda s: applets.System()),
    Kind("storage", "storage", "how full your drives are", "disk", _storage,
         every=120, applet=lambda s: applets.Storage()),
    Kind("photos", "photos", "pictures from a folder, a new one every so often", "photo", _photos,
         least=(2, 1), default=(4, 2), every=12,
         applet=lambda s: applets.Photos(s.get("folder") or "~/Pictures"),
         params=(("folder", "folder", "~/Pictures"),)),
    Kind("recent", "recent files", "the files you opened last", "recent", _recent,
         least=(2, 1), default=(4, 2), every=30, applet=lambda s: applets.Recent()),
    Kind("windows", "open windows", "what is open, on which desktop", "windows", _windows,
         every=4, applet=lambda s: applets.Windows()),
    Kind("note", "note", "a few lines you want to keep in sight", "note", _note, default=(4, 2),
         every=3600),
    Kind("command", "command", "any command, showing what it prints", "terminal", _command,
         default=(4, 1), every=60,
         applet=lambda s: applets.Command(s.get("command", ""), s.get("label") or "command"),
         params=(("command", "command", ""), ("label", "name (leave empty to show the command)", ""),
                 ("every", "run every, in seconds", "60"))),
    Kind("shortcut", "shortcut", "lock, settings, screenshot and more in one click", "lock", _shortcut,
         most=(2, 2), default=(1, 1), every=3600,
         params=(("action", "does", "lock", list(tiles.ACTIONS)),)),
]}


def load():
    try:
        with open(PATH) as fh:
            data = json.load(fh)
        specs = [t for t in data.get("tiles", []) if isinstance(t, dict) and t.get("type") in KINDS]
        if isinstance(data.get("tiles"), list):
            return specs
    except (OSError, ValueError, AttributeError) as err:
        if os.path.exists(PATH):
            print("tube-start: can't read %s (%s); using the default tiles" % (PATH, err), file=sys.stderr)
    return [dict(t) for t in DEFAULT]


def save(specs):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"tiles": [{k: v for k, v in s.items() if not k.startswith("_")} for s in specs]},
                  fh, indent=1)
        fh.write("\n")
    os.replace(tmp, PATH)


def pack(specs):
    """Place tiles in order, each in the first free spot that fits, left to
    right and top to bottom. Returns ({id(spec): (column, row)}, rows used)."""
    taken, where = set(), {}
    for s in specs:
        w, h = dims(s)
        r = 0
        while True:
            spot = next((c for c in range(COLS - w + 1)
                         if not any((c + x, r + y) in taken for x in range(w) for y in range(h))), None)
            if spot is not None:
                taken.update((spot + x, r + y) for x in range(w) for y in range(h))
                where[id(s)] = (spot, r)
                break
            r += 1
    rows = max([where[id(s)][1] + dims(s)[1] for s in specs] or [0])
    return where, rows


def fit(kind, cols, rows):
    """cols x rows, kept within what this kind of tile can show."""
    return (max(kind.least[0], min(kind.most[0], cols)), max(kind.least[1], min(kind.most[1], rows)))


def dims(spec):
    """(columns, rows) a tile takes. Older layouts named a size instead."""
    if "w" not in spec or "h" not in spec:
        spec["w"], spec["h"] = OLD_SIZES.get(spec.pop("size", None), KINDS[spec["type"]].default)
    try:
        w, h = fit(KINDS[spec["type"]], int(spec["w"]), int(spec["h"]))
    except (TypeError, ValueError):
        w, h = KINDS[spec["type"]].default
    spec["w"], spec["h"] = w, h
    return w, h


def _label(text, cls, xalign=0.0):
    lab = Gtk.Label(label=text or "", xalign=xalign)
    lab.set_ellipsize(Pango.EllipsizeMode.END)
    lab.get_style_context().add_class(cls)
    return lab


# ── a tile ─────────────────────────────────────────────────────────────────

class Tile(Gtk.EventBox):
    def __init__(self, glance, spec):
        super().__init__()
        self.glance, self.spec = glance, spec
        self.kind = KINDS[spec["type"]]
        self.state = {}
        self.busy = False
        self.next_read = 0.0
        self.face = None
        self.x = self.y = None
        self.set_visible_window(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.get_style_context().add_class("glance-tile")
        self.over = Gtk.Overlay()
        self.add(self.over)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.over.add(self.body)
        self.grip = Gtk.EventBox()
        self.grip.set_halign(Gtk.Align.END)
        self.grip.set_valign(Gtk.Align.END)
        self.grip.set_size_request(26, 26)
        self.grip.get_style_context().add_class("glance-grip")
        self.grip.set_tooltip_text("drag to resize")
        self.grip.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK)
        mark = Gtk.DrawingArea()
        mark.connect("draw", self._draw_grip)
        self.grip.add(mark)
        self.grip.set_opacity(0)
        self.over.add_overlay(self.grip)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        self.connect("button-press-event", self.glance.on_press, self, "move")
        self.connect("motion-notify-event", self.glance.on_motion)
        self.connect("button-release-event", self.glance.on_release)
        self.grip.connect("button-press-event", self.glance.on_press, self, "size")
        self.grip.connect("motion-notify-event", self.glance.on_motion)
        self.grip.connect("button-release-event", self.glance.on_release)
        self.restyle()

    def shape(self):
        """cell: one square; row: one row high; narrow: one column wide; block: the rest."""
        cols, rows = dims(self.spec)
        return "cell" if cols == rows == 1 else "row" if rows == 1 else "narrow" if cols == 1 else "block"

    @staticmethod
    def _draw_grip(widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        rgba = widget.get_style_context().get_color(widget.get_state_flags())
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        cr.set_line_width(2)
        cr.move_to(w - 7, h - 17)
        cr.line_to(w - 7, h - 7)
        cr.line_to(w - 17, h - 7)
        cr.stroke()

    def _on_enter(self, _w, _event):
        self.grip.set_opacity(1)
        self.set_state_flags(Gtk.StateFlags.PRELIGHT, False)

    def _on_leave(self, _w, event):
        if event.detail != Gdk.NotifyType.INFERIOR and not self.glance.held(self):
            self.grip.set_opacity(0)
            self.unset_state_flags(Gtk.StateFlags.PRELIGHT)

    def restyle(self):
        ctx = self.get_style_context()
        cols, rows = dims(self.spec)
        for c in ("cell", "row", "narrow", "block"):
            ctx.remove_class(c)
        ctx.add_class(self.shape())
        (ctx.add_class if self.spec.get("color") == "accent" else ctx.remove_class)("glance-accent")
        cell = self.glance.cell
        self.w, self.h = cols * cell + (cols - 1) * GAP, rows * cell + (rows - 1) * GAP
        self.set_size_request(self.w, self.h)
        if self.face is not None:
            self.show_face(self.face)

    # Reading happens on a thread; showing on the main loop.
    def due(self, now):
        return not self.busy and now >= self.next_read

    def refresh(self, now=None):
        self.busy = True
        every = self.kind.every
        if self.kind.name == "command":
            try:
                every = max(2, int(self.spec.get("every") or 60))
            except ValueError:
                every = 60
        self.next_read = (now or time.monotonic()) + every
        spec = dict(self.spec)

        def work():
            try:
                face = self.kind.read(spec, self.state)
            except Exception as err:  # noqa: BLE001 - a broken tile shouldn't take start down
                print("tube-start: %s tile: %s" % (self.kind.name, err), file=sys.stderr)
                face = {"label": self.kind.title, "big": "…", "glyph": self.kind.glyph}
            GLib.idle_add(self._got, face)
        threading.Thread(target=work, daemon=True).start()

    def _got(self, face):
        self.busy = False
        if face != self.face:
            self.show_face(face)
        return False

    def show_face(self, face):
        self.face = face
        for c in self.body.get_children():
            self.body.remove(c)
            c.destroy()
        cols, rows = dims(self.spec)
        shape = self.shape()
        caption = face.get("caption") or face.get("label") or ""
        if face.get("image"):
            pb = tiles.cover_pixbuf(face["image"], self.w, self.h)
            if pb is not None:
                pic = Gtk.Overlay()
                pic.add(Gtk.Image.new_from_pixbuf(pb))
                shade = Gtk.Box()
                shade.get_style_context().add_class("glance-shade")
                pic.add_overlay(shade)
                lab = _label(caption, "glance-label")
                lab.set_valign(Gtk.Align.END)
                lab.set_margin_start(16)
                lab.set_margin_bottom(12)
                pic.add_overlay(lab)
                self.body.pack_start(pic, True, True, 0)
                self.body.show_all()
                return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("glance-face")
        box.get_style_context().add_class(shape)
        self.body.pack_start(box, True, True, 0)
        if shape in ("cell", "narrow"):
            # One column wide: the number (or a glyph), and what it is under it.
            if face.get("value"):
                w = _label(face["value"], "glance-value", xalign=0.5)
            else:
                w = glyphs.Glyph(face.get("glyph") or self.kind.glyph, 30)
            w.set_valign(Gtk.Align.END if rows == 1 else Gtk.Align.CENTER)
            box.pack_start(w, True, True, 0)
            if caption:
                box.pack_end(_label(caption, "glance-caption", xalign=0.5), False, False, 0)
            self.body.show_all()
            return
        if face.get("label"):
            box.pack_start(_label(face["label"], "glance-label"), False, False, 0)
        big = _label(face.get("big"), "glance-big")
        big.get_style_context().add_class("cols-%d" % cols)
        if shape == "row":
            # One row high: the label above, the big part and its line beside each other.
            line = Gtk.Box(spacing=14)
            line.set_valign(Gtk.Align.END)
            big.get_style_context().add_class("row")
            line.pack_start(big, False, False, 0)
            if face.get("sub"):
                sub = _label(face["sub"], "glance-sub")
                sub.set_valign(Gtk.Align.BASELINE)
                big.set_valign(Gtk.Align.BASELINE)
                line.pack_start(sub, True, True, 0)
            box.pack_start(line, True, True, 0)
            self.body.show_all()
            return
        more = (face.get("more") or [])[:max(0, (rows - 2) * 2)]
        box.pack_start(big, not more, not more, 0)
        big.set_valign(Gtk.Align.START if more else Gtk.Align.END)
        if face.get("sub"):
            box.pack_start(_label(face["sub"], "glance-sub"), False, False, 0)
        if more:
            rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            rows_box.get_style_context().add_class("glance-more")
            for left, right in more:
                row = Gtk.Box(spacing=14)
                row.pack_start(_label(left, "glance-more-left"), False, False, 0)
                if right:
                    row.pack_start(_label(right, "glance-sub"), True, True, 0)
                rows_box.pack_start(row, False, False, 0)
            box.pack_end(rows_box, False, False, 0)
        self.body.show_all()


# ── the column ─────────────────────────────────────────────────────────────

class Glance(Gtk.Box):
    """The glance column. Pack things that belong under the tiles (start's
    "open now") into self.below; call back() on Escape."""

    def __init__(self, width, closes=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.width = width
        self.cell = (width - (COLS - 1) * GAP) // COLS
        self.closes = closes
        self.specs = load()
        self.tiles = []
        self.drag = None
        self.applet = None
        self.anim = None

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(260)
        self.stack.set_vexpand(True)
        self.pack_start(self.stack, True, True, 0)

        # The tiles.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        head = Gtk.Box()
        head.pack_start(_label("glance", "start-hint"), False, False, 0)
        add = self._link("add a tile", lambda: self.show_library())
        head.pack_end(add, False, False, 0)
        head.set_margin_bottom(16)
        page.pack_start(head, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(True)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.grid = Gtk.Fixed()
        self.grid.set_size_request(width, 0)
        inner.pack_start(self.grid, False, False, 0)
        self.empty = _label("no tiles: add one from the library", "start-kind")
        self.empty.set_no_show_all(True)
        inner.pack_start(self.empty, False, False, 0)
        self.below = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        inner.pack_start(self.below, False, False, 0)
        scroll.add(inner)
        page.pack_start(scroll, True, True, 0)
        self.stack.add_named(page, "tiles")

        # The library, an applet, and a tile's settings, each under a back arrow.
        self.lib_page, self.lib_body, _t = self._page("add a tile")
        self.stack.add_named(self.lib_page, "library")
        self.app_page, self.app_body, self.app_title = self._page("")
        self.stack.add_named(self.app_page, "applet")
        self.set_page, self.set_body, self.set_title = self._page("")
        self.stack.add_named(self.set_page, "settings")
        self.fill_library()

        for spec in self.specs:
            self._add_tile(spec)
        self.layout(animate=False)
        GLib.timeout_add(1000, self.tick)
        GLib.idle_add(lambda: self.tick() and False)   # once, not every idle moment

    # ── building blocks ──────────────────────────────────────────────
    @staticmethod
    def _link(text, cb, cls="start-hint"):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("start-link")
        b.get_style_context().add_class("glance-link")
        b.add(_label(text, cls))
        b.connect("clicked", lambda *_: cb())
        return b

    def _page(self, title):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        head = Gtk.Box(spacing=16)
        head.get_style_context().add_class("glance-head")
        back = Gtk.Button()
        back.set_relief(Gtk.ReliefStyle.NONE)
        back.get_style_context().add_class("applet-back")
        back.add(glyphs.Glyph("left", 18))
        back.set_tooltip_text("back")
        back.set_valign(Gtk.Align.CENTER)
        back.connect("clicked", lambda *_: self.back())
        head.pack_start(back, False, False, 0)
        lab = _label(title, "glance-title")
        head.pack_start(lab, True, True, 0)
        page.pack_start(head, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.get_style_context().add_class("glance-page")
        scroll.add(body)
        page.pack_start(scroll, True, True, 0)
        return page, body, lab

    # ── the grid ─────────────────────────────────────────────────────
    def _add_tile(self, spec):
        t = Tile(self, spec)
        self.tiles.append(t)
        self.grid.put(t, 0, 0)
        t.show_all()
        return t

    def _order(self):
        return self.drag["order"] if self.drag and self.drag.get("order") else self.specs

    def layout(self, animate=True):
        order = self._order()
        where, rows = pack(order)
        step = self.cell + GAP
        self.grid.set_size_request(self.width, rows * step - GAP if rows else 0)
        self.empty.set_visible(not order)
        goals = {}
        for t in self.tiles:
            c, r = where[id(t.spec)]
            goals[t] = (c * step, r * step)
        if self.anim:
            GLib.source_remove(self.anim)
            self.anim = None
        if not animate:
            for t, (x, y) in goals.items():
                t.x, t.y = x, y
                self.grid.move(t, x, y)
            return
        starts = {t: (t.x if t.x is not None else x, t.y if t.y is not None else y)
                  for t, (x, y) in goals.items()}
        t0 = GLib.get_monotonic_time()

        def step_anim():
            k = min(1.0, (GLib.get_monotonic_time() - t0) / 1000.0 / SLIDE_MS)
            e = 1 - (1 - k) ** 3
            for t, (gx, gy) in goals.items():
                sx, sy = starts[t]
                t.x, t.y = round(sx + (gx - sx) * e), round(sy + (gy - sy) * e)
                self.grid.move(t, t.x, t.y)
            if k >= 1.0:
                self.anim = None
                return False
            return True
        self.anim = GLib.timeout_add(16, step_anim)

    def tick(self):
        if not self.get_mapped() or not getattr(self, "awake", True):
            return True   # start is hidden: nobody to show the tiles to
        now = time.monotonic()
        if self.stack.get_visible_child_name() == "tiles":
            for t in self.tiles:
                if t.due(now):
                    t.refresh(now)
        return True

    def changed(self):
        try:
            save(self.specs)
        except OSError as err:
            print("tube-start: can't save %s: %s" % (PATH, err), file=sys.stderr)

    # ── dragging and resizing ────────────────────────────────────────
    def held(self, tile):
        return bool(self.drag and self.drag["tile"] is tile)

    def on_press(self, _w, event, tile, mode):
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return True   # double clicks: the first click already counted
        if event.button == 3:
            self.menu(tile)
            return True
        if event.button != 1:
            return False
        # Where the pointer is in the grid, worked out from the root so it
        # stays right however the tile moves underneath it.
        gx, gy = _w.translate_coordinates(self.grid, int(event.x), int(event.y)) or (0, 0)
        self.drag = {"tile": tile, "mode": "press" if mode == "move" else "size", "rx": event.x_root,
                     "ry": event.y_root, "gx": gx, "gy": gy, "order": None, "size": dims(tile.spec)}
        if mode == "size":
            tile.get_style_context().add_class("sizing")
        return True

    def on_motion(self, _w, event):
        d = self.drag
        if not d:
            return False
        dx, dy = event.x_root - d["rx"], event.y_root - d["ry"]
        px, py = d["gx"] + dx, d["gy"] + dy
        tile = d["tile"]
        if d["mode"] == "press" and (abs(dx) > DRAG_SLOP or abs(dy) > DRAG_SLOP):
            d["mode"] = "move"
            d["order"] = list(self.specs)
            tile.get_style_context().add_class("dragging")
        if d["mode"] == "move":
            self._move_to(tile.spec, px, py)
        elif d["mode"] == "size":
            step = self.cell + GAP
            cols = max(1, round((tile.w + dx + GAP) / step))
            rows = max(1, round((tile.h + dy + GAP) / step))
            want = fit(tile.kind, cols, rows)
            if want != dims(tile.spec):
                tile.spec["w"], tile.spec["h"] = want
                tile.restyle()
                self.layout()
        return True

    def _move_to(self, spec, px, py):
        """Put the dragged tile where the pointer is: before or after the
        tile under it, or last when the pointer is below them all."""
        order = self.drag["order"]
        where, rows = pack(order)
        step = self.cell + GAP
        target = None
        for s in order:
            if s is spec:
                continue
            c, r = where[id(s)]
            w, h = dims(s)
            if c * step <= px < c * step + w * step and r * step <= py < r * step + h * step:
                target = s
                break
        new = [s for s in order if s is not spec]
        if target is not None:
            i = new.index(target)
            new.insert(i if order.index(spec) > order.index(target) else i + 1, spec)
        elif py >= rows * step:
            new.append(spec)
        else:
            return
        if new != order:
            self.drag["order"] = new
            self.layout()

    def on_release(self, _w, event):
        d, self.drag = self.drag, None
        if not d or event.button != 1:
            return False
        tile = d["tile"]
        for cls in ("dragging", "sizing"):
            tile.get_style_context().remove_class(cls)
        if d["mode"] == "press":
            self.open(tile)
        elif d["mode"] == "move":
            self.specs[:] = d["order"]
            self.layout()
            self.changed()
        elif d["mode"] == "size":
            if dims(tile.spec) != d["size"]:
                self.changed()
                tile.next_read = 0
        return True

    # ── the right-click menu ─────────────────────────────────────────
    def menu(self, tile):
        pop = Gtk.Popover.new(tile)
        pop.get_style_context().add_class("tube-popover")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("tube-popup")
        pop.add(box)

        def item(text, fn, current=False):
            b = Gtk.Button(label=text)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("tube-popup-item")
            if current:
                b.get_style_context().add_class("current")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_: (pop.popdown(), fn()))
            box.pack_start(b, False, False, 0)

        def rule():
            sep = Gtk.Separator()
            sep.get_style_context().add_class("tube-popup-rule")
            box.pack_start(sep, False, False, 0)

        for name, (w, h) in SHAPES:
            if fit(tile.kind, w, h) == (w, h):
                item("%s, %d by %d" % (name, w, h), lambda wh=(w, h): self.resize(tile, wh),
                     current=(w, h) == dims(tile.spec))
        rule()
        accent = tile.spec.get("color") == "accent"
        item("grey" if accent else "accent colour", lambda: self.recolour(tile, not accent))
        if tile.kind.params:
            item("settings", lambda: self.show_settings(tile))
        rule()
        item("remove", lambda: self.remove(tile))
        box.show_all()
        pop.popup()

    def resize(self, tile, size):
        tile.spec["w"], tile.spec["h"] = size
        tile.restyle()
        tile.next_read = 0
        self.layout()
        self.changed()

    def recolour(self, tile, accent):
        if accent:
            tile.spec["color"] = "accent"
        else:
            tile.spec.pop("color", None)
        tile.restyle()
        self.changed()

    def remove(self, tile):
        self.specs.remove(tile.spec)
        self.tiles.remove(tile)
        tile.destroy()
        self.layout()
        self.changed()

    # ── the pages ────────────────────────────────────────────────────
    def back(self):
        """Back to the tiles. False if they were showing already."""
        if self.stack.get_visible_child_name() == "tiles":
            return False
        self.stack.set_visible_child_name("tiles")
        if self.applet is not None:
            app, self.applet = self.applet, None
            GLib.timeout_add(self.stack.get_transition_duration() + 40, lambda: app.destroy() or False)
        for t in self.tiles:
            t.next_read = 0
        return True

    def open(self, tile):
        """What a click does: open the tile's applet, or run its action."""
        kind, spec = tile.kind, tile.spec
        if kind.name == "note":
            applet = NoteEditor(spec, lambda text: self._note(tile, text))
        elif kind.applet is None:
            _name, _glyph, cmd = tiles.ACTIONS.get(spec.get("action"), tiles.ACTIONS["lock"])
            common.run_detached(cmd)
            if self.closes:
                self.closes()
            return
        else:
            applet = kind.applet(spec)
        applet.closes = self.closes
        applets.clear(self.app_body)
        if self.applet is not None:
            self.applet.destroy()
        self.applet = applet
        self.app_title.set_text(spec.get("label") or kind.title if kind.name == "command" else kind.title)
        self.app_body.pack_start(applet, False, False, 0)
        self.app_body.show_all()
        self.stack.set_visible_child_name("applet")

    def _note(self, tile, text):
        tile.spec["text"] = text
        tile.show_face(_note(tile.spec, tile.state))
        self.changed()

    def fill_library(self):
        for kind in KINDS.values():
            row = Gtk.Box(spacing=16)
            icon = Gtk.Box()
            icon.get_style_context().add_class("glance-lib-icon")
            icon.set_size_request(52, 52)
            icon.set_center_widget(glyphs.Glyph(kind.glyph, 26))
            icon.set_valign(Gtk.Align.CENTER)
            row.pack_start(icon, False, False, 0)
            words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            words.set_valign(Gtk.Align.CENTER)
            words.pack_start(_label(kind.title, "glance-lib-title"), False, False, 0)
            blurb = Gtk.Label(label=kind.blurb, xalign=0)
            blurb.set_line_wrap(True)
            blurb.get_style_context().add_class("glance-lib-blurb")
            words.pack_start(blurb, False, False, 0)
            row.pack_start(words, True, True, 0)
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("glance-lib-row")
            b.add(row)
            b.connect("clicked", lambda _b, k=kind: self.add(k))
            self.lib_body.pack_start(b, False, False, 0)

    def show_library(self):
        self.stack.set_visible_child_name("library")

    def add(self, kind):
        spec = {"type": kind.name, "w": kind.default[0], "h": kind.default[1]}
        for key, _ask, default, *_rest in kind.params:
            if default:
                spec[key] = default
        self.specs.append(spec)
        tile = self._add_tile(spec)
        self.layout(animate=False)
        self.changed()
        if kind.name == "command":
            self.show_settings(tile)
        elif kind.name == "note":
            self.stack.set_visible_child_name("tiles")
            self.open(tile)
        else:
            self.stack.set_visible_child_name("tiles")

    def show_settings(self, tile):
        applets.clear(self.set_body)
        self.set_title.set_text(tile.kind.title)
        fields = {}
        for key, ask, default, *choices in tile.kind.params:
            self.set_body.pack_start(applets.section(ask), False, False, 4)
            if choices:
                first = None
                for c in choices[0]:
                    rb = Gtk.RadioButton.new_with_label_from_widget(first, tiles.ACTIONS[c][0]
                                                                    if c in tiles.ACTIONS else c)
                    first = first or rb
                    rb.get_style_context().add_class("applet-radio")
                    rb.set_active(tile.spec.get(key, default) == c)
                    rb.connect("toggled", lambda b, k=key, c=c: b.get_active() and fields.__setitem__(k, c))
                    self.set_body.pack_start(rb, False, False, 0)
                continue
            e = Gtk.Entry(text=str(tile.spec.get(key, default) or ""))
            e.get_style_context().add_class("field")
            e.connect("activate", lambda *_: done())
            fields[key] = e
            self.set_body.pack_start(e, False, False, 0)

        def done():
            for key, w in fields.items():
                value = w.get_text().strip() if isinstance(w, Gtk.Entry) else w
                if value:
                    tile.spec[key] = value
                else:
                    tile.spec.pop(key, None)
            tile.state.clear()
            tile.next_read = 0
            self.changed()
            self.back()

        row = Gtk.Box()
        row.pack_start(applets.button("done", done, "glance-primary"), False, False, 0)
        self.set_body.pack_start(row, False, False, 14)
        self.set_body.get_style_context().add_class("applet")
        self.set_body.show_all()
        self.stack.set_visible_child_name("settings")
        first = next((w for w in fields.values() if isinstance(w, Gtk.Entry)), None)
        if first:
            GLib.idle_add(lambda: first.grab_focus() and False)
