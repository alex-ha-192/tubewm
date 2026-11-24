"""tube-strip: the thin strip along the top of the screen.

On the left, the start square and the desktops in light type: the one
you're on in white. Click one to go there, right-click it for its menu, +
for a new one. On the right, the time; click it for everything else (sound,
brightness, wi-fi, battery, notifications, power).

Between them is the handle for the window you're in. Point at it and the
window's name and "close" appear. Drag it down to a side of the screen for
half, into a corner for a quarter, or let go in the middle to fill the
screen; an accent outline shows where the window will go.
"""

import json
import os
import subprocess
import sys
import time

from . import common, desktops, wm

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

HEIGHT = 40
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
        LS = common.GtkLayerShell
        if LS is not None and LS.is_supported():
            LS.init_for_window(win)
            LS.set_namespace(win, "tube-strip")
            LS.set_layer(win, LS.Layer.TOP)
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
        self.close = Gtk.Button(label="close")
        self.close.set_relief(Gtk.ReliefStyle.NONE)
        self.close.get_style_context().add_class("strip-word")
        self.close.connect("clicked", self.on_close)
        inner.pack_start(self.title, True, True, 0)
        inner.pack_end(self.close, False, False, 0)
        self.handle.add(inner)
        self.handle.connect("enter-notify-event", self.on_enter)
        self.handle.connect("leave-notify-event", self.on_leave)
        self.handle.connect("button-press-event", self.on_press)
        self.handle.connect("motion-notify-event", self.on_motion)
        self.handle.connect("button-release-event", self.on_release)
        row.pack_start(self.handle, True, True, 0)

        self.clock = Gtk.Button()
        self.clock.set_relief(Gtk.ReliefStyle.NONE)
        self.clock.get_style_context().add_class("strip-clock")
        self.clock.connect("clicked", lambda *_: spawn("tube-status"))
        row.pack_end(self.clock, False, False, 0)

        self.window = None   # the focused window while the handle is in use
        self.drag = None
        self.preview = None
        self.hovered = False

        win.show_all()
        self.set_handle_visible(False)
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        self.watch_desktops()

    # ── the clock ────────────────────────────────────────────────────
    def tick(self):
        self.clock.set_label(time.strftime("%H:%M"))
        return True

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
            self.desks.pack_start(b, False, False, 0)
        if spare:
            b = Gtk.Button(label="+")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("strip-desk")
            b.set_tooltip_text("a new desktop")
            b.connect("clicked", lambda *_: spawn("tube-desktops", "new"))
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
        self.close.set_visible(on)

    def on_enter(self, *_):
        self.hovered = True
        self.window = wm.focused()
        if self.window:
            self.title.set_text(self.window.label.lower())
            self.set_handle_visible(True)
        return False

    def on_leave(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False  # into the close button, still inside
        self.hovered = False
        if not self.drag:
            self.set_handle_visible(False)
        return False

    def on_close(self, *_):
        if self.window:
            wm.close(self.window["id"])
        self.set_handle_visible(False)

    def on_press(self, _w, event):
        if event.button != 1:
            return False
        self.window = self.window or wm.focused()
        if self.window:
            self.drag = {"x": event.x_root, "y": event.y_root, "on": False}
        return True

    def screen(self):
        w, h = common.monitor_size(self.win)
        return w, h

    def on_motion(self, _w, event):
        d = self.drag
        if not d:
            return False
        if not d["on"]:
            if abs(event.x_root - d["x"]) + abs(event.y_root - d["y"]) < DRAG_START:
                return True
            d["on"] = True
            self.preview = self.preview or Preview()
        w, h = self.screen()
        zone = zone_for(event.x_root, event.y_root, w, h)
        d["zone"] = zone
        self.preview.show(zone_rect(zone, w, h, HEIGHT))
        return True

    def on_release(self, _w, event):
        d, self.drag = self.drag, None
        if self.preview:
            self.preview.hide()
        if d and d.get("on") and self.window:
            wm.snap(self.window["id"], d["zone"])
        if not self.hovered:
            self.set_handle_visible(False)
        return True


def main(argv=None):
    if not common.toggle_instance("strip"):
        # A second start replaces the first (after a config change, say).
        common.toggle_instance("strip")
    Strip()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
