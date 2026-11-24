"""Tiles for the start screen.

Sizes follow a 70 px unit with 10 px gutters:
  small 1x1 (70x70), medium 2x2 (150x150), wide 4x2 (310x150), large 4x4 (310x310)

Every tile kind is a class registered in KINDS with a little metadata (a
title and blurb for the "add a tile" menu, the sizes it supports, and the
settings it has), so the start screen can build its menus from it.
"""

import calendar
import datetime
import glob
import json
import os
import random
import subprocess
import threading
import urllib.parse
import xml.etree.ElementTree as ET

from . import common, glyphs  # common pins the GTK version first

from gi.repository import GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

UNIT = 70
GUTTER = 10
SIZES = {"small": (1, 1), "medium": (2, 2), "wide": (4, 2), "large": (4, 4)}
SIZE_ORDER = ["small", "medium", "wide", "large"]

FLIP_MS = 450


def px(units):
    return units * UNIT + (units - 1) * GUTTER


# ── small helpers ──────────────────────────────────────────────────────────

def _label(text, cls, xalign=0.0, wrap=False, lines=1):
    lab = Gtk.Label(label=text, xalign=xalign)
    lab.get_style_context().add_class(cls)
    if wrap:
        lab.set_line_wrap(True)
        lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lab.set_lines(lines)
    lab.set_ellipsize(Pango.EllipsizeMode.END)
    return lab


def _image(gicon, size):
    img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DIALOG)
    img.set_pixel_size(size)
    return img


def _frame(*rows, valign=Gtk.Align.START, margin=12):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.set_valign(valign)
    box.set_margin_start(margin)
    box.set_margin_end(margin)
    box.set_margin_top(margin - 2)
    for r in rows:
        box.pack_start(r, False, False, 0)
    box.show_all()
    return box


def _centered(widget):
    box = Gtk.Box()
    box.set_center_widget(widget)
    box.show_all()
    return box


def run_async(argv, callback, timeout=20):
    """Run a command on a thread and hand its stdout to callback on the main loop."""
    def work():
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        GLib.idle_add(lambda: callback(out) and False)
    threading.Thread(target=work, daemon=True).start()


