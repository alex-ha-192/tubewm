"""tube-charms: the right-edge charms bar with its clock card. The settings
and devices charms open tube-settings. Click anywhere else or press Escape
to dismiss."""

import argparse
import datetime
import os

from . import common, glyphs, tiles

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

BAR_WIDTH = 86

CHARMS = [
    ("search", "search"),
    ("share", "share"),
    ("start", "start"),
    ("devices", "devices"),
    ("settings", "settings"),
]


class Charms:
    def __init__(self, page):
        self.pal = common.apply_css()
        self.win = common.make_layer_window("charms", transparent=True)
        self.win.connect("key-press-event", self.on_key)

        overlay = Gtk.Overlay()
        self.win.add(overlay)

        # Light dismiss: clicks on the empty part of the screen close us.
        catcher = Gtk.EventBox()
        catcher.set_visible_window(False)
        catcher.connect("button-press-event", lambda *_: self.quit())
        catcher.connect("touch-event", lambda *_: self.quit())
        overlay.add(catcher)

        self.side = Gtk.Revealer()
        self.side.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.side.set_transition_duration(220)
        self.side.set_halign(Gtk.Align.END)
        self.side.set_valign(Gtk.Align.FILL)
        overlay.add_overlay(self.side)

        self.pages = Gtk.Stack()
        self.pages.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.pages.set_transition_duration(200)
        self.pages.set_hhomogeneous(False)
        self.pages.set_interpolate_size(True)
        self.side.add(self.pages)
        self.pages.add_named(self.build_bar(), "bar")

        self.card = Gtk.Revealer()
        self.card.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.card.set_transition_duration(260)
        self.card.set_halign(Gtk.Align.START)
        self.card.set_valign(Gtk.Align.END)
        self.card.set_margin_start(60)
        self.card.set_margin_bottom(60)
        self.card.add(self.build_clock())
        overlay.add_overlay(self.card)

        self.win.show_all()
        self.go(page)
        GLib.idle_add(self._reveal)
        GLib.timeout_add_seconds(5, self.update_clock)

    def _reveal(self):
        self.side.set_reveal_child(True)
        self.card.set_reveal_child(self.pages.get_visible_child_name() == "bar")
        return False

    def go(self, page):
        self.pages.set_visible_child_name(page)
        self.card.set_reveal_child(page == "bar")
        child = self.pages.get_visible_child()
        child.child_focus(Gtk.DirectionType.TAB_FORWARD)

    # ── bar ──────────────────────────────────────────────────────────
    def build_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar.get_style_context().add_class("charms-bar")
        bar.set_size_request(BAR_WIDTH, -1)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_valign(Gtk.Align.CENTER)
        col.set_vexpand(True)
        for name, label in CHARMS:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("charm")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            inner.pack_start(glyphs.Glyph(name, 30), False, False, 0)
            inner.pack_start(Gtk.Label(label=label), False, False, 0)
            btn.add(inner)
            btn.connect("clicked", self.on_charm, name)
            col.pack_start(btn, False, False, 0)
        bar.pack_start(col, True, True, 0)
        return bar

    def on_charm(self, _btn, name):
        if name == "search":
            self.run_and_quit("tube-start --search")
        elif name == "start":
            self.run_and_quit("tube-start")
        elif name == "share":
            # Wait for the charms to leave the screen before capturing.
            self.run_and_quit("sleep 0.35; tube-share")
        elif name in ("settings", "devices"):
            self.run_and_quit("tube-settings " + ("devices" if name == "devices" else ""))

    # ── clock card ───────────────────────────────────────────────────
    def build_clock(self):
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        card.get_style_context().add_class("clock-card")
        self.time_label = Gtk.Label(xalign=0)
        self.time_label.get_style_context().add_class("clock-time")
        card.pack_start(self.time_label, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.set_valign(Gtk.Align.CENTER)
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.get_style_context().add_class("clock-status")
        self.day_label = Gtk.Label(xalign=0)
        self.day_label.get_style_context().add_class("clock-date")
        self.date_label = Gtk.Label(xalign=0)
        self.date_label.get_style_context().add_class("clock-date")
        for w in (self.status_label, self.day_label, self.date_label):
            right.pack_start(w, False, False, 0)
        card.pack_start(right, False, False, 0)
        self.update_clock()
        return card

    def update_clock(self):
        now = datetime.datetime.now()
        self.time_label.set_text(now.strftime("%H:%M"))
        self.day_label.set_text(now.strftime("%A").lower())
        self.date_label.set_text(now.strftime("%B %-d").lower())
        bits = []
        cap, status = tiles._battery()
        if cap is not None:
            bits.append("%d%%%s" % (cap, " charging" if status == "charging" else ""))
        net = network_name()
        if net:
            bits.append(net)
        self.status_label.set_text("   ·   ".join(bits))
        return True

    # ── misc ─────────────────────────────────────────────────────────
    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.quit()
            return True
        return False

    def run_and_quit(self, cmd):
        self.win.hide()
        common.run_detached(cmd)
        GLib.idle_add(self.quit)

    def quit(self, *_):
        Gtk.main_quit()
        return False


def network_name():
    if common.have("nmcli"):
        for line in common.sh("nmcli -t -f TYPE,STATE,CONNECTION device").splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "connected" and parts[0] in ("wifi", "ethernet"):
                return parts[2] if parts[0] == "wifi" else "wired"
    if os.path.isdir("/sys/class/net"):
        for iface in sorted(os.listdir("/sys/class/net")):
            if iface == "lo":
                continue
            try:
                with open("/sys/class/net/%s/operstate" % iface) as fh:
                    if fh.read().strip() == "up":
                        return iface
            except OSError:
                continue
    return ""


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-charms", description=__doc__.splitlines()[0])
    # Settings used to be a flyout here; the flags still work for old configs.
    parser.add_argument("--settings", action="store_true", help="open tube-settings")
    parser.add_argument("--power", action="store_true", help="open the side panel, for power")
    parser.add_argument("--devices", action="store_true", help="open tube-settings on devices")
    parser.add_argument("--close", action="store_true", help="close the charms if open")
    args = parser.parse_args(argv)
    if args.settings or args.devices or args.power:
        from . import settings, status
        if args.power:
            return status.main([])
        return settings.main(["devices"] if args.devices else [])
    if not common.toggle_instance("charms", close_only=args.close):
        return 0
    Charms("bar")
    Gtk.main()
    return 0
