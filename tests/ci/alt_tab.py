"""Drive Alt+Tab (tube-switch) in a headless Wayfire and check which window
is lit and which has the keyboard at each step.

    python3 alt_tab.py SOCKET

SOCKET is Wayfire's IPC socket. Wayfire must run the ipc, stipc, ipc-rules,
wm-actions and tube-switch plugins. Keys go in through stipc, windows are
foot terminals. Prints one line per check; exits 1 if any failed, 2 if the
session could not be set up.
"""

import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time

fails = 0
# What the test's wayfire.ini sets [tube-decor] active_color to.
ACCENT = (255, 0, 0)
display = None


class Wayfire:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Wayfire closed the IPC socket")
            buf += chunk
        return buf

    def call(self, method, **data):
        msg = json.dumps({"method": method, "data": data}).encode()
        self.sock.sendall(struct.pack("<I", len(msg)) + msg)
        (n,) = struct.unpack("<I", self._recv(4))
        return json.loads(self._recv(n))


def windows(wf):
    return [v for v in wf.call("window-rules/list-views")
            if v.get("role") == "toplevel" and str(v.get("app-id", "")).startswith("tube-")]


def by_app(wf):
    return {v["app-id"]: v for v in windows(wf)}


def lit(wf):
    """The windows whose title bar is in the accent (activated)."""
    return sorted(v["app-id"] for v in windows(wf) if v.get("activated"))


def focused(wf):
    info = wf.call("window-rules/get-focused-view").get("info") or {}
    return info.get("app-id")


def key(wf, name, state):
    r = wf.call("stipc/feed_key", key=name, state=state)
    if r.get("result") != "ok":
        raise SystemExit("feed_key %s: %s" % (name, r))
    time.sleep(0.15)


def tap(wf, name):
    key(wf, name, True)
    key(wf, name, False)


def screenshot():
    """The screen as (width, height, rgb bytes), from grim, or None."""
    if not shutil.which("grim") or not display:
        return None
    env = dict(os.environ, WAYLAND_DISPLAY=display)
    out = subprocess.run(["grim", "-t", "ppm", "-"], env=env, capture_output=True, timeout=10).stdout
    # P6\nW H\n255\n<rgb>
    parts = out.split(b"\n", 3)
    if len(parts) < 4 or parts[0] != b"P6":
        return None
    w, h = (int(n) for n in parts[1].split())
    return w, h, parts[3]


def title_bar_colour(wf, app):
    """The colour on screen at the left end of APP's title bar."""
    shot = screenshot()
    if not shot:
        return None
    w, _h, rgb = shot
    g = by_app(wf)[app]["geometry"]
    x, y = g["x"] + 4, g["y"] + 4
    i = (y * w + x) * 3
    return tuple(rgb[i:i + 3])


def check_drawn(what, wf, app):
    """APP is in front, so its title bar on screen must be the accent."""
    colour = title_bar_colour(wf, app)
    if colour is None:
        print("skip  %s (no grim)" % what)
        return
    check(what, colour, ACCENT)


def check(what, got, want):
    global fails
    if got == want:
        print("ok    %s" % what)
    else:
        fails += 1
        print("FAIL  %s: got %r, want %r" % (what, got, want))


def wait_for(cond, what, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.1)
    print("setup failed: %s" % what)
    sys.exit(2)


def main():
    global display
    wf = Wayfire(sys.argv[1])
    display = wf.call("stipc/get_display").get("wayland")
    print("outputs: %s" % [o.get("name") for o in wf.call("window-rules/list-outputs")])
    # Open a, b, c in turn; c ends up focused, then b, then a by recency.
    for app in ("tube-a", "tube-b", "tube-c"):
        r = wf.call("stipc/run", cmd="foot --app-id=%s sleep 600" % app)
        if r.get("result") != "ok":
            print("setup failed: run foot: %s" % r)
            sys.exit(2)
        wait_for(lambda: focused(wf) == app, "%s did not open and take focus" % app)
        time.sleep(0.3)
    print("windows: %s" % sorted(by_app(wf)))
    check("before: c has the keyboard", focused(wf), "tube-c")
    check("before: only c is lit", lit(wf), ["tube-c"])
    check_drawn("before: c's title bar is drawn in the accent", wf, "tube-c")

    key(wf, "KEY_LEFTALT", True)
    tap(wf, "KEY_TAB")
    check("Alt+Tab: opens on c, c lit", lit(wf), ["tube-c"])
    check_drawn("Alt+Tab: c's title bar is drawn in the accent", wf, "tube-c")
    tap(wf, "KEY_TAB")
    check("Tab: b lit", lit(wf), ["tube-b"])
    check_drawn("Tab: b's title bar is drawn in the accent", wf, "tube-b")
    tap(wf, "KEY_TAB")
    check("Tab: a lit", lit(wf), ["tube-a"])
    check_drawn("Tab: a's title bar is drawn in the accent", wf, "tube-a")
    key(wf, "KEY_LEFTSHIFT", True)
    tap(wf, "KEY_TAB")
    check("Shift+Tab: back to b, b lit", lit(wf), ["tube-b"])
    key(wf, "KEY_LEFTSHIFT", False)
    check("let go of Shift: still switching, b lit", lit(wf), ["tube-b"])
    key(wf, "KEY_LEFTALT", False)
    time.sleep(0.3)
    check("let go of Alt: b has the keyboard", focused(wf), "tube-b")
    check("let go of Alt: only b is lit", lit(wf), ["tube-b"])

    # Minimise c; by recency the order is now b, c, a.
    c = by_app(wf)["tube-c"]
    wf.call("wm-actions/set-minimized", view_id=c["id"], state=True)
    wait_for(lambda: by_app(wf)["tube-c"].get("minimized"), "c did not minimise")
    time.sleep(0.3)
    key(wf, "KEY_LEFTALT", True)
    tap(wf, "KEY_TAB")
    check("minimised: opens on b, b lit", lit(wf), ["tube-b"])
    tap(wf, "KEY_TAB")
    check("minimised: c lit", lit(wf), ["tube-c"])
    check_drawn("minimised: c's title bar is drawn in the accent", wf, "tube-c")
    key(wf, "KEY_LEFTALT", False)
    time.sleep(0.6)
    check("minimised: c is restored", by_app(wf)["tube-c"].get("minimized"), False)
    check("minimised: c has the keyboard", focused(wf), "tube-c")
    check("minimised: only c is lit", lit(wf), ["tube-c"])

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
