"""tube-share: take a screenshot.

    tube-share           dim the screen and choose what to take
    tube-share screen    take the whole screen at once
    tube-share window    take the window you're in at once

Choosing: the screen holds still and dims, with a strip at the top offering
area, window and screen. For an area, drag across it; for a window, click
it; for a screen, click it. Escape or a right-click puts it away.

The picture is copied, so you can paste it anywhere, and saved in
~/Pictures/Screenshots, and a short notification says so.
"""

import os
import subprocess
import sys
import tempfile
import time

from . import common, wm

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

MODES = ("area", "window", "screen")
HINTS = {"area": "drag across what you want", "window": "click a window",
         "screen": "click a screen"}
DIM = 0.55          # how dark the screen goes around what you're choosing
MIN_DRAG = 4        # px: a smaller drag is a slip, not an area

CSS = """
.shot-strip { background-color: @tube_shell; padding: 6px 22px 10px 22px; }
.shot-strip button { padding: 0 12px; border: none; background: transparent; }
.shot-strip button label { font-size: 24px; font-weight: 300; color: @tube_dim; }
.shot-strip button:hover label { color: @tube_subtle; }
.shot-strip button.on label { color: @tube_fg; }
.shot-hint { font-size: 13px; font-weight: 400; color: @tube_subtle; }
"""


def shots_dir():
    pictures = os.environ.get("XDG_PICTURES_DIR") or os.path.join(common.HOME, "Pictures")
    path = os.path.join(pictures, "Screenshots")
    os.makedirs(path, exist_ok=True)
    return path


def new_name():
    base = os.path.join(shots_dir(), time.strftime("%Y-%m-%d_%H-%M-%S"))
    path, n = base + ".png", 2
    while os.path.exists(path):  # two in the same second
        path, n = "%s-%d.png" % (base, n), n + 1
    return path


