"""Bluetooth, through bluetoothctl (BlueZ): on and off, the devices you've
paired, and finding and pairing new ones.

Everything here is plain functions that run bluetoothctl and read its
answers, so the strip, the time panel, the settings flyout and the bar's
flyout all ask the same way. The slow ones (connecting, scanning, pairing)
take a callback and run off the main loop.
"""

import os
import re
import subprocess
import threading

from . import common

from gi.repository import GLib  # noqa: E402

MAC = re.compile(r"^Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2}) (.*)$", re.I)
UNNAMED = re.compile(r"^(?:[0-9A-F]{2}[-:]){5}[0-9A-F]{2}$", re.I)
SCAN_SECONDS = 12


def _ctl(*args, timeout=4):
    return common.sh(["bluetoothctl"] + list(args), timeout=timeout)


def hardware():
    """Is there a Bluetooth adapter at all? Cheap: no tools are run."""
    try:
        return any(not n.startswith(".") for n in os.listdir("/sys/class/bluetooth"))
    except OSError:
        return False


def available():
    """An adapter, and the tools to drive it."""
    return hardware() and common.have("bluetoothctl")


def powered():
    return "Powered: yes" in _ctl("show")


def set_powered(on):
    if on and common.have("rfkill"):
        # A soft block (airplane mode, a laptop's key) stops "power on".
        common.sh(["rfkill", "unblock", "bluetooth"], timeout=3)
    _ctl("power", "on" if on else "off", timeout=6)


def _devices(*filt):
    out = []
    for line in _ctl("devices", *filt).splitlines():
        m = MAC.match(line.strip())
        if m and not UNNAMED.match(m.group(2).strip()):
            out.append((m.group(1).upper(), m.group(2).strip()))
    return out


def paired():
    """[(mac, name, connected)] of the devices you've paired, connected first."""
    devs = _devices("Paired")
    if not devs and "Paired" not in _ctl("help"):
        # bluetoothctl before 5.65 had no filter on "devices".
        devs = [d for d in (MAC.match(l.strip()) for l in _ctl("paired-devices").splitlines()) if d]
        devs = [(d.group(1).upper(), d.group(2).strip()) for d in devs]
    on = {mac for mac, _n in _devices("Connected")}
    if not on and devs:
        on = {mac for mac, _n in devs if "Connected: yes" in _ctl("info", mac)}
    rows = [(mac, name, mac in on) for mac, name in devs]
    return sorted(rows, key=lambda r: (not r[2], r[1].lower()))


def connected_names():
    return [name for _mac, name, on in paired() if on]


def _async(fn, callback):
    def work():
        try:
            result = fn()
        except Exception:  # noqa: BLE001 - a failed tool is a failed result, not a crash
            result = False
        GLib.idle_add(lambda: callback(result) and False)
    threading.Thread(target=work, daemon=True).start()


def _ok(argv, timeout):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    text = r.stdout + r.stderr
    return r.returncode == 0 and not re.search(r"Failed|not available|Error", text)


def connect(mac, callback):
    """Connect to a paired device; callback(True/False) when done."""
    _async(lambda: _ok(["bluetoothctl", "connect", mac], 25), callback)


def disconnect(mac, callback):
    _async(lambda: _ok(["bluetoothctl", "disconnect", mac], 10), callback)


def forget(mac, callback):
    _async(lambda: _ok(["bluetoothctl", "remove", mac], 10), callback)


def scan(callback, seconds=SCAN_SECONDS):
    """Look for devices that are ready to pair for a few seconds, then
    callback([(mac, name)]) with the ones you haven't paired yet."""
    def work():
        try:
            subprocess.run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"],
                           capture_output=True, text=True, timeout=seconds + 6)
        except (OSError, subprocess.SubprocessError):
            pass
        known = {mac for mac, _n, _c in paired()}
        return [(mac, name) for mac, name in _devices() if mac not in known]
    _async(work, callback)


def pair(mac, callback):
    """Pair, trust (so it can reconnect on its own) and connect.
    callback(True/False) when done."""
    def work():
        if not _ok(["bluetoothctl", "--timeout", "30", "pair", mac], 40):
            # Some devices answer "already exists" or need a second try
            # once they've been seen; it only counts if it really paired.
            if "Paired: yes" not in _ctl("info", mac):
                return False
        _ok(["bluetoothctl", "trust", mac], 8)
        return _ok(["bluetoothctl", "connect", mac], 25)
    _async(work, callback)
