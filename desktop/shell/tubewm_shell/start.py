"""tube-start: start, as a panorama of words.

A huge "start" runs off the top-left corner. Below it, side by side, are
your pinned apps in big light type (with what's playing, if anything), the
things you opened recently, and every app from a to z. Scroll sideways (the
wheel works too) to see more. Type anything to search. Right-click an app to
pin or unpin it. Esc, or a click on the empty space, closes start.
"""

import argparse
import os
import re

from . import common, layout

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

# Entries that are in every menu and that nobody means to open from start.
HIDDEN = {"uxterm", "xterm", "avahi-discover", "bssh", "bvnc", "qv4l2", "qvidcap",
          "lstopo", "cmake-gui", "foot-server", "footclient", "foot --server", "nm-connection-editor",
          "org.freedesktop.ibus.setup", "electron", "jconsole-java-openjdk"}

FADE_MS = 160


def _clean_name(app):
    name = (app.get_display_name() or app.get_name() or "").strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # "ImageMagick (color depth=q16)"
    return name.lower()


def all_apps():
    """Installed apps worth listing, sorted by name."""
    out = []
    for app in Gio.AppInfo.get_all():
        if not app.should_show() or not isinstance(app, Gio.DesktopAppInfo):
            continue
        app_id = (app.get_id() or "").removesuffix(".desktop")
        names = {app_id.lower(), app_id.lower().removeprefix("debian-"),
                 app_id.split(".")[-1].lower(), os.path.basename(app.get_executable() or "")}
        if names & HIDDEN:
            continue
        name = _clean_name(app)
        if name:
            out.append((name, app_id, app))
    out.sort(key=lambda a: a[0])
    return out


def now_playing():
    text = common.sh(["playerctl", "metadata", "--format", "{{status}}\t{{title}}\t{{artist}}"])
    parts = text.split("\t")
    if len(parts) == 3 and parts[0] in ("Playing", "Paused") and parts[1]:
        return parts
    return None


def recent_files(limit=5):
    try:
        from .tiles import _recent_files
        return _recent_files(limit)
    except ImportError:
        return []


def word(text, *classes, xalign=0.0, ellipsize=False):
    lab = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(28)
    for c in classes:
        lab.get_style_context().add_class(c)
    return lab


def link(text, on_click, *classes, on_right=None, ellipsize=False):
    """A word you can click: a flat button whose only look is its type."""
    b = Gtk.Button()
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("pano-link")
    b.add(word(text, *classes, ellipsize=ellipsize))
    b.connect("clicked", lambda *_: on_click())
    if on_right:
        b.connect("button-press-event",
                  lambda _b, ev: (on_right(ev), True)[1] if ev.button == 3 else False)
    return b


