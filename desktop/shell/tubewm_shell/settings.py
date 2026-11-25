"""tube-settings: every setting in one place, full screen, on true black.

    tube-settings [personalise | start | notifications | network | devices]

The categories run down the left under a big "settings"; the one you pick
fills the rest of the screen. This is the only settings surface: the start
screen's "settings", the settings shortcut tile, Super+I, the charms' settings
and devices charms and the bar's network item all open it. Sound, brightness
and power stay where they are quickest, in the side panel (tube-status).
Escape closes it.
"""

import argparse
import json
import os
import sys

from . import common, glyphs

from gi.repository import Gdk, GLib, Gtk  # noqa: E402

PAGES = ("personalise", "start", "notifications", "network", "devices")
GLYPH = {"personalise": "photo", "start": "start", "notifications": "bell",
         "network": "network", "devices": "devices"}
NAV_WIDTH = 420
DND_MODE = "do-not-disturb"


def _label(text, *classes, wrap=False):
    lab = Gtk.Label(label=text, xalign=0)
    for c in classes:
        lab.get_style_context().add_class(c)
    if wrap:
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
    return lab


def _button(text, cb, *classes):
    btn = Gtk.Button(label=text)
    btn.set_relief(Gtk.ReliefStyle.NONE)
    btn.set_halign(Gtk.Align.START)
    for c in classes:
        btn.get_style_context().add_class(c)
    btn.connect("clicked", cb)
    return btn


def _grid(per_line):
    grid = Gtk.FlowBox()
    grid.set_selection_mode(Gtk.SelectionMode.NONE)
    grid.set_max_children_per_line(per_line)
    grid.set_min_children_per_line(per_line)
    grid.set_column_spacing(6)
    grid.set_row_spacing(6)
    grid.set_homogeneous(True)
    grid.set_halign(Gtk.Align.START)
    return grid


