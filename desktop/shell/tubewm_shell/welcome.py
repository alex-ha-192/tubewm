"""tube-welcome: the first-login welcome. Pick a colour, check the keyboard, learn three things.

    tube-welcome               show it
    tube-welcome --first-run   show it only if it hasn't been finished or skipped before

Every page starts with a sensible choice made, so "next, next, start" is fine.
"""

import argparse
import os
import subprocess
import sys

from . import common, keyboard
from .common import GLib, Gtk

MARKER = os.path.join(common.CONFIG, "tubewm", "welcomed")

CSS = """
.welcome { background-image: linear-gradient(135deg, alpha(@tube_accent, 0.22), @tube_bg 60%); }
.welcome-body { margin: 72px 110px 56px 110px; }
.welcome-title { font-size: 72px; font-weight: 300; color: @tube_fg; }
.welcome-sub { font-size: 20px; font-weight: 300; color: @tube_subtle; }
.welcome-dot { min-width: 48px; min-height: 5px; background: @tube_surface_hi; }
.welcome-dot.on { background: @tube_accent; }
.welcome button { border-radius: 0; box-shadow: none; background-image: none; }
.welcome button.primary { background: @tube_accent; color: #FFFFFF; border: none;
    font-size: 17px; font-weight: 600; padding: 10px 34px; }
.welcome button.primary:hover { background: @tube_accent_light; }
.welcome button.ghost { background: transparent; border: none; color: @tube_subtle;
    font-size: 17px; padding: 10px 0; }
.welcome button.ghost:hover { color: @tube_fg; }
.welcome button.swatch { border: none; padding: 0; min-width: 84px; min-height: 84px; }
.welcome button.swatch:hover { box-shadow: inset 0 0 0 3px alpha(#FFFFFF, 0.5); }
.welcome button.swatch.current { box-shadow: inset 0 0 0 4px #FFFFFF; }
.welcome-label { font-size: 15px; color: @tube_subtle; }
.welcome-value { font-size: 26px; font-weight: 300; color: @tube_fg; }
.welcome entry { background: @tube_surface; color: @tube_fg; border: 2px solid @tube_accent;
    border-radius: 0; box-shadow: none; font-size: 20px; min-height: 44px; padding: 0 12px; }
.welcome list { background: @tube_surface; }
.welcome list row { padding: 8px 14px; font-size: 16px; color: @tube_subtle; }
.welcome list row:selected, .welcome list row:hover { background: @tube_surface_hi; color: @tube_fg; }
.welcome button.link { background: transparent; border: none; padding: 4px 0;
    color: @tube_accent_light; font-size: 16px; }
.welcome-tip { background: @tube_surface; padding: 28px; }
.welcome-tip-key { font-size: 32px; font-weight: 300; color: @tube_accent_light; }
.welcome-tip-text { font-size: 17px; color: @tube_subtle; }
"""


def _label(text, cls, wrap=False):
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.get_style_context().add_class(cls)
    if wrap:
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(60)
    return lbl


def _button(text, cls, cb):
    btn = Gtk.Button(label=text)
    btn.get_style_context().add_class(cls)
    btn.connect("clicked", cb)
    if cls == "link":
        btn.set_halign(Gtk.Align.START)
        btn.get_child().set_xalign(0)
    return btn


