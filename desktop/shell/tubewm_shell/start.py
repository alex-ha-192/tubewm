"""tube-start: the start screen.

A full-screen panorama of tile groups that scrolls sideways, an "all apps"
list you reach by typing or with the link at the bottom, and a semantic
zoom (Ctrl+minus) that shrinks the groups to big names for quick jumping.
"""

import argparse
import os
import pwd
import sys

from . import common, tiles

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib  # type: ignore

CONFIG_PATH = os.path.join(common.CONFIG, "tubewm", "start.toml")
DEFAULT_CONFIG = os.path.join(common.SHELL_DIR, "..", "start", "start.toml")

ROW_PX = tiles.UNIT + tiles.GUTTER
LEFT = 120  # left margin of the panorama, in px


def load_config():
    for path in (CONFIG_PATH, DEFAULT_CONFIG):
        if os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    return tomllib.load(fh)
            except (OSError, tomllib.TOMLDecodeError) as err:
                print("tube-start: can't read %s: %s" % (path, err), file=sys.stderr)
    return {"group": []}


BAND = 4  # tiles are packed into bands four units wide, like a wide tile


def pack(specs, rows):
    """First fit, row by row, inside bands BAND units wide; when a band is
    full the next one starts to its right. 2x2 and bigger tiles sit on even
    cells so small tiles cluster in 2x2 blocks. Returns [(spec, col, row)]
    and the group's width in units."""
    occupied = set()
    placed = []
    width = 0
    for spec in specs:
        w, h = tiles.SIZES.get(spec.get("size", "medium"), (2, 2))
        w, h = min(w, BAND), min(h, rows)
        step = 1 if (w, h) == (1, 1) else 2
        band = 0
        while band < 100:
            spot = None
            for row in range(0, rows - h + 1, step):
                for col in range(band * BAND, band * BAND + BAND - w + 1, step):
                    cells = {(col + dx, row + dy) for dx in range(w) for dy in range(h)}
                    if not cells & occupied:
                        spot = (col, row, cells)
                        break
                if spot:
                    break
            if spot:
                col, row, cells = spot
                occupied |= cells
                placed.append((spec, col, row))
                width = max(width, col + w)
                break
            band += 1
    return placed, width


def user_name():
    try:
        pw = pwd.getpwuid(os.getuid())
        return (pw.pw_gecos.split(",")[0] or pw.pw_name).strip()
    except KeyError:
        return os.environ.get("USER", "")