class Settings:
    def __init__(self, page):
        common.apply_css()
        self.win = common.make_layer_window("settings")
        self.win.get_style_context().add_class("tube-settings")
        self.win.set_default_size(*common.monitor_size())
        common.main_quit_on_escape(self.win)

        root = Gtk.Box()
        root.get_style_context().add_class("settings-root")
        self.win.add(root)

        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav.get_style_context().add_class("settings-nav")
        nav.set_size_request(NAV_WIDTH, -1)
        nav.pack_start(_label("settings", "panorama-header", "settings-title"), False, False, 0)
        self.nav = {}
        for name in PAGES:
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("settings-cat")
            row = Gtk.Box(spacing=18)
            row.pack_start(glyphs.Glyph(GLYPH[name], 28), False, False, 0)
            row.pack_start(_label(name, "settings-cat-name"), False, False, 0)
            btn.add(row)
            btn.connect("clicked", lambda _b, n=name: self.go(n))
            nav.pack_start(btn, False, False, 0)
            self.nav[name] = btn
        close = _button("close", lambda *_: Gtk.main_quit(), "settings-link", "settings-close")
        nav.pack_end(close, False, False, 0)
        root.pack_start(nav, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.stack.set_transition_duration(220)
        for name in PAGES:
            self.stack.add_named(self.page(name, getattr(self, "build_" + name)()), name)
        root.pack_start(self.stack, True, True, 0)

        self.win.show_all()
        self.go(page)

    def go(self, name):
        self.stack.set_visible_child_name(name)
        for n, btn in self.nav.items():
            ctx = btn.get_style_context()
            (ctx.add_class if n == name else ctx.remove_class)("current")
        self.nav[name].grab_focus()

    @staticmethod
    def page(title, body):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.get_style_context().add_class("settings-page")
        box.pack_start(_label(title, "page-header", "settings-page-title"), False, False, 0)
        box.pack_start(body, False, False, 0)
        scroll.add(box)
        return scroll

    @staticmethod
    def section(box, title, blurb=None):
        box.pack_start(_label(title, "settings-section"), False, False, 0)
        if blurb:
            box.pack_start(_label(blurb, "settings-text", wrap=True), False, False, 0)

    # ── personalise ──────────────────────────────────────────────────
    def build_personalise(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.section(box, "accent", "The colour of start, tiles, highlights and the bar. "
                                    "Your apps and terminal follow it.")
        grid = _grid(6)
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

        self.section(box, "wallpaper", "Drawn in your accent colour, so it changes with it.")
        box.pack_start(self.build_wallpapers(), False, False, 0)
        return box

    def build_wallpapers(self):
        self.walls = []
        try:
            from . import wallpaper
        except ImportError:  # no pycairo
            return _label("Install pycairo for wallpapers.", "settings-text")
        grid = _grid(4)
        cur = wallpaper.current()
        for name, (_fn, blurb) in wallpaper.STYLES.items():
            btn = Gtk.Button()
            btn.get_style_context().add_class("wall")
            btn.set_tooltip_text("%s: %s" % (name, blurb))
            btn.add(Gtk.Image.new_from_pixbuf(self.thumb(wallpaper, name)))
            btn.name = name
            btn.connect("clicked", self.on_wallpaper)
            if name == cur:
                btn.get_style_context().add_class("current")
            grid.add(btn)
            self.walls.append(btn)
        off = _button("none", self.on_wallpaper, "wall-off")
        off.set_halign(Gtk.Align.FILL)
        off.name = "off"
        grid.add(off)
        self.walls.append(off)
        return grid

    @staticmethod
    def thumb(wallpaper, name, w=160, h=90):
        return Gdk.pixbuf_get_from_surface(wallpaper.render(name, w, h), 0, 0, w, h)

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
        self.win.get_style_context().add_class("tube-settings")
        self.mark_accent()
        if self.walls:
            from . import wallpaper
            for b in self.walls:
                if b.name in wallpaper.STYLES:
                    b.get_child().set_from_pixbuf(self.thumb(wallpaper, b.name))

    # ── start ────────────────────────────────────────────────────────
    def build_start(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.section(box, "tiles", "Drag tiles to move them. Right-click one to resize, recolour, "
                                   "set it up or unpin it. Right-click an app in the list to pin it.")
        box.pack_start(_button("reset start to the default tiles", self.on_reset_start,
                               "settings-link"), False, False, 0)
        return box

    @staticmethod
    def on_reset_start(btn):
        ctx = btn.get_style_context()
        if not ctx.has_class("armed-link"):
            ctx.add_class("armed-link")
            btn.set_label("click again to reset your tiles")
            return
        from . import layout
        layout.reset()
        ctx.remove_class("armed-link")
        btn.set_label("start tiles reset")

    # ── notifications ────────────────────────────────────────────────
    def build_notifications(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        if not common.have("makoctl"):
            box.pack_start(_label("Notifications come from mako, which isn't installed.",
                                  "settings-text", wrap=True), False, False, 0)
            return box
        self.section(box, "quiet hours", "Hide notification pop-ups. They still collect "
                                         "in the side panel.")
        box.pack_start(self.switch(DND_MODE in common.sh(["makoctl", "mode"]).split(),
                                   self.on_dnd), False, False, 0)
        return box

    def on_dnd(self, on):
        common.sh(["makoctl", "mode", "-a" if on else "-r", DND_MODE])

    # ── network ──────────────────────────────────────────────────────
    def build_network(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        from .charms import network_name
        self.section(box, "connected to", None)
        box.pack_start(_label(network_name() or "nothing", "settings-value"), False, False, 0)
        if common.have("nmcli"):
            self.section(box, "wi-fi")
            box.pack_start(self.switch(common.sh(["nmcli", "radio", "wifi"]) == "enabled",
                                       lambda on: common.sh(["nmcli", "radio", "wifi",
                                                             "on" if on else "off"], timeout=5)),
                           False, False, 0)
        if common.have("nm-connection-editor"):
            box.pack_start(_button("edit connections", lambda *_: self.run_and_quit(
                "nm-connection-editor"), "settings-link"), False, False, 0)
        return box

    # ── devices ──────────────────────────────────────────────────────
    def build_devices(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.section(box, "displays")
        outputs = displays()
        active = [o for o in outputs if o["active"]]
        for out in outputs:
            line = Gtk.Box(spacing=24)
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            info.pack_start(_label(out["name"], "settings-value"), False, False, 0)
            info.pack_start(_label(out["detail"] or "display", "settings-text"), False, False, 0)
            line.pack_start(info, False, False, 0)
            if out["active"] and len(active) > 1:
                line.pack_start(self.output_button("turn off", out["name"], False), False, False, 0)
            elif not out["active"]:
                line.pack_start(self.output_button("turn on", out["name"], True), False, False, 0)
            box.pack_start(line, False, False, 0)
        if not outputs:
            box.pack_start(_label("Install wlr-randr to see your displays here.",
                                  "settings-text"), False, False, 0)

        apps = [("arrange displays", "wdisplays"), ("sound", "pavucontrol"),
                ("bluetooth", "blueman-manager"), ("printers", "system-config-printer")]
        shown = [(t, c) for t, c in apps if common.have(c)]
        if shown:
            self.section(box, "more devices")
            for title, cmd in shown:
                box.pack_start(_button(title, lambda _b, c=cmd: self.run_and_quit(c),
                                       "settings-link"), False, False, 0)
        return box

    def output_button(self, text, name, on):
        btn = _button(text, lambda *_: (set_display(name, on), Gtk.main_quit()), "settings-button")
        btn.set_valign(Gtk.Align.CENTER)
        return btn

    # ── bits ─────────────────────────────────────────────────────────
    @staticmethod
    def switch(state, on_change):
        """A Metro toggle: the switch, then "on" / "off" beside it."""
        row = Gtk.Box(spacing=16)
        sw = Gtk.Switch()
        sw.set_active(state)
        sw.set_valign(Gtk.Align.CENTER)
        word = _label("on" if state else "off", "settings-value")

        def flipped(s, _pspec):
            word.set_text("on" if s.get_active() else "off")
            on_change(s.get_active())
        sw.connect("notify::active", flipped)
        row.pack_start(sw, False, False, 0)
        row.pack_start(word, False, False, 0)
        return row

    def run_and_quit(self, cmd):
        self.win.hide()
        common.run_detached(cmd)
        GLib.idle_add(Gtk.main_quit)


def displays():
    """[{name, detail, active}] from sway, or from wlr-randr elsewhere."""
    found = []
    if os.environ.get("SWAYSOCK") and common.have("swaymsg"):
        try:
            outs = json.loads(common.sh(["swaymsg", "-r", "-t", "get_outputs"]) or "[]")
        except ValueError:
            outs = []
        for o in outs:
            mode = o.get("current_mode") or {}
            detail = " ".join(filter(None, [o.get("make"), o.get("model")])).strip()
            if mode:
                detail += "  %dx%d" % (mode.get("width", 0), mode.get("height", 0))
            found.append({"name": o.get("name", "?"), "detail": detail.strip(),
                          "active": bool(o.get("active"))})
    elif common.have("wlr-randr"):
        try:
            outs = json.loads(common.sh(["wlr-randr", "--json"]) or "[]")
        except ValueError:
            outs = []
        for o in outs:
            mode = next((m for m in o.get("modes", []) if m.get("current")), {})
            detail = " ".join(filter(None, [o.get("make"), o.get("model")])).strip()
            if mode:
                detail += "  %dx%d" % (mode.get("width", 0), mode.get("height", 0))
            found.append({"name": o.get("name", "?"), "detail": detail.strip(),
                          "active": bool(o.get("enabled"))})
    return found


def set_display(name, on):
    if os.environ.get("SWAYSOCK") and common.have("swaymsg"):
        common.sh(["swaymsg", "output", name, "enable" if on else "disable"])
    elif common.have("wlr-randr"):
        common.sh(["wlr-randr", "--output", name, "--on" if on else "--off"])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-settings", description=__doc__.splitlines()[0])
    parser.add_argument("page", nargs="?", default=PAGES[0], choices=PAGES)
    parser.add_argument("--close", action="store_true", help="close settings if open")
    args = parser.parse_args(argv)
    if not common.toggle_instance("settings", close_only=args.close):
        return 0
    Settings(args.page)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
