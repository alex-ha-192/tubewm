"""Surfaces that stay running in the background, and how to reach them fast.

Start is built once, at login, and then only shown and hidden: building it
(GTK, every installed app, the live tiles) is what made the Windows key feel
slow. Pressing the key runs tube-start again, which finds the copy already
running and sends it a signal, before it so much as loads GTK.

Nothing here imports GTK, so asking is quick.
"""

import fcntl
import os
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")


def _pidfile(name):
    return os.path.join(RUNTIME, "tubewm-%s.pid" % name)


def running(name):
    """The pid of the tube-NAME that is running in the background, or None."""
    try:
        with open(_pidfile(name)) as fh:
            pid = int(fh.read().strip())
        if pid == os.getpid():
            return None
        # A pid can be reused once its process is gone: check it's still ours.
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            if ("tube-%s" % name).encode() not in fh.read():
                return None
        return pid
    except (OSError, ValueError):
        return None


def send(name, sig):
    """Signal the running tube-NAME. False if there isn't one."""
    pid = running(name)
    if pid is None:
        return False
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def claim(name, wait=0.0):
    """Become the one tube-NAME. Returns the lock to hold for as long as we
    run, or None when another copy has it (it is starting up, so the key
    press that started us is already in hand). Waits up to WAIT seconds for
    the other copy to go."""
    fh = open(_pidfile(name) + ".lock", "w")
    give_up = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.monotonic() >= give_up:
                fh.close()
                return None
            time.sleep(0.05)


def announce(name):
    """Tell later launches where to find us; call once we listen for signals."""
    with open(_pidfile(name), "w") as fh:
        fh.write(str(os.getpid()))