def cover_pixbuf(path, w, h):
    """Load an image scaled and centre-cropped to fill w x h."""
    try:
        info, iw, ih = GdkPixbuf.Pixbuf.get_file_info(path)
        if not info or not iw or not ih:
            return None
        scale = max(w / iw, h / ih)
        sw, sh = max(w, int(iw * scale + 0.5)), max(h, int(ih * scale + 0.5))
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
        return pb.new_subpixbuf((sw - w) // 2, (sh - h) // 2, w, h)
    except GLib.Error:
        return None


_CATEGORY_GLYPHS = [
    ("TerminalEmulator", "terminal"), ("WebBrowser", "web"), ("Email", "mail"),
    ("InstantMessaging", "chat"), ("Chat", "chat"), ("FileManager", "folder"),
    ("IDE", "code"), ("TextEditor", "code"), ("Development", "code"),
    ("Audio", "music"), ("Music", "music"), ("Video", "video"), ("Game", "game"),
    ("Photography", "photo"), ("Graphics", "photo"), ("Calendar", "calendar"),
    ("Settings", "settings"), ("System", "system"),
]


def category_glyph(info):
    if info is None or not hasattr(info, "get_categories"):
        return None
    cats = (info.get_categories() or "").split(";")
    for cat, glyph in _CATEGORY_GLYPHS:
        if cat in cats:
            return glyph
    return None


def glyph_for(spec, label_text, size):
    """Prefer a monochrome glyph: tubewm's own, then a symbolic theme
    icon, then one picked from the app's categories, then its full icon."""
    icon = spec.get("icon")
    if icon and glyphs.has(icon):
        return glyphs.Glyph(icon, size)
    info = spec.get("_info")
    gicon = None
    if icon:
        gicon = Gio.FileIcon.new(Gio.File.new_for_path(icon)) if icon.startswith("/") \
            else Gio.ThemedIcon.new(icon)
    elif info is not None:
        gicon = info.get_icon()
    if isinstance(gicon, Gio.ThemedIcon):
        theme = Gtk.IconTheme.get_default()
        for n in gicon.get_names():
            sym = n if n.endswith("-symbolic") else n + "-symbolic"
            if theme.has_icon(sym):
                return _image(Gio.ThemedIcon.new(sym), size)
    guess = category_glyph(info)
    if guess:
        return glyphs.Glyph(guess, size)
    if gicon is not None:
        return _image(gicon, size)
    letter = (label_text or "?")[:1].lower()
    return _label(letter, "tile-letter", xalign=0.5)


# ── base tile ──────────────────────────────────────────────────────────────

KINDS = {}


def kind(name, title, blurb, sizes=("small", "medium", "wide"), default="medium",
         glyph="start", params=(), addable=True):
    """Register a tile class. params: [(key, label, default)] the user can edit."""
    def wrap(cls):
        cls.kind = name
        cls.title = title
        cls.blurb = blurb
        cls.sizes = tuple(sizes)
        cls.default_size = default
        cls.glyph = glyph
        cls.params = tuple(params)
        cls.addable = addable
        KINDS[name] = cls
        return cls
    return wrap


class Tile(Gtk.Button):
    """A flat coloured tile. Live kinds add frames to self.stack."""

    live = False
    kind = "app"
    sizes = tuple(SIZE_ORDER)
    params = ()
    glyph = "start"

    def __init__(self, spec, on_activate):
        super().__init__()
        self.spec = spec
        self.size = spec.get("size", self.default_size if hasattr(self, "default_size") else "medium")
        if self.size not in SIZES:
            self.size = "medium"
        self.w, self.h = SIZES[self.size]
        self.pw, self.ph = px(self.w), px(self.h)
        self.set_size_request(self.pw, self.ph)
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(True)
        ctx = self.get_style_context()
        ctx.add_class("tile")
        ctx.add_class("entering")
        ctx.add_class("size-" + self.size)
        color = spec.get("color", "accent")
        if color in ("dark", "surface"):
            ctx.add_class("surface")
        elif isinstance(color, str) and color.startswith("#") and len(color) == 7:
            prov = Gtk.CssProvider()
            prov.load_from_data(
                (".tile { background-color: %s; } .tile:active { background-color: %s; }"
                 % (color, common.mix(color, "#000000", 0.3))).encode())
            ctx.add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self.connect("clicked", lambda *_: on_activate(self))

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP)
        self.stack.set_transition_duration(FLIP_MS)
        self.overlay.add(self.stack)
        self._last = {}

        self.label_text = spec.get("label") or self.default_label()
        self.build()
        self.label = None
        if self.label_text and self.size != "small" and not self.hide_label():
            self.label = _label(self.label_text, "tile-label")
            self.label.set_halign(Gtk.Align.START)
            self.label.set_valign(Gtk.Align.END)
            self.label.set_margin_start(10)
            self.label.set_margin_bottom(7)
            self.label.set_margin_end(36)
            self.overlay.add_overlay(self.label)
            self.overlay.set_overlay_pass_through(self.label, True)
        self.badge = None

    # Content -----------------------------------------------------------
    def default_label(self):
        return ""

    def hide_label(self):
        return False

    def param(self, key):
        for p in self.params:
            if p[0] == key:
                return self.spec.get(key, p[2])
        return self.spec.get(key)

    def glyph_px(self):
        return {"small": 30, "medium": 46, "wide": 46, "large": 64}[self.size]

    def face(self, glyph=None):
        spec = dict(self.spec)
        if glyph and not spec.get("icon"):
            spec["icon"] = glyph
        g = glyph_for(spec, self.label_text, self.glyph_px())
        g.set_halign(Gtk.Align.CENTER)
        g.set_valign(Gtk.Align.CENTER)
        if self.size != "small":
            g.set_margin_bottom(14)
        return g

    def build(self):
        self.stack.add_named(self.face(self.glyph if self.kind != "app" else None), "face")

    def add_frame(self, widget, name=None):
        widget.show_all()
        self.stack.add_named(widget, name or "f%d" % len(self.stack.get_children()))
        return widget

    def set_badge(self, text):
        if self.badge is None:
            self.badge = _label("", "tile-badge")
            self.badge.set_halign(Gtk.Align.END)
            self.badge.set_valign(Gtk.Align.END)
            self.badge.set_margin_end(9)
            self.badge.set_margin_bottom(5)
            self.overlay.add_overlay(self.badge)
            self.overlay.set_overlay_pass_through(self.badge, True)
        self.badge.set_text(text or "")
        self.badge.set_visible(bool(text))

    def due(self, key, seconds):
        """True at most once every `seconds` for this key (throttles refresh)."""
        now = GLib.get_monotonic_time() / 1e6
        if now - self._last.get(key, -1e9) < seconds:
            return False
        self._last[key] = now
        return True

    # Live behaviour ------------------------------------------------------
    def flippable(self):
        return self.live and len([c for c in self.stack.get_children() if c.get_visible()]) > 1

    def flip(self):
        kids = [c for c in self.stack.get_children() if c.get_visible()]
        if len(kids) < 2:
            return
        cur = self.stack.get_visible_child()
        i = kids.index(cur) if cur in kids else -1
        self.stack.set_visible_child(kids[(i + 1) % len(kids)])

    def show_first(self, widget):
        """Jump straight to content the first time it appears."""
        if self.stack.get_visible_child_name() == "face" and widget.get_visible():
            self.stack.set_visible_child_full(
                self.stack.child_get_property(widget, "name"), Gtk.StackTransitionType.NONE)

    def refresh(self):
        pass

    def activate_tile(self):
        """What a click does. Return True to keep start open."""
        return False