def grim(path, rect=None):
    cmd = ["grim"]
    if rect:
        cmd += ["-g", "%d,%d %dx%d" % tuple(int(round(v)) for v in rect)]
    try:
        return subprocess.run(cmd + [path], stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def notify(title, body, icon=None):
    cmd = ["notify-send", "-a", "share"] + (["-i", icon] if icon else []) + [title, body]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def finish(path):
    """Copy the saved picture and say where it went."""
    if common.have("wl-copy"):
        with open(path, "rb") as fh:
            # wl-copy stays behind to hand the picture over; don't wait on it.
            subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=fh,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    notify("screenshot", "copied, and saved to Pictures/Screenshots", path)


def failed():
    notify("screenshot", "couldn't take one (is grim installed?)")
    return 1


def _rgb(hexcol):
    h = hexcol.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _contains(r, x, y):
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


class Picker:
    """The dimmed, held-still screen you choose from: one layer per monitor,
    all drawn from the one picture taken before anything appeared."""

    def __init__(self, frozen, accent):
        self.accent = _rgb(accent)
        self.pix = GdkPixbuf.Pixbuf.new_from_file(frozen)
        display = Gdk.Display.get_default()
        self.monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        geos = [m.get_geometry() for m in self.monitors]
        self.screens = [(g.x, g.y, g.width, g.height) for g in geos]
        x0, y0 = min(s[0] for s in self.screens), min(s[1] for s in self.screens)
        x1 = max(s[0] + s[2] for s in self.screens)
        self.origin = (x0, y0)
        # grim draws every screen at the sharpest scale among them, so this
        # is 2 on a Framework 13 at scale 2: one pixel of the picture for
        # every pixel of the screen.
        self.scale = self.pix.get_width() / max(1, x1 - x0)
        self.surface = Gdk.cairo_surface_create_from_pixbuf(self.pix, 1, None)
        rects = wm.window_rects()
        self.windows = [r for r, _ in rects]
        focused = [r for r, f in rects if f]
        self.home = 0  # the screen the strip goes on: the one you're working in
        if focused:
            cx, cy = focused[0][0] + focused[0][2] / 2, focused[0][1] + focused[0][3] / 2
            self.home = next((i for i, s in enumerate(self.screens) if _contains(s, cx, cy)), 0)
        self.mode = "area"
        self.pointer = None
        self.drag = None
        self.chosen = None
        self.areas = []
        self.buttons = {}
        self.hint = None
        for i, mon in enumerate(self.monitors):
            self._layer(i, mon)
        self.set_mode("area")

    # ── building ───────────────────────────────────────────────────────
    def _layer(self, i, mon):
        win = common.make_layer_window("share")
        if common.GtkLayerShell is not None and common.GtkLayerShell.is_supported():
            common.GtkLayerShell.set_monitor(win, mon)
        common.main_quit_on_escape(win)
        overlay = Gtk.Overlay()
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        area.connect("draw", self.draw, i)
        area.connect("button-press-event", self.press, i)
        area.connect("button-release-event", self.release, i)
        area.connect("motion-notify-event", self.motion, i)
        overlay.add(area)
        self.areas.append(area)
        if i == self.home:
            overlay.add_overlay(self._strip())
        win.add(overlay)
        win.show_all()

    def _strip(self):
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        column.get_style_context().add_class("shot-strip")
        row = Gtk.Box(spacing=0, halign=Gtk.Align.CENTER)
        for mode in MODES:
            btn = Gtk.Button(label=mode)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_can_focus(False)
            btn.connect("clicked", lambda _b, m=mode: self.set_mode(m))
            row.pack_start(btn, False, False, 0)
            self.buttons[mode] = btn
        self.hint = Gtk.Label()
        self.hint.get_style_context().add_class("shot-hint")
        column.pack_start(row, False, False, 0)
        column.pack_start(self.hint, False, False, 0)
        return column

    def set_mode(self, mode):
        self.mode, self.drag = mode, None
        for m, btn in self.buttons.items():
            (btn.get_style_context().add_class if m == mode
             else btn.get_style_context().remove_class)("on")
        if self.hint is not None:
            self.hint.set_text(HINTS[mode])
        self.redraw()

    # ── choosing ───────────────────────────────────────────────────────
    def selection(self):
        """What would be taken now, as (x, y, width, height) on the screen."""
        if self.mode == "area":
            if not self.drag or not self.pointer:
                return None
            (ax, ay), (bx, by) = self.drag, self.pointer
            return (min(ax, bx), min(ay, by), abs(bx - ax), abs(by - ay))
        if not self.pointer:
            return None
        x, y = self.pointer
        pool = self.windows if self.mode == "window" else self.screens
        return next((r for r in pool if _contains(r, x, y)), None)

    def _at(self, i, event):
        s = self.screens[i]
        return (s[0] + event.x, s[1] + event.y)

    def motion(self, _w, event, i):
        self.pointer = self._at(i, event)
        self.redraw()
        return True

    def press(self, _w, event, i):
        if event.button == 3:
            Gtk.main_quit()
            return True
        if event.button != 1:
            return False
        self.pointer = self._at(i, event)
        if self.mode == "area":
            self.drag = self.pointer
        else:
            self.take(self.selection())
        return True

    def release(self, _w, event, i):
        if event.button != 1 or self.mode != "area" or not self.drag:
            return False
        self.pointer = self._at(i, event)
        sel = self.selection()
        self.drag = None
        if sel and sel[2] >= MIN_DRAG and sel[3] >= MIN_DRAG:
            self.take(sel)
        else:
            self.redraw()
        return True

    def take(self, rect):
        if not rect:
            return
        self.chosen = rect
        Gtk.main_quit()

    def crop(self, rect, path):
        """Cut what was chosen out of the held-still picture, pixel for pixel."""
        s, (ox, oy) = self.scale, self.origin
        x, y = max(0, round((rect[0] - ox) * s)), max(0, round((rect[1] - oy) * s))
        w = min(self.pix.get_width() - x, round(rect[2] * s))
        h = min(self.pix.get_height() - y, round(rect[3] * s))
        if w <= 0 or h <= 0:
            return False
        self.pix.new_subpixbuf(x, y, w, h).savev(path, "png", [], [])
        return True

    # ── drawing ────────────────────────────────────────────────────────
    def redraw(self):
        for a in self.areas:
            a.queue_draw()

    def draw(self, _w, cr, i):
        sx, sy, sw, sh = self.screens[i]
        cr.translate(-sx, -sy)  # draw in screen coordinates
        cr.save()
        cr.scale(1 / self.scale, 1 / self.scale)  # back to the screen's own pixels
        cr.set_source_surface(self.surface, self.origin[0] * self.scale, self.origin[1] * self.scale)
        cr.paint()
        cr.restore()
        sel = self.selection()
        cr.set_source_rgba(0, 0, 0, DIM)
        cr.rectangle(sx, sy, sw, sh)
        if sel:
            cr.rectangle(*sel)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)  # leave the selection bright
        cr.fill()
        if sel:
            cr.set_source_rgb(*self.accent)
            cr.set_line_width(2)
            cr.rectangle(sel[0] + 1, sel[1] + 1, max(0, sel[2] - 2), max(0, sel[3] - 2))
            cr.stroke()
        return True


def pick():
    # Asking again (Print twice) puts it away.
    if not common.toggle_instance("share"):
        return 0
    fd, frozen = tempfile.mkstemp(prefix="tubewm-shot-", suffix=".png", dir=common.RUNTIME)
    os.close(fd)
    try:
        if not grim(frozen):
            return failed()
        pal = common.apply_css(CSS)
        picker = Picker(frozen, pal.get("ACCENT", common.PALETTE_DEFAULTS["ACCENT"]))
        Gtk.main()
        if not picker.chosen:
            return 0
        path = new_name()
        if not picker.crop(picker.chosen, path):
            return failed()
        finish(path)
        return 0
    finally:
        os.unlink(frozen)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    mode = args[0] if args else "pick"
    if mode in ("pick", "area", "region"):
        return pick()
    if mode in ("-h", "--help") or mode not in ("screen", "window"):
        print(__doc__.split("\n\n")[1])
        return 0 if mode in ("-h", "--help") else 2
    rect = None
    if mode == "window":
        rect = next((r for r, f in wm.window_rects() if f), None)
        if rect is None:
            notify("screenshot", "no window to take")
            return 1
    path = new_name()
    if not grim(path, rect):
        return failed()
    finish(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
