"""levels.py: the watcher that keeps the indicator, strip and status panel
in step with the real volume and brightness. No GTK needed."""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import levels  # noqa: E402


def backlight(root, name, cur, mx=1000):
    dev = os.path.join(root, name)
    os.makedirs(dev, exist_ok=True)
    with open(os.path.join(dev, "brightness"), "w") as f:
        f.write("%d\n" % cur)
    with open(os.path.join(dev, "max_brightness"), "w") as f:
        f.write("%d\n" % mx)
    return dev


def test_read_backlight_rounds_like_tube_osd(tmp_path):
    dev = backlight(str(tmp_path), "intel_backlight", 425, 1000)
    assert levels.read_backlight(dev) == 43
    assert levels.brightness(str(tmp_path)) == 43


def test_read_backlight_missing(tmp_path):
    assert levels.read_backlight(str(tmp_path / "nothing")) is None
    assert levels.brightness(str(tmp_path)) is None


def test_parse_wpctl():
    assert levels.parse_wpctl("Volume: 0.45") == (45, False)
    assert levels.parse_wpctl("Volume: 0.30 [MUTED]") == (30, True)
    assert levels.parse_wpctl("") is None


def test_interesting_events():
    assert levels.interesting("Event 'change' on sink #52")
    assert levels.interesting("Event 'change' on server #0")
    assert not levels.interesting("Event 'change' on sink-input #91")
    assert not levels.interesting("Event 'change' on source #53")
    assert not levels.interesting("Event 'new' on client #120")


def test_hush(tmp_path, monkeypatch):
    monkeypatch.setattr(levels, "HUSH", str(tmp_path / "hush"))
    assert not levels.hushed()
    levels.hush()
    assert levels.hushed()
    assert not levels.hushed(time.time() + 5)


def test_watcher_sees_a_backlight_change_made_elsewhere(tmp_path, monkeypatch):
    """The firmware moves the backlight itself: no tube-osd, still seen."""
    monkeypatch.setattr(levels, "BRIGHTNESS_EVERY", 0.01)
    root = str(tmp_path)
    backlight(root, "acpi_video0", 50, 100)
    got, seen = [], threading.Event()

    def on_change(kind, value, muted):
        got.append((kind, value, muted))
        seen.set()

    w = levels.Watcher(on_change, volume=False, root=root)
    try:
        time.sleep(0.1)
        assert got == []           # the first reading is quiet
        backlight(root, "acpi_video0", 70, 100)
        assert seen.wait(2)
        assert got == [("brightness", 70, False)]
    finally:
        w.stop()


def test_report_dedups_and_quiet():
    got = []
    w = levels.Watcher(lambda *a: got.append(a), volume=False, brightness=False)
    w._report("volume", 40, False)            # first: quiet
    w._report("volume", 40, False)            # same: nothing
    w._report("volume", 45, False)
    w._report("volume", 45, True)             # muted is a change too
    w._report("volume", 80, False, quiet=True)  # new speakers: quiet
    w._report("volume", 75, False)
    assert got == [("volume", 45, False), ("volume", 45, True), ("volume", 75, False)]
