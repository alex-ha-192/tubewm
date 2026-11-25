"""Surfaces that stay running in the background, and how to reach them fast.

Start is built once, at login, and then only shown and hidden: building it
(GTK, every installed app, the live tiles) is what made the Windows key feel
slow. Pressing the key runs tube-start again, which finds the copy already
running and sends it a signal, before it so much as loads GTK.

Nothing here imports GTK, so asking is quick.
"""

import fcntl
import os
import signal
import time

RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
# Asks a stuck copy to write every thread's stack to its log (see
# start.main), before it is replaced.
DUMP = signal.SIGPWR


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


def send(name, sig, answer_within=None):
    """Signal the running tube-NAME. False if there isn't one.

    With ANSWER_WITHIN (seconds), also wait for it to say it heard (see
    heard()). If it doesn't, it is stuck or can't hear us: it is logged and
    killed, and False tells the caller to start a fresh copy, so the key
    never just does nothing."""
    pid = running(name)
    if pid is None:
        return False
    before = _heard_stamp(name)
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    if answer_within is None:
        return True
    give_up = time.monotonic() + answer_within
    while time.monotonic() < give_up:
        if _heard_stamp(name) != before:
            return True
        time.sleep(0.01)
    log(name, "pid %d didn't answer %s within %.1fs; starting a fresh copy. %s"
        % (pid, signal.Signals(sig).name, answer_within, _proc_state(pid)))
    try:
        os.kill(pid, DUMP)   # it writes where every thread is to the log
        time.sleep(0.3)
    except OSError:
        pass
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(100):   # until it's gone, and with it the lock
        if not os.path.exists("/proc/%d" % pid):
            break
        time.sleep(0.01)
    return False


def heard(name, what):
    """Tell send() that we heard it; call first thing in the signal handler."""
    try:
        with open(_pidfile(name) + ".heard", "w") as fh:
            fh.write("%d %s\n" % (time.time_ns(), what))
    except OSError:
        pass


def _heard_stamp(name):
    try:
        with open(_pidfile(name) + ".heard") as fh:
            return fh.read()
    except OSError:
        return None


def _proc_state(pid):
    try:
        with open("/proc/%d/status" % pid) as fh:
            keep = [ln.strip() for ln in fh if ln.startswith(("State", "SigBlk", "SigIgn", "SigCgt"))]
        with open("/proc/%d/wchan" % pid) as fh:
            keep.append("wchan: " + fh.read().strip())
        return "; ".join(keep)
    except OSError:
        return ""


def log_path(name):
    return os.path.join(RUNTIME, "tubewm-%s.log" % name)


def log(name, msg):
    try:
        with open(log_path(name), "a") as fh:
            fh.write("%s [%d] %s\n" % (time.strftime("%H:%M:%S"), os.getpid(), msg))
    except OSError:
        pass


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


def unblock(signals):
    """Make sure SIGNALS reach us. A blocked signal mask is inherited across
    fork and exec, and the compositor that autostarts us (or whatever ran
    us) may have some blocked for itself: then the Windows key's signal is
    held back for ever, and start looks dead from its first close on. Call
    from the main thread before any other thread starts."""
    signal.pthread_sigmask(signal.SIG_UNBLOCK, signals)
