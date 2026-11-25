#!/usr/bin/env python3
"""The tubewm installer: one screen at a time, one question, one password.

Run it through ./install.sh at the top of the repository:

    ./install.sh               install or update, in a full-screen terminal UI
    ./install.sh --yes         same, without questions (uses the detected keyboard)
    ./install.sh --home-only   only touch your home folder: no password needed
    ./install.sh --uninstall   remove tubewm and put your old settings back
    ./install.sh --update      fetch the newest tubewm and install it (what tube-update runs)
    ./install.sh --plain       plain text instead of the full-screen UI

Only the standard library is used, because this runs before anything else is
installed.
"""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "desktop", "shell"))
from tubewm_shell import keyboard  # noqa: E402

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.join(HOME, ".local", "state")),
                         "tubewm")
LOG = os.path.join(STATE_DIR, "install.log")
RECORD = os.path.join(CONFIG, "tubewm", "installed")

SESSION_BIN = "/usr/local/bin/tubewm-session"
SESSION_DIR = "/usr/share/wayland-sessions"
SESSIONS = {"tubewm.desktop": "sway", "tubewm-wayfire.desktop": "wayfire"}

# ── packages ─────────────────────────────────────────────────────────────
# Required: what the desktop can't work without. Optional: installed when the
# distro has them, skipped quietly when it doesn't.
PACKAGES = {
    "arch": (
        "sway swaybg swayidle swaylock waybar fuzzel mako foot grim slurp wl-clipboard jq "
        "playerctl brightnessctl libnotify wireplumber python-gobject python-cairo gtk3 "
        "gtk-layer-shell ttf-opensans",
        "gtklock gtklock-powerbar-module pavucontrol blueman curl ttf-jetbrains-mono xdg-desktop-portal-wlr "
        "xdg-desktop-portal-gtk power-profiles-daemon upower wayfire",
    ),
    "debian": (
        "sway swaybg swayidle swaylock waybar fuzzel mako-notifier foot grim slurp wl-clipboard "
        "jq playerctl brightnessctl libnotify-bin wireplumber python3-gi python3-gi-cairo "
        "gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 fonts-open-sans",
        "gtklock pavucontrol blueman curl fonts-jetbrains-mono xdg-desktop-portal-wlr "
        "xdg-desktop-portal-gtk power-profiles-daemon upower wayfire",
    ),
    "fedora": (
        "sway swaybg swayidle swaylock waybar fuzzel mako foot grim slurp wl-clipboard jq "
        "playerctl brightnessctl libnotify wireplumber python3-gobject python3-cairo gtk3 "
        "gtk-layer-shell open-sans-fonts",
        "gtklock pavucontrol blueman curl jetbrains-mono-fonts xdg-desktop-portal-wlr "
        "xdg-desktop-portal-gtk power-profiles-daemon upower wayfire",
    ),
    "suse": (
        "sway swaybg swayidle swaylock waybar fuzzel mako foot grim slurp wl-clipboard jq "
        "playerctl brightnessctl libnotify-tools wireplumber python3-gobject-Gdk "
        "python3-gobject-cairo typelib-1_0-GtkLayerShell-0_1 open-sans-fonts",
        "",
    ),
}


# What it takes to build the Wayfire plugins in desktop/wayfire/plugins.
BUILD_DEPS = {
    "arch": "meson ninja gcc pkgconf glm wayland-protocols vulkan-headers",
    "debian": "meson ninja-build g++ pkg-config wayfire-dev libdrm-dev libglm-dev wayland-protocols libvulkan-dev",
    "fedora": "meson ninja-build gcc-c++ pkgconf-pkg-config wayfire-devel libdrm-devel glm-devel wayland-protocols-devel vulkan-headers",
    "suse": "meson ninja gcc-c++ pkgconf wayfire-devel glm-devel wayland-protocols-devel vulkan-headers",
}
PLUGIN_BUILD = os.path.join(REPO, "desktop", "wayfire", "plugins", "build.sh")
UPSTREAM = "https://github.com/alex-ha-192/tubewm"
BRANCH = "main"


class Failed(Exception):
    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


# ── what this machine is ─────────────────────────────────────────────────

def os_release():
    vals = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as fh:
                for line in fh:
                    k, _, v = line.strip().partition("=")
                    vals[k] = v.strip('"')
            break
        except OSError:
            continue
    return vals


def quiet(cmd, timeout=60, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.SubprocessError):
        return None


class System:
    def __init__(self):
        rel = os_release()
        self.name = rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux"
        ids = (rel.get("ID", "") + " " + rel.get("ID_LIKE", "")).split()
        self.family = None
        for fam, needles in (("arch", ("arch",)), ("fedora", ("fedora", "rhel")),
                             ("debian", ("debian", "ubuntu")), ("suse", ("suse", "opensuse"))):
            if any(n in i for i in ids for n in needles):
                self.family = fam
                break
        if self.family is None:  # unknown ID: go by the package manager
            for fam, tool in (("arch", "pacman"), ("debian", "apt-get"),
                              ("fedora", "dnf"), ("suse", "zypper")):
                if shutil.which(tool):
                    self.family = fam
                    break
        self.is_cachyos = "cachyos" in ids
        self.laptop = any(n.startswith("BAT") for n in _listdir("/sys/class/power_supply"))
        self.login_manager = _login_manager()
        self.root = os.geteuid() == 0

    @property
    def tool(self):
        return {"arch": "pacman", "debian": "apt", "fedora": "dnf", "suse": "zypper"}.get(
            self.family, "")

    def missing(self, pkgs):
        """The packages in pkgs that aren't installed."""
        if not pkgs:
            return []
        if self.family == "arch":
            r = quiet(["pacman", "-T"] + pkgs)
            return r.stdout.split() if r else pkgs
        if self.family == "debian":
            r = quiet(["dpkg-query", "-W", "-f=${Package} ${Status}\n"] + pkgs)
            ok = set()
            if r:
                for line in r.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and parts[-1] == "installed":
                        ok.add(parts[0])
            return [p for p in pkgs if p not in ok]
        if self.family in ("fedora", "suse"):
            out = []
            for p in pkgs:
                r = quiet(["rpm", "-q", "--whatprovides", p])
                if not r or r.returncode != 0:
                    out.append(p)
            return out
        return []

    def available(self, pkgs):
        """The packages in pkgs that the distro's repositories have."""
        if not pkgs:
            return []
        if self.family == "arch":
            return [p for p in pkgs if (r := quiet(["pacman", "-Si", p])) and r.returncode == 0]
        if self.family == "debian":
            return [p for p in pkgs
                    if (r := quiet(["apt-cache", "show", p])) and r.returncode == 0 and r.stdout]
        if self.family == "fedora":
            r = quiet(["dnf", "-q", "repoquery", "--qf", "%{name}\n"] + pkgs, timeout=180)
            names = set(r.stdout.split()) if r else set()
            return [p for p in pkgs if p in names]
        return []

    def install_commands(self, pkgs, refresh=False):
        if self.family == "arch":
            # A full upgrade is the only supported way to install on Arch, and
            # it is also what fixes the mirror 404s a stale package list causes.
            return [["pacman", "-Syyu" if refresh else "-Syu", "--needed", "--noconfirm"] + pkgs]
        if self.family == "debian":
            env = ["env", "DEBIAN_FRONTEND=noninteractive"]
            return [env + ["apt-get", "update"],
                    env + ["apt-get", "install", "-y", "--no-install-recommends"] + pkgs]
        if self.family == "fedora":
            return [["dnf", "install", "-y"] + (["--refresh"] if refresh else []) + pkgs]
        if self.family == "suse":
            return [["zypper", "--non-interactive", "install"] + pkgs]
        return []

    def remove_commands(self, pkgs):
        return {
            "arch": [["pacman", "-Rns", "--noconfirm"] + pkgs],
            "debian": [["apt-get", "remove", "-y"] + pkgs],
            "fedora": [["dnf", "remove", "-y"] + pkgs],
            "suse": [["zypper", "--non-interactive", "remove"] + pkgs],
        }.get(self.family, [])

    def mirror_hint(self):
        if self.family == "arch":
            if self.is_cachyos:
                return "Your mirrors may be out of date. Run  sudo cachyos-rate-mirrors  and try again."
            return "Your mirrors may be out of date. Run  sudo reflector --latest 10 --sort rate --save /etc/pacman.d/mirrorlist  and try again."
        if self.family == "debian":
            return "Check your internet connection, then run  sudo apt-get update  and try again."
        return "Check your internet connection and try again."


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def _login_manager():
    try:
        target = os.readlink("/etc/systemd/system/display-manager.service")
        return os.path.basename(target).removesuffix(".service")
    except OSError:
        pass
    for dm in ("sddm", "gdm", "lightdm", "greetd", "ly", "plasmalogin"):
        r = quiet(["systemctl", "is-enabled", dm + ".service"], timeout=5)
        if r and r.stdout.strip() == "enabled":
            return dm
    return ""


