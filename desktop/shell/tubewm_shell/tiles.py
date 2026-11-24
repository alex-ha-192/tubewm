"""Tiles for the start screen: plain app tiles and live tiles.

Sizes follow a 70 px unit with 10 px gutters:
  small 1x1 (70x70), medium 2x2 (150x150), wide 4x2 (310x150), large 4x4 (310x310)
"""

import datetime
import glob
import os
import random

from . import common, glyphs  # common pins the GTK version first

from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

UNIT = 70
GUTTER = 10
SIZES = {"small": (1, 1), "medium": (2, 2), "wide": (4, 2), "large": (4, 4)}

FLIP_MS = 450


def px(units):
    return units * UNIT + (units - 1) * GUTTER


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


def glyph_for(spec, label_text, size):
    """Prefer a monochrome glyph: tubewm's own, then a symbolic theme
    icon, then one picked from the app's categories, then its full icon."""
    icon = spec.get("icon")
    name = icon or spec.get("glyph")
    if name and glyphs.has(name):
        return glyphs.Glyph(name, size)
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


class Tile(Gtk.Button):
    """A flat coloured tile. Subclasses add live frames."""

    live = False

    def __init__(self, spec, on_activate):
        super().__init__()
        self.spec = spec
        self.size = spec.get("size", "medium")
        if self.size not in SIZES:
            self.size = "medium"
        self.w, self.h = SIZES[self.size]
        self.set_size_request(px(self.w), px(self.h))
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_can_focus(True)
        ctx = self.get_style_context()
        ctx.add_class("tile")
        ctx.add_class("entering")
        color = spec.get("color", "accent")
        if color == "surface":
            ctx.add_class("surface")
        elif isinstance(color, str) and color.startswith("#"):
            prov = Gtk.CssProvider()
            prov.load_from_data(
                (".tile { background-color: %s; } .tile:active { background-color: %s; }"
                 % (color, common.mix(color, "#000000", 0.3))).encode())
            ctx.add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self._on_activate = on_activate
        self.connect("clicked", lambda *_: on_activate(self))

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP)
        self.stack.set_transition_duration(FLIP_MS)
        self.overlay.add(self.stack)

        self.label_text = spec.get("label", "")
        self.build()
        if self.label_text and self.size != "small" and not spec.get("hide_label"):
            lab = _label(self.label_text, "tile-label")
            lab.set_halign(Gtk.Align.START)
            lab.set_valign(Gtk.Align.END)
            lab.set_margin_start(10)
            lab.set_margin_bottom(7)
            lab.set_margin_end(30)
            self.overlay.add_overlay(lab)
            self.overlay.set_overlay_pass_through(lab, True)
        self.badge = None

    # Content -----------------------------------------------------------
    def glyph_widget(self, size):
        return glyph_for(self.spec, self.label_text, size)

    def build(self):
        glyph_px = {"small": 32, "medium": 48, "wide": 48, "large": 64}[self.size]
        g = self.glyph_widget(glyph_px)
        g.set_halign(Gtk.Align.CENTER)
        g.set_valign(Gtk.Align.CENTER)
        if self.size != "small":
            g.set_margin_bottom(12)
        self.stack.add_named(g, "face")

    def add_frame(self, widget, name=None):
        self.stack.add_named(widget, name or "f%d" % len(self.stack.get_children()))

    def set_badge(self, text):
        if self.badge is None:
            self.badge = _label("", "tile-badge")
            self.badge.set_halign(Gtk.Align.END)
            self.badge.set_valign(Gtk.Align.END)
            self.badge.set_margin_end(8)
            self.badge.set_margin_bottom(4)
            self.overlay.add_overlay(self.badge)
            self.overlay.set_overlay_pass_through(self.badge, True)
        self.badge.set_text(text or "")
        self.badge.set_visible(bool(text))

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

    def refresh(self):
        pass


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


class ClockTile(Tile):
    live = True

    def __init__(self, spec, on_activate):
        spec = dict(spec, hide_label=True)
        super().__init__(spec, on_activate)

    def build(self):
        self.time = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.time.get_style_context().add_class("small")
            self.time.set_xalign(0.5)
            box = Gtk.Box()
            box.set_center_widget(self.time)
            self.stack.add_named(box, "time")
            return
        self.day = _label("", "tile-title")
        self.date = _label("", "tile-text")
        self.stack.add_named(_frame(self.time, self.day, self.date), "time")
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
        start = datetime.date(now.year, 1, 1)
        left = (datetime.date(now.year, 12, 31) - now.date()).days
        self.week.set_text("week %d" % now.isocalendar()[1])
        self.year.set_text("day %d of %d · %d days left this year"
                           % ((now.date() - start).days + 1, 366 if now.year % 4 == 0 else 365, left))


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