# ── app and shortcut tiles ─────────────────────────────────────────────────

@kind("app", "app", "an app from the list", sizes=SIZE_ORDER, addable=False)
class AppTile(Tile):
    def default_label(self):
        info = self.spec.get("_info")
        return (info.get_display_name() or "").lower() if info is not None else ""

    def activate_tile(self):
        if self.spec.get("exec"):
            common.run_detached(self.spec["exec"])
        elif self.spec.get("_info") is not None:
            common.launch_app(self.spec["_info"])
        return False


ACTIONS = {
    "lock": ("lock", "lock", "tube-lock"),
    "settings": ("settings", "settings", "tube-charms --settings"),
    "charms": ("charms", "start", "tube-charms"),
    "switcher": ("switch", "apps", "tube-switcher"),
    "devices": ("devices", "devices", "tube-charms --devices"),
    "screenshot": ("screenshot", "share", "sleep 0.3; tube-share region"),
}


@kind("action", "shortcut", "lock, settings, switcher, screenshot…", sizes=("small", "medium"),
      default="small", glyph="lock", params=(("action", "does", "lock", list(ACTIONS)),))
class ActionTile(Tile):
    def _act(self):
        return ACTIONS.get(self.param("action"), ACTIONS["lock"])

    def default_label(self):
        return self._act()[0]

    def build(self):
        self.stack.add_named(self.face(self._act()[1]), "face")

    def activate_tile(self):
        common.run_detached(self._act()[2])
        return False


# ── time ───────────────────────────────────────────────────────────────────

@kind("clock", "clock", "the time and date", sizes=SIZE_ORDER, default="wide", glyph="clock")
class ClockTile(Tile):
    live = True

    def hide_label(self):
        return True

    def build(self):
        self.time = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.time.get_style_context().add_class("small")
            self.time.set_xalign(0.5)
            self.stack.add_named(_centered(self.time), "time")
            return
        if self.size == "large":
            self.time.get_style_context().add_class("huge")
        self.day = _label("", "tile-title")
        self.date = _label("", "tile-text")
        self.stack.add_named(_frame(self.time, self.day, self.date), "time")
        if self.size != "medium":
            self.week = _label("", "tile-title")
            self.year = _label("", "tile-text", wrap=True, lines=3)
            self.stack.add_named(_frame(self.week, self.year), "week")

    def refresh(self):
        now = datetime.datetime.now()
        self.time.set_text(now.strftime("%H:%M"))
        if self.size == "small":
            return
        self.day.set_text(now.strftime("%A").lower())
        self.date.set_text(now.strftime("%B %-d").lower())
        if self.size != "medium":
            days = 366 if calendar.isleap(now.year) else 365
            doy = now.timetuple().tm_yday
            self.week.set_text("week %d" % now.isocalendar()[1])
            self.year.set_text("day %d of %d\n%d days left this year" % (doy, days, days - doy))


@kind("calendar", "calendar", "today's date and the month at a glance", sizes=SIZE_ORDER,
      glyph="calendar")
