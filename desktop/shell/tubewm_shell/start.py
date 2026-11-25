"""tube-start: every app at once, and type to find one.

Start opens on all your apps from a to z, in columns that fit the screen, so
nothing is cut off; scroll sideways if there are more. Start typing and what
you type grows huge while the list slides away and the results slide in:
the best match first (press Enter to open it), then the rest, apps before
web apps. Up and Down move through the results, and Enter opens the one
you are on. Esc goes back to the list, and again closes start, as does a
click on empty space.

Start is built once and then stays running, hidden, so the Windows key only
has to show it (see resident.py); it opens on the list again each time.

On the right, always, is the glance: live tiles you can move, resize and add
to (see glance.py), the apps you have open, and settings, lock and power.
"""

import argparse
import faulthandler
import os
import re
import signal
import sys

from . import common, glance, layout, resident, wm

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    import cairo   # for an empty input region while start is away
except ImportError:  # pragma: no cover - comes with python-gobject on most systems
    cairo = None

# Entries that are in every menu and that nobody means to open from start.
HIDDEN = {"uxterm", "xterm", "avahi-discover", "bssh", "bvnc", "qv4l2", "qvidcap",
          "lstopo", "cmake-gui", "foot-server", "footclient", "foot --server", "nm-connection-editor",
          "org.freedesktop.ibus.setup", "electron", "jconsole-java-openjdk"}

FADE_MS = 160        # going away
FADE_IN_MS = 90      # coming in: quick, it's what the Windows key waits for
SLIDE_MS = 420
APPS_SHIFT = 120     # px the list moves left as it goes
RESULTS_SHIFT = 160  # px the results travel in from the right
SEARCH_SMALL, SEARCH_BIG = 30, 160   # px: the search text, idle and typing
MARGIN = 72          # around everything
GLANCE_W = 400
COLUMN_GAP = 56
RESULTS = 8

# What a later `tube-start` sends the one already running (bin/tube-start
# sends these too, before it loads GTK).
SIGNALS = {signal.SIGUSR1: "apps", signal.SIGUSR2: "search", signal.SIGHUP: "close"}

# Browsers that install web apps as their own entries.
BROWSERS = {"vivaldi": "vivaldi", "chromium": "chromium", "chrome": "chrome",
            "brave": "brave", "msedge": "edge", "microsoft-edge": "edge", "firefoxpwa": "firefox"}


def _clean_name(app):
    name = (app.get_display_name() or app.get_name() or "").strip()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)  # "ImageMagick (color depth=q16)"
    return name.lower()


def web_app_of(app):
    """The browser a web app was installed through ("vivaldi"), or None."""
    cmd = (app.get_commandline() or "").lower()
    if "--app-id=" not in cmd and "firefoxpwa" not in cmd:
        return None
    exe = os.path.basename(cmd.split()[0]) if cmd.split() else ""
    for key, name in BROWSERS.items():
        if key in exe or key in cmd:
            return name
    return "your browser"


def all_apps():
    """Installed apps worth listing, sorted by name: (name, id, info, web app of)."""
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
            out.append((name, app_id, app, web_app_of(app)))
    out.sort(key=lambda a: a[0])
    return out


def score(app, name, query, web=None):
    """How well an app matches what you typed: lower is better, None is no
    match. The name counts most, and a web app comes after a real app that
    matches as well, so "vivaldi" finds Vivaldi before the web apps installed
    through it."""
    name = name.lower()
    if name == query:
        s = 0
    elif name.startswith(query):
        s = 1
    elif any(w.startswith(query) for w in name.split()):
        s = 2
    elif query in name:
        s = 3
    else:
        words = [app.get_name(), app.get_executable(), app.get_description(), web]
        words += app.get_keywords() or []
        hay = " ".join([name] + [w for w in words if w]).lower()
        if not all(w in hay for w in query.split()):
            return None
        s = 4
    return s * 2 + (1 if web else 0)


