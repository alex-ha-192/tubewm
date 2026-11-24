"""tube-osd-daemon: the small volume / brightness indicator.

A band across the top of the screen, like a Windows Phone toast: the word,
a thin level line and the number. It appears
when a key (or the bar's scroll wheel) changes the level, holds for 1.5 s
and fades away. Clicks go straight through it.

It stays running after the first key press and listens on a FIFO, so later
presses only cost a `printf` from tube-osd. Each line on the FIFO is

    <kind> <value 0-100> <muted 0|1>

with kind one of volume, brightness, microphone.

Without GTK layer shell (a compositor that doesn't support it, or the
Python bindings missing) it falls back to a plain notification.
"""

import errno
import fcntl
import os
import subprocess
import sys

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
FIFO = os.path.join(RUNTIME, "tube-osd.fifo")
LOCK = os.path.join(RUNTIME, "tube-osd.lock")
NO_LAYER = os.path.join(RUNTIME, "tube-osd.nolayer")

HEIGHT = 40          # the same height as the strip it covers
HOLD_MS = 1500       # fully visible
FADE_MS = 300        # fade out
FADE_IN_MS = 90

KINDS = ("volume", "brightness", "microphone")


def parse(line):
    parts = line.split()
    if len(parts) < 2 or parts[0] not in KINDS:
        return None
    try:
        value = max(0, min(100, int(round(float(parts[1])))))
    except ValueError:
        return None
    muted = len(parts) > 2 and parts[2] == "1"
    return parts[0], value, muted