class CalendarTile(Tile):
    live = True

    def default_label(self):
        return "calendar"

    def build(self):
        self.num = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.num.set_xalign(0.5)
            self.num.get_style_context().add_class("small")
            self.stack.add_named(_centered(self.num), "day")
            return
        self.wday = _label("", "tile-title")
        self.stack.add_named(_frame(self.num, self.wday), "day")
        if self.size in ("wide", "large"):
            self.month = Gtk.Label(xalign=0)
            self.month.get_style_context().add_class("tile-mono")
            self.stack.add_named(_frame(self.month), "month")

    def refresh(self):
        today = datetime.date.today()
        self.num.set_text(str(today.day))
        if self.size == "small":
            return
        self.wday.set_text(today.strftime("%A").lower())
        if self.size in ("wide", "large"):
            weeks = calendar.Calendar().monthdayscalendar(today.year, today.month)
            rows = [today.strftime("%B").lower()]
            if self.size == "wide":
                weeks = [w for w in weeks if today.day in w]
                rows = [today.strftime("%B %Y").lower(), "mo tu we th fr sa su"]
            else:
                rows.append("mo tu we th fr sa su")
            for w in weeks:
                cells = []
                for d in w:
                    if d == 0:
                        cells.append("  ")
                    elif d == today.day:
                        cells.append("<b><u>%2d</u></b>" % d)
                    else:
                        cells.append("%2d" % d)
                rows.append(" ".join(cells))
            self.month.set_markup("\n".join(rows))


# ── media ──────────────────────────────────────────────────────────────────

@kind("music", "music", "what's playing, with album art", sizes=SIZE_ORDER, glyph="music")
class MusicTile(Tile):
    live = True

    def default_label(self):
        return "music"

    def build(self):
        super().build()
        self.title = _label("", "tile-title", wrap=True, lines=2)
        self.artist = _label("", "tile-text")
        self.now = _label("now playing", "tile-text")
        self.playing = self.add_frame(_frame(self.now, self.title, self.artist), "playing")
        self.art = Gtk.Image()
        self.art_frame = self.add_frame(self.art, "art")
        self.art_frame.set_visible(False)
        self._art_url = None

    def refresh(self):
        if not common.have("playerctl"):
            self.playing.set_visible(False)
            return
        out = common.sh(["playerctl", "metadata", "--format",
                         "{{status}}\t{{title}}\t{{artist}}\t{{mpris:artUrl}}"], timeout=1)
        parts = out.split("\t")
        if len(parts) >= 3 and parts[1]:
            status, title, artist = parts[:3]
            art = parts[3] if len(parts) > 3 else ""
            self.now.set_text("now playing" if status == "Playing" else status.lower())
            self.title.set_text(title)
            self.artist.set_text(artist)
            self.playing.set_visible(True)
            if art != self._art_url:
                self._art_url = art
                path = urllib.parse.unquote(urllib.parse.urlparse(art).path) if art.startswith("file://") else ""
                pb = cover_pixbuf(path, self.pw, self.ph) if path and os.path.exists(path) else None
                self.art.set_from_pixbuf(pb)
                self.art_frame.set_visible(pb is not None)
            self.show_first(self.playing)
        else:
            self.playing.set_visible(False)
            self.art_frame.set_visible(False)
            self.stack.set_visible_child_name("face")

    def activate_tile(self):
        if self.spec.get("exec"):
            common.run_detached(self.spec["exec"])
            return False
        common.sh("playerctl play-pause")
        GLib.timeout_add(300, lambda: self.refresh() or False)
        return True


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


@kind("photos", "photos", "pictures from a folder, changing as it flips", sizes=SIZE_ORDER[1:],
      default="wide", glyph="photo", params=(("folder", "folder", "~/Pictures"),))
class PhotosTile(Tile):
    live = True

    def default_label(self):
        return "photos"

    def build(self):
        super().build()
        self.images = []
        self.pics = [Gtk.Image(), Gtk.Image()]
        self.frames = [self.add_frame(p, "p%d" % i) for i, p in enumerate(self.pics)]
        for f in self.frames:
            f.set_visible(False)
        self._which = 0
        folder = os.path.expanduser(self.param("folder") or "~/Pictures")

        def scan():
            found = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.lower().endswith(IMAGE_EXT):
                        found.append(os.path.join(root, f))
                if len(found) > 2000:
                    break
            GLib.idle_add(self._scanned, found)
        threading.Thread(target=scan, daemon=True).start()

    def _scanned(self, found):
        self.images = found
        if found:
            self._load(0)
            self.show_first(self.frames[0])
        return False

    def _load(self, i):
        for _ in range(4):
            pb = cover_pixbuf(random.choice(self.images), self.pw, self.ph)
            if pb is not None:
                self.pics[i].set_from_pixbuf(pb)
                self.frames[i].set_visible(True)
                return

    def flip(self):
        if len(self.images) < 2:
            return
        nxt = 1 - self._which
        self._load(nxt)
        self._which = nxt
        self.stack.set_visible_child(self.frames[nxt])

    def flippable(self):
        return len(self.images) > 1

    def activate_tile(self):
        common.run_detached("xdg-open %s" % GLib.shell_quote(os.path.expanduser(
            self.param("folder") or "~/Pictures")))
        return False