def themable_apps():
    """Names of the installed apps that apps/install.sh would theme."""
    r = quiet(["sh", os.path.join(REPO, "apps", "install.sh"), "--list"], timeout=30)
    found = []
    if r:
        for line in r.stdout.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[1] in ("found", "installed"):
                found.append(parts[2].split(":")[0].split(" /")[0].strip())
    return found


# ── running things ───────────────────────────────────────────────────────

class Runner:
    """Runs commands, sends every output line to the log and to a listener."""

    def __init__(self, password=None, root=False):
        self.password = password
        self.root = root
        self.listener = None
        os.makedirs(STATE_DIR, exist_ok=True)
        self.logfile = open(LOG, "a")
        self.logfile.write("\n=== tubewm installer %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))

    def line(self, text):
        self.logfile.write(text + "\n")
        self.logfile.flush()
        if self.listener:
            self.listener(text)

    def run(self, cmd, sudo=False, env=None, check=True):
        if sudo and not self.root:
            cmd = (["sudo", "-S", "-p", ""] if self.password is not None
                   else ["sudo", "-n"]) + cmd
        self.line("$ " + " ".join(shlex.quote(c) for c in cmd if c is not None))
        full_env = dict(os.environ, **(env or {}))
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, env=full_env, text=True,
                                    errors="replace", bufsize=1)
        except OSError as e:
            raise Failed("Couldn't run %s: %s" % (cmd[0], e.strerror))
        if sudo and self.password is not None and not self.root:
            try:
                proc.stdin.write(self.password + "\n")
                proc.stdin.flush()
            except OSError:
                pass
        try:
            proc.stdin.close()
        except OSError:
            pass
        tail = []
        for raw in proc.stdout:
            text = _strip_ansi(raw.rstrip("\n"))
            # pacman and apt draw progress bars with carriage returns.
            text = text.split("\r")[-1]
            if text.strip():
                tail = (tail + [text])[-12:]
                self.line(text)
        proc.wait()
        if check and proc.returncode != 0:
            raise Failed("%s stopped with an error (exit %d)" % (cmd[0] if not sudo else
                                                               _cmd_name(cmd), proc.returncode),
                         "\n".join(tail[-3:]))
        return proc.returncode


def _cmd_name(cmd):
    for c in cmd:
        if c not in ("sudo", "-S", "-n", "-p", "", "env") and "=" not in c:
            return c
    return cmd[0]


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _strip_ansi(s):
    return _ANSI.sub("", s)