class Welcome:
    PAGES = ("colour", "keyboard", "tips")

    def __init__(self, page=0):
        common.apply_css(CSS)
        self.win = common.make_layer_window("welcome")
        self.win.get_style_context().add_class("welcome")
        self.win.connect("key-press-event", self.on_key)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.get_style_context().add_class("welcome-body")
        self.dots = Gtk.Box(spacing=8)
        outer.pack_start(self.dots, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(260)
        self.stack.add_named(self.page_colour(), "colour")
        self.stack.add_named(self.page_keyboard(), "keyboard")
        self.stack.add_named(self.page_tips(), "tips")
        outer.pack_start(self.stack, True, True, 0)

        foot = Gtk.Box()
        self.back = _button("skip", "ghost", self.on_back)
        self.next = _button("next", "primary", self.on_next)
        foot.pack_start(self.back, False, False, 0)
        foot.pack_end(self.next, False, False, 0)
        outer.pack_start(foot, False, False, 0)

        self.win.add(outer)
        self.win.show_all()
        self.picker_box.hide()
        self.update_layout()
        self.show_page(page)

    # ── pages ────────────────────────────────────────────────────────
    def header(self, box, title, sub):
        box.pack_start(_label(title, "welcome-title"), False, False, 0)
        box.pack_start(_label(sub, "welcome-sub", wrap=True), False, False, 0)

    def page_colour(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(48)
        self.header(box, "pick a colour",
                    "It goes on your tiles, your windows, your apps and your background. "
                    "You can change it any time in settings.")
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_max_children_per_line(6)
        grid.set_min_children_per_line(6)
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_halign(Gtk.Align.START)
        grid.set_margin_top(30)
        self.swatches = {}
        for name, hex_ in common.named_accents():
            btn = Gtk.Button()
            btn.get_style_context().add_class("swatch")
            btn.set_tooltip_text(name)
            prov = Gtk.CssProvider()
            prov.load_from_data(("button { background: %s; }" % hex_).encode())
            btn.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            btn.connect("clicked", self.on_accent, name)
            grid.add(btn)
            self.swatches[name] = (btn, hex_)
        box.pack_start(grid, False, False, 0)
        self.mark_accent()
        return box

    def page_keyboard(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(48)
        self.header(box, "check your keyboard",
                    "Type a few symbols below, like \" @ # and £. If they come out wrong, "
                    "choose another layout.")
        cols = Gtk.Box(spacing=60)
        cols.set_margin_top(30)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.pack_start(_label("layout", "welcome-label"), False, False, 0)
        self.layout_label = _label("", "welcome-value")
        left.pack_start(self.layout_label, False, False, 0)
        left.pack_start(_button("choose another", "link", self.on_change_layout), False, False, 0)
        self.system_note = _label("", "welcome-label", wrap=True)
        left.pack_start(self.system_note, False, False, 6)
        self.system_btn = _button("use it on the sign-in screen too", "link", self.on_system)
        left.pack_start(self.system_btn, False, False, 0)
        cols.pack_start(left, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.pack_start(_label("try it", "welcome-label"), False, False, 0)
        self.test = Gtk.Entry()
        self.test.set_width_chars(26)
        right.pack_start(self.test, False, False, 0)

        # The layout list, shown on "choose another".
        self.picker_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.picker_box.set_margin_top(18)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("search layouts")
        self.search.connect("search-changed", lambda *_: self.layout_list.invalidate_filter())
        self.picker_box.pack_start(self.search, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(420, 260)
        self.layout_list = Gtk.ListBox()
        self.layout_list.set_filter_func(self.filter_layout)
        self.layout_list.connect("row-activated", self.on_layout_row)
        for code, var, desc in keyboard.layouts():
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label=desc, xalign=0))
            row.code, row.var, row.desc = code, var, desc
            self.layout_list.add(row)
        scroll.add(self.layout_list)
        self.picker_box.pack_start(scroll, False, False, 0)
        right.pack_start(self.picker_box, False, False, 0)
        cols.pack_start(right, False, False, 0)

        box.pack_start(cols, False, False, 0)
        self.update_layout()
        return box

    def page_tips(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(48)
        self.header(box, "three things to know", "That's all you need. Everything else is in start.")
        row = Gtk.Box(spacing=16, homogeneous=True)
        row.set_margin_top(30)
        tips = (
            ("start", "Click the tile at the top left, or press the Windows key and S. "
                      "Your apps and tiles live here."),
            ("swipe", "Three fingers sideways on the touchpad moves between your desktops."),
            ("power", "The power button asks first: sleep, sign out, restart or shut down. "
                      "Closing the lid locks and sleeps."),
        )
        for key, text in tips:
            tip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            tip.get_style_context().add_class("welcome-tip")
            tip.pack_start(_label(key, "welcome-tip-key"), False, False, 0)
            tip.pack_start(_label(text, "welcome-tip-text", wrap=True), False, False, 0)
            row.pack_start(tip, True, True, 0)
        box.pack_start(row, False, False, 0)
        return box

    # ── navigation ───────────────────────────────────────────────────
    def show_page(self, index):
        self.index = index
        self.stack.set_visible_child_name(self.PAGES[index])
        for child in self.dots.get_children():
            self.dots.remove(child)
        for i in range(len(self.PAGES)):
            dot = Gtk.Box()
            dot.get_style_context().add_class("welcome-dot")
            if i <= index:
                dot.get_style_context().add_class("on")
            self.dots.pack_start(dot, False, False, 0)
        self.dots.show_all()
        self.back.set_label("skip" if index == 0 else "back")
        last = index == len(self.PAGES) - 1
        self.next.set_label("start using it" if last else "next")
        if self.PAGES[index] == "keyboard":
            self.test.grab_focus()
        else:
            self.next.grab_focus()

    def on_next(self, _btn):
        if self.index == len(self.PAGES) - 1:
            self.finish()
        else:
            self.show_page(self.index + 1)

    def on_back(self, _btn):
        if self.index == 0:
            self.finish()
        else:
            self.show_page(self.index - 1)

    def on_key(self, _win, event):
        from gi.repository import Gdk
        if event.keyval == Gdk.KEY_Escape:
            if self.picker_box.get_visible():
                self.picker_box.hide()
            else:
                self.finish()
            return True
        return False

    def finish(self):
        os.makedirs(os.path.dirname(MARKER), exist_ok=True)
        with open(MARKER, "w") as fh:
            fh.write("done\n")
        Gtk.main_quit()

    # ── colour ───────────────────────────────────────────────────────
    def mark_accent(self):
        cur = common.load_palette()["ACCENT"].upper()
        for btn, hex_ in self.swatches.values():
            ctx = btn.get_style_context()
            (ctx.add_class if hex_.upper() == cur else ctx.remove_class)("current")

    def on_accent(self, _btn, name):
        # tube-accent re-renders everything and reloads sway; let it run, then
        # take the new colour ourselves.
        try:
            proc = subprocess.Popen(["tube-accent", name], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError:
            return
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, self.accent_done)
        btn, _hex = self.swatches[name]
        for other, _ in self.swatches.values():
            other.get_style_context().remove_class("current")
        btn.get_style_context().add_class("current")

    def accent_done(self, *_):
        common.apply_css(CSS)
        self.mark_accent()

    # ── keyboard ─────────────────────────────────────────────────────
    def update_layout(self):
        cur = keyboard.load() or keyboard.guess()
        self.layout_label.set_text(keyboard.describe(*cur))
        sysk = keyboard.system()
        differs = sysk is not None and tuple(sysk) != tuple(cur)
        self.system_note.set_text("The sign-in screen uses %s." % keyboard.describe(*sysk)
                                  if differs else "")
        self.system_note.set_visible(differs)
        self.system_btn.set_visible(differs)

    def filter_layout(self, row):
        words = self.search.get_text().lower().split()
        hay = ("%s %s %s" % (row.desc, row.code, row.var)).lower()
        return all(w in hay for w in words)

    def on_change_layout(self, _btn):
        self.picker_box.show_all()
        self.search.grab_focus()

    def on_layout_row(self, _lb, row):
        keyboard.save(row.code, row.var)
        self.picker_box.hide()
        self.update_layout()
        self.test.set_text("")
        self.test.grab_focus()

    def on_system(self, _btn):
        """The login screen needs root: ask for the password in a terminal,
        with this window out of the way until it's done."""
        term = os.environ.get("TERMINAL", "foot")
        script = ("tube-keyboard system && echo && echo 'Done. This window closes in a moment.' "
                  "&& sleep 2 || { echo; read -r -p 'Press enter to close' _; }")
        try:
            proc = subprocess.Popen([term, "-e", "sh", "-c", script])
        except OSError:
            return
        self.win.hide()

        def back(*_):
            self.win.show()
            self.update_layout()
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, back)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-welcome", description=__doc__.split("\n")[0])
    parser.add_argument("--first-run", action="store_true",
                        help="only show if it hasn't been finished or skipped before")
    parser.add_argument("--page", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.first_run and os.path.exists(MARKER):
        return 0
    if not common.toggle_instance("welcome"):
        return 0
    Welcome(max(0, min(args.page, len(Welcome.PAGES) - 1)))
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
