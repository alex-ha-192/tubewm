"""tube-status: everything that isn't an app, in one panel on the right.

Click the time on the strip to open it. A big clock and the date, sound and
brightness as thin lines you drag, wi-fi, battery and quiet hours, your
notifications, and lock / sleep / sign out / restart / shut down as words.
Click outside it, or press Escape, to close it.
"""

import os
import sys
import time

from . import applets, common

from gi.repository import GLib, Gtk  # noqa: E402

WIDTH = 460
DND_MODE = "do-not-disturb"


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


class Status:
    def __init__(self):
        common.apply_css()
        win = common.make_layer_window("status", transparent=True, layer="overlay")
        common.below_strip(win)
        common.main_quit_on_escape(win)
        catcher = Gtk.EventBox()
        catcher.connect("button-press-event", lambda *_: Gtk.main_quit())
        win.add(catcher)

        panel = Gtk.EventBox(halign=Gtk.Align.END)
        panel.connect("button-press-event", lambda *_: True)
        panel.get_style_context().add_class("status")
        panel.set_size_request(WIDTH, -1)
        catcher.add(panel)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("status-box")
        panel.add(box)

        self.time = label("", "status-time")
        self.date = label("", "status-date")
        box.pack_start(self.time, False, False, 0)
        box.pack_start(self.date, False, False, 0)

        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        rows.get_style_context().add_class("status-rows")
        box.pack_start(rows, False, False, 0)

        vol = applets.volume()
        if vol and vol[0] is not None:
            rows.pack_start(self.level_row("sound", vol[0], applets.set_volume), False, False, 0)
        light = applets.brightness()
        if light is not None:
            rows.pack_start(self.level_row(
                "brightness", light,
                lambda v: applets.run(["brightnessctl", "-q", "set", "%d%%" % max(1, v)])), False, False, 0)

        net = applets._net_text()
        rows.pack_start(self.pair("network", net or "not connected",
                                  lambda: common.run_detached("nm-connection-editor")
                                  if common.have("nm-connection-editor") else None), False, False, 0)
        pct, state, left = applets.battery_info()
        if pct is not None:
            detail = "%d%%" % pct
            if "charg" in state and "dis" not in state:
                detail += " · charging"
            elif left:
                detail += " · " + left.replace(" until empty", " left")
            rows.pack_start(self.pair("battery", detail), False, False, 0)
        self.quiet = self.pair("quiet hours", "on" if self.dnd() else "off", self.toggle_dnd)
        rows.pack_start(self.quiet, False, False, 0)

        notes = applets.notification_history()[:4]
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

        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        win.show_all()

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
            b.connect("clicked", lambda *_: on_click())
            b.value = val
            return b
        return row

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

        def changed(s):
            v = int(s.get_value())
            num.set_text(str(v))
            if pending.get("id"):
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(60, lambda: (on_change(v), pending.clear(), False)[2])
        scale.connect("value-changed", changed)
        box.pack_start(scale, False, False, 0)
        return box

    # ── actions ──────────────────────────────────────────────────────
    def tick(self):
        self.time.set_text(time.strftime("%H:%M"))
        self.date.set_text(time.strftime("%A %-d %B").lower())
        return True

    @staticmethod
    def dnd():
        return DND_MODE in applets.run(["makoctl", "mode"]).split()

    def toggle_dnd(self):
        applets.run(["makoctl", "mode", "-t", DND_MODE])
        self.quiet.value.set_text("on" if self.dnd() else "off")

    def clear_notes(self):
        applets.run(["makoctl", "dismiss", "--all"])
        notes = applets.notification_history()
        if notes:
            try:
                with open(applets.HISTORY_MARK, "w") as fh:
                    fh.write(str(max(n["id"] for n in notes)))
            except OSError:
                pass
        Gtk.main_quit()

    def run_and_close(self, cmd):
        common.run_detached(cmd)
        Gtk.main_quit()


def main(argv=None):
    if not common.toggle_instance("status"):
        return 0
    Status()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