class StartScreen:
    def __init__(self, mode):
        self.pal = common.apply_css()
        self.cfg = load_config()
        settings = self.cfg.get("start", {})
        self.win = common.make_layer_window("start")
        self.win.connect("key-press-event", self.on_key)

        _w, screen_h = common.monitor_size()
        rows = settings.get("rows") or max(4, min(8, (screen_h - 300) // ROW_PX))
        self.rows = int(rows) - int(rows) % 2 if int(rows) > 1 else 2

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.add(root)

        # Header row: title on the left, search and user on the right.
        head = Gtk.Box(spacing=24)
        head.set_margin_start(LEFT)
        head.set_margin_end(60)
        head.set_margin_top(36)
        head.set_margin_bottom(34)
        self.title = Gtk.Label(label=settings.get("title", "start"), xalign=0)
        self.title.get_style_context().add_class("panorama-header")
        head.pack_start(self.title, False, False, 0)
        user = Gtk.Label(label=user_name())
        user.get_style_context().add_class("user-label")
        user.set_valign(Gtk.Align.CENTER)
        head.pack_end(user, False, False, 0)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("search apps")
        self.entry.get_style_context().add_class("search")
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.connect("search-changed", self.on_search)
        self.entry.connect("activate", self.on_search_activate)
        self.entry.set_no_show_all(True)
        head.pack_end(self.entry, False, False, 0)
        root.pack_start(head, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)
        self.stack.set_vhomogeneous(False)
        root.pack_start(self.stack, True, True, 0)

        self.tile_widgets = []
        self.group_offsets = []
        self.stack.add_named(self.build_tiles(), "tiles")
        self.stack.add_named(self.build_apps(screen_h), "apps")
        self.stack.add_named(self.build_zoom(), "zoom")

        foot = Gtk.Box()
        foot.set_margin_start(LEFT)
        foot.set_margin_bottom(30)
        self.apps_link = Gtk.Button(label="all apps  ›")
        self.apps_link.set_relief(Gtk.ReliefStyle.NONE)
        self.apps_link.get_style_context().add_class("apps-link")
        self.apps_link.connect("clicked", lambda *_: self.show("apps"))
        foot.pack_start(self.apps_link, False, False, 0)
        root.pack_end(foot, False, False, 0)

        self.win.show_all()
        self.scheduler = tiles.FlipScheduler(self.tile_widgets)
        self.animate_in()
        if mode in ("apps", "search"):
            self.show("apps", focus_search=(mode == "search"))
        elif mode == "zoom":
            self.show("zoom")
        elif self.tile_widgets:
            self.tile_widgets[0].grab_focus()

    # ── tiles ────────────────────────────────────────────────────────
    def build_tiles(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.set_overlay_scrolling(True)
        scroll.connect("scroll-event", self.on_wheel)
        self.tiles_scroll = scroll
        strip = Gtk.Box(spacing=80)
        strip.set_margin_start(LEFT)
        strip.set_margin_end(LEFT)
        strip.set_valign(Gtk.Align.START)
        scroll.add(strip)

        x = LEFT
        col_base = 0
        for group in self.cfg.get("group", []):
            specs = [s for s in (self.resolve(t) for t in group.get("tiles", [])) if s]
            if not specs:
                continue
            placed, width = pack(specs, self.rows)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            name = Gtk.Label(label=group.get("name", ""), xalign=0)
            name.get_style_context().add_class("group-title")
            box.pack_start(name, False, False, 0)
            fixed = Gtk.Fixed()
            fixed.set_size_request(tiles.px(width), tiles.px(self.rows))
            for spec, col, row in placed:
                tile = tiles.make(spec, self.on_tile)
                tile.column = col_base + col
                fixed.put(tile, col * ROW_PX, row * ROW_PX)
                self.tile_widgets.append(tile)
            box.pack_start(fixed, False, False, 0)
            strip.pack_start(box, False, False, 0)
            self.group_offsets.append((group.get("name", ""), x - LEFT))
            x += tiles.px(width) + 80
            col_base += width + 1
        return scroll

    def resolve(self, spec):
        spec = dict(spec)
        kind = spec.get("type", "app")
        if kind == "app":
            info = common.find_app(spec.get("app"))
            if info is None and not spec.get("exec"):
                return None
            spec["_info"] = info
            if not spec.get("label") and info is not None:
                spec["label"] = (info.get_display_name() or "").lower()
        elif kind == "battery" and tiles._battery()[0] is None:
            return None  # no battery: nothing to show
        elif spec.get("app"):
            spec["_info"] = common.find_app(spec["app"])
        return spec

    def animate_in(self):
        def reveal(tile):
            tile.get_style_context().remove_class("entering")
            return False
        for tile in self.tile_widgets:
            GLib.timeout_add(70 + 35 * tile.column, reveal, tile)

    def on_wheel(self, scroll, event):
        adj = scroll.get_hadjustment()
        ok, dx, dy = event.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.direction, 0)
            dx = {Gdk.ScrollDirection.LEFT: -1, Gdk.ScrollDirection.RIGHT: 1}.get(event.direction, 0)
        adj.set_value(adj.get_value() + (dx + dy) * 90)
        return True

    def on_tile(self, tile):
        spec = tile.spec
        kind = spec.get("type", "app")
        if kind == "action":
            self.run_action(spec.get("action"))
            return
        if spec.get("exec"):
            common.run_detached(spec["exec"])
        elif spec.get("_info") is not None:
            common.launch_app(spec["_info"])
        else:
            return
        if kind == "music" and spec.get("exec", "").startswith("playerctl"):
            GLib.timeout_add(300, lambda: tile.refresh() or False)
            return  # play/pause in place, stay open
        self.quit()

    def run_action(self, action):
        if action in ("apps", "search"):
            self.show("apps", focus_search=(action == "search"))
        elif action == "zoom":
            self.show("zoom")
        elif action == "accent":
            common.run_detached("tube-accent random")
            GLib.timeout_add(600, lambda: common.apply_css() and False)
        elif action in ("charms", "settings", "lock", "devices"):
            cmd = {"charms": "tube-charms", "settings": "tube-charms --settings",
                   "devices": "tube-charms --devices", "lock": "tube-lock"}[action]
            common.run_detached(cmd)
            self.quit()

    # ── all apps ─────────────────────────────────────────────────────
    def build_apps(self, screen_h):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scroll.connect("scroll-event", self.on_wheel)
        flow = Gtk.FlowBox()
        flow.set_orientation(Gtk.Orientation.VERTICAL)
        per_col = max(5, (screen_h - 330) // 52)
        flow.set_min_children_per_line(per_col)
        flow.set_max_children_per_line(per_col)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_activate_on_single_click(True)
        flow.set_column_spacing(48)
        flow.set_row_spacing(4)
        flow.set_valign(Gtk.Align.START)
        flow.set_halign(Gtk.Align.START)
        flow.set_margin_start(LEFT - 4)
        flow.set_margin_end(LEFT)
        flow.get_style_context().add_class("apps")
        flow.connect("child-activated", self.on_app_child)
        flow.set_filter_func(self.filter_app)
        scroll.add(flow)
        self.flow = flow

        apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        apps.sort(key=lambda a: (a.get_display_name() or "").lower())
        letter = None
        for app in apps:
            name = app.get_display_name() or ""
            first = name[:1].lower()
            first = first if first.isalpha() else "#"
            if first != letter:
                letter = first
                lab = Gtk.Label(label=letter, xalign=0)
                lab.get_style_context().add_class("app-letter")
                child = Gtk.FlowBoxChild()
                child.add(lab)
                child.app = None
                child.set_can_focus(False)
                flow.add(child)
            flow.add(self.app_row(app))
        return scroll

    def app_row(self, app):
        row = Gtk.Box(spacing=14)
        row.get_style_context().add_class("app-row")
        row.set_size_request(300, 48)
        square = Gtk.Box()
        square.get_style_context().add_class("app-icon")
        square.set_size_request(40, 40)
        glyph = tiles.glyph_for({"_info": app}, app.get_display_name(), 24)
        square.set_center_widget(glyph)
        row.pack_start(square, False, False, 0)
        name = Gtk.Label(label=app.get_display_name(), xalign=0)
        name.get_style_context().add_class("app-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(24)
        row.pack_start(name, True, True, 0)
        child = Gtk.FlowBoxChild()
        child.add(row)
        child.app = app
        child.set_tooltip_text(app.get_description() or app.get_display_name())
        return child

    def filter_app(self, child):
        text = self.entry.get_text().strip().lower()
        if not text:
            return True
        app = getattr(child, "app", None)
        if app is None:
            return False
        words = [app.get_display_name(), app.get_name(), app.get_executable(),
                 app.get_description()]
        if isinstance(app, Gio.DesktopAppInfo):
            words += app.get_keywords() or []
        hay = " ".join(w for w in words if w).lower()
        return all(word in hay for word in text.split())

    def on_search(self, _entry):
        self.flow.invalidate_filter()

    def on_search_activate(self, _entry):
        for child in self.flow.get_children():
            if getattr(child, "app", None) is not None and child.get_child_visible() \
                    and self.filter_app(child):
                self.on_app_child(self.flow, child)
                return

    def on_app_child(self, _flow, child):
        if getattr(child, "app", None) is not None:
            common.launch_app(child.app)
            self.quit()

    # ── semantic zoom ────────────────────────────────────────────────
    def build_zoom(self):
        box = Gtk.FlowBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)
        box.set_max_children_per_line(4)
        box.set_min_children_per_line(min(4, max(1, len(self.group_offsets))))
        box.set_column_spacing(10)
        box.set_row_spacing(10)
        box.set_margin_start(LEFT)
        box.set_margin_end(LEFT)
        box.set_valign(Gtk.Align.START)
        box.set_halign(Gtk.Align.START)
        for name, offset in self.group_offsets:
            btn = Gtk.Button()
            lab = Gtk.Label(label=name, xalign=0, yalign=1)
            btn.add(lab)
            btn.set_size_request(310, 230)
            btn.get_style_context().add_class("zoom-group")
            btn.connect("clicked", self.on_zoom_pick, offset)
            box.add(btn)
        return box

    def on_zoom_pick(self, _btn, offset):
        self.show("tiles")
        GLib.idle_add(lambda: self.tiles_scroll.get_hadjustment().set_value(offset) or False)

    # ── navigation ───────────────────────────────────────────────────
    def show(self, page, focus_search=False):
        self.stack.set_visible_child_name(page)
        self.title.set_text({"apps": "apps", "zoom": self.cfg.get("start", {}).get("title", "start")}
                            .get(page, self.cfg.get("start", {}).get("title", "start")))
        self.entry.set_visible(page == "apps")
        self.apps_link.set_visible(page == "tiles")
        if page == "apps":
            if focus_search:
                self.entry.grab_focus()
            else:
                for child in self.flow.get_children():
                    if getattr(child, "app", None) is not None:
                        child.grab_focus()
                        break
        elif page == "tiles":
            self.entry.set_text("")
            if self.tile_widgets:
                self.tile_widgets[0].grab_focus()

    def on_key(self, _win, event):
        page = self.stack.get_visible_child_name()
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        key = event.keyval
        if key == Gdk.KEY_Escape:
            if page == "apps" and self.entry.get_text():
                self.entry.set_text("")
            elif page != "tiles":
                self.show("tiles")
            else:
                self.quit()
            return True
        if ctrl and key in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.show("zoom")
            return True
        if ctrl and key in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.show("tiles")
            return True
        if page == "tiles" and key in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
            adj = self.tiles_scroll.get_hadjustment()
            sign = 1 if key == Gdk.KEY_Page_Down else -1
            adj.set_value(adj.get_value() + sign * adj.get_page_size() * 0.8)
            return True
        # Typing anywhere searches.
        text = event.string
        if not ctrl and text and text.isprintable() and not text.isspace() \
                and not self.entry.has_focus():
            if page != "apps":
                self.show("apps")
            self.entry.grab_focus_without_selecting()
            self.entry.set_text(self.entry.get_text() + text)
            self.entry.set_position(-1)
            return True
        return False

    def quit(self):
        Gtk.main_quit()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-start", description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apps", action="store_true", help="open on the all apps list")
    group.add_argument("--search", action="store_true", help="open with the search box focused")
    group.add_argument("--zoom", action="store_true", help="open zoomed out to the group names")
    parser.add_argument("--close", action="store_true", help="close start if it is open")
    args = parser.parse_args(argv)

    if not common.toggle_instance("start", close_only=args.close):
        return 0
    mode = "apps" if args.apps else "search" if args.search else "zoom" if args.zoom else "tiles"
    StartScreen(mode)
    Gtk.main()
    return 0