# ── outside world ──────────────────────────────────────────────────────────

@kind("weather", "weather", "temperature and conditions from wttr.in", sizes=SIZE_ORDER,
      glyph="weather", params=(("location", "place (blank: guess from your connection)", ""),))
class WeatherTile(Tile):
    live = True

    def default_label(self):
        return "weather"

    def build(self):
        super().build()
        self.temp = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.temp.get_style_context().add_class("small")
            self.temp.set_xalign(0.5)
            self.now = self.add_frame(_centered(self.temp), "now")
        else:
            self.cond = _label("", "tile-title", wrap=True, lines=2)
            self.now = self.add_frame(_frame(self.temp, self.cond), "now")
            self.place = _label("", "tile-title")
            self.more = _label("", "tile-text", wrap=True, lines=3)
            self.detail = self.add_frame(_frame(self.place, self.more), "detail")
            self.detail.set_visible(False)
        self.now.set_visible(False)

    def refresh(self):
        if not self.due("fetch", 1800) or not common.have("curl"):
            return
        loc = urllib.parse.quote((self.param("location") or "").strip())
        url = "https://wttr.in/%s?format=%%t%%09%%C%%09%%l%%09%%h%%09%%w&m" % loc
        run_async(["curl", "-fsS", "--max-time", "10", url], self._got)

    def _got(self, out):
        parts = out.strip().split("\t")
        if len(parts) < 3 or "unknown" in out.lower():
            self._last.pop("fetch", None) if not out else None
            return
        temp, cond, place = parts[0], parts[1], parts[2]
        self.temp.set_text(temp.replace("+", ""))
        self.now.set_visible(True)
        if self.size != "small":
            self.cond.set_text(cond.lower())
            self.place.set_text(place.split(",")[0].lower())
            extra = []
            if len(parts) > 3:
                extra.append("humidity %s" % parts[3])
            if len(parts) > 4:
                extra.append("wind %s" % parts[4])
            self.more.set_text("\n".join(extra))
            self.detail.set_visible(True)
        self.show_first(self.now)


def _recent_files(limit=6):
    path = os.path.join(common.DATA, "recently-used.xbel")
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    items = []
    for bm in root.iter("bookmark"):
        href = bm.get("href", "")
        if not href.startswith("file://"):
            continue
        p = urllib.parse.unquote(urllib.parse.urlparse(href).path)
        if os.path.exists(p):
            items.append((bm.get("visited") or bm.get("modified") or "", p))
    items.sort(reverse=True)
    return [p for _, p in items[:limit]]


@kind("recent", "recent files", "the files you opened last", sizes=SIZE_ORDER[1:],
      default="wide", glyph="recent")
class RecentTile(Tile):
    live = True

    def default_label(self):
        return "recent"

    def build(self):
        super().build()
        self.frames = []

    def refresh(self):
        if not self.due("scan", 30):
            return
        files = _recent_files(4 if self.size != "large" else 2)
        for f in self.frames:
            self.stack.remove(f)
        self.frames = []
        if self.size == "large" and files:
            rows = []
            for p in _recent_files(7):
                rows.append(_label(os.path.basename(p), "tile-text"))
            f = self.add_frame(_frame(_label("recent", "tile-title"), *rows))
            f.path = None
            self.frames.append(f)
        else:
            for p in files:
                f = self.add_frame(_frame(_label(os.path.basename(p), "tile-title", wrap=True, lines=2),
                                          _label(os.path.dirname(p).replace(common.HOME, "~"),
                                                 "tile-text")))
                f.path = p
                self.frames.append(f)
        if self.frames:
            self.show_first(self.frames[0])

    def activate_tile(self):
        cur = self.stack.get_visible_child()
        path = getattr(cur, "path", None)
        common.run_detached("xdg-open %s" % GLib.shell_quote(path) if path else "xdg-open ~")
        return False


