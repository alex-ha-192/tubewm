"""tube-start: the start screen.

Your pinned tiles on the left: app shortcuts and live tiles that you add,
drag around, resize, recolour and unpin in place. Every app on the right,
in one alphabetical column; type anywhere to filter it.
"""

import argparse
import math
import os
import pwd

from . import common, layout, tiles

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

CELL = tiles.UNIT + tiles.GUTTER
LEFT = 120     # left margin, px
APPS_W = 380   # width of the app list column
DRAG_START = 10
LONG_PRESS = 600  # ms


def user_name():
    try:
        pw = pwd.getpwuid(os.getuid())
        return (pw.pw_gecos.split(",")[0] or pw.pw_name).strip()
    except KeyError:
        return os.environ.get("USER", "")


def pack(specs, cols):
    """Row-major first fit in a grid `cols` units wide. Tiles of 2x2 and up
    sit on even cells; small tiles fill 2x2 blocks before moving on, so
    they gather in little squares.
    Returns [(index, col, row, w, h)], the rows used, and the occupied cells."""
    occupied = set()
    placed = []
    rows_used = 0

    def candidates(w, h, row):
        if (w, h) == (1, 1):
            for bcol in range(0, cols, 2):
                for dr in (0, 1):
                    for dc in (0, 1):
                        if bcol + dc < cols:
                            yield bcol + dc, row + dr
        else:
            for col in range(0, cols - w + 1, 2):
                yield col, row

    for i, spec in enumerate(specs):
        w, h = tiles.SIZES.get(spec.get("size", "medium"), (2, 2))
        w = min(w, cols)
        row = 0
        while True:
            spot = None
            for col, r in candidates(w, h, row):
                cells = {(col + dx, r + dy) for dx in range(w) for dy in range(h)}
                if not cells & occupied:
                    spot = (col, r, cells)
                    break
            if spot:
                occupied |= spot[2]
                placed.append((i, spot[0], spot[1], w, h))
                rows_used = max(rows_used, spot[1] + h)
                break
            row += 2
    return placed, rows_used, occupied