def check_sudo_password(password):
    try:
        r = subprocess.run(["sudo", "-S", "-p", "", "-v"], input=password + "\n",
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sudo_without_password():
    r = quiet(["sudo", "-n", "true"], timeout=10)
    return bool(r and r.returncode == 0)


def can_sudo():
    return shutil.which("sudo") is not None


# ── the plan ─────────────────────────────────────────────────────────────

class Step:
    def __init__(self, key, title, detail, action, system=False, on=True, toggle=True,
                 soft=False):
        self.key, self.title, self.detail = key, title, detail
        self.action, self.system, self.on, self.toggle = action, system, on, toggle
        self.soft = soft  # a failure is reported but doesn't stop the rest
        self.status = "pending"  # pending running done warned failed skipped


def read_record():
    vals = {}
    try:
        with open(RECORD) as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                if k and not k.startswith("#"):
                    vals[k] = v
    except OSError:
        pass
    return vals


def write_record(**updates):
    vals = read_record()
    for k, v in updates.items():
        if v is None:
            vals.pop(k, None)
        else:
            vals[k] = v
    os.makedirs(os.path.dirname(RECORD), exist_ok=True)
    with open(RECORD, "w") as fh:
        fh.write("# What ./install.sh changed outside your home folder, for --uninstall.\n")
        for k, v in sorted(vals.items()):
            fh.write("%s=%s\n" % (k, v))


def session_files(include_wayfire):
    files = {SESSION_BIN: os.path.join(REPO, "desktop", "session", "tubewm-session"),
             os.path.join(SESSION_DIR, "tubewm.desktop"):
                 os.path.join(REPO, "desktop", "session", "tubewm.desktop")}
    if include_wayfire:
        files[os.path.join(SESSION_DIR, "tubewm-wayfire.desktop")] = os.path.join(
            REPO, "desktop", "session", "tubewm-wayfire.desktop")
    return files


def _same(a, b):
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def wants_wayfire(pkgs_to_install):
    return os.path.isdir(os.path.join(REPO, "desktop", "wayfire")) and (
        shutil.which("wayfire") is not None or "wayfire" in pkgs_to_install)


def builds_plugins(pkgs_to_install=()):
    return os.path.exists(PLUGIN_BUILD) and (
        shutil.which("wayfire") is not None or "wayfire" in pkgs_to_install)


class Plan:
    def __init__(self, system, home_only=False, update=False):
        self.sys = system
        self.home_only = home_only
        self.update = update
        self.layout = keyboard.guess()
        self.packages = []
        self.apps = []
        self.steps = []

    def survey(self):
        s = self.sys
        if s.family in PACKAGES:
            req, opt = (p.split() for p in PACKAGES[s.family])
            missing_req = s.missing(req)
            if not os.path.isdir(os.path.join(REPO, "desktop", "wayfire")):
                opt = [p for p in opt if p != "wayfire"]
            missing_opt = s.available(s.missing(opt))
            self.packages = missing_req + missing_opt
            if builds_plugins(self.packages):
                self.packages += [p for p in s.missing(BUILD_DEPS.get(s.family, "").split())
                                  if p not in self.packages]
        self.apps = themable_apps()

    def build(self):
        s = self.sys
        steps = []
        if self.packages:
            names = ", ".join(self.packages[:6]) + (" and %d more" % (len(self.packages) - 6)
                                                    if len(self.packages) > 6 else "")
            title = "Install %d package%s" % (len(self.packages), "" if len(self.packages) == 1 else "s")
            if s.family == "arch":
                title += " and update the system"
            steps.append(Step("packages", title, names, self.do_packages, system=True))
        steps.append(Step("desktop", "Set up the desktop",
                          "Start screen, charms, bar and configs. Old configs are backed up.",
                          self.do_desktop, toggle=False))
        apps_on = bool(self.apps) and not (self.update and read_record().get("apps") == "off")
        steps.append(Step("apps", "Theme your apps",
                          (", ".join(self.apps) if self.apps else "None found yet; they'll be themed when you rerun this")
                          + ". Same colour as the desktop.",
                          self.do_apps, on=apps_on, soft=True))
        if builds_plugins(self.packages):
            steps.append(Step("plugins", "Build the window title bars",
                              "The square close button, for the Wayfire session.",
                              self.do_plugins, toggle=False, soft=True))
        sysk = keyboard.system()
        if not self.update and (sysk != tuple(self.layout) or not sysk):
            steps.append(Step("keyboard", "Use %s on the sign-in screen" % keyboard.describe(*self.layout),
                              "And on text consoles." + (" It is %s now." % keyboard.describe(*sysk)
                                                         if sysk else ""),
                              self.do_keyboard_system, system=True, soft=True))
        files = session_files(wants_wayfire(self.packages))
        if not all(_same(dst, src) for dst, src in files.items()):
            where = {"sddm": "SDDM", "gdm": "GDM", "lightdm": "LightDM", "greetd": "greetd",
                     "plasmalogin": "the Plasma login screen"}.get(s.login_manager, "")
            steps.append(Step("session", "Add tubewm to the sign-in screen",
                              ("Pick it from the session menu in %s." % where) if where
                              else "Or start it from a console with  tubewm-session",
                              self.do_session, system=True))
        if self.home_only or not (s.root or can_sudo()):
            for st in steps:
                if st.system:
                    st.on = False
        self.steps = steps
        return steps

    def needs_password(self):
        return any(st.on and st.system for st in self.steps) and not self.sys.root

    # the steps themselves

    def do_packages(self, run):
        cmds = self.sys.install_commands(self.packages)
        try:
            for c in cmds:
                run.run(c, sudo=True)
        except Failed:
            if self.sys.family not in ("arch", "fedora"):
                raise Failed("The packages didn't install.", self.sys.mirror_hint())
            run.line("Retrying with a fresh package list…")
            try:
                for c in self.sys.install_commands(self.packages, refresh=True):
                    run.run(c, sudo=True)
            except Failed:
                raise Failed("The packages didn't install.", self.sys.mirror_hint())
        prev = read_record().get("packages", "").split()
        write_record(packages=" ".join(sorted(set(prev) | set(self.packages))))

    def remember(self):
        """What the person chose, so updates keep to it."""
        for st in self.steps:
            if st.key == "apps":
                write_record(apps="on" if st.on else "off")

    def do_desktop(self, run):
        if not (self.update and keyboard.load()):
            keyboard.save(*self.layout)
        run.line("keyboard: %s" % keyboard.describe(*self.layout))
        write_record(source=REPO)
        run.run(["bash", os.path.join(REPO, "desktop", "install.sh")],
                env={"TUBEWM_FROM_INSTALLER": "1"})

    def do_apps(self, run):
        run.run(["sh", os.path.join(REPO, "apps", "install.sh")], check=False)

    def do_plugins(self, run):
        run.run(["bash", PLUGIN_BUILD])

    def do_keyboard_system(self, run):
        run.run(keyboard.system_command(*self.layout), sudo=True)

    def do_session(self, run):
        files = session_files(wants_wayfire(self.packages))
        run.run(["install", "-d", "-m", "755", SESSION_DIR, os.path.dirname(SESSION_BIN)], sudo=True)
        for dst, src in files.items():
            mode = "755" if dst == SESSION_BIN else "644"
            run.run(["install", "-m", mode, src, dst], sudo=True)
        write_record(session=" ".join(sorted(files)))


class Removal:
    def __init__(self, system):
        self.sys = system
        rec = read_record()
        self.packages = rec.get("packages", "").split()
        self.session = [f for f in rec.get("session", "").split() if os.path.exists(f)] or [
            f for f in [SESSION_BIN] + [os.path.join(SESSION_DIR, n) for n in SESSIONS]
            if os.path.exists(f)]
        self.steps = []

    def build(self):
        steps = [Step("desktop", "Remove the desktop and app themes",
                      "Your configs from before tubewm are put back.", self.do_desktop,
                      toggle=False)]
        if self.session:
            steps.append(Step("session", "Take tubewm off the sign-in screen",
                              " ".join(self.session), self.do_session, system=True))
        steps.append(Step("settings", "Delete your tubewm settings",
                          "Colour, start tiles, keyboard choice and config backups.",
                          self.do_settings, on=False))
        if self.packages:
            steps.append(Step("packages", "Remove the packages tubewm installed",
                              ", ".join(self.packages), self.do_packages, system=True, on=False))
        self.steps = steps
        return steps

    def needs_password(self):
        return any(st.on and st.system for st in self.steps) and not self.sys.root

    def do_desktop(self, run):
        run.run(["sh", os.path.join(REPO, "apps", "install.sh"), "--uninstall"], check=False)
        run.run(["bash", os.path.join(REPO, "desktop", "install.sh"), "--uninstall"])

    def do_session(self, run):
        run.run(["rm", "-f"] + self.session, sudo=True)
        write_record(session=None)

    def do_settings(self, run):
        target = os.path.join(CONFIG, "tubewm")
        run.line("deleting %s" % target)
        shutil.rmtree(target, ignore_errors=True)

    def do_packages(self, run):
        for c in self.sys.remove_commands(self.packages):
            run.run(c, sudo=True, check=False)
        if os.path.exists(RECORD):
            write_record(packages=None)


def run_steps(steps, runner, on_change=lambda: None):
    for st in steps:
        if not st.on:
            st.status = "skipped"
            continue
        st.status = "running"
        on_change()
        try:
            st.action(runner)
        except Failed as e:
            if st.soft:
                st.status = "warned"
                runner.line("(carrying on: %s)" % e)
                on_change()
                continue
            st.status = "failed"
            on_change()
            return st, e
        st.status = "done"
        on_change()
    return None, None


# ── updates ──────────────────────────────────────────────────────────────

class Source:
    """The tubewm checkout this was installed from, as a git clone."""

    def __init__(self, path=REPO):
        self.path = path
        self.remote = "refs/remotes/origin/" + BRANCH
        self.notes = []

    def git(self, *args, timeout=120):
        r = quiet(["git", "-C", self.path] + list(args), timeout=timeout)
        if r is None:
            raise Failed("git isn't working.", "Install git, then try again.")
        return r

    def ok(self, *args, timeout=120):
        r = self.git(*args, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()

    def fetch(self):
        if not os.path.isdir(os.path.join(self.path, ".git")):
            raise Failed("%s isn't a git clone, so it can't update itself." % _tilde(self.path),
                         "Run  tube-update  instead: it fetches its own copy.")
        good, _, err = self.ok("fetch", "--quiet", "origin",
                               "+refs/heads/%s:%s" % (BRANCH, self.remote))
        if not good:
            raise Failed("Couldn't reach GitHub to look for updates.",
                         "Check your internet connection and try again.\n" + err.splitlines()[-1]
                         if err else "Check your internet connection and try again.")

    def head(self):
        return self.ok("rev-parse", "HEAD")[1]

    def news(self, since="HEAD"):
        """Subjects of the changes in main that aren't in `since`, newest first."""
        good, out, _ = self.ok("log", "--no-merges", "--format=%s", "%s..%s" % (since, self.remote))
        return [l for l in out.splitlines() if l.strip()] if good else []

    def pull(self):
        """Bring the checkout to the newest main without losing anything of yours:
        your edits are stashed, and commits of your own stop the update."""
        good, branch, _ = self.ok("rev-parse", "--abbrev-ref", "HEAD")
        good, dirty, _ = self.ok("status", "--porcelain", "--untracked-files=no")
        if dirty:
            stamp = time.strftime("%Y-%m-%d %H:%M")
            self.ok("stash", "push", "--quiet", "-m", "tubewm update %s" % stamp)
            self.notes.append("Your own edits in %s were set aside before updating. "
                              "\"git stash list\" there shows them." % _tilde(self.path))
        if branch != BRANCH:
            # Usually a pull request that was tried out and has since been merged.
            has_main = self.ok("rev-parse", "--verify", "--quiet", "refs/heads/" + BRANCH)[0]
            good, _, err = (self.ok("checkout", "--quiet", BRANCH) if has_main else
                            self.ok("checkout", "--quiet", "-b", BRANCH, "--track", "origin/" + BRANCH))
            if not good:
                raise Failed("Couldn't switch the tubewm folder back to %s." % BRANCH, err)
            self.notes.append("The tubewm folder was on \"%s\"; it's back on %s now."
                              % (branch, BRANCH))
        good, ahead, _ = self.ok("rev-list", "--count", "%s..HEAD" % self.remote)
        if good and ahead.isdigit() and int(ahead) > 0:
            raise Failed("You have commits of your own in %s, so it won't update by itself."
                         % _tilde(self.path),
                         "Update it with git there (git pull --rebase), then run tube-update.")
        good, _, err = self.ok("merge", "--quiet", "--ff-only", self.remote)
        if not good:
            raise Failed("The update couldn't be applied.", err)


def relaunch_after_pull(args, old_head):
    """Run the installer that just arrived, so new steps and packages count."""
    argv = [sys.executable, os.path.join(REPO, "installer", "install.py"), "--update",
            "--pulled", old_head]
    for flag in ("yes", "plain", "home_only"):
        if getattr(args, flag):
            argv.append("--" + flag.replace("_", "-"))
    os.execv(sys.executable, argv)


def update_lines(source, old_head):
    new = source.news(old_head) if old_head else []
    if new:
        return "%d change%s, including: %s" % (len(new), "" if len(new) == 1 else "s",
                                               "; ".join(new[:3]).rstrip(".") + ".")
    return ""


# ── the full-screen UI ───────────────────────────────────────────────────

# A thin three-line display face for the headings, so they read like the
# big light type on the desktop. Drawn with light box-drawing lines.
GLYPHS = {
    'a': ['┌─┐', '├─┤', '╵ ╵'], 'b': ['┌┐ ', '├┴┐', '└─┘'], 'c': ['┌─╴', '│  ', '└─╴'],
    'd': ['╶┬┐', ' ││', '╶┴┘'], 'e': ['┌─╴', '├╴ ', '└─╴'], 'f': ['┌─╴', '├╴ ', '╵  '],
    'g': ['┌─╴', '│╶┐', '└─┘'], 'h': ['╷ ╷', '├─┤', '╵ ╵'], 'i': ['╷', '│', '╵'],
    'j': [' ┌┐', '  │', '└─┘'], 'k': ['╷┌ ', '├┴┐', '╵ ╵'], 'l': ['╷  ', '│  ', '└─╴'],
    'm': ['┌┬┐', '│││', '╵ ╵'], 'n': ['┌┐╷', '│└┤', '╵ ╵'], 'o': ['┌─┐', '│ │', '└─┘'],
    'p': ['┌─┐', '├─┘', '╵  '], 'q': ['┌─┐', '│┐│', '└┴┘'], 'r': ['┌─┐', '├┬┘', '╵└╴'],
    's': ['┌─┐', '└─┐', '└─┘'], 't': ['╶┬╴', ' │ ', ' ╵ '], 'u': ['╷ ╷', '│ │', '└─┘'],
    'v': ['╷ ╷', '│┌┘', '└┘ '], 'w': ['╷ ╷', '│╷│', '└┴┘'], 'x': ['╷ ╷', '└┼┐', '╵ ╵'],
    'y': ['╷ ╷', '└┬┘', ' ╵ '], 'z': ['╶─┐', '┌─┘', '└─╴'], "'": ['╷', ' ', ' '],
    '.': [' ', ' ', '╵'], ' ': ['  ', '  ', '  '],
}


def big(text):
    """text in the display face, as three lines (None if a letter is missing)."""
    rows = ["", "", ""]
    for ch in text.lower():
        g = GLYPHS.get(ch)
        if g is None:
            return None
        for i in range(3):
            rows[i] += g[i] + " "
    return [r.rstrip() for r in rows]



try:
    import curses
except ImportError:  # pragma: no cover - every Linux Python has it
    curses = None


class UI:
    """A Metro screen in a terminal: black, one accent, lowercase headings."""

    STAGES_INSTALL = ("keyboard", "ready", "installing", "done")
    STAGES_REMOVE = ("ready", "removing", "done")
    STAGES_UPDATE = ("what's new", "updating", "done")

    def __init__(self, scr, system, removing=False, home_only=False, updating=False):
        self.scr = scr
        self.sys = system
        self.removing = removing
        self.stages = (self.STAGES_REMOVE if removing else
                       self.STAGES_UPDATE if updating else self.STAGES_INSTALL)
        self.home_only = home_only
        self.log = []
        self.lock = threading.Lock()
        curses.curs_set(0)
        curses.use_default_colors()
        self.colours()
        scr.keypad(True)
        scr.bkgd(" ", curses.color_pair(1))

    def colours(self):
        n = curses.COLORS
        rich = n >= 256
        accent = 162 if rich else curses.COLOR_MAGENTA
        subtle = 245 if rich else curses.COLOR_WHITE
        dim = 240 if rich else curses.COLOR_WHITE
        surface = 235 if rich else curses.COLOR_BLACK
        green = 70 if rich else curses.COLOR_GREEN
        red = 160 if rich else curses.COLOR_RED
        black = 16 if rich else curses.COLOR_BLACK
        white = 231 if rich else curses.COLOR_WHITE
        curses.init_pair(1, white, black)       # text
        curses.init_pair(2, accent, black)      # accent text
        curses.init_pair(3, subtle, black)      # secondary text
        curses.init_pair(4, white, accent)      # button
        curses.init_pair(5, dim, black)         # hints, rules
        curses.init_pair(6, green, black)
        curses.init_pair(7, red, black)
        curses.init_pair(8, white, surface)     # input field
        curses.init_pair(9, subtle, surface)
        self.TEXT, self.ACCENT, self.SUBTLE = (curses.color_pair(i) for i in (1, 2, 3))
        self.BUTTON, self.DIM, self.OK, self.ERR = (curses.color_pair(i) for i in (4, 5, 6, 7))
        self.FIELD, self.FIELD_DIM = curses.color_pair(8), curses.color_pair(9)
        if not rich:
            self.DIM |= curses.A_DIM
            self.SUBTLE |= curses.A_DIM

    # drawing helpers

    def put(self, y, x, text, attr=0, width=None):
        h, w = self.scr.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        avail = w - x - 1 if width is None else min(width, w - x - 1)
        if avail <= 0:
            return
        if len(text) > avail:
            text = text[:max(0, avail - 1)] + "…"
        try:
            self.scr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def frame(self, stage, title, subtitle=""):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        self.mx = 4 if w < 90 else 8
        self.put(1, self.mx, "tubewm", self.ACCENT | curses.A_BOLD)
        # Where we are, as a row of pivots: the current one bright.
        x = w - self.mx
        for name in reversed(self.stages):
            x -= len(name)
            self.put(1, x, name, (self.TEXT | curses.A_BOLD) if name == stage else self.DIM)
            x -= 3
        rows = big(title)
        if rows and max(len(r) for r in rows) < w - 2 * self.mx:
            for i, r in enumerate(rows):
                self.put(4 + i, self.mx, r, self.TEXT)
            y = 8
        else:
            self.put(4, self.mx, title, self.TEXT | curses.A_BOLD)
            y = 6
        for line in _wrap(subtitle, min(72, w - 2 * self.mx)):
            self.put(y, self.mx, line, self.SUBTLE)
            y += 1
        return y + 1

    def footer(self, hints):
        h, w = self.scr.getmaxyx()
        self.put(h - 2, self.mx, "   ".join(hints), self.DIM)

    def button(self, y, x, label, focused=True):
        text = "  %s  " % label
        self.put(y, x, text, (self.BUTTON | curses.A_BOLD) if focused else self.FIELD_DIM)
        return x + len(text) + 2

    # screens

    def pick_keyboard(self, current):
        everything = keyboard.layouts()
        query = ""
        # The guess first, then everything else in the usual order.
        first = [i for i in everything if (i[0], i[1]) == tuple(current)]
        if not first:
            first = [(current[0], current[1], keyboard.describe(*current))]
        ordered = first + [i for i in everything if i not in first]
        sel, top = 0, 0
        while True:
            items = keyboard.search(query, ordered)
            sel = max(0, min(sel, len(items) - 1))
            y = self.frame("keyboard", "your keyboard",
                           "We picked this from your system. If it isn't right, type to search "
                           "and choose yours. It's used on the desktop, the lock screen and the "
                           "sign-in screen.")
            h, w = self.scr.getmaxyx()
            fw = min(56, w - 2 * self.mx)
            self.put(y, self.mx, (" " + (query or "search") + " ").ljust(fw),
                     self.FIELD if query else self.FIELD_DIM)
            if query:
                self.put(y, self.mx + 1 + len(query), " ", self.BUTTON)
            y += 2
            rows = max(3, h - y - 4)
            if sel < top:
                top = sel
            if sel >= top + rows:
                top = sel - rows + 1
            if not items:
                self.put(y, self.mx, "No layout matches \"%s\"." % query, self.SUBTLE)
            for i, (code, var, desc) in enumerate(items[top:top + rows]):
                idx = top + i
                code_s = code + ("(%s)" % var if var else "")
                if idx == sel:
                    self.put(y + i, self.mx - 2, "▌", self.ACCENT)
                    self.put(y + i, self.mx, desc, self.TEXT | curses.A_BOLD, width=fw - 14)
                    self.put(y + i, self.mx + fw - len(code_s), code_s, self.ACCENT)
                else:
                    self.put(y + i, self.mx, desc, self.SUBTLE, width=fw - 14)
                    self.put(y + i, self.mx + fw - len(code_s), code_s, self.DIM)
            if top + rows < len(items):
                self.put(y + rows, self.mx, "↓ %d more" % (len(items) - top - rows), self.DIM)
            self.footer(["↑↓ choose", "type to search", "enter next", "esc quit"])
            self.scr.refresh()
            k = self.scr.get_wch()
            if k in ("\n", "\r", curses.KEY_ENTER) and items:
                return items[sel][0], items[sel][1]
            if k == "\x1b":
                if query:
                    query, sel = "", 0
                else:
                    return None
            elif k == curses.KEY_UP:
                sel -= 1
            elif k == curses.KEY_DOWN:
                sel += 1
            elif k == curses.KEY_PPAGE:
                sel -= rows
            elif k == curses.KEY_NPAGE:
                sel += rows
            elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                query, sel = query[:-1], 0
            elif isinstance(k, str) and k.isprintable():
                query, sel = query + k, 0
            elif k == curses.KEY_RESIZE:
                pass

    def review(self, steps, title, subtitle, go_label):
        # In the order they're drawn: home folder first, then the password ones.
        rows = [s for s in steps if not s.system] + [s for s in steps if s.system]
        sel = len(rows)  # start on the button
        while True:
            y = self.frame("ready", title, subtitle)
            h, w = self.scr.getmaxyx()
            cw = min(72, w - 2 * self.mx)
            groups = (("in your home folder", [s for s in rows if not s.system]),
                      ("needs your password", [s for s in rows if s.system]))
            for label, members in groups:
                if not members:
                    continue
                self.put(y, self.mx, label, self.ACCENT)
                y += 1
                for st in members:
                    idx = rows.index(st)
                    focused = idx == sel
                    if focused:
                        self.put(y, self.mx - 2, "▌", self.ACCENT)
                    if st.toggle:
                        box, battr = ("■", self.ACCENT) if st.on else ("□", self.DIM)
                    else:
                        box, battr = ("■", self.DIM)
                    self.put(y, self.mx, box, battr)
                    self.put(y, self.mx + 2, st.title,
                             (self.TEXT | curses.A_BOLD) if focused else
                             (self.TEXT if st.on else self.SUBTLE), width=cw - 2)
                    y += 1
                    for line in _wrap(st.detail, cw - 2)[:2]:
                        self.put(y, self.mx + 2, line, self.DIM)
                        y += 1
                    y += 1
            if any(s.system for s in rows) and not (self.sys.root or can_sudo()):
                self.put(y, self.mx, "sudo isn't available, so the password steps are off.", self.ERR)
                y += 1
            self.button(min(y + 1, h - 4), self.mx, go_label, sel == len(rows))
            self.footer(["↑↓ move", "space on/off", "enter %s" % go_label, "esc back"])
            self.scr.refresh()
            k = self.scr.get_wch()
            if k in ("\n", "\r", curses.KEY_ENTER):
                if sel < len(rows) and rows[sel].toggle:
                    rows[sel].on = not rows[sel].on  # enter on a row toggles it too
                    continue
                return True
            if k == "\x1b":
                return False
            if k == curses.KEY_UP:
                sel = max(0, sel - 1)
            elif k in (curses.KEY_DOWN, "\t"):
                sel = min(len(rows), sel + 1)
            elif k == " " and sel < len(rows) and rows[sel].toggle:
                st = rows[sel]
                if st.system and not (self.sys.root or can_sudo()):
                    continue
                st.on = not st.on

    def whats_new(self, news):
        top = 0
        while True:
            y = self.frame("what's new", "what's new",
                           "%d change%s since you last updated. Your colour, tiles and settings "
                           "stay as they are." % (len(news), "" if len(news) == 1 else "s"))
            h, w = self.scr.getmaxyx()
            cw = min(76, w - 2 * self.mx)
            rows = max(3, h - y - 6)
            for i, subject in enumerate(news[top:top + rows]):
                self.put(y + i, self.mx, "■", self.ACCENT)
                self.put(y + i, self.mx + 2, subject, self.TEXT, width=cw - 2)
            shown = min(rows, len(news) - top)
            if top + rows < len(news):
                self.put(y + shown, self.mx + 2, "↓ %d more" % (len(news) - top - rows), self.DIM)
            self.button(y + shown + 2, self.mx, "update")
            self.footer(["enter update", "↑↓ scroll", "esc not now"])
            self.scr.refresh()
            k = self.scr.get_wch()
            if k in ("\n", "\r", curses.KEY_ENTER):
                return True
            if k in ("\x1b", "q"):
                return False
            if k == curses.KEY_DOWN and top + rows < len(news):
                top += 1
            elif k == curses.KEY_UP and top > 0:
                top -= 1

    def message(self, stage, title, subtitle=""):
        self.frame(stage, title, subtitle)
        self.scr.refresh()

    def password(self):
        message, tries = "", 0
        typed = ""
        while True:
            y = self.frame(self.stages[-3] if not self.removing else "ready", "your password",
                           "The steps marked \"needs your password\" change the system, so sudo "
                           "asks for it once. It is passed to sudo and never written down.")
            h, w = self.scr.getmaxyx()
            fw = min(40, w - 2 * self.mx)
            self.put(y, self.mx, (" " + "●" * len(typed)).ljust(fw), self.FIELD)
            self.put(y, self.mx + 1 + len(typed), " ", self.BUTTON)
            if message:
                self.put(y + 2, self.mx, message, self.ERR)
            self.button(y + 4, self.mx, "continue")
            self.footer(["enter continue", "esc back"])
            self.scr.refresh()
            k = self.scr.get_wch()
            if k in ("\n", "\r", curses.KEY_ENTER):
                self.put(y + 2, self.mx, "Checking…".ljust(40), self.SUBTLE)
                self.scr.refresh()
                if check_sudo_password(typed):
                    return typed
                tries += 1
                typed = ""
                message = ("That password didn't work. Try again." if tries < 3 else
                           "Still not working. Is your account allowed to use sudo?")
            elif k == "\x1b":
                return None
            elif k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                typed = typed[:-1]
            elif k == "\x15":  # ctrl+u
                typed = ""
            elif isinstance(k, str) and k.isprintable():
                typed += k

    def progress(self, steps, runner, stage, title):
        result = {}

        def listener(text):
            with self.lock:
                self.log = (self.log + [text])[-200:]

        runner.listener = listener

        def work():
            result["failed"] = run_steps(steps, runner)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        spin = "◐◓◑◒"
        n = 0
        self.scr.timeout(100)
        while t.is_alive():
            self.draw_progress(steps, stage, title, spin[n % 4])
            n += 1
            try:
                self.scr.get_wch()
            except curses.error:
                pass
        self.scr.timeout(-1)
        return result.get("failed", (None, None))

    def draw_progress(self, steps, stage, title, spinner="●", failure=None):
        y = self.frame(stage, title, "This can take a few minutes. You can watch, or make a cup of tea.")
        h, w = self.scr.getmaxyx()
        cw = min(80, w - 2 * self.mx)
        for st in steps:
            if st.status == "skipped":
                continue
            mark, attr = {"pending": ("○", self.DIM), "running": (spinner, self.ACCENT),
                          "done": ("✓", self.OK), "warned": ("!", self.ERR),
                          "failed": ("✗", self.ERR)}[st.status]
            self.put(y, self.mx, mark, attr)
            self.put(y, self.mx + 2, st.title,
                     self.TEXT | (curses.A_BOLD if st.status == "running" else 0)
                     if st.status != "pending" else self.SUBTLE, width=cw)
            y += 1
        y += 1
        if failure:
            st, err = failure
            self.put(y, self.mx, str(err), self.ERR | curses.A_BOLD, width=cw)
            y += 1
            for line in _wrap(err.hint, cw):
                self.put(y, self.mx, line, self.TEXT)
                y += 1
            self.put(y + 1, self.mx, "The full log is in %s" % _tilde(LOG), self.SUBTLE, width=cw)
            y += 3
        box = h - y - 3
        if box > 2:
            self.put(y, self.mx, "─" * cw, self.DIM)
            with self.lock:
                tail = self.log[-(box - 1):]
            for i, line in enumerate(tail):
                self.put(y + 1 + i, self.mx, line, self.DIM, width=cw)
        if failure:
            self.footer(["r try again", "enter quit"])
        self.scr.refresh()

    def failure(self, steps, failed):
        while True:
            self.draw_progress(steps, self.stages[-2], "that didn't work", failure=failed)
            k = self.scr.get_wch()
            if k in ("r", "R"):
                return True
            if k in ("\n", "\r", "\x1b", "q", curses.KEY_ENTER):
                return False

    def done(self, title, lines, offer_logout, stage="done"):
        options = (["log out now", "close"] if offer_logout else ["close"])
        choice = len(options) - 1  # "close": logging out is a deliberate choice
        while True:
            y = self.frame(stage, title)
            h, w = self.scr.getmaxyx()
            cw = min(72, w - 2 * self.mx)
            for text, attr in lines:
                for line in _wrap(text, cw):
                    self.put(y, self.mx, line, attr)
                    y += 1
                y += 1
            x = self.mx
            for i, label in enumerate(options):
                x = self.button(y + 1, x, label, i == choice)
            self.footer(["←→ choose", "enter ok"])
            self.scr.refresh()
            k = self.scr.get_wch()
            if k in (curses.KEY_LEFT, curses.KEY_RIGHT, "\t"):
                choice = (choice + 1) % len(options)
            elif k in ("\n", "\r", curses.KEY_ENTER):
                return options[choice]
            elif k == "\x1b":
                return "close"


def _wrap(text, width):
    import textwrap
    out = []
    for para in (text or "").split("\n"):
        out.extend(textwrap.wrap(para, max(10, width)) or [""])
    return out if text else []


def _tilde(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


def finish_lines(system):
    session = os.path.exists(SESSION_BIN)
    if system.login_manager:
        how = ("Log out, then pick %s from the session menu on the sign-in screen "
               "(usually a button in a corner) and sign in." % ("tubewm" if session else "Sway"))
    else:
        how = ("Log out, sign in on the text console, and type  %s"
               % ("tubewm-session" if session else "sway"))
    return how, "The first time, a short welcome lets you pick your colour."


def logout():
    sid = os.environ.get("XDG_SESSION_ID")
    if sid:
        subprocess.call(["loginctl", "terminate-session", sid])


def tui_update(ui, args, system):
    source = Source()
    if args.pulled is None:
        ui.message("what's new", "one moment", "Looking for updates…")
        try:
            source.fetch()
        except Failed as e:
            ui.done("can't check", [(str(e), ui.ERR), (e.hint, ui.TEXT)], False, "what's new")
            return 1
        news = source.news()
        if not news:
            ui.done("up to date", [("You have the newest tubewm.", ui.TEXT)], False, "what's new")
            return 0
        if not ui.whats_new(news):
            return 1
        ui.message("updating", "one moment", "Fetching the new version…")
        old = source.head()
        try:
            source.pull()
        except Failed as e:
            ui.done("that didn't work", [(str(e), ui.ERR), (e.hint, ui.TEXT),
                                         ("Nothing was changed.", ui.SUBTLE)], False, "updating")
            return 1
        if source.notes:
            _save_notes(source.notes)
        curses.endwin()
        relaunch_after_pull(args, old)

    plan = Plan(system, home_only=args.home_only, update=True)
    ui.message("updating", "one moment", "Looking at what's changed…")
    plan.survey()
    steps = plan.build()
    password = None
    if plan.needs_password() and not sudo_without_password():
        while True:
            if not ui.review(steps, "almost there", "These need your password this time. "
                             "Space turns one off.", "update"):
                for st in steps:
                    if st.system:
                        st.on = False
                break
            if not plan.needs_password():
                break
            password = ui.password()
            if password is not None:
                break
    runner = Runner(password, system.root)
    while True:
        for st in steps:
            if st.status != "done":
                st.status = "pending"
        failed = ui.progress([s for s in steps if s.status != "done"], runner, "updating", "updating")
        if failed[0] is None:
            break
        if not ui.failure(steps, failed):
            return 1
    plan.remember()
    lines = []
    summary = update_lines(Source(), args.pulled)
    if summary:
        lines.append((summary, ui.TEXT))
    lines.append(("Sign out and back in to see everything new.", ui.TEXT))
    for note in _take_notes():
        lines.append((note, ui.SUBTLE))
    for st in steps:
        if st.status == "warned":
            lines.append(("\"%s\" didn't work; the rest is fine. Details are in %s."
                          % (st.title, _tilde(LOG)), ui.ERR))
    _write_update_count(0)
    if ui.done("updated", lines, bool(os.environ.get("XDG_SESSION_ID"))) == "log out now":
        logout()
    return 0


NOTES = os.path.join(STATE_DIR, "update-notes")
UPDATE_COUNT = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")),
                            "tubewm", "updates")


def _save_notes(notes):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(NOTES, "w") as fh:
        fh.write("\n".join(notes) + "\n")


def _take_notes():
    try:
        with open(NOTES) as fh:
            notes = [l.strip() for l in fh if l.strip()]
        os.remove(NOTES)
        return notes
    except OSError:
        return []


def _write_update_count(n):
    try:
        os.makedirs(os.path.dirname(UPDATE_COUNT), exist_ok=True)
        with open(UPDATE_COUNT, "w") as fh:
            fh.write("%d\n" % n)
    except OSError:
        pass


def tui_main(scr, args, system):
    ui = UI(scr, system, removing=args.uninstall, home_only=args.home_only, updating=args.update)
    if args.update:
        return tui_update(ui, args, system)
    if args.uninstall:
        rem = Removal(system)
        steps = rem.build()
        while True:
            if not ui.review(steps, "remove tubewm",
                             "Your settings from before tubewm come back. Space turns a step "
                             "on or off.", "remove"):
                return 1
            password = None
            if rem.needs_password() and not sudo_without_password():
                password = ui.password()
                if password is None:
                    continue
            break
        runner = Runner(password, system.root)
        while True:
            for st in steps:
                st.status = "pending"
            failed = ui.progress(steps, runner, "removing", "removing")
            if failed[0] is None or not ui.failure(steps, failed):
                break
        if failed[0] is not None:
            return 1
        ui.done("removed", [("Log out to finish. Your old desktop and settings are back.",
                             ui.TEXT)], False)
        return 0

    plan = Plan(system, home_only=args.home_only)
    ui.frame("keyboard", "one moment", "Looking at what's already installed…")
    ui.scr.refresh()
    plan.survey()
    stage = "keyboard"
    password = None
    while True:
        if stage == "keyboard":
            pick = ui.pick_keyboard(plan.layout)
            if pick is None:
                return 1
            plan.layout = pick
            steps = plan.build()
            stage = "ready"
        elif stage == "ready":
            sub = "Everything is ticked already, so press enter to start."
            if not any(s.system for s in steps):
                sub = "Nothing here needs your password. Press enter to start."
            stage = "password" if ui.review(steps, "ready to install", sub, "install") else "keyboard"
        elif stage == "password":
            password = None
            if plan.needs_password() and not sudo_without_password():
                password = ui.password()
                if password is None:
                    stage = "ready"
                    continue
            stage = "install"
        elif stage == "install":
            runner = Runner(password, system.root)
            while True:
                for st in steps:
                    if st.status != "done":
                        st.status = "pending"
                pending = [s for s in steps if s.status != "done"]
                failed = ui.progress(pending, runner, "installing", "installing")
                if failed[0] is None:
                    break
                if not ui.failure(steps, failed):
                    return 1
            break
    plan.remember()
    how, then = finish_lines(system)
    warned = [s for s in steps if s.status == "warned"]
    already = os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "sway" and os.environ.get("SWAYSOCK")
    lines = [(how, ui.TEXT), (then, ui.SUBTLE)]
    for st in warned:
        lines.append(("\"%s\" didn't work; the rest is fine. Details are in %s."
                      % (st.title, _tilde(LOG)), ui.ERR))
    if already:
        lines = [("You're already in Sway, so it has been reloaded. Press Super+S for start.",
                  ui.TEXT), (then, ui.SUBTLE)]
        subprocess.call(["swaymsg", "-q", "reload"])
    offer = bool(os.environ.get("XDG_SESSION_ID")) and not already
    if ui.done("all set", lines, offer) == "log out now":
        logout()
    return 0


# ── plain text, for --yes and when there's no terminal to draw on ────────

def plain_main(args, system):
    def say(s):
        print("\033[1m%s\033[0m" % s if sys.stdout.isatty() else s, flush=True)

    if args.update and args.pulled is None:
        source = Source()
        try:
            source.fetch()
            news = source.news()
            if not news:
                say("tubewm is up to date.")
                return 0
            say("%d change%s:" % (len(news), "" if len(news) == 1 else "s"))
            for subject in news[:15]:
                print("  ■ " + subject)
            if not args.yes and sys.stdin.isatty():
                if input("Update now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
                    return 1
            old = source.head()
            source.pull()
        except Failed as e:
            print("tubewm: %s\n%s" % (e, e.hint), file=sys.stderr)
            return 1
        for note in source.notes:
            print("  " + note)
        relaunch_after_pull(args, old)

    if args.uninstall:
        work = Removal(system)
        steps = work.build()
        if args.purge:
            for st in steps:
                st.on = True
    else:
        work = Plan(system, home_only=args.home_only, update=args.update)
        say("tubewm · %s" % system.name)
        print("  looking at what's installed…", flush=True)
        work.survey()
        if args.keyboard:
            parts = args.keyboard.split(":", 1)
            work.layout = (parts[0], parts[1] if len(parts) > 1 else "")
        steps = work.build()
    for st in steps:
        print("  %s %s" % ("■" if st.on else "□", st.title))
    if not args.yes and sys.stdin.isatty():
        ans = input("Go ahead? [Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            return 1
    runner = Runner(None, system.root)
    runner.listener = lambda t: print("    " + t, flush=True)
    if work.needs_password() and not system.root:
        if subprocess.call(["sudo", "-v"]) != 0:
            print("tubewm: sudo didn't accept that; nothing was changed.", file=sys.stderr)
            return 1

    def change():
        for st in steps:
            if st.status == "running":
                say("» " + st.title)

    st, err = run_steps(steps, runner, change)
    for w in steps:
        if w.status == "warned":
            print("  note: \"%s\" didn't work; the rest is fine. Details: %s" % (w.title, LOG))
    if st is not None:
        print("\ntubewm: %s\n%s\nFull log: %s" % (err, err.hint, LOG), file=sys.stderr)
        return 1
    if not args.uninstall:
        work.remember()
    if args.update:
        _write_update_count(0)
        say("Updated. Sign out and back in to see everything new.")
        return 0
    if args.uninstall:
        say("Removed. Log out to finish.")
    else:
        how, then = finish_lines(system)
        say("All set.")
        print("  " + how + "\n  " + then)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="install.sh", description="Install the tubewm desktop.")
    p.add_argument("--yes", "-y", action="store_true", help="no questions; take the defaults")
    p.add_argument("--home-only", action="store_true",
                   help="only change your home folder (no password, no packages)")
    p.add_argument("--uninstall", action="store_true", help="remove tubewm")
    p.add_argument("--purge", action="store_true",
                   help="with --uninstall --yes: also delete settings and packages")
    p.add_argument("--keyboard", metavar="LAYOUT[:VARIANT]", help="e.g. gb or us:intl")
    p.add_argument("--plain", action="store_true", help="plain text instead of the full-screen UI")
    p.add_argument("--update", action="store_true",
                   help="fetch the newest tubewm from GitHub and install it")
    p.add_argument("--pulled", metavar="COMMIT", help=argparse.SUPPRESS)
    p.add_argument("--packages-only", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    system = System()
    if args.packages_only:
        plan = Plan(system)
        plan.survey()
        if not plan.packages:
            print("  all packages present")
            return 0
        runner = Runner(None, system.root)
        runner.listener = print
        try:
            plan.do_packages(runner)
        except Failed as e:
            print("%s\n%s" % (e, e.hint), file=sys.stderr)
            return 1
        return 0

    interactive = (not args.plain and not args.yes and curses is not None
                   and sys.stdin.isatty() and sys.stdout.isatty()
                   and os.environ.get("TERM", "dumb") != "dumb")
    if not interactive:
        return plain_main(args, system)
    os.environ.setdefault("ESCDELAY", "25")
    try:
        return curses.wrapper(tui_main, args, system)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