@kind("messages", "notifications", "recent notifications and how many there were",
      sizes=SIZE_ORDER, glyph="bell")
class MessagesTile(Tile):
    live = True

    def default_label(self):
        return "notifications"

    def build(self):
        super().build()
        self.frames = []
        self.count = 0

    def _history(self):
        out = common.sh("makoctl history")
        items = []
        try:
            data = json.loads(out)
            for n in (data.get("data") or [[]])[0]:
                get = lambda k: (n.get(k) or {}).get("data", "")  # noqa: E731
                items.append((get("app-name"), get("summary"), get("body")))
        except ValueError:
            # mako 1.9+ prints plain text: "Notification N: summary" lines.
            for line in out.splitlines():
                if line.startswith("Notification "):
                    items.append(("", line.split(":", 1)[-1].strip(), ""))
                elif line.strip().startswith("App name:") and items:
                    items[-1] = (line.split(":", 1)[1].strip(),) + items[-1][1:]
        return items

    def refresh(self):
        if not self.due("poll", 6) or not common.have("makoctl"):
            return
        items = self._history()
        if len(items) == self.count and self.frames:
            return
        self.count = len(items)
        for f in self.frames:
            self.stack.remove(f)
        self.frames = []
        self.set_badge(str(min(self.count, 99)) if self.count and self.size != "small" else "")
        if self.size == "small":
            if self.count:
                big = _label(str(min(self.count, 99)), "tile-hero", xalign=0.5)
                big.get_style_context().add_class("small")
                self.frames.append(self.add_frame(_centered(big)))
        else:
            for app, summary, body in items[:4]:
                rows = [_label((app or "").lower(), "tile-text"),
                        _label(summary, "tile-title", wrap=True, lines=2)]
                if body and self.size != "medium":
                    rows.append(_label(body, "tile-text", wrap=True, lines=3))
                self.frames.append(self.add_frame(_frame(*rows)))
        if self.frames:
            self.show_first(self.frames[0])
        else:
            self.stack.set_visible_child_name("face")

    def activate_tile(self):
        common.sh("makoctl restore")
        return False


@kind("windows", "open windows", "how many windows are open, and what they are",
      sizes=("small", "medium", "wide"), glyph="windows")
class WindowsTile(Tile):
    live = True

    def default_label(self):
        return "open"

    def build(self):
        super().build()
        self.frames = []

    def refresh(self):
        if not self.due("poll", 4) or not os.environ.get("SWAYSOCK"):
            return
        try:
            tree = json.loads(common.sh("swaymsg -r -t get_tree") or "{}")
        except ValueError:
            return
        wins = []

        def walk(node, ws):
            if node.get("type") == "workspace":
                ws = node.get("name", "")
            if node.get("pid") and node.get("type") in ("con", "floating_con"):
                wins.append((node.get("name") or node.get("app_id") or "", ws.split(":", 1)[-1]))
            for child in node.get("nodes", []) + node.get("floating_nodes", []):
                walk(child, ws)
        walk(tree, "")
        for f in self.frames:
            self.stack.remove(f)
        self.frames = []
        n = len(wins)
        if self.size == "small":
            big = _label(str(n), "tile-hero", xalign=0.5)
            big.get_style_context().add_class("small")
            self.frames.append(self.add_frame(_centered(big)))
        else:
            head = _label("%d open" % n, "tile-title")
            names = [_label("%s · %s" % (t, w), "tile-text") for t, w in wins[:4 if self.size == "wide" else 3]]
            self.frames.append(self.add_frame(_frame(head, *names)))
        self.show_first(self.frames[0])

    def activate_tile(self):
        common.run_detached("tube-switcher")
        return False


# ── this machine ───────────────────────────────────────────────────────────

def _battery():
    for path in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(path, "capacity")) as fh:
                cap = int(fh.read().strip())
            with open(os.path.join(path, "status")) as fh:
                status = fh.read().strip().lower()
            return cap, status
        except (OSError, ValueError):
            continue
    return None, None


@kind("battery", "battery", "charge left and whether it's charging", sizes=("small", "medium", "wide"),
      default="small", glyph="battery")