class BatteryTile(Tile):
    live = True

    def build(self):
        self.pct = _label("", "tile-hero", xalign=0.0)
        if self.size == "small":
            self.pct.get_style_context().add_class("small")
            self.pct.set_xalign(0.5)
            box = Gtk.Box()
            box.set_center_widget(self.pct)
            self.stack.add_named(box, "pct")
        else:
            self.state = _label("", "tile-text")
            self.stack.add_named(_frame(self.pct, self.state), "pct")
        if not self.label_text:
            self.label_text = "battery"

    def refresh(self):
        cap, status = _battery()
        if cap is None:
            self.pct.set_text("ac")
            if self.size != "small":
                self.state.set_text("no battery")
            return
        self.pct.set_text("%d" % cap if self.size == "small" else "%d%%" % cap)
        if self.size != "small":
            self.state.set_text(status.replace("not charging", "plugged in"))


class MusicTile(Tile):
    live = True

    def build(self):
        super().build()
        self.title = _label("", "tile-title", wrap=True, lines=2)
        self.artist = _label("", "tile-text")
        self.now = _label("now playing", "tile-text")
        self.playing = _frame(self.now, self.title, self.artist)
        self.stack.add_named(self.playing, "playing")
        if not self.label_text:
            self.label_text = "music"

    def refresh(self):
        if not common.have("playerctl"):
            self.playing.set_visible(False)
            return
        out = common.sh(["playerctl", "metadata", "--format",
                         "{{status}}\t{{title}}\t{{artist}}"], timeout=1)
        parts = out.split("\t")
        if len(parts) == 3 and parts[1]:
            status, title, artist = parts
            self.now.set_text("now playing" if status == "Playing" else status.lower())
            self.title.set_text(title)
            self.artist.set_text(artist)
            self.playing.set_visible(True)
        else:
            self.playing.set_visible(False)
            self.stack.set_visible_child_name("face")


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


class SystemTile(Tile):
    live = True

    def build(self):
        super().build()
        self.cpu = _label("", "tile-title")
        self.mem = _label("", "tile-text")
        self.up = _label("", "tile-text")
        self.stack.add_named(_frame(self.cpu, self.mem, self.up), "stats")
        if not self.label_text:
            self.label_text = "system"

    def refresh(self):
        try:
            with open("/proc/loadavg") as fh:
                load = fh.read().split()[0]
            with open("/proc/uptime") as fh:
                up = int(float(fh.read().split()[0]))
        except (OSError, ValueError, IndexError):
            return
        self.cpu.set_text("load %s" % load)
        mem = _meminfo()
        self.mem.set_text("memory %d%%" % mem if mem is not None else "")
        h, m = divmod(up // 60, 60)
        self.up.set_text("up %dh %02dm" % (h, m))


class CommandTile(Tile):
    """Generic live tile: runs `command` every `interval` seconds and shows
    each output line as a frame (first line large, the rest as text)."""

    live = True

    def build(self):
        super().build()
        self.frames = []
        self._last = 0

    def refresh(self):
        interval = int(self.spec.get("interval", 60))
        now = GLib.get_monotonic_time() / 1e6
        if self._last and now - self._last < interval:
            return
        self._last = now
        cmd = self.spec.get("command")
        if not cmd:
            return
        out = common.sh(["sh", "-c", cmd], timeout=5)
        lines = [ln for ln in out.splitlines() if ln.strip()][:5]
        for f in self.frames:
            self.stack.remove(f)
        self.frames = []
        for ln in lines:
            head, _, rest = ln.partition("\t")
            rows = [_label(head, "tile-title", wrap=True, lines=2)]
            if rest:
                rows.append(_label(rest, "tile-text", wrap=True, lines=3))
            f = _frame(*rows)
            self.frames.append(f)
            self.add_frame(f)
        if self.frames and self.stack.get_visible_child_name() == "face":
            # Show the content straight away; the face comes round on a flip.
            self.stack.set_visible_child_full(self.stack.child_get_property(self.frames[0], "name"),
                                              Gtk.StackTransitionType.NONE)


KINDS = {
    "app": Tile, "action": Tile, "clock": ClockTile, "battery": BatteryTile,
    "music": MusicTile, "system": SystemTile, "command": CommandTile,
}


def make(spec, on_activate):
    cls = KINDS.get(spec.get("type", "app"), Tile)
    return cls(spec, on_activate)


class FlipScheduler:
    """Flips live tiles one or two at a time, never all together: every
    4.5-7 s a random live tile turns over to its next frame."""

    def __init__(self, tiles):
        self.tiles = tiles
        GLib.timeout_add(2000, self._refresh)
        self._refresh()
        self._schedule()

    def _refresh(self):
        for t in self.tiles:
            if t.live:
                t.refresh()
        return True

    def _schedule(self):
        GLib.timeout_add(int(4500 + random.random() * 2500), self._tick)

    def _tick(self):
        cands = [t for t in self.tiles if t.flippable() and t.get_mapped()]
        random.shuffle(cands)
        for t in cands[: 2 if random.random() < 0.25 else 1]:
            t.flip()
        self._schedule()
        return False