class Start:
    def __init__(self, mode):
        common.apply_css()
        self.data = layout.load()
        self.apps = all_apps()
        self.by_id = {a[1]: a for a in self.apps}

        win = common.make_layer_window("start")
        win.get_style_context().add_class("pano")
        win.connect("key-press-event", self.on_key)
        self.win = win

        over = Gtk.Overlay()
        win.add(over)
        # The click-catcher behind everything: empty space closes start.
        back = Gtk.EventBox()
        back.connect("button-press-event", lambda _w, ev: self.quit() if ev.button == 1 else False)
        over.add(back)

        # The title is bigger than the space it's given: it runs off the top.
        title_box = Gtk.Fixed()
        title_box.put(word("start", "pano-title"), 52, -64)
        over.add_overlay(title_box)
        over.set_overlay_pass_through(title_box, True)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroll.set_overlay_scrolling(True)
        self.scroll.get_style_context().add_class("pano-scroll")
        self.scroll.connect("scroll-event", self.on_scroll)
        over.add_overlay(self.scroll)

        self.row = Gtk.Box(spacing=72)
        self.row.get_style_context().add_class("pano-row")
        self.row.set_valign(Gtk.Align.START)
        self.row.set_margin_top(230)
        self.row.set_margin_start(64)
        self.row.set_margin_end(64)
        self.scroll.add(self.row)

        # Search: hidden until you type.
        self.entry = Gtk.Entry()
        self.entry.get_style_context().add_class("pano-search")
        self.entry.set_no_show_all(True)
        self.entry.connect("changed", lambda *_: self.fill())
        self.entry.connect("activate", self.launch_first)

        self.fill()
        win.show_all()
        win.set_opacity(0.0)
        self._fade(1.0, None)
        if mode == "search":
            self.start_search("")
        elif mode == "apps":
            GLib.idle_add(self.scroll_to_apps)

    # ── content ──────────────────────────────────────────────────────
    def pinned_ids(self):
        return [t.get("app") for t in self.data["tiles"]
                if t.get("type", "app") == "app" and t.get("app")]

    def section(self, title, width=None):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.get_style_context().add_class("pano-section")
        if width:
            col.set_size_request(width, -1)
        col.pack_start(word(title, "pano-header"), False, False, 0)
        self.row.pack_start(col, False, False, 0)
        return col

    def fill(self):
        for child in self.row.get_children():
            self.row.remove(child)
        query = self.entry.get_text().strip().lower()
        if query:
            self.fill_search(query)
        else:
            self.fill_pinned()
            self.fill_recent()
            self.fill_apps()
        self.row.show_all()

    def fill_pinned(self):
        col = self.section("pinned", 460)
        col.get_style_context().add_class("pano-first")
        ids = [i for i in self.pinned_ids() if i in self.by_id]
        if not ids:
            col.pack_start(word("right-click an app to pin it here", "pano-dim"), False, False, 0)
        for app_id in ids[:9]:
            name, _id, app = self.by_id[app_id]
            col.pack_start(link(name, lambda a=app: self.launch(a), "pano-big",
                                on_right=lambda ev, i=app_id: self.app_menu(ev, i)),
                           False, False, 0)
        playing = now_playing()
        if playing:
            status, track, artist = playing
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.get_style_context().add_class("pano-playing")
            box.pack_start(word("now playing" if status == "Playing" else "paused", "pano-dim"),
                           False, False, 0)
            box.pack_start(link(track.lower(), lambda: common.sh(["playerctl", "play-pause"]),
                                "pano-medium"), False, False, 0)
            if artist:
                box.pack_start(word(artist.lower(), "pano-subtle"), False, False, 0)
            col.pack_start(box, False, False, 0)

    def fill_recent(self):
        files = recent_files()
        if not files:
            return
        col = self.section("recent", 380)
        for path in files:
            name = os.path.basename(path).lower()
            col.pack_start(link(name, lambda p=path: self.open_file(p), "pano-item", ellipsize=True),
                           False, False, 0)

    def fill_apps(self):
        col = self.section("apps")
        self.apps_col = col
        # Letters and names flow down, then into the next column.
        flow = Gtk.FlowBox(orientation=Gtk.Orientation.VERTICAL)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(False)
        rows = self._rows_fit()
        flow.set_min_children_per_line(rows)
        flow.set_max_children_per_line(rows)
        flow.set_column_spacing(48)
        flow.get_style_context().add_class("pano-apps")
        letter = None
        pinned = set(self.pinned_ids())
        for name, app_id, app in self.apps:
            first = name[:1] if name[:1].isalpha() else "#"
            if first != letter:
                letter = first
                flow.add(word(letter, "pano-letter"))
            cls = ("pano-item", "pinned") if app_id in pinned else ("pano-item",)
            flow.add(link(name, lambda a=app: self.launch(a), *cls,
                          on_right=lambda ev, i=app_id: self.app_menu(ev, i)))
        col.pack_start(flow, False, False, 0)

    def fill_search(self, query):
        col = self.section("search", 900)
        col.pack_start(self.entry, False, False, 0)
        hits = [a for a in self.apps if self._matches(a[2], a[0], query)]
        if not hits:
            col.pack_start(word("nothing called that", "pano-dim"), False, False, 0)
        for name, app_id, app in hits[:8]:
            col.pack_start(link(name, lambda a=app: self.launch(a), "pano-big",
                                on_right=lambda ev, i=app_id: self.app_menu(ev, i)),
                           False, False, 0)
        self.hits = hits

    @staticmethod
    def _matches(app, name, query):
        words = [name, app.get_name(), app.get_executable(), app.get_description()]
        words += app.get_keywords() or []
        hay = " ".join(w for w in words if w).lower()
        return all(w in hay for w in query.split())

    def _rows_fit(self):
        _w, h = common.monitor_size(self.win)
        return max(6, int((h - 330) / 36))

    def scroll_to_apps(self):
        col = getattr(self, "apps_col", None)
        if col is not None:
            alloc = col.get_allocation()
            self.scroll.get_hadjustment().set_value(alloc.x - 64)
        return False

    # ── pinning ──────────────────────────────────────────────────────
    def app_menu(self, event, app_id):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("tube-menu")
        if app_id in self.pinned_ids():
            item = Gtk.MenuItem(label="unpin")
            item.connect("activate", lambda *_: self.set_pinned(app_id, False))
        else:
            item = Gtk.MenuItem(label="pin")
            item.connect("activate", lambda *_: self.set_pinned(app_id, True))
        menu.append(item)
        menu.show_all()
        menu.attach_to_widget(self.win, None)
        menu.popup_at_pointer(event)
        self._menu = menu

    def set_pinned(self, app_id, pinned):
        tiles = [t for t in self.data["tiles"]
                 if not (t.get("type", "app") == "app" and t.get("app") == app_id)]
        if pinned:
            tiles.append({"type": "app", "app": app_id, "size": "medium"})
        self.data["tiles"] = tiles
        layout.save(self.data)
        self.fill()

    # ── doing things ─────────────────────────────────────────────────
    def launch(self, app):
        common.launch_app(app)
        self.quit()

    def open_file(self, path):
        common.run_detached("xdg-open %s" % GLib.shell_quote(path))
        self.quit()

    def launch_first(self, *_):
        hits = getattr(self, "hits", [])
        if hits:
            self.launch(hits[0][2])

    def start_search(self, text):
        self.entry.show()
        self.entry.set_text(text)
        self.fill()
        self.entry.grab_focus_without_selecting()
        self.entry.set_position(-1)

    def on_scroll(self, _w, event):
        # The wheel scrolls the panorama sideways.
        adj = self.scroll.get_hadjustment()
        ok, dx, dy = event.get_scroll_deltas()
        if ok:
            delta = (dx or dy) * 60
        elif event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            delta = 120
        elif event.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            delta = -120
        else:
            return False
        adj.set_value(adj.get_value() + delta)
        return True

    def on_key(self, _win, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            if self.entry.get_text():
                self.entry.set_text("")
                self.entry.hide()
                self.fill()
            else:
                self.quit()
            return True
        if self.entry.has_focus():
            return False
        text = event.string
        mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK)
        if not mods and text and text.isprintable() and not text.isspace():
            self.start_search(text)
            return True
        return False

    def _fade(self, target, then):
        start = self.win.get_opacity()
        t0 = GLib.get_monotonic_time()

        def tick():
            t = min(1.0, (GLib.get_monotonic_time() - t0) / 1000.0 / FADE_MS)
            ease = 1 - (1 - t) ** 3
            self.win.set_opacity(start + (target - start) * ease)
            if t >= 1.0:
                if then:
                    then()
                return False
            return True
        GLib.timeout_add(16, tick)

    def quit(self):
        self._fade(0.0, Gtk.main_quit)
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-start", description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apps", action="store_true", help="open at the list of apps")
    group.add_argument("--search", action="store_true", help="open ready to search")
    parser.add_argument("--close", action="store_true", help="close start if it is open")
    parser.add_argument("--reset", action="store_true", help="forget your pinned apps")
    args = parser.parse_args(argv)

    if args.reset:
        layout.reset()
    if not common.toggle_instance("start", close_only=args.close):
        return 0
    Start("apps" if args.apps else "search" if args.search else "pinned")
    Gtk.main()
    return 0