class BatteryTile(Tile):
    live = True

    def default_label(self):
        return "battery"

    def build(self):
        super().build()  # the glyph, shown on machines with no battery
        self.pct = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.pct.get_style_context().add_class("small")
            self.pct.set_xalign(0.5)
            self.pct_frame = _centered(self.pct)
        else:
            self.state = _label("", "tile-text")
            self.pct_frame = _frame(self.pct, self.state)
        self.add_frame(self.pct_frame, "pct")

    def refresh(self):
        cap, status = _battery()
        self.pct_frame.set_visible(cap is not None)
        if cap is None:
            return
        self.show_first(self.pct_frame)
        self.pct.set_text("%d" % cap if self.size == "small" else "%d%%" % cap)
        if self.size != "small":
            self.state.set_text(status.replace("not charging", "plugged in"))


def _meminfo():
    vals = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":", 1)
                vals[k] = int(v.split()[0])
    except (OSError, ValueError):
        return None
    total, avail = vals.get("MemTotal"), vals.get("MemAvailable")
    if not total or avail is None:
        return None
    return 100 * (total - avail) // total


def _cpu_times():
    try:
        with open("/proc/stat") as fh:
            parts = [int(x) for x in fh.readline().split()[1:]]
        return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)
    except (OSError, ValueError, IndexError):
        return None


@kind("system", "system", "processor, memory and uptime", sizes=("small", "medium", "wide"),
      glyph="system")