def search(apps, query):
    scored = sorted((s, len(a[0]), a[0], i) for i, a in enumerate(apps)
                    for s in [score(a[2], a[0], query, a[3])] if s is not None)
    return [apps[i] for *_rest, i in scored]


# ── building blocks ────────────────────────────────────────────────────────

def word(text, *classes, xalign=0.0, ellipsize=False):
    lab = Gtk.Label(label=text, xalign=xalign)
    if ellipsize:
        lab.set_ellipsize(Pango.EllipsizeMode.END)
    for c in classes:
        lab.get_style_context().add_class(c)
    return lab


def link(child, on_click, *classes):
    """Something you can click whose only look is its type."""
    b = Gtk.Button()
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class("start-link")
    for c in classes:
        b.get_style_context().add_class(c)
    b.add(child if isinstance(child, Gtk.Widget) else word(child))
    b.connect("clicked", lambda *_: on_click())
    return b


class Start:
    def __init__(self, mode):
        common.apply_css()
        self.apps = all_apps()
        self.hits = []
        self.rows = []   # the result buttons shown, best match first
        self.sel = 0     # which of them Enter opens
        self.shown = False
        self.away = False
        self.fade_tick = None
        self.apps_stale = False
        # New or removed apps: list them again the next time start opens.
        self.app_monitor = Gio.AppInfoMonitor.get()
        self.app_monitor.connect("changed", lambda *_: setattr(self, "apps_stale", True))
        self.look = look_stamp()

        # The window itself is see-through and everything in it sits on
        # self.sheet, which carries the background. Wayland ignores a whole
        # window's opacity, so fading the sheet is what makes start fade.
        win = common.make_layer_window("start", transparent=True)
        common.below_strip(win)
        win.get_style_context().add_class("start")
        win.connect("key-press-event", self.on_key)
        self.win = win

        over = Gtk.Overlay()
        self.sheet = Gtk.Box()
        self.sheet.get_style_context().add_class("start-sheet")
        self.sheet.pack_start(over, True, True, 0)
        win.add(self.sheet)
        # The click-catcher behind everything: empty space closes start.
        back = Gtk.EventBox()
        back.connect("button-press-event", lambda _w, ev: self.quit() if ev.button == 1 else False)
        over.add(back)

        body = Gtk.Box(spacing=48)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, "set_margin_" + side)(MARGIN if side in ("start", "end") else 48)
        over.add_overlay(body)
        over.set_overlay_pass_through(body, False)

        # Left: the search field, and under it all apps or the results,
        # one sliding away as the other slides in.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_hexpand(True)
        self.hint = word("all apps · type to search", "start-hint")
        left.pack_start(self.hint, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.get_style_context().add_class("start-search")
        self.entry.set_has_frame(False)
        self.entry.set_placeholder_text("start typing")
        self.entry_css = Gtk.CssProvider()
        self.entry.get_style_context().add_provider(self.entry_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)
        self.entry.connect("changed", self.on_changed)
        self.entry.connect("activate", self.launch_selected)
        left.pack_start(self.entry, False, False, 0)
        self.stage = Gtk.Layout()
        self.stage.set_vexpand(True)
        self.stage.connect("size-allocate", self.on_stage_size)
        self.apps_page = self.build_apps()
        self.results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.results.get_style_context().add_class("start-results")
        self.stage.put(self.apps_page, 0, 0)
        self.stage.put(self.results, RESULTS_SHIFT, 0)
        left.pack_start(self.stage, True, True, 0)
        body.pack_start(left, True, True, 0)
        self.searching = False
        self.slide_t = 0.0   # 0: all apps, 1: results
        self.slide_tick = None

        line = Gtk.Box()
        line.get_style_context().add_class("start-divider")
        body.pack_start(line, False, False, 0)

        body.pack_start(self.build_glance(), False, False, 0)

        win.show_all()
        self.results.set_opacity(0.0)
        self.results.hide()
        self.fill_columns()
        self.refresh_glance()
        self.sheet.set_opacity(0.0)
        self.shown = True
        self._fade(1.0, None, FADE_IN_MS)
        if mode == "search":
            self.start_search("")

    # ── shown and hidden ─────────────────────────────────────────────
    def on_signal(self, mode):
        resident.heard("start", mode)   # before anything slow: tube-start is waiting
        if mode == "close":
            self.quit()
        elif self.shown:
            self.quit()   # the key again closes start, as it always has
        else:
            self.show(mode)
        return True       # keep listening

    def show(self, mode="apps"):
        if look_stamp() != self.look and os.path.basename(sys.argv[0]) == "tube-start":
            # The accent or the stylesheet changed while we were hidden:
            # come back as a fresh copy, so every colour is the new one.
            argv = [sys.executable, os.path.abspath(sys.argv[0])] + (["--search"] if mode == "search" else [])
            os.execv(sys.executable, argv)
        self.shown = True
        if self.away:
            self.sheet.set_opacity(0.0)
            self.set_away(False)
        if not common.layer_shell():
            # Not on a layer surface: ask for focus. On one, keyboard
            # interactivity already gives us the keys, and present() asks
            # the compositor for an activation token and waits for it, which
            # can block start for good once another app has the focus.
            self.win.present()
        if self.apps_stale or common.monitor_size(self.win) != self.columns_for:
            self.apps_stale = False
            self.apps = all_apps()
            for child in self.columns.get_children():
                self.columns.remove(child)
                child.destroy()
            self.fill_columns()
        self.refresh_glance()
        # The tiles slept while start was hidden: bring them up to date.
        for t in self.glance.tiles:
            t.next_read = 0
        GLib.idle_add(lambda: self.glance.tick() and False)
        self._fade(1.0, None, FADE_IN_MS)
        if mode == "search":
            self.start_search("")

    def set_away(self, away):
        """Put start out of the way, or bring it back, without ever unmapping
        the window. Hiding and showing a layer-shell window again can leave
        GTK stuck for good inside show() (seen on Wayfire), and start with
        it, deaf to the Windows key. So, when away, the window stays mapped
        but drops below everything, transparent (the sheet has faded out),
        taking no clicks and no keys."""
        self.away = away
        self.glance.awake = not away
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

    def hidden(self):
        """Out of sight, and back to how start opens: the list, scrolled to
        the start, tiles showing."""
        self.set_away(True)
        self.glance.back()
        if self.slide_tick:
            GLib.source_remove(self.slide_tick)
            self.slide_tick = None
        self.entry.handler_block_by_func(self.on_changed)
        self.entry.set_text("")
        self.entry.handler_unblock_by_func(self.on_changed)
        self.win.set_focus(None)
        self.searching, self.slide_t = False, 0.0
        self.hits, self.rows, self.sel = [], [], 0
        self.hint.set_text("all apps · type to search")
        self.grow(0.0)
        self.apps_page.set_opacity(1.0)
        self.apps_page.show()
        self.stage.move(self.apps_page, 0, 0)
        self.results.set_opacity(0.0)
        self.results.hide()
        self.stage.move(self.results, RESULTS_SHIFT, 0)
        self.scroll.get_hadjustment().set_value(0)

    # ── all apps ─────────────────────────────────────────────────────
    def build_apps(self):
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroll.set_overlay_scrolling(True)
        self.scroll.connect("scroll-event", self.on_scroll)
        self.columns = Gtk.Box(spacing=COLUMN_GAP)
        self.columns.set_valign(Gtk.Align.START)
        self.columns.get_style_context().add_class("start-columns")
        self.scroll.add(self.columns)
        return self.scroll

    def on_stage_size(self, _w, alloc):
        size = (alloc.width, alloc.height)
        if getattr(self, "_stage_size", None) != size:
            self._stage_size = size

            def fit():
                self.apps_page.set_size_request(alloc.width, alloc.height)
                self.results.set_size_request(alloc.width, alloc.height)
                return False
            GLib.idle_add(fit)   # not from inside an allocation

    def group(self, letter, apps):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("start-group")
        box.pack_start(word(letter, "start-letter"), False, False, 0)
        for name, _id, app, _web in apps:
            box.pack_start(link(word(name, "start-item"), lambda a=app: self.launch(a)),
                           False, False, 0)
        return box

    def fill_columns(self):
        """Lay the letters out in columns as tall as the screen allows. A
        letter is never split from its apps, and nothing runs off the bottom."""
        groups, cur = [], None
        for app in self.apps:
            first = app[0][:1] if app[0][:1].isalpha() else "#"
            if first != cur:
                cur = first
                groups.append((first, []))
            groups[-1][1].append(app)
        self.columns_for = common.monitor_size(self.win)
        _w, h = self.columns_for
        above = sum(w.get_preferred_height()[1] for w in (self.hint, self.entry))
        room = h - common.STRIP_HEIGHT - 96 - above - 24   # 96: margins; 24: air
        col, used = None, 0
        for letter, apps in groups:
            g = self.group(letter, apps)
            g.show_all()
            gh = g.get_preferred_height()[1]
            if col is None or (used + gh > room and used > 0):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                self.columns.pack_start(col, False, False, 0)
                used = 0
            col.pack_start(g, False, False, 0)
            used += gh
        self.columns.show_all()

    # ── search ───────────────────────────────────────────────────────
    def result(self, app, big=False):
        name, _id, info, web = app
        row = Gtk.Box(spacing=20)
        row.pack_start(word(name, "start-best" if big else "start-result"), False, False, 0)
        kind = ("%s web app" % web) if web else "app"
        kind_label = word(kind, "start-kind")
        kind_label.set_valign(Gtk.Align.BASELINE)
        row.pack_start(kind_label, False, False, 0)
        return link(row, lambda: self.launch(info))

    def fill_results(self, query):
        for child in self.results.get_children():
            self.results.remove(child)
        self.hits = search(self.apps, query)
        self.rows, self.sel = [], 0
        if not self.hits:
            self.results.pack_start(word("nothing matches", "start-none"), False, False, 0)
        else:
            self.results.pack_start(word("best match · press enter", "start-dim"), False, False, 0)
            self.rows.append(self.result(self.hits[0], big=True))
            self.results.pack_start(self.rows[0], False, False, 0)
            if len(self.hits) > 1:
                more = word("more results", "start-dim")
                more.get_style_context().add_class("start-also")
                self.results.pack_start(more, False, False, 0)
            for app in self.hits[1:RESULTS]:
                self.rows.append(self.result(app))
                self.results.pack_start(self.rows[-1], False, False, 0)
            self.select(0)
        self.results.show_all()

    def select(self, i):
        """Light up result i: the one Enter opens."""
        if not self.rows:
            return
        self.sel = max(0, min(i, len(self.rows) - 1))
        for n, row in enumerate(self.rows):
            ctx = row.get_style_context()
            (ctx.add_class if n == self.sel else ctx.remove_class)("start-selected")

    def on_changed(self, *_):
        query = self.entry.get_text().strip().lower()
        if query:
            self.fill_results(query)
            if not self.searching:
                self.slide(True)
        elif self.searching:
            self.slide(False)

    def start_search(self, text):
        self.entry.grab_focus_without_selecting()
        self.entry.set_text(text)
        self.entry.set_position(-1)

    def show_apps(self):
        self.entry.set_text("")
        self.win.set_focus(None)

    def grow(self, t):
        """What you type grows from 30 px to 160 px as the search comes in."""
        size = SEARCH_SMALL + (SEARCH_BIG - SEARCH_SMALL) * t
        spacing = -7 * t
        self.entry_css.load_from_data(
            (".start-search { font-size: %.1fpx; letter-spacing: %.2fpx; }" % (size, spacing)).encode())

    def slide(self, searching):
        """The list slides left and fades as the results slide in from the
        right (a moment behind), and the other way back."""
        self.searching = searching
        self.hint.set_text("search apps · esc to go back" if searching else "all apps · type to search")
        self.results.show()
        self.apps_page.show()
        start_t, goal = self.slide_t, 1.0 if searching else 0.0
        t0 = GLib.get_monotonic_time()
        span = SLIDE_MS * abs(goal - start_t) or 1

        def ease(x):
            x = min(1.0, max(0.0, x))
            return 1 - (1 - x) ** 3

        def tick(*_):
            k = min(1.0, (GLib.get_monotonic_time() - t0) / 1000.0 / span)
            t = start_t + (goal - start_t) * k
            self.slide_t = t
            out = ease(t)
            inn = ease((t - 0.2) / 0.8)   # the results start a little later
            self.grow(out)
            self.apps_page.set_opacity(1 - out)
            self.stage.move(self.apps_page, -int(APPS_SHIFT * out), 0)
            self.results.set_opacity(inn)
            self.stage.move(self.results, int(RESULTS_SHIFT * (1 - inn)), 0)
            if k >= 1.0:
                (self.apps_page if searching else self.results).hide()
                self.slide_tick = None
                return False
            return True

        if self.slide_tick:
            GLib.source_remove(self.slide_tick)
        self.slide_tick = GLib.timeout_add(16, tick)

    # ── the glance ───────────────────────────────────────────────────
    def build_glance(self):
        """Live tiles you arrange (glance.py), what's open now, and settings,
        lock and power."""
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        col.set_size_request(GLANCE_W, -1)
        self.glance = glance.Glance(GLANCE_W, closes=self.quit)
        col.pack_start(self.glance, True, True, 0)

        self.open_head = word("open now", "start-hint")
        self.open_head.get_style_context().add_class("start-open-head")
        self.glance.below.pack_start(self.open_head, False, False, 0)
        self.open_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.glance.below.pack_start(self.open_box, False, False, 0)

        links = Gtk.Box(spacing=40)
        links.set_halign(Gtk.Align.END)
        for text, cmd in (("settings", "tube-settings"), ("lock", "tube-lock"),
                          ("power", "tube-status")):
            links.pack_start(link(word(text, "start-foot"), lambda c=cmd: self.run(c)), False, False, 0)
        col.pack_end(links, False, False, 0)
        return col

    def fill_open(self):
        for child in self.open_box.get_children():
            self.open_box.remove(child)
        try:
            wins = wm.windows()[:5]
            names = wm.desktop_names()
        except Exception:  # noqa: BLE001 - no compositor to ask
            wins, names = [], []
        for w in wins:
            row = Gtk.Box(spacing=16)
            title = (common.find_app(w.get("app_id", "")) or None)
            name = _clean_name(title) if title else (w.get("app_id") or w.get("title") or "").lower()
            row.pack_start(word(name, "start-open", ellipsize=True), False, False, 0)
            ws = w.get("workspace", 0)
            where = word(names[ws] if ws < len(names) and names[ws] else "desktop %d" % (ws + 1), "start-kind")
            row.pack_start(where, False, False, 0)
            self.open_box.pack_start(link(row, lambda i=w["id"], n=ws: self.go_to(i, n)), False, False, 0)
        self.open_head.set_visible(bool(wins))
        self.open_box.show_all()

    def go_to(self, win_id, desk):
        wm.go_to_pivot(desk)
        wm.focus(win_id)
        self.quit()

    def run(self, cmd):
        argv = cmd.split()
        common.run_detached(" ".join([os.path.join(common.BIN_DIR, argv[0])] + argv[1:]))
        self.quit()

    def refresh_glance(self):
        self.fill_open()   # the tiles keep themselves up to date

    # ── doing things ─────────────────────────────────────────────────
    def launch(self, app):
        common.launch_app(app)
        self.quit()

    def launch_selected(self, *_):
        if self.hits:
            self.launch(self.hits[min(self.sel, len(self.hits) - 1)][2])

    def on_scroll(self, _w, event):
        # The wheel scrolls the columns sideways.
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
            if self.glance.back():
                return True
            if self.searching or self.entry.get_text():
                self.show_apps()
            else:
                self.quit()
            return True
        typing_elsewhere = (not self.entry.has_focus()
                            and isinstance(self.win.get_focus(), (Gtk.Entry, Gtk.TextView)))
        if (self.searching and not typing_elsewhere
                and key in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_KP_Up, Gdk.KEY_KP_Down)):
            # Move through the results; the text keeps the focus, so you
            # can go on typing.
            self.select(self.sel + (-1 if key in (Gdk.KEY_Up, Gdk.KEY_KP_Up) else 1))
            return True
        if self.entry.has_focus() or isinstance(self.win.get_focus(), (Gtk.Entry, Gtk.TextView)):
            return False   # typing into search, a tile's note or its settings
        # From the key itself: event.string is often empty under Wayland.
        code = Gdk.keyval_to_unicode(event.keyval)
        text = chr(code) if code else ""
        mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK)
        if not mods and text and text.isprintable() and not text.isspace():
            self.start_search(text)
            return True
        return False

    def _fade(self, target, then, ms=FADE_MS):
        if self.fade_tick:
            GLib.source_remove(self.fade_tick)   # turned round half way
        start = self.sheet.get_opacity()
        t0 = GLib.get_monotonic_time()

        def tick():
            t = min(1.0, (GLib.get_monotonic_time() - t0) / 1000.0 / ms)
            ease = 1 - (1 - t) ** 3
            self.sheet.set_opacity(start + (target - start) * ease)
            if t >= 1.0:
                self.fade_tick = None
                if then:
                    then()
                return False
            return True
        self.fade_tick = GLib.timeout_add(16, tick)

    def quit(self):
        """Close start: it fades out and waits, hidden, for the next time."""
        if self.shown:
            self.shown = False
            self._fade(0.0, self.hidden)
        return True


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
    parser = argparse.ArgumentParser(prog="tube-start", description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apps", action="store_true", help="open at the list of apps (the default)")
    group.add_argument("--search", action="store_true", help="open ready to search")
    parser.add_argument("--close", action="store_true", help="close start if it is open")
    parser.add_argument("--reset", action="store_true", help="forget start's saved layout")
    args = parser.parse_args(argv)

    mode = "search" if args.search else "apps"
    wait = 0.0
    if args.reset:
        layout.reset()
        # The running copy still has the old tiles; let it go and start over.
        wait = 3.0 if resident.send("start", signal.SIGTERM) else 0.0
    elif resident.send("start", signal.SIGHUP if args.close else
                       signal.SIGUSR2 if args.search else signal.SIGUSR1, answer_within=1.0):
        return 0
    if args.close:
        return 0
    lock = resident.claim("start", wait=wait)
    if lock is None:
        return 0   # another copy is starting up right now
    # Before Start() starts the tile threads, so they inherit it too.
    resident.unblock(set(SIGNALS) | {signal.SIGTERM})
    if not sys.stderr.isatty():
        # Started by the compositor, which throws our output away: keep
        # warnings and tracebacks where someone can find them.
        try:
            fd = os.open(resident.log_path("start"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.dup2(fd, 2)
            os.close(fd)
        except OSError:
            pass
    resident.log("start", "starting (%s)" % mode)
    # If we ever stop answering, tube-start asks for our stacks before it
    # replaces us; faulthandler writes them even if Python itself is stuck.
    faulthandler.register(resident.DUMP, all_threads=True)
    start = Start(mode)
    for sig, what in SIGNALS.items():
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_a, w=what: start.on_signal(w))
    resident.announce("start")
    Gtk.main()
    return 0
