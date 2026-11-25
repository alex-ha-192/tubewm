"""tube-status: everything that isn't an app, in one panel on the right.

Click the time on the strip to open it. A big clock and the date, sound and
brightness as thin lines you drag, which speakers and microphone to use,
wi-fi, bluetooth, battery, quiet hours and caffeine, your
notifications, and lock / sleep / sign out / restart / shut down as words.
Click network, bluetooth or battery to open it up: the wi-fi networks around
you, your bluetooth devices and pairing new ones, the power mode.
Click caffeine to keep the screen on and the desktop awake (tube-caffeine).
Click outside it, or press Escape, to close it.

The panel is built at login (tube-status --background) and then stays
running, out of sight, so clicking the time only has to bring it back; it
reads everything again as it opens and puts in whatever has changed.
"""

import argparse
import faulthandler
import os
import signal
import sys
import threading
import time

from . import applets, bluetooth, caffeine, common, levels, resident

from gi.repository import GLib, Gtk, Pango  # noqa: E402

try:
    import cairo   # for an empty input region while the panel is away
except ImportError:  # pragma: no cover - comes with python-gobject on most systems
    cairo = None

WIDTH = 460
DND_MODE = "do-not-disturb"
INSIDE_MAX = 340   # px: the most an opened row takes before it scrolls
# What a later `tube-status` sends the one already running (bin/tube-status
# sends these too, before it loads GTK).
SIGNALS = {signal.SIGUSR1: "toggle", signal.SIGHUP: "close"}
PROFILE_NAMES = {"power-saver": "battery saver", "balanced": "balanced", "performance": "performance"}


def label(text, *classes, xalign=0.0):
    lab = Gtk.Label(label=text, xalign=xalign)
    for c in classes:
        lab.get_style_context().add_class(c)
    return lab


def word_button(text, cb, *classes):
    b = Gtk.Button(label=text)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("status-word")
    for c in classes:
        b.get_style_context().add_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def pending_updates():
    """How many tubewm changes are waiting, as last seen by tube-update."""
    path = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(common.HOME, ".cache")),
                        "tubewm", "updates")
    try:
        with open(path) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def gather():
    """Everything the panel shows, read from the tools that know it. Slow
    (a dozen or so commands) and free of GTK, so it runs off the main loop
    while the panel is already on screen with what it read last time."""
    vol = applets.volume()
    pct, state, left = applets.battery_info()
    names, cur = applets.profiles()
    return {
        "volume": vol if vol and vol[0] is not None else None,
        "outputs": applets.audio_devices("output"),
        "inputs": applets.audio_devices("input"),
        "brightness": applets.brightness(),
        "net": applets._net_text(),
        "nmcli": common.have("nmcli"),
        "bluetooth": bluetooth.available(),
        "battery": (pct, state, left),
        "profiles": (names, cur),
        "dnd": Status.dnd(),
        "caffeine": (caffeine.shown(), caffeine.active()),
        "updates": pending_updates(),
        "notes": applets.notification_history()[:4],
    }


