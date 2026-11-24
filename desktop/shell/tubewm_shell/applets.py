"""Applets: the detail views behind live tiles and bar buttons.

Each builder returns an Applet (a Gtk.Box) with a title. Start shows one when
you click a live tile; tube-flyout shows one under the bar. Applets refresh
themselves while they are on screen and stop when they are destroyed.
"""

import calendar as _cal
import datetime
import json
import os
import re
import urllib.parse

from . import common, glyphs, tiles, wm  # common picks the GTK version

from gi.repository import GLib, Gtk, Pango  # noqa: E402


def _net_text():
    name, addr = tiles._network()
    return " · ".join(x for x in (name, addr) if x)


# ── building blocks ────────────────────────────────────────────────────────

def label(text, *classes, xalign=0.0, wrap=False, ellipsize=False, selectable=False):
    lab = Gtk.Label(label=text, xalign=xalign)
    for c in classes:
        lab.get_style_context().add_class(c)
    if wrap:
        lab.set_line_wrap(True)
        lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    lab.set_selectable(selectable)
    return lab


def button(text=None, cb=None, *classes, glyph=None, tooltip=None, size=18):
    b = Gtk.Button()
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("applet-button")
    for c in classes:
        b.get_style_context().add_class(c)
    if glyph and text:
        box = Gtk.Box(spacing=10)
        box.pack_start(glyphs.Glyph(glyph, size), False, False, 0)
        box.pack_start(label(text), False, False, 0)
        b.add(box)
    elif glyph:
        b.add(glyphs.Glyph(glyph, size))
        b.get_style_context().add_class("icon-button")
    else:
        b.add(label(text, xalign=0.5))
    if tooltip:
        b.set_tooltip_text(tooltip)
    if cb:
        b.connect("clicked", lambda *_: cb())
    return b


def section(text):
    return label(text, "applet-section")


def bar(fraction, *classes):
    lb = Gtk.LevelBar()
    lb.set_min_value(0)
    lb.set_max_value(1)
    lb.set_value(max(0.0, min(1.0, fraction)))
    lb.get_style_context().add_class("applet-level")
    for c in classes:
        lb.get_style_context().add_class(c)
    for name in ("low", "high", "full"):
        lb.remove_offset_value(name)
    return lb


def slider(value, on_change, lo=0, hi=100):
    adj = Gtk.Adjustment(value=value, lower=lo, upper=hi, step_increment=1, page_increment=10)
    sc = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
    sc.set_draw_value(False)
    sc.set_hexpand(True)
    sc.get_style_context().add_class("applet-scale")
    pending = {"id": None}

    def changed(*_):
        # Debounce: drags fire many events, the tools are slow-ish.
        if pending["id"]:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(60, lambda: on_change(int(adj.get_value())) or
                                         pending.update(id=None) or False)
    adj.connect("value-changed", changed)
    return sc


def clear(box):
    for c in box.get_children():
        box.remove(c)
        c.destroy()


