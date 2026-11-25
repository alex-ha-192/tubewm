"""tube-strip: the thin strip along the top of the screen.

It is always there. On the left, the start square and the desktops in light
type: the one you're on in white. Click one to go there, right-click it for
its menu, + for a new one. On the right, sound, network, bluetooth (while
it's on) and battery as small marks, and the time; click any of them for
everything else (sound, brightness, wi-fi, bluetooth, battery and power
mode, notifications, power).

Between them is the handle for the window you're in. Point at it and the
window's name appears. Drag it down to a side of the screen for half, into
a corner for a quarter, or let go in the middle to fill the screen; an
accent outline shows where the window will go. Drag it along the strip onto
a desktop's name (or +) to move the window there; let go anywhere else on
the strip to leave it be. Right-click it for the same as a menu. (Each
window's own title strip has its close button.)

When an app goes full screen (F11, a video's full-screen button) the strip
slides up out of the way, and back when it leaves. It slides without ever
changing the room it keeps at the top of the screen: if that room changed,
Wayfire's grid would put every snapped window back in its slot, and a window
that had just gone full screen would drop straight out of it again.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

from . import applets, bluetooth, common, desktops, levels, marks, wm

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

HEIGHT = 40
ICON = 18            # logical px; drawn at the screen's scale so it stays sharp
START_ICON = 18      # px: the start mark, a little cluster of tiles in the accent colour
HIDE_MS = 220       # the slide out of the way for full screen
STATUS_EVERY = 5     # seconds between looks at sound, network and battery
ICON_DIR = os.path.normpath(os.path.join(common.SHELL_DIR, "..", "templates", "waybar", "icons"))
DRAG_START = 12      # px the pointer moves before a press becomes a drag
EDGE = 0.2           # the outer fifth of the screen on each side snaps there


def _bin(name):
    return os.path.join(common.BIN_DIR, name)


def spawn(*argv):
    subprocess.Popen([_bin(argv[0])] + list(argv[1:]), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zone_for(x, y, w, h):
    """Where a window dropped at (x, y) on a w x h screen goes."""
    if x < w * EDGE:
        side = "left"
    elif x > w * (1 - EDGE):
        side = "right"
    else:
        return "max"
    if y < h / 3:
        return "top-" + side
    if y > h * 2 / 3:
        return "bottom-" + side
    return side


def zone_rect(zone, w, h, top):
    """The screen area a zone covers, below the strip."""
    h2 = h - top
    hw, hh = w // 2, h2 // 2
    return {
        "max": (0, top, w, h2),
        "left": (0, top, hw, h2), "right": (hw, top, w - hw, h2),
        "top-left": (0, top, hw, hh), "top-right": (hw, top, w - hw, hh),
        "bottom-left": (0, top + hh, hw, h2 - hh), "bottom-right": (hw, top + hh, w - hw, h2 - hh),
    }[zone]


def icon_surface(name, pal, scale, widget, svg=None):
    """One of tubewm's line icons, in the palette's colours, drawn for this
    screen's scale. Pass svg to draw that instead of the named file."""
    try:
        if svg is None:
            with open(os.path.join(ICON_DIR, name + ".svg")) as fh:
                svg = re.sub(r"@([A-Z_]+)@", lambda m: pal.get(m.group(1), pal.get("FG", "#FFFFFF")),
                             fh.read())
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.set_size(ICON * scale, ICON * scale)
        loader.write(svg.encode())
        loader.close()
        return Gdk.cairo_surface_create_from_pixbuf(loader.get_pixbuf(), scale, widget.get_window())
    except (OSError, GLib.Error):
        return None


