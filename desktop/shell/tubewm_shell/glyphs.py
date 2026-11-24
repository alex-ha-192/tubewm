"""Monochrome line glyphs drawn with cairo.

tubewm draws its own simple glyphs instead of shipping an icon font, so the
shell looks the same on any system and doesn't borrow anyone's artwork.
Every glyph is drawn in a 24x24 box and scaled to the requested size.
"""

import math

from gi.repository import Gtk


def _circle(cr, x, y, r):
    cr.new_sub_path()
    cr.arc(x, y, r, 0, 2 * math.pi)


def _search(cr):
    _circle(cr, 10, 10, 6.5)
    cr.move_to(14.8, 14.8)
    cr.line_to(21, 21)


def _share(cr):
    _circle(cr, 6, 12, 2.6)
    _circle(cr, 18, 5.5, 2.6)
    _circle(cr, 18, 18.5, 2.6)
    cr.move_to(8.3, 10.8)
    cr.line_to(15.7, 6.7)
    cr.move_to(8.3, 13.2)
    cr.line_to(15.7, 17.3)


def _start(cr):
    # The tubewm mark: one solid square inside an outline.
    cr.rectangle(3, 3, 18, 18)
    cr.stroke()
    cr.rectangle(8, 8, 8, 8)
    cr.fill()


def _devices(cr):
    cr.rectangle(2.5, 4, 19, 12.5)
    cr.move_to(8, 20.5)
    cr.line_to(16, 20.5)
    cr.move_to(12, 16.5)
    cr.line_to(12, 20.5)


def _settings(cr):
    _circle(cr, 12, 12, 3.2)
    cr.stroke()
    _circle(cr, 12, 12, 7)
    for i in range(8):
        a = i * math.pi / 4
        cr.move_to(12 + 7 * math.cos(a), 12 + 7 * math.sin(a))
        cr.line_to(12 + 10 * math.cos(a), 12 + 10 * math.sin(a))


def _lock(cr):
    cr.rectangle(4.5, 10.5, 15, 11)
    cr.move_to(8, 10.5)
    cr.line_to(8, 7)
    cr.arc(12, 7, 4, math.pi, 2 * math.pi)
    cr.line_to(16, 10.5)


def _power(cr):
    cr.arc(12, 13, 8, -math.pi / 2 + 0.75, 3 * math.pi / 2 - 0.75)
    cr.move_to(12, 2.5)
    cr.line_to(12, 12)


def _sleep(cr):
    cr.arc(12, 12, 8.5, math.pi * 0.35, math.pi * 1.65)
    cr.arc_negative(15.5, 9.5, 6, math.pi * 1.25, math.pi * 0.62)


def _restart(cr):
    cr.arc(12, 12, 8, -math.pi / 2, math.pi * 1.25)
    cr.move_to(12, 4)
    cr.line_to(15.5, 1.5)
    cr.move_to(12, 4)
    cr.line_to(15.5, 6.5)


def _signout(cr):
    cr.move_to(13, 3.5)
    cr.line_to(4, 3.5)
    cr.line_to(4, 20.5)
    cr.line_to(13, 20.5)
    cr.move_to(9, 12)
    cr.line_to(21, 12)
    cr.move_to(17, 8)
    cr.line_to(21, 12)
    cr.line_to(17, 16)


def _music(cr):
    cr.move_to(9, 17.5)
    cr.line_to(9, 4)
    cr.line_to(20, 2.5)
    cr.line_to(20, 15.5)
    cr.stroke()
    _circle(cr, 6.5, 17.5, 2.8)
    cr.fill()
    _circle(cr, 17.5, 15.5, 2.8)
    cr.fill()


def _video(cr):
    cr.rectangle(2.5, 5.5, 13, 13)
    cr.move_to(15.5, 10)
    cr.line_to(21.5, 6.5)
    cr.line_to(21.5, 17.5)
    cr.line_to(15.5, 14)


def _apps(cr):
    for y in (4.5, 12, 19.5):
        cr.rectangle(2.5, y - 1.5, 3, 3)
        cr.move_to(9, y)
        cr.line_to(21.5, y)


def _terminal(cr):
    cr.rectangle(2.5, 3.5, 19, 17)
    cr.move_to(6.5, 9)
    cr.line_to(10, 12)
    cr.line_to(6.5, 15)
    cr.move_to(12, 15.5)
    cr.line_to(17, 15.5)


def _folder(cr):
    cr.move_to(2.5, 5)
    cr.line_to(9.5, 5)
    cr.line_to(11.5, 7.5)
    cr.line_to(21.5, 7.5)
    cr.line_to(21.5, 19.5)
    cr.line_to(2.5, 19.5)
    cr.close_path()


def _web(cr):
    _circle(cr, 12, 12, 9.5)
    cr.move_to(2.5, 12)
    cr.line_to(21.5, 12)
    cr.save()
    cr.translate(12, 12)
    cr.scale(0.45, 1)
    cr.new_sub_path()
    cr.arc(0, 0, 9.5, 0, 2 * math.pi)
    cr.restore()