class SystemTile(Tile):
    live = True

    def default_label(self):
        return "system"

    def build(self):
        if self.size == "small":
            self.cpu = _label("", "tile-hero", xalign=0.5)
            self.cpu.get_style_context().add_class("small")
            self.stack.add_named(_centered(self.cpu), "cpu")
        else:
            super().build()
            self.cpu = _label("", "tile-title")
            self.mem = _label("", "tile-text")
            self.up = _label("", "tile-text")
            self.stats = self.add_frame(_frame(self.cpu, self.mem, self.up), "stats")
        self._prev = _cpu_times()

    def refresh(self):
        now = _cpu_times()
        pct = None
        if now and self._prev and now[0] > self._prev[0]:
            total, idle = now[0] - self._prev[0], now[1] - self._prev[1]
            pct = max(0, min(100, round(100 * (total - idle) / total)))
        self._prev = now
        if self.size == "small":
            self.cpu.set_text("%d%%" % pct if pct is not None else "…")
            return
        self.cpu.set_text("cpu %d%%" % pct if pct is not None else "cpu …")
        mem = _meminfo()
        self.mem.set_text("memory %d%%" % mem if mem is not None else "")
        try:
            with open("/proc/uptime") as fh:
                up = int(float(fh.read().split()[0]))
            h, m = divmod(up // 60, 60)
            self.up.set_text("up %dh %02dm" % (h, m))
        except (OSError, ValueError, IndexError):
            pass
        self.show_first(self.stats)


@kind("disk", "storage", "how full your drives are", sizes=("small", "medium", "wide"),
      glyph="disk")
class DiskTile(Tile):
    live = True

    def default_label(self):
        return "storage"

    def build(self):
        if self.size == "small":
            self.big = _label("", "tile-hero", xalign=0.5)
            self.big.get_style_context().add_class("small")
            self.stack.add_named(_centered(self.big), "pct")
            return
        super().build()
        self.rows = [_label("", "tile-title"), _label("", "tile-text"), _label("", "tile-text")]
        self.stats = self.add_frame(_frame(*self.rows), "stats")

    def refresh(self):
        if not self.due("df", 60):
            return
        seen, lines = set(), []
        for mount in ("/", common.HOME):
            try:
                st = os.statvfs(mount)
            except OSError:
                continue
            key = (st.f_blocks, st.f_bfree)
            if key in seen:
                continue
            seen.add(key)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = 100 - round(100 * free / total) if total else 0
            lines.append((mount.replace(common.HOME, "home") if mount != "/" else "system",
                          used, free / 1e9))
        if not lines:
            return
        if self.size == "small":
            self.big.set_text("%d%%" % lines[0][1])
            return
        self.rows[0].set_text("%d%% full" % lines[0][1])
        for row, (name, used, free) in zip(self.rows[1:], lines):
            row.set_text("%s · %.0f GB free" % (name, free))
        self.show_first(self.stats)


def _network():
    name = ""
    if common.have("nmcli"):
        for line in common.sh("nmcli -t -f TYPE,STATE,CONNECTION device").splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("wifi", "ethernet"):
                name = parts[2] if parts[0] == "wifi" else "wired"
                break
    addr = ""
    for line in common.sh("ip -4 -o addr show scope global").splitlines():
        bits = line.split()
        if len(bits) > 3:
            if not name:
                name = bits[1]
            addr = bits[3].split("/")[0]
            break
    return name, addr


@kind("network", "network", "what you're connected to", sizes=("small", "medium", "wide"),
      glyph="network")
class NetworkTile(Tile):
    live = True

    def default_label(self):
        return "network"

    def build(self):
        super().build()
        if self.size != "small":
            self.name = _label("", "tile-title")
            self.addr = _label("", "tile-text")
            self.info = self.add_frame(_frame(self.name, self.addr), "info")

    def refresh(self):
        if self.size == "small" or not self.due("poll", 15):
            return
        name, addr = _network()
        self.name.set_text(name or "offline")
        self.addr.set_text(addr)
        self.show_first(self.info)

    def activate_tile(self):
        common.run_detached("nm-connection-editor" if common.have("nm-connection-editor")
                            else "tube-charms --settings")
        return False


# ── yours ──────────────────────────────────────────────────────────────────

@kind("note", "note", "a line of text you choose", sizes=SIZE_ORDER, default="wide", glyph="note",
      params=(("text", "text", "make something today"),))
class NoteTile(Tile):
    def build(self):
        text = self.param("text") or ""
        if self.size == "small":
            self.stack.add_named(_centered(_label(text[:3], "tile-hero", xalign=0.5)), "note")
            return
        cls = "tile-note-big" if self.size in ("large", "wide") and len(text) < 40 else "tile-title"
        lab = _label(text, cls, wrap=True, lines=6 if self.size == "large" else 3)
        lab.set_valign(Gtk.Align.START)
        self.stack.add_named(_frame(lab), "note")

    def activate_tile(self):
        return True  # editing happens from the tile's menu


@kind("command", "command", "any shell command; each output line becomes a frame",
      sizes=SIZE_ORDER, default="wide", glyph="terminal",
      params=(("command", "command", "date '+%A'; uptime -p"), ("interval", "update every (seconds)", "60"),
              ("label", "label", "")))
class CommandTile(Tile):
    live = True

    def build(self):
        super().build()
        self.frames = []

    def refresh(self):
        try:
            interval = max(2, int(self.param("interval") or 60))
        except (TypeError, ValueError):
            interval = 60
        cmd = self.param("command")
        if not cmd or not self.due("run", interval):
            return
        run_async(["sh", "-c", cmd], self._got, timeout=15)

    def _got(self, out):
        lines = [ln for ln in out.splitlines() if ln.strip()][:5]
        for f in self.frames:
            self.stack.remove(f)
        self.frames = []
        for ln in lines:
            head, _, rest = ln.partition("\t")
            rows = [_label(head, "tile-title", wrap=True, lines=2)]
            if rest:
                rows.append(_label(rest, "tile-text", wrap=True, lines=3))
            self.frames.append(self.add_frame(_frame(*rows)))
        if self.frames:
            self.show_first(self.frames[0])

    def activate_tile(self):
        self._last.pop("run", None)
        self.refresh()
        return True


def make(spec, on_activate):
    cls = KINDS.get(spec.get("type", "app"), AppTile)
    return cls(spec, on_activate)


def allowed_sizes(spec):
    return KINDS.get(spec.get("type", "app"), AppTile).sizes


# ── flipping ───────────────────────────────────────────────────────────────

class FlipScheduler:
    """Flips live tiles one or two at a time, never all together: every
    4.5-7 s a random live tile turns over to its next frame."""

    def __init__(self, get_tiles):
        self.get_tiles = get_tiles
        GLib.timeout_add(2000, self.refresh)
        self.refresh()
        self._schedule()

    def refresh(self):
        for t in self.get_tiles():
            if t.live:
                try:
                    t.refresh()
                except Exception as err:  # a broken tile shouldn't take start down
                    print("tube-start: %s tile: %s" % (t.kind, err))
        return True

    def _schedule(self):
        GLib.timeout_add(int(4500 + random.random() * 2500), self._tick)

    def _tick(self):
        cands = [t for t in self.get_tiles() if t.flippable() and t.get_mapped()]
        random.shuffle(cands)
        for t in cands[: 2 if random.random() < 0.25 else 1]:
            t.flip()
        self._schedule()
        return False
