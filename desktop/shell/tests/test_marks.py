"""marks.py: the strip's level-aware sound and battery marks, and the date;
plus a guard on the indicator's FIFO watch. No GTK needed."""

import os
import re
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import marks  # noqa: E402

PAL = {"FG": "#FFFFFF", "DIM": "#656565", "SUBTLE": "#8A8A8A", "ACCENT_LIGHT": "#FF66C4"}
NS = "{http://www.w3.org/2000/svg}"


def strokes(svg):
    return [p.get("stroke") for p in ET.fromstring(svg).iter(NS + "path")]


def test_waves_by_level():
    assert [marks.waves(v) for v in (0, 1, 33, 34, 66, 67, 100, 150)] == [0, 1, 1, 2, 2, 3, 3, 3]


def test_volume_lights_that_many_waves():
    for level, lit in ((10, 1), (50, 2), (90, 3)):
        svg = marks.volume_svg(level, False, PAL)
        waves = strokes(svg)[1:]          # the first path is the speaker
        assert len(waves) == 3
        assert waves.count("#FFFFFF") == lit
        assert waves.count("#656565") == 3 - lit


def test_volume_muted_or_zero_is_crossed_out():
    for level, muted in ((40, True), (0, False)):
        svg = marks.volume_svg(level, muted, PAL)
        assert len(strokes(svg)) == 2     # the speaker and the cross
    assert marks.volume_key(40, True) == marks.volume_key(0, False)


def fill_width(svg):
    rects = list(ET.fromstring(svg).iter(NS + "rect"))
    return float(rects[1].get("width")) if len(rects) > 1 else 0.0


def test_battery_fills_with_charge():
    widths = [fill_width(marks.battery_svg(p, False, PAL)) for p in (5, 30, 60, 100)]
    assert widths == sorted(widths)
    assert widths[-1] == marks.FILL_W
    assert fill_width(marks.battery_svg(0, False, PAL)) == 0.0
    assert fill_width(marks.battery_svg(1, False, PAL)) > 0     # a sliver, never nothing


def test_battery_low_is_accent_unless_charging():
    assert 'stroke="#FF66C4"' in marks.battery_svg(10, False, PAL)
    assert "#FF66C4" not in marks.battery_svg(10, True, PAL)
    assert "#FF66C4" not in marks.battery_svg(60, False, PAL)
    assert marks.BOLT in marks.battery_svg(60, True, PAL)


def test_marks_are_valid_svg():
    for svg in (marks.volume_svg(55, False, {}), marks.battery_svg(42, True, {})):
        root = ET.fromstring(svg)
        assert root.get("viewBox") == "0 0 24 24"


def test_cache_keys_change_with_what_is_drawn():
    assert marks.battery_key(50, False) != marks.battery_key(90, False)
    assert marks.battery_key(50, False) != marks.battery_key(50, True)
    assert marks.volume_key(20, False) != marks.volume_key(80, False)


def test_date_text():
    t = time.mktime((2026, 11, 25, 12, 0, 0, 0, 0, -1))
    text = marks.date_text(t)
    assert text == text.lower()
    assert re.fullmatch(r"\S+ 25 \S+", text)


def test_osd_fifo_watch_is_not_high_priority():
    """A HIGH-priority watch that maps the window deadlocks GDK's Wayland
    source (the indicator froze for good on its first FIFO line)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "tubewm_shell", "osd.py")).read()
    call = re.search(r"GLib\.io_add_watch\(fd, ([\w.]+),", src)
    assert call and call.group(1) != "GLib.PRIORITY_HIGH"