def _code(cr):
    cr.move_to(8, 6)
    cr.line_to(2.5, 12)
    cr.line_to(8, 18)
    cr.move_to(16, 6)
    cr.line_to(21.5, 12)
    cr.line_to(16, 18)
    cr.move_to(13.5, 4)
    cr.line_to(10.5, 20)


def _chat(cr):
    cr.move_to(2.5, 3.5)
    cr.line_to(21.5, 3.5)
    cr.line_to(21.5, 16)
    cr.line_to(10, 16)
    cr.line_to(5, 21)
    cr.line_to(5, 16)
    cr.line_to(2.5, 16)
    cr.close_path()


def _mail(cr):
    cr.rectangle(2.5, 5, 19, 14)
    cr.move_to(2.5, 5)
    cr.line_to(12, 13)
    cr.line_to(21.5, 5)


def _photo(cr):
    cr.rectangle(2.5, 4, 19, 16)
    cr.move_to(2.5, 17)
    cr.line_to(9, 10.5)
    cr.line_to(14, 15.5)
    cr.line_to(16.5, 13)
    cr.line_to(21.5, 18)
    cr.stroke()
    _circle(cr, 16.5, 8.5, 1.8)
    cr.fill()


def _game(cr):
    cr.rectangle(2.5, 7, 19, 11)
    cr.move_to(7, 10)
    cr.line_to(7, 15)
    cr.move_to(4.5, 12.5)
    cr.line_to(9.5, 12.5)
    cr.stroke()
    _circle(cr, 16, 11, 1.3)
    cr.fill()
    _circle(cr, 18.5, 14, 1.3)
    cr.fill()


def _calendar(cr):
    cr.rectangle(2.5, 4.5, 19, 16)
    cr.move_to(2.5, 9)
    cr.line_to(21.5, 9)
    cr.move_to(7, 2.5)
    cr.line_to(7, 6.5)
    cr.move_to(17, 2.5)
    cr.line_to(17, 6.5)
    cr.stroke()
    cr.rectangle(13, 13, 5, 4)
    cr.fill()


def _clock(cr):
    _circle(cr, 12, 12, 9.5)
    cr.move_to(12, 6)
    cr.line_to(12, 12)
    cr.line_to(16, 14.5)


def _battery(cr):
    cr.rectangle(2.5, 7, 17, 10)
    cr.stroke()
    cr.rectangle(19.5, 10, 2.5, 4)
    cr.fill()


def _system(cr):
    cr.move_to(2.5, 14)
    cr.line_to(7, 14)
    cr.line_to(9.5, 6)
    cr.line_to(13.5, 19)
    cr.line_to(16, 11)
    cr.line_to(17.5, 14)
    cr.line_to(21.5, 14)


def _bluetooth(cr):
    cr.move_to(6.5, 7.5)
    cr.line_to(17, 16.5)
    cr.line_to(12, 21)
    cr.line_to(12, 3)
    cr.line_to(17, 7.5)
    cr.line_to(6.5, 16.5)


def _sound(cr):
    cr.move_to(3, 9)
    cr.line_to(7, 9)
    cr.line_to(12, 4.5)
    cr.line_to(12, 19.5)
    cr.line_to(7, 15)
    cr.line_to(3, 15)
    cr.close_path()
    cr.stroke()
    cr.arc(12, 12, 5, -0.8, 0.8)
    cr.stroke()
    cr.arc(12, 12, 9, -0.85, 0.85)


GLYPHS = {
    "search": _search, "share": _share, "start": _start, "devices": _devices,
    "settings": _settings, "lock": _lock, "power": _power, "sleep": _sleep,
    "restart": _restart, "signout": _signout, "music": _music, "video": _video,
    "apps": _apps, "terminal": _terminal, "folder": _folder, "files": _folder,
    "web": _web, "code": _code, "chat": _chat, "mail": _mail, "photo": _photo,
    "game": _game, "calendar": _calendar, "clock": _clock, "battery": _battery,
    "system": _system, "bluetooth": _bluetooth, "sound": _sound,
}


def draw(cr, name, size, rgba=(1, 1, 1, 1)):
    fn = GLYPHS.get(name)
    if fn is None:
        return False
    cr.save()
    s = size / 24.0
    cr.scale(s, s)
    cr.set_source_rgba(*rgba)
    cr.set_line_width(1.6 if size >= 32 else 1.9)
    cr.set_line_cap(1)   # round
    cr.set_line_join(1)  # round
    cr.new_path()
    fn(cr)
    cr.stroke()
    cr.restore()
    return True


class Glyph(Gtk.DrawingArea):
    """A widget that draws one glyph in the widget's foreground colour."""

    def __init__(self, name, size):
        super().__init__()
        self.name = name
        self.size = size
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._on_draw)

    def _on_draw(self, widget, cr):
        color = widget.get_style_context().get_color(widget.get_state_flags())
        draw(cr, self.name, self.size, (color.red, color.green, color.blue, color.alpha))
        return False


def has(name):
    return name in GLYPHS