class Preview:
    """The accent outline that shows where a dragged window will land."""

    def __init__(self):
        win = common.make_layer_window("snap-preview", transparent=True, layer="overlay")
        if common.GtkLayerShell is not None and common.GtkLayerShell.is_supported():
            common.GtkLayerShell.set_exclusive_zone(win, -1)
            common.GtkLayerShell.set_keyboard_interactivity(win, False)
        win.disconnect_by_func(Gtk.main_quit)  # closing the preview isn't quitting
        area = Gtk.DrawingArea()
        area.connect("draw", self.draw)
        win.add(area)
        win.connect("realize", lambda w: w.input_shape_combine_region(_empty_region()))
        self.win, self.area, self.rect = win, area, None
        self.pal = common.load_palette()

    def show(self, rect):
        if rect != self.rect:
            self.rect = rect
            self.area.queue_draw()
        if not self.win.get_visible():
            self.win.show_all()
            self.win.input_shape_combine_region(_empty_region())

    def hide(self):
        self.rect = None
        self.win.hide()

    def draw(self, _w, cr):
        import cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if not self.rect:
            return False
        x, y, w, h = self.rect
        r, g, b = (int(self.pal["ACCENT"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        cr.set_source_rgba(r, g, b, 0.28)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgba(r, g, b, 1)
        cr.set_line_width(4)
        cr.rectangle(x + 2, y + 2, w - 4, h - 4)
        cr.stroke()
        return False


def _empty_region():
    import cairo
    return cairo.Region()


class Strip:
    def __init__(self):
        common.apply_css()
        win = Gtk.Window()
        win.set_title("tube-strip")
        win.get_style_context().add_class("tube")
        win.get_style_context().add_class("strip")
        # See-through, so that out of the way it can leave one invisible row
        # on screen (see slide()); the row of controls paints the strip.
        visual = win.get_screen().get_rgba_visual()
        if visual is not None:
            win.set_visual(visual)
            win.set_app_paintable(True)
        LS = common.GtkLayerShell
        if LS is not None and LS.is_supported():
            LS.init_for_window(win)
            LS.set_namespace(win, "tube-strip")
            # Above everything but the lock screen, so it is always there.
            LS.set_layer(win, LS.Layer.OVERLAY)
            for edge in (LS.Edge.TOP, LS.Edge.LEFT, LS.Edge.RIGHT):
                LS.set_anchor(win, edge, True)
            LS.set_exclusive_zone(win, HEIGHT)
        win.set_size_request(-1, HEIGHT)
        win.connect("destroy", Gtk.main_quit)
        self.win = win

        row = Gtk.Box()
        row.get_style_context().add_class("strip-row")
        win.add(row)

        start = Gtk.Button()
        start.set_relief(Gtk.ReliefStyle.NONE)
        start.get_style_context().add_class("strip-start")
        start.set_tooltip_text("start")
        start.connect("clicked", lambda *_: spawn("tube-start"))
        start.set_valign(Gtk.Align.CENTER)
        glyph = Gtk.DrawingArea()
        glyph.set_size_request(START_ICON, START_ICON)
        glyph.connect("draw", self.draw_start)
        start.add(glyph)
        start.connect("state-flags-changed", lambda *_: glyph.queue_draw())
        self.start, self.start_glyph = start, glyph
        row.pack_start(start, False, False, 0)

        self.desks = Gtk.Box()
        row.pack_start(self.desks, False, False, 0)

        # The handle: the rest of the strip, for the window you're in.
        self.handle = Gtk.EventBox()
        self.handle.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                               Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                               Gdk.EventMask.LEAVE_NOTIFY_MASK)
        inner = Gtk.Box(spacing=22)
        inner.get_style_context().add_class("strip-handle")
        self.title = Gtk.Label(xalign=0)
        self.title.get_style_context().add_class("strip-title")
        self.title.set_ellipsize(3)  # Pango.EllipsizeMode.END
        inner.pack_start(self.title, True, True, 0)
        self.handle.add(inner)
        self.handle.connect("enter-notify-event", self.on_enter)
        self.handle.connect("leave-notify-event", self.on_leave)
        self.handle.connect("button-press-event", self.on_press)
        self.handle.connect("motion-notify-event", self.on_motion)
        self.handle.connect("button-release-event", self.on_release)
        row.pack_start(self.handle, True, True, 0)

        # Sound, network, battery and the time: one thing to click.
        right = Gtk.Button()
        right.set_relief(Gtk.ReliefStyle.NONE)
        right.get_style_context().add_class("strip-status")
        right.connect("clicked", lambda *_: spawn("tube-status"))
        marks = Gtk.Box(spacing=16)
        self.sound, self.net, self.batt = Gtk.Image(), Gtk.Image(), Gtk.Image()
        self.bt = Gtk.Image()
        self.batt_pct = Gtk.Label()
        self.batt_pct.get_style_context().add_class("strip-pct")
        # The volume, like the battery: the mark shows roughly how loud, the
        # number exactly.
        self.sound_pct = Gtk.Label()
        self.sound_pct.get_style_context().add_class("strip-pct")
        sound = Gtk.Box(spacing=6)
        sound.pack_start(self.sound, False, False, 0)
        sound.pack_start(self.sound_pct, False, False, 0)
        self.sound_box = sound
        marks.pack_start(sound, False, False, 0)
        for w in (self.net, self.bt):
            marks.pack_start(w, False, False, 0)
        batt = Gtk.Box(spacing=6)
        batt.pack_start(self.batt, False, False, 0)
        batt.pack_start(self.batt_pct, False, False, 0)
        marks.pack_start(batt, False, False, 0)
        self.batt_box = batt
        # The date, then the time.
        clock = Gtk.Box(spacing=0)
        self.date = Gtk.Label()
        self.date.get_style_context().add_class("strip-date")
        self.clock = Gtk.Label()
        self.clock.get_style_context().add_class("strip-clock")
        clock.pack_start(self.date, False, False, 0)
        clock.pack_start(self.clock, False, False, 0)
        marks.pack_start(clock, False, False, 0)
        right.add(marks)
        self.status_button = right
        row.pack_end(right, False, False, 0)
        self.pal = common.load_palette()
        self.icons = {}
        self.accent_stamp = self._accent_stamp()

        self.window = None   # the focused window while the handle is in use
        self.drag = None
        self.preview = None
        self.hovered = False

        win.show_all()
        self.set_handle_visible(False)
        self.batt_box.hide()
        self.sound_box.hide()
        self.bt.hide()
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        self.watch_desktops()
        win.connect("notify::scale-factor", lambda *_: (self.icons.clear(), self.look()))
        self.look()
        GLib.timeout_add_seconds(STATUS_EVERY, self.look)
        self.watch_sound()
        self.watch_accent()
        self.shown = 1.0        # 1: on screen, 0: slid up out of the way
        self.slide_tick = None
        if wm.WAYFIRE:
            threading.Thread(target=self._watch_fullscreen, daemon=True).start()

    # ── the start mark ───────────────────────────────────────────────
    # A small Start screen on an 18-unit square: one wide tile over a medium
    # one, a short wide one and two small ones (x, y, w, h).
    START_TILES = ((0, 0, 18, 8), (0, 10, 8, 8), (10, 10, 8, 3), (10, 15, 3, 3), (15, 15, 3, 3))

    def draw_start(self, area, cr):
        """The start cluster: a tiny tile layout in the accent colour."""
        hover = self.start.get_state_flags() & (Gtk.StateFlags.PRELIGHT | Gtk.StateFlags.ACTIVE)
        hexcol = self.pal.get("ACCENT", "#E3008C")
        r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
        if hover:
            r, g, b = (c + (1 - c) * 0.3 for c in (r, g, b))
        cr.set_source_rgb(r, g, b)
        size = min(area.get_allocated_width(), area.get_allocated_height())
        k = size / 18.0
        for x, y, w, h in self.START_TILES:
            cr.rectangle(x * k, y * k, w * k, h * k)
        cr.fill()
        return False

    # ── a new accent ─────────────────────────────────────────────────
    ACCENT_FILE = os.path.join(common.CONFIG, "tubewm", "accent")

    def _accent_stamp(self):
        try:
            st = os.stat(self.ACCENT_FILE)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def watch_accent(self):
        """tube-accent rewrites ~/.config/tubewm/accent; when it does, take
        the new colour. The strip lives for the whole session, so without
        this the start mark keeps the accent it was started with."""
        try:
            os.makedirs(os.path.dirname(self.ACCENT_FILE), exist_ok=True)
            f = Gio.File.new_for_path(self.ACCENT_FILE)
            self.accent_monitor = f.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self.accent_monitor.connect("changed", lambda *_: GLib.idle_add(self.check_accent))
        except (OSError, GLib.Error):
            self.accent_monitor = None   # look() still checks now and then

    def check_accent(self):
        stamp = self._accent_stamp()
        if stamp != self.accent_stamp:
            self.accent_stamp = stamp
            self.recolour()
        return False

    def recolour(self):
        """Redraw everything that carries the accent."""
        self.pal = common.apply_css()
        self.icons.clear()
        if self.preview is not None:
            self.preview.pal = self.pal
        self.start_glyph.queue_draw()
        self.look()

    # ── out of the way for full screen ───────────────────────────────
    FULLSCREEN_EVENTS = ["view-fullscreen", "view-focused", "view-unmapped", "view-mapped",
                         "wset-workspace-changed", "output-gain-focus"]

    def _watch_fullscreen(self):
        while True:
            try:
                GLib.idle_add(self.check_fullscreen)
                for _ev in wm.wf_watch(self.FULLSCREEN_EVENTS):
                    GLib.idle_add(self.check_fullscreen)
            except (OSError, wm.WayfireError, ValueError, KeyError):
                time.sleep(1)

    def check_fullscreen(self):
        """Hide while the window you're in fills the whole screen."""
        try:
            views = wm.wf_views()
        except (OSError, wm.WayfireError):
            return False
        full = any(v.get("fullscreen") and v.get("activated") and v.get("mapped")
                   and v.get("role") == "toplevel" for v in views)
        self.slide(0.0 if full else 1.0)
        return False

    def slide(self, goal):
        """Slide the strip up out of the way (goal 0) or back down (1).

        The room the strip keeps at the top stays HEIGHT the whole time:
        Wayfire reserves exclusive zone + top margin, so as the margin goes
        negative the zone grows by the same amount. If the room changed,
        Wayfire's grid would re-place every snapped window, and that takes a
        full-screen window out of full screen.

        It never goes away completely either: unmapping it would give the
        room back, and a surface entirely off screen gets no frames to slide
        back with. Out of the way, one row stays on screen, invisible and
        letting clicks through."""
        LS = common.GtkLayerShell
        if LS is None or not LS.is_supported() or goal == self.shown and not self.slide_tick:
            return
        gone = self.win.get_style_context()
        if goal > 0:
            gone.remove_class("strip-gone")
            self.win.input_shape_combine_region(None)
        start, t0 = self.shown, GLib.get_monotonic_time()
        span = HIDE_MS * abs(goal - start) or 1
        lowest = HEIGHT - 1  # px slid up when out of the way

        def place(shown):
            up = min(lowest, int(round(HEIGHT * (1 - shown))))
            LS.set_exclusive_zone(self.win, HEIGHT + up)
            LS.set_margin(self.win, LS.Edge.TOP, -up)

        def tick(*_):
            k = min(1.0, (GLib.get_monotonic_time() - t0) / 1000.0 / span)
            ease = 1 - (1 - k) ** 3
            self.shown = start + (goal - start) * ease
            place(self.shown)
            if k >= 1.0:
                self.shown = goal
                self.slide_tick = None
                if goal == 0:
                    gone.add_class("strip-gone")
                    self.win.input_shape_combine_region(_empty_region())
                return False
            return True

        if self.slide_tick:
            GLib.source_remove(self.slide_tick)
        self.slide_tick = GLib.timeout_add(16, tick)

    # ── the clock ────────────────────────────────────────────────────
    def tick(self):
        self.clock.set_text(time.strftime("%H:%M"))
        self.date.set_text(marks.date_text())
        return True

    # ── sound, network, bluetooth, battery ───────────────────────────
    def look(self):
        """Ask how things are, off the main loop (the tools can be slow)."""
        self.check_accent()   # in case the file watch missed it
        threading.Thread(target=self._gather, daemon=True).start()
        return True

    def _gather(self):
        try:
            vol = applets.volume()
        except Exception:  # noqa: BLE001 - no sound server is not an error here
            vol = (None, False)
        try:
            name, _addr = applets.tiles._network()
        except Exception:  # noqa: BLE001
            name = ""
        try:
            pct, state, left = applets.battery_info()
        except Exception:  # noqa: BLE001
            pct, state, left = None, "", ""
        bt = None   # None: no bluetooth, or it's off; else the connected names
        try:
            if bluetooth.available() and bluetooth.powered():
                bt = bluetooth.connected_names()
        except Exception:  # noqa: BLE001
            pass
        GLib.idle_add(self._show, vol, name, (pct, state, left), bt)

    def _icon(self, image, name, svg=None):
        """Set image to a named icon, or to svg (cached under name, which is
        then any hashable key for it)."""
        scale = self.win.get_scale_factor()
        key = (name, scale)
        if key not in self.icons:
            self.icons[key] = icon_surface(name, self.pal, scale, self.win, svg)
        if self.icons[key] is not None:
            image.set_from_surface(self.icons[key])

    def _show_sound(self, level, muted):
        self.sound_box.set_visible(level is not None)
        if level is not None:
            self._icon(self.sound, marks.volume_key(level, muted),
                       marks.volume_svg(level, muted, self.pal))
            self.sound_pct.set_text("off" if muted else "%d%%" % level)
            self.sound_box.set_tooltip_text("sound off" if muted else "sound %d%%" % level)
        return False

    def watch_sound(self):
        """The volume as soon as it moves (keys, a headset, an app), not at
        the next look in a few seconds."""
        self.sound_watcher = levels.Watcher(
            lambda kind, v, muted: GLib.idle_add(self._show_sound, v, muted), brightness=False)

    def _show(self, vol, net, batt, bt=None):
        self._show_sound(*(vol if vol else (None, False)))
        self._icon(self.net, "wired" if net == "wired" else "wifi" if net else "offline")
        self.net.set_tooltip_text(("wi-fi: " + net) if net and net != "wired" else net or "not connected")
        self.bt.set_visible(bt is not None)
        if bt is not None:
            self._icon(self.bt, "bluetooth-connected" if bt else "bluetooth")
            self.bt.set_tooltip_text(("bluetooth: " + ", ".join(bt).lower()) if bt else "bluetooth on")
        pct, state, left = batt
        self.batt_box.set_visible(pct is not None)
        if pct is not None:
            charging = "charg" in state and "dis" not in state
            self._icon(self.batt, marks.battery_key(pct, charging),
                       marks.battery_svg(pct, charging, self.pal))
            self.batt_pct.set_text("%d%%" % pct)
            tip = "battery %d%%" % pct + (", charging" if charging else "")
            if left and not charging:
                tip += ", " + left.replace(" until empty", " left")
            self.batt_box.set_tooltip_text(tip)
        return False

    # ── desktops ─────────────────────────────────────────────────────
    def watch_desktops(self):
        self.refresh_desktops()
        f = Gio.File.new_for_path(desktops.BAR_FILE)
        self.monitor = f.monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", lambda *_: GLib.idle_add(self.refresh_desktops))
        if not wm.WAYFIRE:
            # Sway: no daemon, so look again now and then.
            GLib.timeout_add_seconds(1, lambda: self.refresh_desktops() or True)

    def desktop_entries(self):
        if wm.WAYFIRE:
            try:
                with open(desktops.BAR_FILE) as fh:
                    lines = [json.loads(line) for line in fh if line.strip()]
            except (OSError, ValueError):
                lines = []
            items = [(d.get("text", ""), "current" in d.get("class", [])) for d in lines[:-1]]
            spare = bool(lines and lines[-1].get("text"))
            return [(i, t, cur) for i, (t, cur) in enumerate(items) if t], spare
        names = wm.desktop_names()
        cur = wm.current_pivot()
        return [(i, n, i == cur) for i, n in enumerate(names)], False

    def refresh_desktops(self):
        entries, spare = self.desktop_entries()
        spare_index = max([i for i, _n, _c in entries], default=-1) + 1
        self.names = [(i, n) for i, n, _c in entries]
        key = (tuple(entries), spare)
        if getattr(self, "_desk_key", None) == key:
            return False
        self._desk_key = key
        for c in self.desks.get_children():
            self.desks.remove(c)
        for i, name, cur in entries:
            b = Gtk.Button(label=name)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("strip-desk")
            if cur:
                b.get_style_context().add_class("current")
            b.connect("clicked", lambda _b, n=i: spawn("tube-desktops", "go", str(n + 1)))
            b.connect("button-press-event", self.on_desk_press, i)
            b.desk = i
            self.desks.pack_start(b, False, False, 0)
        if spare:
            b = Gtk.Button(label="+")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("strip-desk")
            b.set_tooltip_text("a new desktop")
            b.connect("clicked", lambda *_: spawn("tube-desktops", "new"))
            b.desk = spare_index
            self.desks.pack_start(b, False, False, 0)
        self.desks.show_all()
        return False

    def on_desk_press(self, button, event, i):
        if event.button != 3:
            return False
        x = button.translate_coordinates(self.win, 0, 0)[0]
        spawn("tube-desktops", "menu", str(i + 1), str(x))
        return True

    # ── the handle ───────────────────────────────────────────────────
    def set_handle_visible(self, on):
        self.title.set_visible(on)

    def on_enter(self, *_):
        self.hovered = True
        self.window = wm.focused()
        if self.window:
            self.title.set_text(self.window.label.lower())
            self.set_handle_visible(True)
        return False

    def on_leave(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False  # into the title, still inside
        self.hovered = False
        if not self.drag:
            self.set_handle_visible(False)
        return False

    def on_press(self, _w, event):
        if event.button == 3:
            self.window = self.window or wm.focused()
            if self.window:
                self.move_menu(event)
            return True
        if event.button != 1:
            return False
        self.window = self.window or wm.focused()
        if self.window:
            self.drag = {"x": event.x_root, "y": event.y_root, "on": False}
        return True

    def screen(self):
        w, h = common.monitor_size(self.win)
        return w, h

    def desk_at(self, x, y):
        """The desktop button (or +) under a point on the strip, if any."""
        if y >= HEIGHT:
            return None
        for b in self.desks.get_children():
            bx = b.translate_coordinates(self.win, 0, 0)[0]
            if bx <= x < bx + b.get_allocated_width() and hasattr(b, "desk"):
                return b
        return None

    def mark_drop(self, target):
        for b in self.desks.get_children():
            ctx = b.get_style_context()
            (ctx.add_class if b is target else ctx.remove_class)("drop")

    def on_motion(self, _w, event):
        d = self.drag
        if not d:
            return False
        if not d["on"]:
            if abs(event.x_root - d["x"]) + abs(event.y_root - d["y"]) < DRAG_START:
                return True
            d["on"] = True
            self.preview = self.preview or Preview()
        if event.y_root < HEIGHT:
            # Along the strip: onto a desktop's name moves the window there;
            # anywhere else on the strip, letting go does nothing.
            target = self.desk_at(event.x_root, event.y_root)
            self.mark_drop(target)
            d["zone"] = None
            d["desk"] = target.desk if target is not None else None
            self.preview.hide()
            return True
        self.mark_drop(None)
        d["desk"] = None
        w, h = self.screen()
        zone = zone_for(event.x_root, event.y_root, w, h)
        d["zone"] = zone
        self.preview.show(zone_rect(zone, w, h, HEIGHT))
        return True

    def on_release(self, _w, event):
        d, self.drag = self.drag, None
        if self.preview:
            self.preview.hide()
        self.mark_drop(None)
        if d and d.get("on") and self.window:
            if d.get("desk") is not None:
                self.move_to(d["desk"])
            elif d.get("zone"):
                wm.snap(self.window["id"], d["zone"])
        if not self.hovered:
            self.set_handle_visible(False)
        return True

    def move_to(self, desk):
        """Take the window you're in to another desktop, and go with it."""
        win_id = self.window["id"]
        wm.send_to_pivot(win_id, desk)
        wm.go_to_pivot(desk)
        wm.focus(win_id)

    def move_menu(self, event):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("tube-menu")
        head = Gtk.MenuItem(label="move to")
        head.set_sensitive(False)
        menu.append(head)
        cur = (self.window or {}).get("workspace")
        names = getattr(self, "names", [])
        for i, name in names:
            item = Gtk.MenuItem(label=name)
            item.set_sensitive(i != cur)
            item.connect("activate", lambda _m, n=i: self.move_to(n))
            menu.append(item)
        spare = max([i for i, _n in names], default=-1) + 1
        item = Gtk.MenuItem(label="a new desktop")
        item.connect("activate", lambda _m: self.move_to(spare))
        menu.append(item)
        menu.show_all()
        menu.attach_to_widget(self.handle, None)
        menu.popup_at_pointer(event)


def main(argv=None):
    if not common.toggle_instance("strip"):
        # A second start replaces the first (after a config change, say).
        common.toggle_instance("strip")
    Strip()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