class StartScreen:
    def __init__(self, mode):
        self.pal = common.apply_css()
        self.data = layout.load()
        self.win = common.make_layer_window("start")
        self.win.connect("key-press-event", self.on_key)
        self.drag = None
        self.just_dragged = False
        self.tile_widgets = []
        self.placed = []
        self.first_show = True

        screen_w, screen_h = common.monitor_size()
        avail = screen_w - LEFT - APPS_W - 100 - 60
        cols = max(4, min(16, (avail + tiles.GUTTER) // CELL))
        self.cols = cols - cols % 2

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.win.add(root)

        head = Gtk.Box(spacing=24)
        head.set_margin_start(LEFT)
        head.set_margin_end(60)
        head.set_margin_top(36)
        head.set_margin_bottom(30)
        self.title = Gtk.Label(label=self.data.get("title", "start"), xalign=0)
        self.title.get_style_context().add_class("panorama-header")
        head.pack_start(self.title, False, False, 0)
        user = Gtk.Label(label=user_name())
        user.get_style_context().add_class("user-label")
        user.set_valign(Gtk.Align.CENTER)
        head.pack_end(user, False, False, 0)
        root.pack_start(head, False, False, 0)

        body = Gtk.Box(spacing=100)
        body.set_margin_start(LEFT)
        body.set_margin_end(60)
        root.pack_start(body, True, True, 0)

        body.pack_start(self.build_tile_area(), True, True, 0)
        body.pack_start(self.build_app_column(), False, False, 0)

        self.rebuild()
        self.win.show_all()
        self.scheduler = tiles.FlipScheduler(lambda: self.tile_widgets)
        if mode in ("apps", "search"):
            self.entry.grab_focus() if mode == "search" else self.focus_first_app()
        elif self.tile_widgets:
            self.tile_widgets[0].grab_focus()

    # ── tile area ────────────────────────────────────────────────────
    def build_tile_area(self):
        self.tile_scroll = Gtk.ScrolledWindow()
        self.tile_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.tile_scroll.set_overlay_scrolling(True)
        self.tile_scroll.set_size_request(tiles.px(self.cols), -1)
        self.tile_scroll.set_halign(Gtk.Align.START)
        self.overlay = Gtk.Overlay()
        self.fixed = Gtk.Fixed()
        self.fixed.set_halign(Gtk.Align.START)
        self.fixed.set_valign(Gtk.Align.START)
        self.overlay.add(self.fixed)
        self.ghost = Gtk.Box()
        self.ghost.get_style_context().add_class("tile")
        self.ghost.get_style_context().add_class("ghost")
        self.ghost.set_halign(Gtk.Align.START)
        self.ghost.set_valign(Gtk.Align.START)
        self.ghost.set_no_show_all(True)
        self.overlay.add_overlay(self.ghost)
        self.overlay.set_overlay_pass_through(self.ghost, True)
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.pack_start(self.overlay, False, False, 0)
        bottom.set_margin_bottom(60)
        self.tile_scroll.add(bottom)
        return self.tile_scroll

    def resolve(self, spec):
        if spec.get("type", "app") == "app" or spec.get("app"):
            spec["_info"] = common.find_app(spec.get("app")) if spec.get("app") else None
        return spec

    def rebuild(self, focus_index=None):
        for child in self.fixed.get_children():
            self.fixed.remove(child)
            child.destroy()
        self.tile_widgets = []
        specs = [self.resolve(s) for s in self.data["tiles"]]
        self.placed, rows, occupied = pack(specs, self.cols)
        for i, col, row, w, h in self.placed:
            tile = tiles.make(specs[i], self.on_tile)
            tile.index = i
            tile.cell = (col, row)
            self.wire(tile)
            self.fixed.put(tile, col * CELL, row * CELL)
            self.tile_widgets.append(tile)
        # The + tile goes on its own row under everything else.
        col, row = 0, rows
        add = Gtk.Button()
        add.set_relief(Gtk.ReliefStyle.NONE)
        add.get_style_context().add_class("tile")
        add.get_style_context().add_class("add-tile")
        add.set_size_request(tiles.UNIT, tiles.UNIT)
        add.set_tooltip_text("add a live tile")
        add.add(tiles.glyphs.Glyph("plus", 26))
        add.connect("clicked", self.add_menu)
        self.fixed.put(add, col * CELL, row * CELL)
        self.add_button = add
        self.fixed.set_size_request(tiles.px(self.cols), tiles.px(max(rows, row + 1)))
        self.fixed.show_all()
        if self.first_show:
            self.first_show = False
            self.animate_in()
        else:
            for t in self.tile_widgets:
                t.get_style_context().remove_class("entering")
            if hasattr(self, "scheduler"):
                self.scheduler.refresh()
        if focus_index is not None:
            for t in self.tile_widgets:
                if t.index == focus_index:
                    t.grab_focus()
        self.refresh_pins()

    def animate_in(self):
        def reveal(tile):
            tile.get_style_context().remove_class("entering")
            return False
        for tile in self.tile_widgets:
            col, row = tile.cell
            GLib.timeout_add(60 + 28 * (col + row), reveal, tile)

    def save(self):
        layout.save(self.data)

    # ── clicking ─────────────────────────────────────────────────────
    def on_tile(self, tile):
        if self.just_dragged:
            self.just_dragged = False
            return
        if tile.kind == "note":
            self.edit_params(tile)
            return
        if not tile.activate_tile():
            self.quit()

    # ── dragging ─────────────────────────────────────────────────────
    def wire(self, tile):
        tile.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        tile.connect("button-press-event", self.on_press)
        tile.connect("motion-notify-event", self.on_motion)
        tile.connect("button-release-event", self.on_release)
        tile.connect("popup-menu", lambda t: self.tile_menu(t, None) or True)

    def on_press(self, tile, event):
        if event.button == 3:
            self.tile_menu(tile, event)
            return True
        if event.button == 1:
            self.drag = {"tile": tile, "x": event.x_root, "y": event.y_root,
                         "ox": event.x, "oy": event.y, "on": False}
            # Holding still opens the tile menu, for touchscreens.
            self.drag["hold"] = GLib.timeout_add(LONG_PRESS, self._long_press, tile)
        return False

    def _long_press(self, tile):
        d = self.drag
        if d:
            d["hold"] = None
        if d and d["tile"] is tile and not d["on"]:
            self.drag = None
            self.just_dragged = True  # swallow the click that follows the release
            self.tile_menu(tile, None)
        return False

    def _cancel_hold(self, d):
        if d and d.get("hold"):
            GLib.source_remove(d["hold"])
            d["hold"] = None

    def on_motion(self, tile, event):
        d = self.drag
        if not d or d["tile"] is not tile:
            return False
        if not d["on"]:
            if math.hypot(event.x_root - d["x"], event.y_root - d["y"]) < DRAG_START:
                return False
            d["on"] = True
            self._cancel_hold(d)
            self.ghost.set_size_request(tile.pw, tile.ph)
            self.ghost.show()
            tile.get_style_context().add_class("lifted")
        x, y = tile.translate_coordinates(self.fixed, int(event.x), int(event.y))
        gx = max(0, min(x - d["ox"], tiles.px(self.cols) - tile.pw))
        gy = max(0, y - d["oy"])
        self.ghost.set_margin_start(int(gx))
        self.ghost.set_margin_top(int(gy))
        d["gx"], d["gy"] = gx, gy
        return True

    def on_release(self, tile, event):
        d, self.drag = self.drag, None
        self._cancel_hold(d)
        if not d or not d["on"]:
            return False
        self.ghost.hide()
        tile.get_style_context().remove_class("lifted")
        self.just_dragged = True
        GLib.timeout_add(150, self._clear_drag_flag)
        col = int(round(d["gx"] / CELL))
        row = int(round(d["gy"] / CELL))
        self.move_to_cell(tile.index, col, row)
        return True

    def _clear_drag_flag(self):
        self.just_dragged = False
        return False

    def move_to_cell(self, index, col, row):
        """Drop tile `index` on a cell: onto another tile it takes that
        tile's place; onto an empty cell it goes before whatever follows."""
        for i, c, r, w, h in self.placed:
            if i != index and c <= col < c + w and r <= row < r + h:
                self.move(index, i)
                return
        later = [i for i, c, r, w, h in self.placed if (r, c) > (row, col) and i != index]
        if not later:
            self.move(index, len(self.data["tiles"]) - 1)
        else:
            nxt = min(later)
            self.move(index, nxt - 1 if nxt > index else nxt)

    def move(self, index, new_pos):
        """Move tile `index` so it ends up at position `new_pos`."""
        tl = self.data["tiles"]
        new_pos = max(0, min(new_pos, len(tl) - 1))
        if not 0 <= index < len(tl) or index == new_pos:
            return
        tl.insert(new_pos, tl.pop(index))
        self.save()
        self.rebuild(focus_index=new_pos)

    # ── tile menu ────────────────────────────────────────────────────
    def tile_menu(self, tile, event):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("tube-menu")
        spec = self.data["tiles"][tile.index]

        def item(label, cb, parent=menu, sensitive=True):
            it = Gtk.MenuItem(label=label)
            it.set_sensitive(sensitive)
            it.connect("activate", lambda *_: cb())
            parent.append(it)
            return it

        def sub(label):
            it = Gtk.MenuItem(label=label)
            m = Gtk.Menu()
            it.set_submenu(m)
            menu.append(it)
            return m

        if tile.kind == "app":
            item("open", lambda: self.on_tile(tile))
        sizes = sub("size")
        for s in tiles.SIZE_ORDER:
            if s in tile.sizes:
                mark = "●  " if s == tile.size else "    "
                item(mark + s, lambda s=s: self.set_prop(tile.index, "size", s), sizes)
        colours = sub("colour")
        cur = spec.get("color", "accent")
        for name, value in [("accent", "accent"), ("dark", "dark")] + common.named_accents():
            mark = "●  " if value == cur else "    "
            item(mark + name, lambda v=value: self.set_prop(tile.index, "color", v), colours)
        if tile.params:
            item("set up…", lambda: self.edit_params(tile))
        menu.append(Gtk.SeparatorMenuItem())
        item("move earlier", lambda: self.move(tile.index, tile.index - 1), sensitive=tile.index > 0)
        item("move later", lambda: self.move(tile.index, tile.index + 1),
             sensitive=tile.index < len(self.data["tiles"]) - 1)
        menu.append(Gtk.SeparatorMenuItem())
        item("unpin from start", lambda: self.unpin(tile.index))
        menu.show_all()
        menu.attach_to_widget(tile, None)
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(tile, Gdk.Gravity.CENTER, Gdk.Gravity.NORTH_WEST, None)
        self._menu = menu

    def set_prop(self, index, key, value):
        spec = self.data["tiles"][index]
        if key == "color" and value == "accent":
            spec.pop("color", None)
        else:
            spec[key] = value
        self.save()
        self.rebuild(focus_index=index)

    def unpin(self, index):
        del self.data["tiles"][index]
        self.save()
        self.rebuild()
        self.refresh_pins()

    def edit_params(self, tile):
        pop = Gtk.Popover()
        pop.set_relative_to(tile)
        pop.get_style_context().add_class("tube-popover")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        head = Gtk.Label(label=tile.title, xalign=0)
        head.get_style_context().add_class("group-title")
        box.pack_start(head, False, False, 0)
        entries = {}
        for param in tile.params:
            key, label, default = param[:3]
            choices = param[3] if len(param) > 3 else None
            lab = Gtk.Label(label=label, xalign=0)
            lab.get_style_context().add_class("caption")
            box.pack_start(lab, False, False, 0)
            value = str(tile.spec.get(key, default) or "")
            if choices:
                ent = Gtk.ComboBoxText()
                for c in choices:
                    ent.append(c, c)
                ent.set_active_id(value if value in choices else choices[0])
                ent.get_text = ent.get_active_id
            else:
                ent = Gtk.Entry()
                ent.set_text(value)
                ent.set_width_chars(32)
                ent.connect("activate", lambda *_: save())
            ent.get_style_context().add_class("field")
            box.pack_start(ent, False, False, 0)
            entries[key] = ent

        def save(*_):
            spec = self.data["tiles"][tile.index]
            for key, ent in entries.items():
                val = ent.get_text().strip()
                if val:
                    spec[key] = val
                else:
                    spec.pop(key, None)
            pop.popdown()
            self.save()
            self.rebuild(focus_index=tile.index)

        btn = Gtk.Button(label="save")
        btn.get_style_context().add_class("accent-button")
        btn.set_halign(Gtk.Align.START)
        btn.connect("clicked", save)
        box.pack_start(btn, False, False, 6)
        pop.add(box)
        box.show_all()
        pop.popup()

    def add_menu(self, button):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("tube-menu")
        for name, cls in tiles.KINDS.items():
            if not cls.addable:
                continue
            it = Gtk.MenuItem()
            lab = Gtk.Label(xalign=0)
            lab.set_markup("%s  <span alpha='60%%'>%s</span>" % (
                GLib.markup_escape_text(cls.title), GLib.markup_escape_text(cls.blurb)))
            it.add(lab)
            it.connect("activate", lambda _i, n=name: self.add_tile({"type": n}))
            menu.append(it)
        menu.append(Gtk.SeparatorMenuItem())
        hint = Gtk.MenuItem(label="apps: right-click one in the list and pin it")
        hint.connect("activate", lambda *_: self.focus_first_app())
        menu.append(hint)
        menu.show_all()
        menu.attach_to_widget(button, None)
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        self._menu = menu

    def add_tile(self, spec):
        cls = tiles.KINDS.get(spec.get("type", "app"), tiles.AppTile)
        spec.setdefault("size", cls.default_size)
        for param in cls.params:
            key, default = param[0], param[2]
            if default and key != "label":
                spec.setdefault(key, default)
        self.data["tiles"].append(spec)
        self.save()
        self.rebuild(focus_index=len(self.data["tiles"]) - 1)
        GLib.idle_add(self.scroll_to_end)

    def scroll_to_end(self):
        adj = self.tile_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    # ── app list ─────────────────────────────────────────────────────
    def build_app_column(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        col.set_size_request(APPS_W, -1)
        col.get_style_context().add_class("app-column")
        head = Gtk.Label(label="apps", xalign=0)
        head.get_style_context().add_class("page-header")
        col.pack_start(head, False, False, 0)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("search")
        self.entry.get_style_context().add_class("search")
        self.entry.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.entry.connect("activate", self.on_search_activate)
        col.pack_start(self.entry, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(True)
        scroll.set_margin_bottom(40)
        self.listbox = Gtk.ListBox()
        self.listbox.get_style_context().add_class("apps")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.set_filter_func(self.filter_row)
        self.listbox.connect("row-activated", self.on_app_row)
        scroll.add(self.listbox)
        col.pack_start(scroll, True, True, 0)

        apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        apps.sort(key=lambda a: (a.get_display_name() or "").lower())
        letter = None
        for app in apps:
            name = app.get_display_name() or ""
            first = name[:1].lower()
            first = first if first.isalpha() else "#"
            if first != letter:
                letter = first
                row = Gtk.ListBoxRow()
                row.app = None
                row.set_activatable(False)
                row.set_can_focus(False)
                lab = Gtk.Label(label=letter, xalign=0)
                lab.get_style_context().add_class("app-letter")
                row.add(lab)
                self.listbox.add(row)
            self.listbox.add(self.app_row(app))
        return col

    def app_row(self, app):
        box = Gtk.Box(spacing=16)
        box.get_style_context().add_class("app-row")
        square = Gtk.Box()
        square.get_style_context().add_class("app-icon")
        square.set_size_request(40, 40)
        square.set_center_widget(tiles.glyph_for({"_info": app}, app.get_display_name(), 24))
        box.pack_start(square, False, False, 0)
        name = Gtk.Label(label=(app.get_display_name() or "").lower(), xalign=0)
        name.get_style_context().add_class("app-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(name, True, True, 0)
        pin = tiles.glyphs.Glyph("pin", 16)
        pin.get_style_context().add_class("pin-mark")
        pin.set_no_show_all(True)
        box.pack_end(pin, False, False, 0)
        row = Gtk.ListBoxRow()
        row.add(box)
        row.app = app
        row.app_id = (app.get_id() or "").removesuffix(".desktop")
        row.pin_mark = pin
        row.set_tooltip_text(app.get_description() or app.get_display_name())
        row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        row.connect("button-press-event", self.on_app_press)
        row.connect("popup-menu", lambda r: self.app_menu(r, None) or True)
        return row

    def pinned_ids(self):
        return {t.get("app") for t in self.data["tiles"] if t.get("type", "app") == "app"}

    def refresh_pins(self):
        if not hasattr(self, "listbox"):
            return
        pinned = self.pinned_ids()
        for row in self.listbox.get_children():
            if getattr(row, "app", None) is not None:
                row.pin_mark.set_visible(row.app_id in pinned)

    def on_app_press(self, row, event):
        if event.button == 3:
            self.app_menu(row, event)
            return True
        return False

    def app_menu(self, row, event):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("tube-menu")
        open_it = Gtk.MenuItem(label="open")
        open_it.connect("activate", lambda *_: self.on_app_row(self.listbox, row))
        menu.append(open_it)
        if row.app_id in self.pinned_ids():
            it = Gtk.MenuItem(label="unpin from start")
            it.connect("activate", lambda *_: self.unpin_app(row.app_id))
        else:
            it = Gtk.MenuItem(label="pin to start")
            it.connect("activate", lambda *_: self.pin_app(row))
        menu.append(it)
        menu.show_all()
        menu.attach_to_widget(row, None)
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            menu.popup_at_widget(row, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        self._menu = menu

    def pin_app(self, row):
        self.add_tile({"type": "app", "app": row.app_id, "size": "medium"})

    def unpin_app(self, app_id):
        for i, t in enumerate(self.data["tiles"]):
            if t.get("type", "app") == "app" and t.get("app") == app_id:
                self.unpin(i)
                return

    def filter_row(self, row):
        text = self.entry.get_text().strip().lower()
        if not text:
            return True
        app = getattr(row, "app", None)
        if app is None:
            return False
        words = [app.get_display_name(), app.get_name(), app.get_executable(),
                 app.get_description()]
        if isinstance(app, Gio.DesktopAppInfo):
            words += app.get_keywords() or []
        hay = " ".join(w for w in words if w).lower()
        return all(word in hay for word in text.split())

    def visible_app_rows(self):
        return [r for r in self.listbox.get_children()
                if getattr(r, "app", None) is not None and self.filter_row(r)]

    def on_search_activate(self, _entry):
        rows = self.visible_app_rows()
        if rows:
            self.on_app_row(self.listbox, rows[0])

    def on_app_row(self, _lb, row):
        if getattr(row, "app", None) is not None:
            common.launch_app(row.app)
            self.quit()

    def focus_first_app(self):
        rows = self.visible_app_rows()
        if rows:
            rows[0].grab_focus()

    # ── keys ─────────────────────────────────────────────────────────
    def on_key(self, _win, event):
        key = event.keyval
        mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK)
        if key == Gdk.KEY_Escape:
            if self.drag and self.drag.get("on"):
                self.ghost.hide()
                self.drag["tile"].get_style_context().remove_class("lifted")
                self.drag = None
            elif self.entry.get_text():
                self.entry.set_text("")
            else:
                self.quit()
            return True
        focus = self.win.get_focus()
        # Alt+arrows move the focused tile.
        if (event.state & Gdk.ModifierType.MOD1_MASK) and isinstance(focus, tiles.Tile):
            if key in (Gdk.KEY_Left, Gdk.KEY_Up):
                self.move(focus.index, focus.index - 1)
                return True
            if key in (Gdk.KEY_Right, Gdk.KEY_Down):
                self.move(focus.index, focus.index + 1)
                return True
        if isinstance(focus, Gtk.ListBoxRow) and key == Gdk.KEY_p \
                and event.state & Gdk.ModifierType.CONTROL_MASK:
            if focus.app_id in self.pinned_ids():
                self.unpin_app(focus.app_id)
            else:
                self.pin_app(focus)
            return True
        # Typing anywhere searches the app list.
        text = event.string
        if not mods and text and text.isprintable() and not text.isspace() \
                and not self.entry.has_focus() and not isinstance(focus, Gtk.Entry):
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
    group.add_argument("--apps", action="store_true", help="open with the app list focused")
    group.add_argument("--search", action="store_true", help="open with the search box focused")
    parser.add_argument("--close", action="store_true", help="close start if it is open")
    parser.add_argument("--reset", action="store_true",
                        help="forget your tile layout and go back to the default one")
    args = parser.parse_args(argv)

    if args.reset:
        layout.reset()
    if not common.toggle_instance("start", close_only=args.close):
        return 0
    mode = "apps" if args.apps else "search" if args.search else "tiles"
    StartScreen(mode)
    Gtk.main()
    return 0
