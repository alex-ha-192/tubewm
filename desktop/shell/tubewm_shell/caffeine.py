"""tube-caffeine: keep the screen on and the desktop awake.

    tube-caffeine [on | off | toggle | status]

While caffeine is on, the screen doesn't dim, lock or turn off when you step
away, and the computer doesn't go to sleep on its own. Locking, sleep and
closing the lid still work as they always do. It's off when you sign in,
and it switches itself off when the session ends.

It's a row in the side panel (tube-status) and a switch in settings, under
devices; settings can also take the row out of the side panel.

How: a small process holds a logind idle inhibitor (systemd-inhibit
--what=idle, so no idle suspend), tube-idle runs swayidle without its
timeouts (no dim, no lock), and Wayfire's [idle] dpms_timeout is written as
-1 (no screen off).
"""

import os
import shutil
import signal
import subprocess
import sys

from . import common

PIDFILE = os.path.join(common.RUNTIME, "tubewm-caffeine.pid")
HIDDEN = os.path.join(common.CONFIG, "tubewm", "caffeine-hidden")
MARK = "tubewm-caffeine"   # in the holder's command line, so a reused pid isn't mistaken for it
# Stays while the Wayland session does, so caffeine never outlives it.
HOLD = 'while [ -S "${XDG_RUNTIME_DIR:-/tmp}/${WAYLAND_DISPLAY:-wayland-0}" ]; do sleep 20; done'


def _holder():
    try:
        with open(PIDFILE) as fh:
            pid = int(fh.read().strip())
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            if MARK.encode() in fh.read():
                return pid
    except (OSError, ValueError):
        pass
    return None


def active():
    return _holder() is not None


def shown():
    """Whether the side panel has a caffeine row (settings can hide it)."""
    return not os.path.exists(HIDDEN)


def set_shown(on):
    if on:
        try:
            os.remove(HIDDEN)
        except OSError:
            pass
    else:
        os.makedirs(os.path.dirname(HIDDEN), exist_ok=True)
        open(HIDDEN, "w").close()


def hold_command():
    """The holder: the wait, under a logind idle inhibitor when there is one
    to be had, else on its own (no logind, or it refused)."""
    script = ('systemd-inhibit --what=idle --who=tubewm --why="caffeine is on" --mode=block '
              'sh -c "$1" 2>/dev/null || eval "$1"')
    return ["sh", "-c", script, MARK, HOLD]


def _tube(name):
    """A tube-* command: beside this one, else ~/.local/bin, else PATH."""
    for d in (os.path.join(common.SHELL_DIR, "..", "bin"), os.path.join(common.HOME, ".local", "bin")):
        path = os.path.normpath(os.path.join(d, name))
        if os.access(path, os.X_OK):
            return path
    return shutil.which(name)


def _apply():
    """Bring the screen-off timeout and swayidle in line with the state."""
    if os.environ.get("WAYFIRE_SOCKET"):
        from . import wfconfig
        try:
            wfconfig.render()   # Wayfire notices and reloads it
        except (OSError, SystemExit) as err:
            print("tube-caffeine: couldn't write wayfire.ini: %s" % err, file=sys.stderr)
    idle = _tube("tube-idle")
    if idle and shutil.which("swayidle"):
        # tube-idle replaces the running swayidle with the right one.
        subprocess.Popen([idle], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_active(on):
    pid = _holder()
    if on and pid is None:
        proc = subprocess.Popen(hold_command(), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        with open(PIDFILE, "w") as fh:
            fh.write(str(proc.pid))
    elif not on and pid is not None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
    if not on:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
    if on != (pid is not None):
        _apply()
    return on


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    what = argv[0] if argv else "status"
    if what not in ("on", "off", "toggle", "status"):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    if what == "toggle":
        what = "off" if active() else "on"
    if what != "status":
        set_active(what == "on")
    print("on" if active() else "off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