class Status:
    """The panel. It is built once and then stays running, mapped but out of
    the way while closed, so clicking the time only has to bring it back
    (see resident.py, and start.py, which does the same)."""

    def __init__(self, shown=True):
        common.apply_css()
        self.look = look_stamp()
        win = common.make_layer_window("status", transparent=True, layer="overlay")
        self.win = win
        common.below_strip(win)
        common.main_quit_on_escape(win, self.quit)
        catcher = Gtk.EventBox()
        catcher.connect("button-press-event", lambda *_: self.quit())
        win.add(catcher)
        self.sheet = catcher

        panel = Gtk.EventBox(halign=Gtk.Align.END)
        panel.connect("button-press-event", lambda *_: True)
        panel.get_style_context().add_class("status")
        panel.set_size_request(WIDTH, -1)
        catcher.add(panel)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.box.get_style_context().add_class("status-box")
        panel.add(self.box)

        self.levels = {}   # kind -> its row, for the watcher to move
        # Keys, the firmware, a headset or an app can move them, open or
        # not: follow, so the lines always say what the level really is.
        self.watcher = levels.Watcher(lambda kind, v, muted: GLib.idle_add(self.follow, kind, v, muted))

        self.shown = shown
        self.away = False
        self.touched = False   # opened a row or moved a line since it showed
        self.asked = 0         # which gather() the next result has to be
        self.data = gather()
        self.fill(self.data)
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        if not shown:
            self.sheet.set_opacity(0.0)
        win.show_all()
        if not shown:
            self.set_away(True)

    # ── shown and hidden ─────────────────────────────────────────────
    def on_signal(self, what):
        resident.heard("status", what)   # before anything slow: tube-status is waiting
        if what == "close" or self.shown:
            self.quit()
        else:
            self.show()
        return True   # keep listening

    def show(self):
        if look_stamp() != self.look:
            # The accent or the stylesheet changed while we were closed.
            self.look = look_stamp()
            common.apply_css()
        self.shown, self.touched = True, False
        self.sheet.set_opacity(1.0)
        self.set_away(False)
        self.tick()
        # What we show is what we read when it last closed; read it again
        # now, and put it in if anything moved.
        self.refresh()

    def quit(self):
        """Close the panel: it goes out of the way and waits for next time."""
        if self.shown:
            self.shown = False
            self.sheet.set_opacity(0.0)
            self.set_away(True)
            # Back to how it opens (every row closed, the wi-fi and bluetooth
            # lists gone with their timers), and fresh for next time.
            self.fill(self.data)
            self.refresh()
        return True

    def set_away(self, away):
        """Put the panel out of the way, or bring it back, without unmapping
        it: hiding and showing a layer-shell window again can leave GTK stuck
        inside show() for good (start.set_away has the story). Away, it stays
        mapped but drops below everything, transparent, taking no clicks and
        no keys."""
        self.away = away
        if not common.layer_shell():
            self.win.hide() if away else self.win.show()   # nested/X11 for development
            return
        GtkLayerShell = common.GtkLayerShell
        GtkLayerShell.set_keyboard_interactivity(self.win, not away)
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.BACKGROUND if away
                                else GtkLayerShell.Layer.OVERLAY)
        gdk_win = self.win.get_window()
        if gdk_win is not None and cairo is not None:
            gdk_win.input_shape_combine_region(
                cairo.Region() if away else cairo.Region(cairo.RectangleInt(0, 0, 1 << 15, 1 << 15)), 0, 0)

    def refresh(self):
        self.asked += 1
        asked = self.asked

        def work():
            try:
                data = gather()
            except Exception:  # noqa: BLE001 - keep what we have
                return
            GLib.idle_add(lambda: self.refreshed(asked, data) and False)
        threading.Thread(target=work, daemon=True).start()

    def refreshed(self, asked, data):
        if asked != self.asked:
            return   # opened or closed since: a newer reading is on its way
        changed = data != self.data
        self.data = data
        # Don't pull a row shut under someone who has just opened it.
        if changed and not (self.shown and self.touched):
            self.fill(data)

    def fill(self, d):
        for child in self.box.get_children():
            self.box.remove(child)
            child.destroy()
        box = self.box
        self.levels = {}
        self.time = label("", "status-time")
        self.date = label("", "status-date")
        box.pack_start(self.time, False, False, 0)
        box.pack_start(self.date, False, False, 0)
        self.tick()

        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        rows.get_style_context().add_class("status-rows")
        box.pack_start(rows, False, False, 0)

        vol = d["volume"]
        if vol:
            self.levels["volume"] = self.level_row("sound", vol[0], applets.set_volume)
            if vol[1]:
                self.levels["volume"].set_level(vol[0], True)
            rows.pack_start(self.levels["volume"], False, False, 0)
        # Speakers and microphones: rebuilt when a bluetooth headset comes or goes.
        self.audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        rows.pack_start(self.audio, False, False, 0)
        self.fill_audio(d["outputs"], d["inputs"])
        if d["brightness"] is not None:
            self.levels["brightness"] = self.level_row("brightness", d["brightness"], applets.set_brightness)
            rows.pack_start(self.levels["brightness"], False, False, 0)

        net = d["net"]
        if d["nmcli"]:
            self.net = self.expander("network", net or "not connected", self.network_applet)
            rows.pack_start(self.net, False, False, 0)
        else:
            rows.pack_start(self.pair("network", net or "not connected"), False, False, 0)
        if d["bluetooth"]:
            self.bt = self.expander("bluetooth", "", self.bluetooth_applet)
            rows.pack_start(self.bt, False, False, 0)
            bt = self.bt
            applets.bluetooth._async(lambda: (bluetooth.powered(), bluetooth.connected_names()),
                                     lambda result: bt is self.bt and self.show_bluetooth(result))
        pct, state, left = d["battery"]
        if pct is not None:
            detail = "%d%%" % pct
            if "charg" in state and "dis" not in state:
                detail += " · charging"
            elif left:
                detail += " · " + left.replace(" until empty", " left")
        else:
            detail = "plugged in"
        names, cur = d["profiles"]
        if names:
            rows.pack_start(self.expander("battery" if pct is not None else "power",
                                          detail + " · " + PROFILE_NAMES.get(cur, cur),
                                          lambda row: self.power_modes(row, names, cur, detail)),
                            False, False, 0)
        elif pct is not None:
            rows.pack_start(self.pair("battery", detail), False, False, 0)
        self.quiet = self.pair("quiet hours", "on" if d["dnd"] else "off", self.toggle_dnd)
        rows.pack_start(self.quiet, False, False, 0)
        # Settings can take caffeine out of the panel; it still shows while on,
        # so it can always be switched off from here.
        shown, on = d["caffeine"]
        if shown or on:
            self.caffeine = self.pair("caffeine", "on" if on else "off", self.toggle_caffeine)
            rows.pack_start(self.caffeine, False, False, 0)
        updates = d["updates"]
        if updates:
            rows.pack_start(self.pair(
                "tubewm", "%d update%s" % (updates, "" if updates == 1 else "s"),
                lambda: self.run_and_close(os.path.join(common.HOME, ".local", "bin", "tube-update"))),
                False, False, 0)

        notes = d["notes"]
        if notes:
            head = Gtk.Box()
            head.get_style_context().add_class("status-notes-head")
            head.pack_start(label("notifications", "status-header"), False, False, 0)
            head.pack_end(word_button("clear", self.clear_notes, "status-small"), False, False, 0)
            box.pack_start(head, False, False, 0)
            for n in notes:
                item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                item.get_style_context().add_class("status-note")
                item.pack_start(label(n["summary"] or n["app"], "status-note-title"), False, False, 0)
                if n["body"]:
                    body = label(n["body"].splitlines()[0][:80], "status-note-body")
                    item.pack_start(body, False, False, 0)
                box.pack_start(item, False, False, 0)

        power = Gtk.Box(spacing=24)
        power.get_style_context().add_class("status-power")
        for text, cmd in (("lock", "tube-lock"), ("sleep", "systemctl suspend"),
                          ("sign out", "swaymsg exit" if os.environ.get("SWAYSOCK")
                           else 'loginctl terminate-session "$XDG_SESSION_ID"'),
                          ("restart", "systemctl reboot"), ("shut down", "systemctl poweroff")):
            power.pack_start(word_button(text, lambda c=cmd: self.run_and_close(c)), False, False, 0)
        box.pack_end(power, False, False, 0)
        box.show_all()
        self.audio.set_visible(bool(self.audio.get_children()))

    # ── rows ─────────────────────────────────────────────────────────
    def pair(self, name, value, on_click=None):
        row = Gtk.Box()
        row.pack_start(label(name, "status-name"), False, False, 0)
        val = label(value, "status-value", xalign=1.0)
        row.pack_end(val, False, False, 0)
        row.value = val
        if on_click:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("status-row-button")
            b.add(row)
            b.connect("clicked", lambda *_: (self.touch(), on_click()))
            b.value = val
            return b
        return row

    def expander(self, name, value, make):
        """A row that opens up when clicked. make(row) builds what's inside
        the first time it opens, so nothing slow runs until you ask."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        reveal = Gtk.Revealer()
        reveal.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        reveal.set_transition_duration(180)

        def toggle():
            if not reveal.get_child():
                inner = make(box)
                inner.get_style_context().add_class("status-inside")
                # A long list of networks scrolls rather than pushing the
                # power words off the bottom of the screen.
                scroll = Gtk.ScrolledWindow()
                scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
                scroll.set_propagate_natural_height(True)
                scroll.set_max_content_height(INSIDE_MAX)
                scroll.add(inner)
                reveal.add(scroll)
                scroll.show_all()
            reveal.set_reveal_child(not reveal.get_reveal_child())
        row = self.pair(name, value, toggle)
        row.value.set_ellipsize(Pango.EllipsizeMode.END)
        row.value.set_max_width_chars(26)
        box.pack_start(row, False, False, 0)
        box.pack_start(reveal, False, False, 0)
        box.value = row.value
        return box

    def power_modes(self, row, names, cur, detail):
        """Battery saver / balanced / performance, as words: the one in use
        is in the accent colour."""
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        listing.get_style_context().add_class("status-devices")
        order = [n for n in ("power-saver", "balanced", "performance") if n in names]
        order += [n for n in names if n not in order]

        def pick(n):
            applets.run(["powerprofilesctl", "set", n])
            now = applets.run(["powerprofilesctl", "get"]) or n
            row.value.set_text(detail + " · " + PROFILE_NAMES.get(now, now))
            for b in listing.get_children():
                ctx = b.get_style_context()
                (ctx.add_class if b.mode == now else ctx.remove_class)("current")
        for n in order:
            b = word_button(PROFILE_NAMES.get(n, n), lambda n=n: pick(n), "status-device")
            b.mode = n
            b.get_child().set_xalign(0.0)
            if n == cur:
                b.get_style_context().add_class("current")
            listing.pack_start(b, False, False, 0)
        return listing

    def network_applet(self, _row):
        applet = applets.Network()
        applet.closes = self.quit
        return applet

    def bluetooth_applet(self, _row):
        applet = applets.Bluetooth()
        applet.closes = self.quit
        # Connecting a headset adds speakers; show them, and the row's words.
        applet.on_change = self.after_bluetooth
        return applet

    def show_bluetooth(self, result):
        if not result:
            return
        on, names = result
        self.bt.value.set_text(", ".join(names).lower() if names and on else "on" if on else "off")

    def after_bluetooth(self):
        applets.bluetooth._async(lambda: (bluetooth.powered(), bluetooth.connected_names()),
                                 self.show_bluetooth)
        # The sound server takes a moment to offer a headset once it connects.
        for delay in (2, 5):
            GLib.timeout_add_seconds(delay, lambda: self.fill_audio() or False)

    def fill_audio(self, outputs=None, inputs=None):
        if outputs is None:
            outputs, inputs = applets.audio_devices("output"), applets.audio_devices("input")
        for child in self.audio.get_children():
            self.audio.remove(child)
            child.destroy()
        for kind, devices in (("output", outputs), ("input", inputs)):
            if devices:
                self.audio.pack_start(self.device_row(kind, devices), False, False, 0)
        self.audio.set_visible(bool(self.audio.get_children()))
        self.audio.show_all()

    def device_row(self, kind, devices):
        """Which speakers (output) or microphone (input) to use. Click to
        see the others as a list of words; click one to switch to it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        current = next((d for _n, d, on in devices if on), devices[0][1])
        choose = Gtk.Revealer()
        choose.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        choose.set_transition_duration(180)
        row = self.pair(kind, current.lower(),
                        (lambda: choose.set_reveal_child(not choose.get_reveal_child()))
                        if len(devices) > 1 else None)
        row.value.set_ellipsize(Pango.EllipsizeMode.END)
        row.value.set_max_width_chars(26)
        box.pack_start(row, False, False, 0)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        listing.get_style_context().add_class("status-devices")
        for name, desc, on in devices:
            b = word_button(desc.lower(), lambda n=name, d=desc: pick(n, d), "status-device")
            if on:
                b.get_style_context().add_class("current")
            b.get_child().set_xalign(0.0)
            b.get_child().set_ellipsize(Pango.EllipsizeMode.END)
            listing.pack_start(b, False, False, 0)
        choose.add(listing)
        box.pack_start(choose, False, False, 0)

        def pick(name, desc):
            applets.set_audio_device(kind, name)
            row.value.set_text(desc.lower())
            for b in listing.get_children():
                ctx = b.get_style_context()
                (ctx.add_class if b.get_label() == desc.lower() else ctx.remove_class)("current")
            choose.set_reveal_child(False)
        return box

    def level_row(self, name, value, on_change):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        top = Gtk.Box()
        top.pack_start(label(name, "status-name"), False, False, 0)
        num = label(str(value), "status-value", xalign=1.0)
        top.pack_end(num, False, False, 0)
        box.pack_start(top, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_value(value)
        scale.get_style_context().add_class("status-line")
        pending = {}
        held = [False]   # the pointer is on the line, dragging it

        def changed(s):
            v = int(s.get_value())
            num.set_text(str(v))
            if pending.get("id"):
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(60, lambda: (on_change(v), pending.clear(), False)[2])
        handler = scale.connect("value-changed", changed)
        scale.connect("button-press-event", lambda *_: self.touch() or held.__setitem__(0, True) or False)
        scale.connect("button-release-event", lambda *_: held.__setitem__(0, False) or False)
        box.pack_start(scale, False, False, 0)

        def set_level(v, muted=False):
            """Moved from outside: show it, without sending it back."""
            if held[0] or pending.get("id"):
                return   # you're moving it; what you set wins
            scale.handler_block(handler)
            scale.set_value(v)
            scale.handler_unblock(handler)
            num.set_text("off" if muted else str(v))
        box.set_level = set_level
        return box

    def follow(self, kind, value, muted):
        row = self.levels.get(kind)
        if row is not None:
            row.set_level(value, muted)
        return False

    # ── actions ──────────────────────────────────────────────────────
    def touch(self):
        self.touched = True

    def tick(self):
        if self.away:
            return True   # nobody to see it; show() catches it up
        self.time.set_text(time.strftime("%H:%M"))
        self.date.set_text(time.strftime("%A %-d %B").lower())
        return True

    @staticmethod
    def dnd():
        return DND_MODE in applets.run(["makoctl", "mode"]).split()

    def toggle_dnd(self):
        applets.run(["makoctl", "mode", "-t", DND_MODE])
        self.quiet.value.set_text("on" if self.dnd() else "off")

    def toggle_caffeine(self):
        on = caffeine.set_active(not caffeine.active())
        self.caffeine.value.set_text("on" if on else "off")

    def clear_notes(self):
        applets.run(["makoctl", "dismiss", "--all"])
        notes = applets.notification_history()
        if notes:
            try:
                with open(applets.HISTORY_MARK, "w") as fh:
                    fh.write(str(max(n["id"] for n in notes)))
            except OSError:
                pass
        self.data = dict(self.data, notes=[])
        self.quit()

    def run_and_close(self, cmd):
        common.run_detached(cmd)
        self.quit()


def look_stamp():
    """When the accent, the palette or the stylesheets last changed."""
    stamps = []
    for path in (os.path.join(common.CONFIG, "tubewm", "accent"),
                 os.path.join(common.CONFIG, "tubewm", "user.css"),
                 os.path.join(common.SHELL_DIR, "style.css"),
                 common._palette_file() or ""):
        try:
            st = os.stat(path)
            stamps.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamps.append(None)
    return stamps


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-status", description=__doc__.splitlines()[0])
    parser.add_argument("--background", action="store_true",
                        help="get ready, closed, so the first click is quick (at login)")
    parser.add_argument("--close", action="store_true", help="close the panel if it is open")
    args = parser.parse_args(argv)

    if args.background:
        if resident.running("status"):
            return 0
    elif resident.send("status", signal.SIGHUP if args.close else signal.SIGUSR1, answer_within=1.0):
        return 0
    if args.close:
        return 0
    lock = resident.claim("status")
    if lock is None:
        return 0   # another copy is starting up right now
    # Before the level watcher starts its threads, so they inherit it too.
    resident.unblock(set(SIGNALS) | {signal.SIGTERM})
    if not sys.stderr.isatty():
        # Started by the compositor, which throws our output away.
        try:
            fd = os.open(resident.log_path("status"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.dup2(fd, 2)
            os.close(fd)
        except OSError:
            pass
    resident.log("status", "starting (%s)" % ("background" if args.background else "shown"))
    faulthandler.register(resident.DUMP, all_threads=True)
    status = Status(shown=not args.background)
    for sig, what in SIGNALS.items():
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_a, w=what: status.on_signal(w))
    resident.announce("status")
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
