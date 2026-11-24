"""Shared bits for the tubewm shell surfaces (start screen, charms)."""

import os
import shlex
import shutil
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402
except (ValueError, ImportError):  # pragma: no cover - depends on the system
    GtkLayerShell = None

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
DATA = os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local", "share"))
TUBEWM_HOME = os.environ.get("TUBEWM_HOME", os.path.join(DATA, "tubewm"))
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
SHELL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# tubewm's own commands (tube-lock, tube-charms…) live beside the shell, so
# they work even when ~/.local/bin isn't on PATH.
BIN_DIR = os.path.normpath(os.path.join(SHELL_DIR, "..", "bin"))
if os.path.isdir(BIN_DIR) and BIN_DIR not in os.environ.get("PATH", "").split(":"):
    os.environ["PATH"] = BIN_DIR + ":" + os.environ.get("PATH", "/usr/bin:/bin")

PALETTE_DEFAULTS = {
    "BG": "#000000",
    "SHELL": "#111111",
    "SURFACE": "#1D1D1D",
    "SURFACE_HI": "#2B2B2B",
    "FG": "#FFFFFF",
    "SUBTLE": "#8A8A8A",
    "DIM": "#656565",
    "URGENT": "#E81123",
    "ACCENT": "#E3008C",
}


def _palette_file():
    for candidate in (
        os.path.join(TUBEWM_HOME, "palette", "tubewm-colors.sh"),
        # Running from a checkout: desktop/shell -> repo/palette
        os.path.join(SHELL_DIR, "..", "..", "palette", "tubewm-colors.sh"),
    ):
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def load_palette():
    """Resolve the shared palette by sourcing it with sh, like everything else does."""
    pal = dict(PALETTE_DEFAULTS)
    path = _palette_file()
    if path:
        try:
            out = subprocess.run(
                ["sh", "-c", 'set -a; . "$1"; env', "sh", path],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            for line in out.splitlines():
                key, _, value = line.partition("=")
                if key.startswith("TUBEWM_") and value.startswith("#") and len(value) == 7:
                    pal[key[len("TUBEWM_"):]] = value.upper()
        except (OSError, subprocess.SubprocessError):
            pass
    pal["ACCENT_DARK"] = mix(pal["ACCENT"], "#000000", 0.30)
    pal["ACCENT_LIGHT"] = mix(pal["ACCENT"], "#FFFFFF", 0.30)
    return pal


def mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    out = "#"
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out += "%02X" % round(ca * (1 - t) + cb * t)
    return out


def named_accents():
    path = os.path.join(TUBEWM_HOME, "palette", "accents")
    if not os.path.exists(path):
        path = os.path.join(SHELL_DIR, "..", "..", "palette", "accents")
    accents = []
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and not parts[0].startswith("#"):
                    accents.append((parts[0], parts[1].upper()))
    except OSError:
        pass
    return accents


_provider = None


def apply_css(extra=""):
    """(Re)load the shell stylesheet with the current palette."""
    global _provider
    pal = load_palette()
    defs = "".join(
        "@define-color tube_%s %s;\n" % (k.lower(), v) for k, v in sorted(pal.items())
    )
    parts = [defs]
    with open(os.path.join(SHELL_DIR, "style.css")) as fh:
        parts.append(fh.read())
    user = os.path.join(CONFIG, "tubewm", "user.css")
    if os.path.exists(user):
        with open(user) as fh:
            parts.append(fh.read())
    parts.append(extra)
    provider = Gtk.CssProvider()
    provider.load_from_data("\n".join(parts).encode())
    screen = Gdk.Screen.get_default()
    if _provider is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, _provider)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1
    )
    _provider = provider
    return pal


def toggle_instance(name, close_only=False):
    """Single instance per surface: a second launch closes the first.

    Returns True when the caller should carry on and show itself.
    """
    pidfile = os.path.join(RUNTIME, "tubewm-%s.pid" % name)
    try:
        with open(pidfile) as fh:
            pid = int(fh.read().strip())
        os.kill(pid, 0)
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            if name.encode() in fh.read():
                os.kill(pid, signal.SIGTERM)
                return False
    except (OSError, ValueError):
        pass
    if close_only:
        return False
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
    return True


def make_layer_window(name, transparent=False, layer="overlay"):
    win = Gtk.Window()
    win.set_title("tube-%s" % name)
    win.get_style_context().add_class("tube")
    if transparent:
        win.get_style_context().add_class("tube-transparent")
        visual = win.get_screen().get_rgba_visual()
        if visual is not None:
            win.set_visual(visual)
        win.set_app_paintable(True)
    if GtkLayerShell is not None and GtkLayerShell.is_supported():
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "tube-%s" % name)
        GtkLayerShell.set_layer(
            win, GtkLayerShell.Layer.OVERLAY if layer == "overlay" else GtkLayerShell.Layer.TOP
        )
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_interactivity(win, True)
    else:
        # No layer shell (e.g. running nested for development): plain fullscreen.
        win.fullscreen()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *_: Gtk.main_quit() or False)
    win.connect("destroy", Gtk.main_quit)
    return win


def monitor_size(win=None):
    display = Gdk.Display.get_default()
    mon = display.get_primary_monitor() or display.get_monitor(0)
    if mon is None:
        return 1920, 1080
    geo = mon.get_geometry()
    return geo.width, geo.height


_FIELD_CODES = ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%i", "%c", "%k", "%v", "%m")


def app_command(info):
    """Command line for a Gio.DesktopAppInfo, field codes removed."""
    cmd = info.get_commandline() or info.get_executable() or ""
    for code in _FIELD_CODES:
        cmd = cmd.replace(" " + code, "").replace(code, "")
    cmd = cmd.replace("%%", "%").strip()
    if isinstance(info, Gio.DesktopAppInfo) and info.get_boolean("Terminal"):
        term = os.environ.get("TERMINAL", "foot")
        cmd = "%s -e %s" % (term, cmd)
    return cmd


def run_detached(cmd):
    """Run a shell command so it outlives us; through sway when we can, so the
    new window lands on the current workspace."""
    if not cmd:
        return
    if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
        # sway runs it with sway's own PATH, so hand ours along.
        cmd = "PATH=%s; %s" % (shlex.quote(os.environ.get("PATH", "")), cmd)
        subprocess.Popen(["swaymsg", "exec", "--", cmd],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def launch_app(info):
    run_detached(app_command(info))


def find_app(app_id):
    """Look an app up by desktop id, with or without .desktop, case-insensitively."""
    if not app_id:
        return None
    ids = [app_id] if app_id.endswith(".desktop") else [app_id + ".desktop", app_id]
    for i in ids:
        try:
            info = Gio.DesktopAppInfo.new(i)
        except TypeError:
            info = None
        if info is not None:
            return info
    low = app_id.lower().removesuffix(".desktop")
    for info in Gio.AppInfo.get_all():
        if not isinstance(info, Gio.DesktopAppInfo):
            continue
        did = (info.get_id() or "").lower().removesuffix(".desktop")
        if did == low or did.endswith("." + low) or (info.get_executable() or "") == app_id:
            return info
    return None


def sh(cmd, timeout=2):
    try:
        return subprocess.run(cmd if isinstance(cmd, list) else shlex.split(cmd),
                              capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def have(cmd):
    return shutil.which(cmd) is not None


def main_quit_on_escape(win, handler=None):
    def on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            if handler is None or not handler():
                Gtk.main_quit()
            return True
        return False
    win.connect("key-press-event", on_key)


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)