class Applet(Gtk.Box):
    """A titled detail view. Subclasses fill self.body and override update()."""

    title = ""
    every = 0       # seconds between update() calls; 0 means once
    closes = None   # called when an action means the whole surface should close

    def __init__(self, title=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.get_style_context().add_class("applet")
        if title:
            self.title = title
        self.body = self
        self._timer = None
        self.build()
        self.update()
        if self.every:
            self._timer = GLib.timeout_add_seconds(self.every, self._tick)
        self.connect("destroy", self._stop)
        self.show_all()

    def _tick(self):
        self.update()
        return True

    def _stop(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def build(self):
        pass

    def update(self):
        pass

    def done(self):
        """An action finished: close start or the flyout."""
        if self.closes:
            self.closes()


def run(cmd, timeout=3):
    return common.sh(cmd, timeout=timeout)


def spawn(cmd):
    common.run_detached(cmd)


# ── time ───────────────────────────────────────────────────────────────────

class Calendar(Applet):
    title = "calendar"

    def build(self):
        today = datetime.date.today()
        self.month = today.replace(day=1)
        head = Gtk.Box(spacing=6)
        self.caption = label("", "applet-heading")
        head.pack_start(self.caption, True, True, 0)
        head.pack_start(button(glyph="left", cb=lambda: self.shift(-1), tooltip="previous month"), False, False, 0)
        head.pack_start(button(glyph="right", cb=lambda: self.shift(1), tooltip="next month"), False, False, 0)
        self.pack_start(head, False, False, 0)
        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=2, column_spacing=2)
        self.grid.get_style_context().add_class("month")
        self.pack_start(self.grid, False, False, 0)

    def shift(self, n):
        y, m = self.month.year, self.month.month + n
        while m < 1:
            y, m = y - 1, m + 12
        while m > 12:
            y, m = y + 1, m - 12
        self.month = datetime.date(y, m, 1)
        self.update()

    def update(self):
        clear(self.grid)
        self.caption.set_text(self.month.strftime("%B %Y").lower())
        for i, d in enumerate(["mo", "tu", "we", "th", "fr", "sa", "su"]):
            self.grid.attach(label(d, "month-dow", xalign=0.5), i, 0, 1, 1)
        today = datetime.date.today()
        weeks = _cal.Calendar(firstweekday=0).monthdatescalendar(self.month.year, self.month.month)
        for r, week in enumerate(weeks, 1):
            for c, day in enumerate(week):
                cls = ["month-day"]
                if day.month != self.month.month:
                    cls.append("other")
                if day == today:
                    cls.append("today")
                self.grid.attach(label(str(day.day), *cls, xalign=0.5), c, r, 1, 1)
        self.grid.show_all()


class Clock(Applet):
    title = "clock"
    every = 1

    def build(self):
        self.time = label("", "applet-huge")
        self.date = label("", "applet-heading")
        self.pack_start(self.time, False, False, 0)
        self.pack_start(self.date, False, False, 0)
        self.pack_start(Calendar(), False, False, 8)

    def update(self):
        now = datetime.datetime.now()
        self.time.set_text(now.strftime("%H:%M:%S"))
        self.date.set_text(now.strftime("%A %-d %B").lower())


# ── outside world ──────────────────────────────────────────────────────────

class Weather(Applet):
    title = "weather"

    def __init__(self, location=""):
        self.location = location
        super().__init__()

    def build(self):
        self.status = label("looking outside…", "applet-dim")
        self.pack_start(self.status, False, False, 0)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.pack_start(self.box, False, False, 0)

    def update(self):
        if not common.have("curl"):
            self.status.set_text("weather needs curl")
            return
        loc = urllib.parse.quote(self.location.strip())
        tiles.run_async(["curl", "-fsS", "--max-time", "12", "https://wttr.in/%s?format=j1" % loc], self._got)

    def _got(self, out):
        try:
            data = json.loads(out)
            now = data["current_condition"][0]
        except (ValueError, KeyError, IndexError):
            self.status.set_text("couldn't reach wttr.in; check your connection")
            return
        self.status.hide()
        clear(self.box)
        area = (data.get("nearest_area") or [{}])[0]
        place = ((area.get("areaName") or [{}])[0].get("value") or "").lower()
        top = Gtk.Box(spacing=18)
        top.pack_start(label("%s°" % now.get("temp_C", "?"), "applet-huge"), False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.set_valign(Gtk.Align.CENTER)
        right.pack_start(label(((now.get("weatherDesc") or [{}])[0].get("value") or "").lower(),
                               "applet-heading"), False, False, 0)
        right.pack_start(label(place, "applet-dim"), False, False, 0)
        top.pack_start(right, False, False, 0)
        self.box.pack_start(top, False, False, 0)
        facts = "feels like %s°   humidity %s%%   wind %s km/h" % (
            now.get("FeelsLikeC", "?"), now.get("humidity", "?"), now.get("windspeedKmph", "?"))
        self.box.pack_start(label(facts, "applet-text"), False, False, 0)
        days = Gtk.Box(spacing=10, homogeneous=True)
        for d in data.get("weather", [])[:3]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.get_style_context().add_class("applet-card")
            try:
                name = datetime.date.fromisoformat(d["date"]).strftime("%A").lower()
                desc = d["hourly"][len(d["hourly"]) // 2]["weatherDesc"][0]["value"].lower()
            except (KeyError, ValueError, IndexError):
                name, desc = d.get("date", ""), ""
            card.pack_start(label(name, "applet-strong"), False, False, 0)
            card.pack_start(label("%s° / %s°" % (d.get("maxtempC", "?"), d.get("mintempC", "?")),
                                  "applet-heading"), False, False, 0)
            card.pack_start(label(desc, "applet-dim", wrap=True), False, False, 0)
            days.pack_start(card, True, True, 0)
        self.box.pack_start(days, False, False, 0)
        self.box.show_all()


class Music(Applet):
    title = "music"
    every = 1

    def build(self):
        self.art = Gtk.Image()
        self.art.set_halign(Gtk.Align.CENTER)
        self.pack_start(self.art, False, False, 0)
        self.song = label("", "applet-heading", xalign=0.5, wrap=True)
        self.artist = label("", "applet-dim", xalign=0.5, wrap=True)
        for lab in (self.song, self.artist):
            lab.set_justify(Gtk.Justification.CENTER)
        self.pack_start(self.song, False, False, 0)
        self.pack_start(self.artist, False, False, 0)
        self.pos = bar(0)
        self.pack_start(self.pos, False, False, 0)
        row = Gtk.Box(spacing=18)
        prev = button(glyph="prev", cb=lambda: self.ctl("previous"), tooltip="previous", size=20)
        self.play = button(glyph="play", cb=lambda: self.ctl("play-pause"), tooltip="play / pause", size=24)
        nxt = button(glyph="next", cb=lambda: self.ctl("next"), tooltip="next", size=20)
        for b in (prev, self.play, nxt):
            b.get_style_context().add_class("transport")
            b.set_valign(Gtk.Align.CENTER)
            row.pack_start(b, False, False, 0)
        self.play.get_style_context().add_class("main")
        row.set_halign(Gtk.Align.CENTER)
        self.controls = row
        self.pack_start(row, False, False, 0)
        self.controls.set_no_show_all(True)
        row.show_all()
        self._art = None

    def ctl(self, what):
        run(["playerctl", what])
        GLib.timeout_add(250, lambda: self.update() or False)

    def update(self):
        if not common.have("playerctl"):
            self.song.set_text("music controls need playerctl")
            return
        meta = run(["playerctl", "metadata", "--format",
                    "{{status}}\t{{title}}\t{{artist}}\t{{album}}\t{{mpris:artUrl}}\t{{position}}\t{{mpris:length}}"])
        parts = (meta.split("\t") + [""] * 7)[:7]
        status, title, artist, album, art, pos, length = parts
        if not title:
            self.song.set_text("nothing playing")
            self.artist.set_text("start some music and it shows up here")
            self.pos.hide()
            self.art.hide()
            self.controls.hide()
            return
        self.controls.show()
        self.song.set_text(title.lower())
        self.artist.set_text(" · ".join(x for x in (artist, album) if x).lower())
        try:
            self.pos.set_value(int(pos) / max(1, int(length)))
            self.pos.show()
        except ValueError:
            self.pos.hide()
        g = self.play.get_child()
        g.name = "pause" if status == "Playing" else "play"
        g.queue_draw()
        if art != self._art:
            self._art = art
            path = urllib.parse.unquote(urllib.parse.urlparse(art).path) if art.startswith("file://") else None
            pb = tiles.cover_pixbuf(path, 220, 220) if path else None
            if pb:
                self.art.set_from_pixbuf(pb)
                self.art.show()
            else:
                self.art.hide()


class Photos(Applet):
    title = "photos"

    def __init__(self, folder="~/Pictures"):
        self.folder = os.path.expanduser(folder or "~/Pictures")
        super().__init__()

    def build(self):
        self.flow = Gtk.FlowBox(max_children_per_line=4, min_children_per_line=2,
                                selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6)
        self.pack_start(self.flow, False, False, 0)
        self.pack_start(button("open the folder", lambda: (spawn("xdg-open %s" % GLib.shell_quote(self.folder)),
                                                           self.done()), glyph="folder"), False, False, 0)

    def update(self):
        found = []
        for root, dirs, files in os.walk(self.folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.lower().endswith(tiles.IMAGE_EXT):
                    p = os.path.join(root, f)
                    try:
                        found.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
            if len(found) > 400:
                break
        found.sort(reverse=True)
        if not found:
            self.pack_start(label("no pictures in %s yet" % self.folder.replace(common.HOME, "~"), "applet-dim"),
                            False, False, 0)
        for _, p in found[:24]:
            pb = tiles.cover_pixbuf(p, 150, 110)
            if pb is None:
                continue
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("photo-thumb")
            b.add(Gtk.Image.new_from_pixbuf(pb))
            b.set_tooltip_text(os.path.basename(p))
            b.connect("clicked", lambda _b, p=p: (spawn("xdg-open %s" % GLib.shell_quote(p)), self.done()))
            self.flow.add(b)
        self.flow.show_all()


# ── your stuff ─────────────────────────────────────────────────────────────

class Recent(Applet):
    title = "recent files"

    def build(self):
        files = tiles._recent_files(limit=20)
        if not files:
            self.pack_start(label("files you open show up here", "applet-dim"), False, False, 0)
        for p in files:
            row = button(cb=lambda p=p: (spawn("xdg-open %s" % GLib.shell_quote(p)), self.done()))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(label(os.path.basename(p), "applet-strong", ellipsize=True), False, False, 0)
            box.pack_start(label(os.path.dirname(p).replace(common.HOME, "~"), "applet-dim", ellipsize=True),
                           False, False, 0)
            row.remove(row.get_child())
            row.add(box)
            row.get_style_context().add_class("applet-row")
            self.pack_start(row, False, False, 0)


HISTORY_MARK = os.path.join(common.RUNTIME, "tubewm-notifications-cleared")


def notification_history():
    out = run(["makoctl", "history"])
    items = []
    try:
        data = json.loads(out)
        for n in (data.get("data") or [[]])[0]:
            items.append({"id": (n.get("id") or {}).get("data", 0),
                          "app": (n.get("app-name") or {}).get("data", ""),
                          "summary": (n.get("summary") or {}).get("data", ""),
                          "body": (n.get("body") or {}).get("data", "")})
    except (ValueError, AttributeError, IndexError):
        for line in out.splitlines():  # mako >= 1.9 prints text
            m = re.match(r"Notification (\d+): (.*)", line)
            if m:
                items.append({"id": int(m.group(1)), "app": "", "summary": m.group(2), "body": ""})
            elif items and line.strip().startswith("App name:"):
                items[-1]["app"] = line.split(":", 1)[1].strip()
    try:
        with open(HISTORY_MARK) as fh:
            cleared = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        cleared = 0
    return [n for n in items if n["id"] > cleared]


class Notifications(Applet):
    title = "notifications"

    def build(self):
        head = Gtk.Box(spacing=8)
        self.dnd = Gtk.ToggleButton(label="do not disturb")
        self.dnd.get_style_context().add_class("applet-toggle")
        self.dnd.set_active("do-not-disturb" in run(["makoctl", "mode"]))
        self.dnd.connect("toggled", lambda b: run(["makoctl", "mode", "-a" if b.get_active() else "-r",
                                                   "do-not-disturb"]))
        head.pack_start(self.dnd, False, False, 0)
        head.pack_end(button("clear all", self.clear_all), False, False, 0)
        self.pack_start(head, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pack_start(self.list, False, False, 0)

    def clear_all(self):
        items = notification_history()
        top = max([n["id"] for n in items] + [0])
        run(["makoctl", "dismiss", "--all"])
        try:
            with open(HISTORY_MARK, "w") as fh:
                fh.write(str(top))
        except OSError:
            pass
        self.update()

    def update(self):
        clear(self.list)
        items = notification_history()
        if not items:
            self.list.pack_start(label("you're all caught up", "applet-dim"), False, False, 0)
        for n in items[:30]:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            card.get_style_context().add_class("applet-card")
            if n["app"]:
                card.pack_start(label(n["app"].lower(), "applet-dim"), False, False, 0)
            card.pack_start(label(n["summary"], "applet-strong", wrap=True), False, False, 0)
            if n["body"]:
                card.pack_start(label(n["body"], "applet-text", wrap=True), False, False, 0)
            self.list.pack_start(card, False, False, 0)
        self.list.show_all()


class Windows(Applet):
    title = "open windows"
    every = 2

    def build(self):
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.list, False, False, 0)
        self._sig = None

    def update(self):
        wins = wm.windows()
        sig = tuple((w["id"], w.label, w.get("workspace")) for w in wins)
        if sig == self._sig:
            return
        self._sig = sig
        clear(self.list)
        if not wins:
            self.list.pack_start(label("no windows open", "applet-dim"), False, False, 0)
        names = wm.desktop_names()
        for w in wins:
            row = Gtk.Box(spacing=6)
            go = button(cb=lambda w=w: (wm.focus(w["id"]), self.done()))
            go.remove(go.get_child())
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.pack_start(label(w.label, "applet-strong", ellipsize=True), False, False, 0)
            ws = w.get("workspace", 0)
            where = names[ws] if ws < len(names) else "pivot %d" % (ws + 1)
            box.pack_start(label("%s · %s%s" % ((w.get("app_id") or "").lower(), where,
                                                " · minimised" if w.get("minimized") else ""),
                                 "applet-dim", ellipsize=True), False, False, 0)
            go.add(box)
            go.get_style_context().add_class("applet-row")
            row.pack_start(go, True, True, 0)
            row.pack_end(button(glyph="close", cb=lambda w=w: (wm.close(w["id"]), self.update()),
                                tooltip="close"), False, False, 0)
            self.list.pack_start(row, False, False, 0)
        self.list.show_all()


# ── this machine ───────────────────────────────────────────────────────────

def battery_info():
    """(percent, state, time text) from upower, or from sysfs."""
    dev = next((d for d in run(["upower", "-e"]).splitlines() if "BAT" in d), None) if common.have("upower") else None
    if dev:
        info = run(["upower", "-i", dev])
        pct = re.search(r"percentage:\s*([\d.]+)%", info)
        state = re.search(r"state:\s*(\S+)", info)
        tleft = re.search(r"time to (empty|full):\s*(.+)", info)
        if pct:
            t = ""
            if tleft:
                t = "%s until %s" % (tleft.group(2).strip(), tleft.group(1))
            return int(float(pct.group(1))), (state.group(1) if state else ""), t
    cap, status = tiles._battery()
    if cap is None:
        return None, "", ""
    return cap, status, ""


def profiles():
    if not common.have("powerprofilesctl"):
        return [], None
    out = run(["powerprofilesctl", "list"])
    names = re.findall(r"^\s*\*?\s*([a-z-]+):\s*$", out, re.M)
    cur = run(["powerprofilesctl", "get"])
    return names, cur


def brightness():
    if not common.have("brightnessctl"):
        return None
    try:
        cur, mx = int(run(["brightnessctl", "g"])), int(run(["brightnessctl", "m"]))
        return round(100 * cur / max(1, mx))
    except ValueError:
        return None


class Power(Applet):
    title = "power"
    every = 20

    def build(self):
        self.pct = label("", "applet-huge")
        self.state = label("", "applet-heading")
        self.time = label("", "applet-dim")
        for w in (self.pct, self.state, self.time):
            self.pack_start(w, False, False, 0)
        self.level = bar(0, "battery")
        self.pack_start(self.level, False, False, 0)
        names, cur = profiles()
        if names:
            self.pack_start(section("power mode"), False, False, 4)
            row = Gtk.Box(spacing=6, homogeneous=True)
            first = None
            nice = {"power-saver": "battery saver", "balanced": "balanced", "performance": "performance"}
            for n in names[::-1] if names[0] == "performance" else names:
                rb = Gtk.RadioButton.new_with_label_from_widget(first, nice.get(n, n))
                rb.set_mode(False)
                rb.get_style_context().add_class("applet-toggle")
                first = first or rb
                rb.set_active(n == cur)
                rb.connect("toggled", lambda b, n=n: b.get_active() and run(["powerprofilesctl", "set", n]))
                row.pack_start(rb, True, True, 0)
            self.pack_start(row, False, False, 0)
        b = brightness()
        if b is not None:
            self.pack_start(section("brightness"), False, False, 4)
            line = Gtk.Box(spacing=10)
            line.pack_start(glyphs.Glyph("brightness", 20), False, False, 0)
            line.pack_start(slider(b, lambda v: run(["brightnessctl", "-q", "set", "%d%%" % max(1, v)])),
                            True, True, 0)
            self.pack_start(line, False, False, 0)

    def update(self):
        pct, state, t = battery_info()
        if pct is None:
            self.pct.set_text("plugged in")
            self.state.set_text("no battery: running on mains power")
            self.time.set_text("")
            self.level.hide()
            return
        self.pct.set_text("%d%%" % pct)
        self.state.set_text({"discharging": "on battery", "charging": "charging",
                             "fully-charged": "fully charged", "pending-charge": "plugged in, not charging"}
                            .get(state.lower(), state.lower()))
        self.time.set_text(t)
        self.level.set_value(pct / 100)
        ctx = self.level.get_style_context()
        (ctx.add_class if pct <= 15 else ctx.remove_class)("low")


def volume():
    """(percent, muted) of the default output."""
    out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]) if common.have("wpctl") else ""
    m = re.search(r"([\d.]+)", out)
    if m:
        return round(float(m.group(1)) * 100), "MUTED" in out
    out = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    m = re.search(r"(\d+)%", out)
    muted = "yes" in run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    return (int(m.group(1)) if m else None), muted


def set_volume(v):
    if common.have("wpctl"):
        run(["wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "%d%%" % v])
    else:
        run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "%d%%" % v])


def sinks():
    """[(name, description, is_default)] from pactl (works on PipeWire too)."""
    if not common.have("pactl"):
        return []
    default = run(["pactl", "get-default-sink"])
    out, cur = [], {}
    for line in run(["pactl", "list", "sinks"]).splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            cur = {"name": line.split(":", 1)[1].strip()}
            out.append(cur)
        elif line.startswith("Description:") and cur:
            cur["desc"] = line.split(":", 1)[1].strip()
    return [(s["name"], s.get("desc", s["name"]), s["name"] == default) for s in out]


def audio_devices(kind="output"):
    """[(name, description, is_default)] of the sound outputs (speakers,
    headphones) or inputs (microphones). An input's "monitor of ..." twin
    isn't a microphone, so it is left out."""
    if not common.have("pactl"):
        return []
    what = "sinks" if kind == "output" else "sources"
    default = run(["pactl", "get-default-" + what[:-1]])
    out, cur = [], {}
    for line in run(["pactl", "list", what]).splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            cur = {"name": line.split(":", 1)[1].strip()}
            out.append(cur)
        elif line.startswith("Description:") and cur:
            cur["desc"] = line.split(":", 1)[1].strip()
    out = [d for d in out if not d["name"].endswith(".monitor")]
    return [(d["name"], d.get("desc", d["name"]), d["name"] == default) for d in out]


def set_audio_device(kind, name):
    """Make `name` the default output or input; what's playing follows it."""
    run(["pactl", "set-default-" + ("sink" if kind == "output" else "source"), name])


class Volume(Applet):
    title = "sound"

    def build(self):
        v, muted = volume()
        line = Gtk.Box(spacing=10)
        self.mute = button(glyph="sound", cb=self.toggle_mute, tooltip="mute", size=22)
        line.pack_start(self.mute, False, False, 0)
        line.pack_start(slider(v or 0, set_volume, hi=150 if (v or 0) > 100 else 100), True, True, 0)
        self.pct = label("", "applet-strong")
        line.pack_start(self.pct, False, False, 0)
        self.pack_start(line, False, False, 0)
        outs = sinks()
        if len(outs) > 1:
            self.pack_start(section("play sound through"), False, False, 4)
            first = None
            for name, desc, default in outs:
                rb = Gtk.RadioButton.new_with_label_from_widget(first, desc.lower())
                first = first or rb
                rb.get_style_context().add_class("applet-radio")
                rb.set_active(default)
                rb.connect("toggled", lambda b, n=name: b.get_active() and run(["pactl", "set-default-sink", n]))
                self.pack_start(rb, False, False, 0)
        if common.have("pavucontrol"):
            self.pack_start(button("more sound settings", lambda: (spawn("pavucontrol"), self.done()),
                                   glyph="settings"), False, False, 6)

    def toggle_mute(self):
        if common.have("wpctl"):
            run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
        else:
            run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        self.update()

    def update(self):
        v, muted = volume()
        self.pct.set_text("muted" if muted else ("%d%%" % v if v is not None else ""))
        ctx = self.mute.get_style_context()
        (ctx.add_class if muted else ctx.remove_class)("off")


class Network(Applet):
    title = "network"

    def build(self):
        self.now = label("", "applet-heading")
        self.pack_start(self.now, False, False, 0)
        self.toggle = Gtk.Switch()
        line = Gtk.Box(spacing=10)
        line.pack_start(label("wi-fi", "applet-strong"), True, True, 0)
        line.pack_start(self.toggle, False, False, 0)
        self.pack_start(line, False, False, 0)
        self.toggle.connect("state-set", self.set_wifi)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.pack_start(self.list, False, False, 0)
        if common.have("nm-connection-editor"):
            self.pack_end(button("network settings", lambda: (spawn("nm-connection-editor"), self.done()),
                                 glyph="settings"), False, False, 6)

    def set_wifi(self, _sw, state):
        run(["nmcli", "radio", "wifi", "on" if state else "off"])
        GLib.timeout_add_seconds(2, lambda: self.update() or False)
        return False

    def update(self):
        clear(self.list)
        if not common.have("nmcli"):
            self.now.set_text(_net_text() or "no network tools (install NetworkManager)")
            self.toggle.set_sensitive(False)
            return
        self.now.set_text(_net_text() or "not connected")
        on = run(["nmcli", "radio", "wifi"]) == "enabled"
        self.toggle.handler_block_by_func(self.set_wifi)
        self.toggle.set_active(on)
        self.toggle.handler_unblock_by_func(self.set_wifi)
        if not on:
            return
        tiles.run_async(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], self._got)

    def _got(self, out):
        seen = set()
        for line in out.splitlines():
            parts = re.split(r"(?<!\\):", line)
            if len(parts) < 4:
                continue
            inuse, ssid, signal, sec = parts[0], parts[1].replace("\\:", ":"), parts[2], parts[3]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            self.list.pack_start(self._row(ssid, int(signal or 0), sec, inuse == "*"), False, False, 0)
            if len(seen) >= 12:
                break
        self.list.show_all()

    def _row(self, ssid, signal, sec, active):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        b = button(cb=lambda: self.connect_to(ssid, sec, box))
        b.remove(b.get_child())
        inner = Gtk.Box(spacing=10)
        inner.pack_start(label(ssid, "applet-strong", ellipsize=True), True, True, 0)
        inner.pack_start(label(("connected · " if active else "") + ("locked · " if sec and sec != "--" else "")
                               + "%d%%" % signal, "applet-dim"), False, False, 0)
        b.add(inner)
        b.get_style_context().add_class("applet-row")
        if active:
            b.get_style_context().add_class("active")
        box.pack_start(b, False, False, 0)
        return box

    def connect_to(self, ssid, sec, box):
        known = ssid in run(["nmcli", "-t", "-f", "NAME", "connection", "show"]).splitlines()
        if known or not sec or sec == "--":
            tiles.run_async(["nmcli", "dev", "wifi", "connect", ssid], lambda _o: self.update(), timeout=40)
            self.now.set_text("connecting to %s…" % ssid)
            return
        if len(box.get_children()) > 1:
            return
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text("password for %s" % ssid)
        entry.get_style_context().add_class("field")
        entry.connect("activate", lambda e: (
            tiles.run_async(["nmcli", "dev", "wifi", "connect", ssid, "password", e.get_text()],
                            lambda _o: self.update(), timeout=40),
            self.now.set_text("connecting to %s…" % ssid)))
        box.pack_start(entry, False, False, 4)
        entry.show()
        entry.grab_focus()


class System(Applet):
    title = "system"
    every = 2

    def build(self):
        self._prev = tiles._cpu_times()
        self.cpu_l, self.cpu = label("", "applet-strong"), bar(0)
        self.mem_l, self.mem = label("", "applet-strong"), bar(0)
        for w in (self.cpu_l, self.cpu, self.mem_l, self.mem):
            self.pack_start(w, False, False, 0)
        self.up = label("", "applet-dim")
        self.pack_start(self.up, False, False, 0)
        self.pack_start(section("busiest"), False, False, 4)
        self.procs = label("", "applet-mono")
        self.pack_start(self.procs, False, False, 0)
        tool = "btop" if common.have("btop") else "htop" if common.have("htop") else "top"
        self.pack_start(button("open %s" % tool, lambda: (spawn("foot -e %s" % tool), self.done()),
                               glyph="system"), False, False, 6)

    def update(self):
        cur = tiles._cpu_times()
        pct = 0
        if cur and self._prev:
            total = cur[0] - self._prev[0]   # _cpu_times() is (total, idle)
            idle = cur[1] - self._prev[1]
            pct = 100 * (1 - idle / total) if total > 0 else 0
        self._prev = cur
        self.cpu_l.set_text("processor %d%%" % pct)
        self.cpu.set_value(pct / 100)
        mem = tiles._meminfo()
        self.mem_l.set_text("memory %s%%" % (mem if mem is not None else "?"))
        self.mem.set_value((mem or 0) / 100)
        try:
            with open("/proc/uptime") as fh:
                secs = int(float(fh.read().split()[0]))
            self.up.set_text("up %d hours %d minutes" % (secs // 3600, secs % 3600 // 60))
        except (OSError, ValueError):
            pass
        out = run(["ps", "-eo", "comm,%cpu,%mem", "--sort=-%cpu", "--no-headers"])
        rows = ["%-18s %5s%% processor %5s%% memory" % tuple((l.split() + ["", "", ""])[:3])
                for l in out.splitlines()[:6]]
        self.procs.set_text("\n".join(rows))


class Storage(Applet):
    title = "storage"

    def build(self):
        seen = set()
        for line in run(["df", "-P", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay",
                         "-x", "efivarfs"]).splitlines()[1:]:
            parts = line.split()
            if len(parts) < 6 or parts[0] in seen or not parts[0].startswith("/dev"):
                continue
            seen.add(parts[0])
            size, used, avail, mount = int(parts[1]) * 1024, int(parts[2]) * 1024, int(parts[3]) * 1024, parts[5]
            name = "system" if mount == "/" else "home" if mount == "/home" else os.path.basename(mount) or mount
            b = button(cb=lambda m=mount: (spawn("xdg-open %s" % GLib.shell_quote(m)), self.done()))
            b.remove(b.get_child())
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(label("%s   %s free of %s" % (name, _size(avail), _size(size)), "applet-strong"),
                           False, False, 0)
            box.pack_start(bar(used / max(1, used + avail)), False, False, 0)
            box.pack_start(label(mount, "applet-dim"), False, False, 0)
            b.add(box)
            b.get_style_context().add_class("applet-row")
            self.pack_start(b, False, False, 0)


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return ("%.0f %s" if n >= 10 or unit == "B" else "%.1f %s") % (n, unit)
        n /= 1000.0


class Command(Applet):
    every = 30

    def __init__(self, command="", title="command"):
        self.command = command
        super().__init__(title)

    def build(self):
        self.out = label("", "applet-mono", selectable=True, wrap=True)
        self.pack_start(self.out, False, False, 0)

    def update(self):
        tiles.run_async(["sh", "-c", self.command], lambda o: self.out.set_text(o.rstrip() or "(no output)"))


# ── the window menu ────────────────────────────────────────────────────────

class WindowMenu(Applet):
    """What you can do to the focused window: on the bar's window title."""
    title = "window"

    def __init__(self, win=None):
        self.win = win or wm.focused()
        super().__init__(title=(self.win.label if self.win else "no window").lower())

    def build(self):
        if not self.win:
            self.pack_start(label("click a window first", "applet-dim"), False, False, 0)
            return
        wid = self.win["id"]
        grid = Gtk.Grid(column_homogeneous=True, column_spacing=6, row_spacing=6)
        acts = [
            ("snap-left", "left half", lambda: wm.snap(wid, "left")),
            ("maximize", "fill", lambda: wm.snap(wid, "max")),
            ("snap-right", "right half", lambda: wm.snap(wid, "right")),
            ("minimize", "minimise", lambda: wm.minimize(wid)),
            ("up", "keep on top", lambda: wm.set_always_on_top(wid, True)),
            ("close", "close", lambda: wm.close(wid)),
        ]
        for i, (g, text, fn) in enumerate(acts):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("applet-tile")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.pack_start(glyphs.Glyph(g, 26), False, False, 0)
            box.pack_start(label(text, xalign=0.5), False, False, 0)
            b.add(box)
            b.connect("clicked", lambda _b, fn=fn: (fn(), self.done()))
            grid.attach(b, i % 3, i // 3, 1, 1)
        self.pack_start(grid, False, False, 0)
        names = wm.desktop_names()
        here = self.win.get("workspace", 0)
        others = [(i, n) for i, n in enumerate(names) if i != here]
        if others:
            self.pack_start(section("move to"), False, False, 4)
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                               column_spacing=6, row_spacing=6)
            for i, n in others:
                flow.add(button(n, lambda i=i: (wm.send_to_pivot(wid, i, names), self.done())))
            self.pack_start(flow, False, False, 0)



BUILDERS = {
    "clock": lambda spec: Clock(),
    "calendar": lambda spec: Calendar(),
    "weather": lambda spec: Weather(spec.get("location", "")),
    "music": lambda spec: Music(),
    "photos": lambda spec: Photos(spec.get("folder", "~/Pictures")),
    "recent": lambda spec: Recent(),
    "messages": lambda spec: Notifications(),
    "notifications": lambda spec: Notifications(),
    "windows": lambda spec: Windows(),
    "battery": lambda spec: Power(),
    "power": lambda spec: Power(),
    "system": lambda spec: System(),
    "disk": lambda spec: Storage(),
    "storage": lambda spec: Storage(),
    "network": lambda spec: Network(),
    "volume": lambda spec: Volume(),
    "sound": lambda spec: Volume(),
    "command": lambda spec: Command(spec.get("command", ""), spec.get("label") or "command"),
    "window": lambda spec: WindowMenu(),
}


def build(kind, spec=None):
    fn = BUILDERS.get(kind)
    return fn(spec or {}) if fn else None