def notify_fallback(kind, value, muted):
    """Plain notification, for when we can't draw our own surface."""
    text = "off" if muted else str(value)
    try:
        subprocess.run(
            ["notify-send", "-a", "tube-osd", "-t", "1500",
             "-h", "int:value:%d" % (0 if muted else value),
             "-h", "string:x-canonical-private-synchronous:tube-osd",
             kind, text],
            timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ---------------------------------------------------------------- the window

def run():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GLib, Gtk, GtkLayerShell  # noqa: F401
    import cairo

    from .common import load_palette

    if not GtkLayerShell.is_supported():
        raise RuntimeError("no layer shell")

    pal = load_palette()

    class Osd:
        def __init__(self):
            self.kind, self.value, self.muted = "volume", 0, False
            self.alpha = 0.0
            self.anim = None      # (start alpha, end alpha, start time, duration)
            self.hold = None
            self.palette_mtime = self._palette_mtime()

            win = Gtk.Window()
            win.set_title("tube-osd")
            visual = win.get_screen().get_rgba_visual()
            if visual is not None:
                win.set_visual(visual)
            win.set_app_paintable(True)
            win.set_size_request(-1, HEIGHT)
            GtkLayerShell.init_for_window(win)
            GtkLayerShell.set_namespace(win, "tube-osd")
            GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
            for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(win, edge, True)
            GtkLayerShell.set_exclusive_zone(win, -1)
            GtkLayerShell.set_keyboard_interactivity(win, False)
            area = Gtk.DrawingArea()
            area.connect("draw", self.draw)
            win.add(area)
            win.connect("realize", self._click_through)
            self.win, self.area = win, area

        def _click_through(self, win):
            # An empty input region: the pointer goes to whatever is below.
            win.input_shape_combine_region(cairo.Region())

        @staticmethod
        def _palette_mtime():
            from .common import _palette_file
            path = _palette_file()
            try:
                return os.path.getmtime(path) if path else 0
            except OSError:
                return 0

        def show(self, kind, value, muted):
            nonlocal pal
            mtime = self._palette_mtime()
            if mtime != self.palette_mtime:   # accent changed since we started
                self.palette_mtime = mtime
                pal = load_palette()
            self.kind, self.value, self.muted = kind, value, muted
            if not self.win.get_visible():
                self.alpha = 0.0
                self.win.show_all()
                self.win.input_shape_combine_region(cairo.Region())
            self._animate(1.0, FADE_IN_MS)
            if self.hold:
                GLib.source_remove(self.hold)
            self.hold = GLib.timeout_add(HOLD_MS, self._fade_out)
            self.area.queue_draw()

        def _fade_out(self):
            self.hold = None
            self._animate(0.0, FADE_MS)
            return False

        def _animate(self, target, duration):
            now = GLib.get_monotonic_time() / 1000.0
            running = self.anim is not None
            self.anim = (self.alpha, target, now, duration)
            if not running:
                GLib.timeout_add(16, self._tick)

        def _tick(self):
            if self.anim is None:
                return False
            start, end, t0, dur = self.anim
            now = GLib.get_monotonic_time() / 1000.0
            t = 1.0 if dur <= 0 else min(1.0, (now - t0) / dur)
            ease = 1 - (1 - t) ** 3   # ease out, as Metro does
            self.alpha = start + (end - start) * ease
            self.area.queue_draw()
            if t >= 1.0:
                self.anim = None
                if end == 0.0:
                    self.win.hide()
                return False
            return True

        def draw(self, widget, cr):
            w, h = widget.get_allocated_width(), widget.get_allocated_height()
            a = self.alpha
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)

            # The band: the surface colour, edge to edge.
            r, g, b = hex_rgb(pal["SURFACE"])
            cr.set_source_rgba(r, g, b, a)
            cr.rectangle(0, 0, w, h)
            cr.fill()

            fg = hex_rgb(pal["FG"])
            subtle = hex_rgb(pal["SUBTLE"])
            accent = hex_rgb(pal["ACCENT"])
            track = hex_rgb(pal["SURFACE_HI"])
            pad = 24

            # The word on the left, in light type.
            cr.select_font_face("Open Sans Light", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(16)
            cr.set_source_rgba(*fg, a)
            cr.move_to(pad, h / 2 + 6)
            cr.show_text(self.kind)
            word_w = cr.text_extents("brightness").x_advance

            # The number (or off/on) on the right.
            if self.kind == "microphone":
                text = "off" if self.muted else "on"
            else:
                text = "off" if self.muted else str(self.value)
            cr.set_font_size(20)
            ext = cr.text_extents(text)
            num_w = cr.text_extents("100").x_advance
            cr.move_to(w - pad - ext.x_advance, h / 2 + 7)
            cr.set_source_rgba(*(subtle if self.muted else fg), a)
            cr.show_text(text)

            # Between them, a hairline track with a thicker accent level.
            if self.kind != "microphone":
                x0 = pad + word_w + 24
                x1 = w - pad - num_w - 24
                cr.set_source_rgba(*track, a)
                cr.rectangle(x0, h / 2 - 1, x1 - x0, 2)
                cr.fill()
                cr.set_source_rgba(*(subtle if self.muted else accent), a)
                cr.rectangle(x0, h / 2 - 2, (x1 - x0) * self.value / 100.0, 4)
                cr.fill()
            return False

    osd = Osd()

    # The FIFO. Opened read-write so it never reports end-of-file when a
    # writer goes away.
    try:
        os.mkfifo(FIFO, 0o600)
    except FileExistsError:
        pass
    fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
    buf = [b""]

    def on_input(source, condition):
        try:
            data = os.read(fd, 4096)
        except OSError as e:
            if e.errno == errno.EAGAIN:
                return True
            raise
        buf[0] += data
        *lines, buf[0] = buf[0].split(b"\n")
        latest = None
        for line in lines:
            msg = parse(line.decode("utf-8", "replace"))
            if msg:
                latest = msg
        if latest:
            osd.show(*latest)
        return True

    GLib.io_add_watch(fd, GLib.PRIORITY_HIGH, GLib.IO_IN, on_input)
    return osd, Gtk


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    first = parse(" ".join(argv)) if argv else None

    # One daemon per session. A second one just hands its message on.
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if first and os.path.exists(FIFO):
            fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, (" ".join(argv) + "\n").encode())
            os.close(fd)
        return 0

    try:
        osd, Gtk = run()
    except (ImportError, ValueError, RuntimeError) as e:
        # Remember, so tube-osd goes straight to notifications next time.
        with open(NO_LAYER, "w") as f:
            f.write("%s\n" % e)
        if first:
            notify_fallback(*first)
        return 1
    try:
        os.unlink(NO_LAYER)
    except OSError:
        pass

    if first:
        osd.show(*first)
    Gtk.main()
    return 0
