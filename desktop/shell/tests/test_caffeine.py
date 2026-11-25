"""caffeine.py and its part of wfconfig: the holder process, the pid check,
hiding the side panel row, and wayfire.ini's screen-off timeout. No GTK or
compositor needed: tube-idle and wayfire.ini are stubbed out."""

import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import caffeine, wfconfig  # noqa: E402

TUBE_IDLE = os.path.join(os.path.dirname(__file__), "..", "..", "bin", "tube-idle")


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(caffeine, "PIDFILE", str(tmp_path / "tubewm-caffeine.pid"))
    monkeypatch.setattr(caffeine, "HIDDEN", str(tmp_path / "config" / "caffeine-hidden"))
    applied = []
    monkeypatch.setattr(caffeine, "_apply", lambda: applied.append(caffeine.active()))
    # The holder lives while this "Wayland socket" does.
    sock = tmp_path / "wayland-test"
    sock.touch()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-test")
    monkeypatch.setattr(caffeine, "HOLD", caffeine.HOLD.replace("-S", "-e"))
    yield applied
    caffeine.set_active(False)


def gone(pid, wait=3.0):
    end = time.time() + wait
    while time.time() < end:
        try:
            with open("/proc/%d/stat" % pid) as fh:
                if fh.read().split(")")[-1].split()[0] == "Z":
                    return True
        except OSError:
            return True
        time.sleep(0.05)
    return False


def test_off_by_default(state):
    assert not caffeine.active()
    assert caffeine.main(["status"]) == 0


def test_on_off(state):
    caffeine.set_active(True)
    assert caffeine.active()
    pid = caffeine._holder()
    caffeine.set_active(True)            # already on: same holder, nothing reapplied
    assert caffeine._holder() == pid
    caffeine.set_active(False)
    assert not caffeine.active()
    assert gone(pid)
    assert state == [True, False]


def test_toggle(state):
    caffeine.main(["toggle"])
    assert caffeine.active()
    caffeine.main(["toggle"])
    assert not caffeine.active()


def test_bad_word(state):
    assert caffeine.main(["maybe"]) == 2


def test_stale_pid_is_not_caffeine(state):
    with open(caffeine.PIDFILE, "w") as fh:
        fh.write(str(os.getpid()))       # alive, but not the holder
    assert not caffeine.active()


def test_ends_with_the_session(state, tmp_path):
    caffeine.set_active(True)
    pid = caffeine._holder()
    os.remove(tmp_path / "wayland-test")
    assert gone(pid, wait=30)
    assert not caffeine.active()


def test_inhibits_idle_only():
    cmd = caffeine.hold_command()
    assert "--what=idle " in cmd[2] and caffeine.MARK in cmd


def test_holds_without_logind(state, tmp_path, monkeypatch):
    """systemd-inhibit missing or refused (no logind): it still holds."""
    fake = tmp_path / "nologind"
    fake.mkdir()
    (fake / "systemd-inhibit").write_text("#!/bin/sh\nexit 1\n")
    (fake / "systemd-inhibit").chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (fake, os.environ["PATH"]))
    caffeine.set_active(True)
    time.sleep(0.5)
    assert caffeine.active()


def test_hide_and_show(state):
    assert caffeine.shown()
    caffeine.set_shown(False)
    assert not caffeine.shown()
    caffeine.set_shown(True)
    assert caffeine.shown()


INI = """[core]
plugins = idle

[idle]
toggle = none
dpms_timeout = 600  # from ~/.config/tubewm/wayfire.ini
disable_on_fullscreen = true

[autostart]
idle = ~/.local/bin/tube-idle
"""


def test_keep_screen_on_replaces_timeout():
    out = wfconfig.keep_screen_on(INI)
    assert "dpms_timeout = -1  # caffeine is on" in out
    assert "600" not in out
    assert out.count("dpms_timeout") == 1
    assert "idle = ~/.local/bin/tube-idle" in out


def test_keep_screen_on_adds_missing_timeout():
    out = wfconfig.keep_screen_on(INI.replace("dpms_timeout = 600  # from ~/.config/tubewm/wayfire.ini\n", ""))
    idle = out.split("[idle]")[1].split("[autostart]")[0]
    assert "dpms_timeout = -1" in idle


def test_build_follows_caffeine(monkeypatch):
    monkeypatch.setattr(wfconfig, "USER_INI", "/nonexistent/wayfire.ini")
    monkeypatch.setattr(caffeine, "active", lambda: False)
    assert "dpms_timeout = 600" in wfconfig.build()
    monkeypatch.setattr(caffeine, "active", lambda: True)
    built = wfconfig.build()
    assert "dpms_timeout = -1" in built and "dpms_timeout = 600" not in built


@pytest.mark.parametrize("on", [False, True])
def test_tube_idle_drops_timeouts(state, tmp_path, on):
    """tube-idle with a fake swayidle that prints what it was given."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "swayidle").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    (fake / "pkill").write_text("#!/bin/sh\nexit 0\n")
    (fake / "brightnessctl").write_text("#!/bin/sh\necho backlight\n")
    for f in fake.iterdir():
        f.chmod(0o755)
    if on:
        caffeine.set_active(True)
        time.sleep(0.5)   # past systemd-inhibit failing, where there's no logind
    env = dict(os.environ, PATH="%s:/usr/bin:/bin" % fake)
    env.pop("SWAYSOCK", None)
    out = subprocess.run(["bash", TUBE_IDLE], env=env, capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    args = out.stdout.split("\n")
    assert "before-sleep" in args and "lock" in args
    assert ("timeout" in args) is (not on)
