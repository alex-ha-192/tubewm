"""levels: notice when the volume or the brightness changes, whatever changed it.

tube-osd only knows about the presses that reach it. Plenty don't: on many
laptops the firmware (or the kernel's ACPI video driver) moves the backlight
itself when you press Fn+brightness, some keyboards send keys the compositor
has no binding for, a headset has its own buttons, and apps set their own
volume. So rather than trust the key, the indicator, the strip and the status
panel watch the levels themselves:

  * brightness: /sys/class/backlight/*/brightness, read a few times a second
    (a sysfs read, no process started);
  * volume: `pactl subscribe` (PipeWire answers it too), which says when a
    sink or the default sink changes, with a slow poll if there is no pactl.

Watcher(on_change) calls on_change(kind, value, muted) from a worker thread,
with kind "volume" or "brightness", whenever the value it reads differs from
the last one. Callers in GTK hand it to the main loop with GLib.idle_add.

No GTK here, so this can be used (and tested) anywhere.
"""

import glob
import os
import re
import shutil
import subprocess
import threading
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
BACKLIGHT = "/sys/class/backlight"
# Touched by our own sliders: changes within HUSH_S of it are ours, and the
# indicator needn't pop up over the slider that made them.
HUSH = os.path.join(RUNTIME, "tube-levels.hush")
HUSH_S = 1.0

BRIGHTNESS_EVERY = 0.2   # seconds between backlight reads
VOLUME_EVERY = 1.0       # seconds between volume reads when there's no pactl


def have(cmd):
    return shutil.which(cmd) is not None


def _sh(cmd, timeout=2):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ── hush: changes we made ourselves ─────────────────────────────────────────

def hush():
    """Mark the next second of changes as made from a slider of ours."""
    try:
        with open(HUSH, "a"):
            pass
        os.utime(HUSH, None)
    except OSError:
        pass


def hushed(now=None):
    try:
        return (now or time.time()) - os.path.getmtime(HUSH) < HUSH_S
    except OSError:
        return False


# ── brightness ──────────────────────────────────────────────────────────────

def backlights(root=BACKLIGHT):
    return sorted(glob.glob(os.path.join(root, "*")))


def read_backlight(dev):
    """Percent (rounded as tube-osd does) of one backlight device, or None."""
    try:
        with open(os.path.join(dev, "brightness")) as f:
            cur = int(f.read().strip())
        with open(os.path.join(dev, "max_brightness")) as f:
            mx = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if mx <= 0:
        return None
    return max(0, min(100, (cur * 100 + mx // 2) // mx))


def brightness(root=BACKLIGHT):
    """Percent of the first backlight (the one brightnessctl picks), or None."""
    for dev in backlights(root):
        pct = read_backlight(dev)
        if pct is not None:
            return pct
    return None


# ── volume ──────────────────────────────────────────────────────────────────

def parse_wpctl(out):
    """(percent, muted) from `wpctl get-volume`, or None."""
    m = re.search(r"Volume:\s*([\d.]+)", out or "")
    if not m:
        return None
    return int(float(m.group(1)) * 100 + 0.5), "MUTED" in out


def volume():
    """(percent, muted) of the default output, or None with no sound server."""
    if have("wpctl"):
        got = parse_wpctl(_sh(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
        if got:
            return got
    if have("pactl"):
        m = re.search(r"(\d+)%", _sh(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
        if m:
            return int(m.group(1)), "yes" in _sh(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
    return None


def default_sink():
    return _sh(["pactl", "get-default-sink"]) if have("pactl") else ""


def interesting(line):
    """Does a `pactl subscribe` line say the output volume may have moved?
    Sinks change their volume and mute; the server changes the default sink.
    Streams (sink-input) and sources come and go all the time: not those."""
    return bool(re.match(r"Event '(change|new|remove)' on (sink|server) ", line or ""))


# ── the watcher ─────────────────────────────────────────────────────────────

class Watcher:
    """Calls on_change(kind, value, muted) from a thread when a level moves.

    The first reading of each is taken quietly, as is the first after the
    default speakers change (a headset coming in is not a volume change)."""

    def __init__(self, on_change, volume=True, brightness=True, root=BACKLIGHT):
        self.on_change = on_change
        self.root = root
        self.stopped = threading.Event()
        self.proc = None
        self.last = {}
        if brightness and backlights(root):
            threading.Thread(target=self._brightness, daemon=True).start()
        if volume:
            threading.Thread(target=self._volume, daemon=True).start()

    def stop(self):
        self.stopped.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass

    def _report(self, kind, value, muted=False, quiet=False):
        if value is None:
            return
        now = (value, muted)
        before = self.last.get(kind)
        self.last[kind] = now
        if before is None or before == now or quiet:
            return
        try:
            self.on_change(kind, value, muted)
        except Exception:  # noqa: BLE001 - a bad callback mustn't stop the watch
            pass

    # Brightness: every device, so whichever one the firmware moved is seen.
    def _brightness(self):
        seen = {}
        while not self.stopped.is_set():
            for dev in backlights(self.root):
                pct = read_backlight(dev)
                if pct is None:
                    continue
                if dev not in seen:
                    seen[dev] = pct
                    if "brightness" not in self.last:
                        self.last["brightness"] = (pct, False)
                elif seen[dev] != pct:
                    seen[dev] = pct
                    self._report("brightness", pct)
            self.stopped.wait(BRIGHTNESS_EVERY)

    def _volume(self):
        sink = default_sink()
        got = volume()
        if got:
            self._report("volume", *got)
        if have("pactl"):
            self._volume_events(sink)
        while not self.stopped.is_set():   # no pactl, or it went away
            got = volume()
            if got:
                self._report("volume", *got)
            self.stopped.wait(VOLUME_EVERY)

    def _volume_events(self, sink):
        while not self.stopped.is_set():
            try:
                self.proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
            except OSError:
                return
            for line in self.proc.stdout:
                if self.stopped.is_set():
                    break
                if not interesting(line):
                    continue
                now_sink = default_sink() if " on server" in line else sink
                got = volume()
                if got:
                    self._report("volume", *got, quiet=now_sink != sink)
                sink = now_sink
            self.proc.wait()
            if self.stopped.is_set():
                return
            # The sound server restarted (or isn't up yet): try again soon.
            self.stopped.wait(2)
            if not have("pactl"):
                return
