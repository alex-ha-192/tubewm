"""tube-charms: the right-edge charms bar with its clock card. The settings
and devices charms open tube-settings. Click anywhere else or press Escape
to dismiss."""

import argparse
import datetime
import os

from . import bluetooth, common, glyphs, tiles

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

    # ── settings flyout ──────────────────────────────────────────────
    def flyout(self, title):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(FLYOUT_WIDTH, -1)
        scroll.set_propagate_natural_width(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.get_style_context().add_class("flyout")
        box.set_vexpand(True)
        head = Gtk.Label(label=title, xalign=0)
        head.get_style_context().add_class("page-header")
        box.pack_start(head, False, False, 0)
        scroll.add(box)
        return scroll, box

    def build_settings(self):
        scroll, box = self.flyout("settings")

        box.pack_start(_section("accent"), False, False, 0)
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_max_children_per_line(6)
        grid.set_min_children_per_line(6)
        grid.set_column_spacing(4)
        grid.set_row_spacing(4)
        grid.set_homogeneous(True)
        self.swatches = []
        for name, hex_ in common.named_accents():
            sw = Gtk.Button()
            sw.set_tooltip_text(name)
            sw.get_style_context().add_class("swatch")
            prov = Gtk.CssProvider()
            prov.load_from_data((".swatch { background: %s; }" % hex_).encode())
            sw.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            sw.hex = hex_
            sw.connect("clicked", self.on_accent, name)
            grid.add(sw)
            self.swatches.append(sw)
        self.mark_accent()
        box.pack_start(grid, False, False, 0)

        box.pack_start(_section("wallpaper"), False, False, 0)
        box.pack_start(self.build_wallpapers(), False, False, 0)

        if common.have("wpctl"):
            box.pack_start(_section("volume"), False, False, 0)
            vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            vol.set_draw_value(False)
            vol.set_value(volume_get())
            vol.connect("value-changed", lambda s: common.sh(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "%d%%" % s.get_value()]))
            box.pack_start(vol, False, False, 0)

        if common.have("brightnessctl"):
            box.pack_start(_section("brightness"), False, False, 0)
            bri = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
            bri.set_draw_value(False)
            try:
                bri.set_value(100 * int(common.sh("brightnessctl get")) /
                              max(1, int(common.sh("brightnessctl max"))))
            except ValueError:
                pass
            bri.connect("value-changed", lambda s: common.sh(
                ["brightnessctl", "-q", "set", "%d%%" % s.get_value()]))
            box.pack_start(bri, False, False, 0)

        toggles = Gtk.Box(spacing=8)
        if common.have("makoctl"):
            dnd = _button("do not disturb", self.on_dnd)
            if "do-not-disturb" in common.sh("makoctl mode"):
                dnd.get_style_context().add_class("toggle-on")
            toggles.pack_start(dnd, False, False, 0)
        if common.have("nmcli"):
            wifi = _button("wi-fi", self.on_wifi)
            if common.sh("nmcli radio wifi") == "enabled":
                wifi.get_style_context().add_class("toggle-on")
            toggles.pack_start(wifi, False, False, 0)
        if bluetooth.available():
            bt = _button("bluetooth", self.on_bluetooth)
            if bluetooth.powered():
                bt.get_style_context().add_class("toggle-on")
            toggles.pack_start(bt, False, False, 0)
        if toggles.get_children():
            box.pack_start(_section("quick"), False, False, 0)
            box.pack_start(toggles, False, False, 0)

        box.pack_start(_section("power"), False, False, 0)
        power = Gtk.FlowBox()
        power.set_selection_mode(Gtk.SelectionMode.NONE)
        power.set_max_children_per_line(2)
        power.set_column_spacing(8)
        power.set_row_spacing(8)
        for label, cmd, confirm in (
            ("lock", "tube-lock", False),
            ("sleep", "systemctl suspend", False),
            ("sign out", "swaymsg exit" if os.environ.get("SWAYSOCK")
             else 'loginctl terminate-session "$XDG_SESSION_ID"', True),
            ("restart", "systemctl reboot", True),
            ("shut down", "systemctl poweroff", True),
        ):
            btn = _button(label, self.on_power)
            btn.cmd, btn.confirm, btn.text = cmd, confirm, label
            power.add(btn)
        box.pack_start(power, False, False, 0)

        box.pack_start(_section("start"), False, False, 0)
        box.pack_start(_text("Drag tiles to move them. Right-click one to resize, recolour, "
                             "set up or unpin it. Right-click an app in the list to pin it."),
                       False, False, 0)
        reset = _button("reset start to the default tiles", self.on_reset_start, "link")
        box.pack_start(reset, False, False, 0)
        return scroll

    def on_reset_start(self, btn):
        if not btn.get_style_context().has_class("armed-link"):
            btn.get_style_context().add_class("armed-link")
            btn.set_label("click again to reset your tiles")
            return
        from . import layout
        layout.reset()
        btn.get_style_context().remove_class("armed-link")
        btn.set_label("start tiles reset")

    def build_wallpapers(self):
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_max_children_per_line(3)
        grid.set_min_children_per_line(3)
        grid.set_column_spacing(4)
        grid.set_row_spacing(4)
        grid.set_homogeneous(True)
        self.walls = []
        try:
            from . import wallpaper
        except ImportError:  # no pycairo
            return _text("Install pycairo for wallpapers.")
        cur = wallpaper.current()
        for name, (_fn, blurb) in wallpaper.STYLES.items():
            btn = Gtk.Button()
            btn.get_style_context().add_class("wall")
            btn.set_tooltip_text("%s: %s" % (name, blurb))
            surf = wallpaper.render(name, 90, 51)
            pb = Gdk.pixbuf_get_from_surface(surf, 0, 0, 90, 51)
            btn.add(Gtk.Image.new_from_pixbuf(pb))
            btn.name = name
            btn.connect("clicked", self.on_wallpaper)
            if name == cur:
                btn.get_style_context().add_class("current")
            grid.add(btn)
            self.walls.append(btn)
        off = _button("none", self.on_wallpaper, "wall-off")
        off.name = "off"
        grid.add(off)
        self.walls.append(off)
        return grid

    def on_wallpaper(self, btn):
        common.sh(["tube-wallpaper", btn.name], timeout=20)
        for b in self.walls:
            ctx = b.get_style_context()
            (ctx.add_class if b is btn else ctx.remove_class)("current")

    def mark_accent(self):
        cur = common.load_palette()["ACCENT"]
        for sw in self.swatches:
            ctx = sw.get_style_context()
            (ctx.add_class if sw.hex == cur else ctx.remove_class)("current")

    def on_accent(self, _btn, name):
        common.sh(["tube-accent", name], timeout=20)
        common.apply_css()
        self.mark_accent()
        if hasattr(self, "walls"):
            from . import wallpaper
            for b in self.walls:
                if b.name in wallpaper.STYLES:
                    surf = wallpaper.render(b.name, 90, 51)
                    b.get_child().set_from_pixbuf(Gdk.pixbuf_get_from_surface(surf, 0, 0, 90, 51))

    def on_dnd(self, btn):
        common.sh("makoctl mode -t do-not-disturb")
        ctx = btn.get_style_context()
        (ctx.add_class if "do-not-disturb" in common.sh("makoctl mode") else ctx.remove_class)("toggle-on")

    def on_wifi(self, btn):
        on = common.sh("nmcli radio wifi") == "enabled"
        common.sh(["nmcli", "radio", "wifi", "off" if on else "on"], timeout=5)
        ctx = btn.get_style_context()
        (ctx.remove_class if on else ctx.add_class)("toggle-on")

    def on_bluetooth(self, btn):
        on = bluetooth.powered()
        bluetooth.set_powered(not on)
        ctx = btn.get_style_context()
        (ctx.add_class if bluetooth.powered() else ctx.remove_class)("toggle-on")

    def on_power(self, btn):
        ctx = btn.get_style_context()
        if btn.confirm and not ctx.has_class("armed"):
            ctx.add_class("armed")
            btn.set_label("%s now?" % btn.text)
            GLib.timeout_add_seconds(4, self._disarm, btn)
            return
        self.run_and_quit(btn.cmd)

    @staticmethod
    def _disarm(btn):
        btn.get_style_context().remove_class("armed")
        btn.set_label(btn.text)
        return False

    # ── devices flyout ───────────────────────────────────────────────
    def build_devices(self):
        scroll, box = self.flyout("devices")
        box.pack_start(_section("displays"), False, False, 0)
        outputs = []
        try:
            outputs = json.loads(common.sh("swaymsg -r -t get_outputs") or "[]")
        except ValueError:
            pass
        active = [o for o in outputs if o.get("active")]
        for out in outputs:
            mode = out.get("current_mode") or {}
            desc = " ".join(filter(None, [out.get("make"), out.get("model")])).strip()
            line = Gtk.Box(spacing=10)
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            info.pack_start(Gtk.Label(label=out.get("name", "?"), xalign=0), False, False, 0)
            detail = desc
            if mode:
                detail += "  %dx%d" % (mode.get("width", 0), mode.get("height", 0))
            info.pack_start(_text(detail.strip() or "display"), False, False, 0)
            line.pack_start(info, True, True, 0)
            toggle = None
            if out.get("active") and len(active) > 1:
                toggle = _button("turn off", self.on_output)
                toggle.output = (out["name"], "disable")
            elif not out.get("active"):
                toggle = _button("turn on", self.on_output)
                toggle.output = (out["name"], "enable")
            if toggle is not None:
                toggle.set_valign(Gtk.Align.CENTER)
                line.pack_end(toggle, False, False, 0)
            box.pack_start(line, False, False, 0)
        if not outputs:
            box.pack_start(_text("No displays reported by sway."), False, False, 0)

        apps = [("sound", "pavucontrol"), ("bluetooth", "blueman-manager"),
                ("network", "nm-connection-editor"), ("printers", "system-config-printer")]
        shown = [(t, c) for t, c in apps if common.have(c)]
        if shown:
            box.pack_start(_section("more devices"), False, False, 0)
            for title, cmd in shown:
                box.pack_start(_button(title, lambda _b, c=cmd: self.run_and_quit(c), "link"),
                               False, False, 0)
        return scroll

    def on_output(self, btn):
        name, action = btn.output
        common.sh(["swaymsg", "output", name, action])
        self.quit()

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
