#!/usr/bin/env python3
"""Install the tubewm Metro theme into every supported app that is present.

    python3 apps/lib/appthemes.py list
    python3 apps/lib/appthemes.py install   [--only a,b] [--skip a,b] [--accent X] [--light] [-q]
    python3 apps/lib/appthemes.py uninstall [--only a,b] [-q]

Each app gets its generated theme file(s) written into its own config folder.
Where the app needs a line in your main config to load that file (an
include, an import, a theme name), the line is added only if it isn't
already there, and only where it is safe to edit the file mechanically;
otherwise the one line to add is printed instead.

Everything written is recorded in ~/.config/tubewm/state/apps.json so that
uninstall removes exactly that: our files (unless you edited them), the lines
we added, and the settings we changed, restored to their old values. Every
existing file is copied to <file>.tubewm-<date>.bak before it is modified.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
APPS = HERE.parent
sys.path.insert(0, str(HERE))
import jsonc  # noqa: E402
import palette as P  # noqa: E402
import tokens as T  # noqa: E402

ENV = os.environ
HOME = Path(ENV.get("HOME", "~")).expanduser()
CONFIG = Path(ENV.get("XDG_CONFIG_HOME") or HOME / ".config")
STATE_FILE = CONFIG / "tubewm" / "state" / "apps.json"


# --------------------------------------------------------------------- utils

def which(*names: str) -> bool:
    return any(shutil.which(n) for n in names)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = path.with_name(f"{path.name}.tubewm-{stamp}.bak"), 1
    while dest.exists():
        n += 1
        dest = path.with_name(f"{path.name}.tubewm-{stamp}-{n}.bak")
    shutil.copy2(path, dest)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tubewm-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Ctx:
    """What one run of an app's installer needs, and what it records."""

    def __init__(self, toks: dict, record: dict, quiet: bool):
        self.toks = toks
        self.rec = record          # this app's state entry, mutated in place
        self.quiet = quiet
        self.notes: list[str] = []

    # -- files we own --------------------------------------------------------
    def put(self, template: str, dest: Path) -> Path:
        text = T.render((APPS / template).read_text(encoding="utf-8"), self.toks)
        files = self.rec.setdefault("files", {})
        if dest.exists() and str(dest) not in files:
            backup(dest)  # a file of the same name that isn't ours
        write_text(dest, text)
        files[str(dest)] = sha(text)
        return dest

    # -- one line in a config file we don't own ------------------------------
    def ensure_line(self, path: Path, line: str, where: str = "append",
                    present: Callable[[str], bool] | None = None) -> bool:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if (present or (lambda t: line in t.splitlines()))(text):
            return False
        self.created(path)
        backup(path)
        if where == "prepend":
            new = line + "\n" + text
        else:
            new = text + ("" if not text or text.endswith("\n") else "\n") + line + "\n"
        write_text(path, new)
        self.rec.setdefault("lines", []).append([str(path), line])
        return True

    # -- a value inside a structured file, restorable --------------------------
    def remember(self, kind: str, path: Path, key: str, had: bool, old, new) -> None:
        edits = self.rec.setdefault("edits", [])
        for e in edits:
            if e["kind"] == kind and e["path"] == str(path) and e["key"] == key:
                e["new"] = new
                return
        edits.append({"kind": kind, "path": str(path), "key": key, "had": had, "old": old, "new": new})

    def created(self, path: Path) -> None:
        """Note a config file that only exists because we wrote to it."""
        made = self.rec.setdefault("created", [])
        if not path.exists() and str(path) not in made:
            made.append(str(path))

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def run_quiet(*cmd: str) -> bool:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# -------------------------------------------------- structured-file editors

def _ini_find(lines: list[str], section: str, key: str):
    """(section header index or None, key line index or None, end of section)."""
    head = key_at = None
    end = len(lines)
    for i, ln in enumerate(lines):
        st = ln.strip()
        if st.startswith("[") and st.endswith("]"):
            if head is not None:
                end = i
                break
            if st[1:-1] == section:
                head = i
        elif head is not None and key_at is None and "=" in st and st.split("=", 1)[0].strip() == key:
            key_at = i
    return head, key_at, end


def ini_set(ctx: Ctx, path: Path, section: str, key: str, value: str) -> None:
    """Set one key in an INI file (qt5ct.conf style), editing only that line."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    head, at, end = _ini_find(lines, section, key)
    new = f"{key}={value}"
    if at is not None and lines[at].strip() == new:
        return
    ctx.created(path)
    backup(path)
    if at is not None:
        old = lines[at]
        lines[at] = new
    else:
        old = None
        if head is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{section}]", new]
        else:
            ins = end
            while ins > head + 1 and not lines[ins - 1].strip():
                ins -= 1
            lines.insert(ins, new)
    write_text(path, "\n".join(lines) + "\n")
    ctx.remember("ini", path, f"{section}\x1f{key}", at is not None, old, new)


def ini_restore(e: dict) -> None:
    path = Path(e["path"])
    if not path.exists():
        return
    section, key = e["key"].split("\x1f")
    lines = path.read_text(encoding="utf-8").splitlines()
    head, at, _ = _ini_find(lines, section, key)
    if at is None or lines[at].strip() != e["new"]:
        return
    backup(path)
    if e["had"]:
        lines[at] = e["old"]
    else:
        del lines[at]
    write_text(path, "\n".join(lines) + "\n")


def kv_set(ctx: Ctx, path: Path, key: str, value: str, fmt: str, top: bool = False) -> bool:
    """Set ``key = value`` style lines in a flat config (btop.conf, helix's
    top-level). ``fmt`` renders the whole line from the value. Returns False
    when the key is set to something else by the user and we left it alone.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.M)
    m = pat.search(text)
    line = fmt.format(value)
    if m and m.group(0).strip() == line.strip():
        return True
    ctx.created(path)
    backup(path)
    if m:
        old = m.group(0)
        text = text[:m.start()] + line + text[m.end():]
        ctx.remember("kv", path, key, True, old, line)
    else:
        text = (line + "\n" + text) if top else (text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")
        ctx.remember("kv", path, key, False, None, line)
    write_text(path, text)
    return True


def kv_restore(e: dict) -> None:
    path = Path(e["path"])
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.rstrip("\n") == e["new"]:
            backup(path)
            if e["had"]:
                lines[i] = e["old"] + ("\n" if ln.endswith("\n") else "")
            else:
                del lines[i]
            write_text(path, "".join(lines))
            return


def json_set(ctx: Ctx, path: Path, key: str, value, only_if_absent: bool = True) -> bool:
    data = jsonc.load(path)
    if key in data:
        if data[key] == value:
            return True
        if only_if_absent:
            return False
    had, old = key in data, data.get(key)
    ctx.created(path)
    backup(path)
    data[key] = value
    jsonc.write(path, data)
    ctx.remember("json", path, key, had, old, value)
    return True


def json_restore(e: dict) -> None:
    path = Path(e["path"])
    if not path.exists():
        return
    data = jsonc.load(path)
    if data.get(e["key"]) != e["new"]:
        return
    backup(path)
    if e["had"]:
        data[e["key"]] = e["old"]
    else:
        data.pop(e["key"], None)
    jsonc.write(path, data)


RESTORERS = {"ini": ini_restore, "kv": kv_restore, "json": json_restore}


# ------------------------------------------------------------------ the apps

@dataclass
class App:
    name: str
    title: str
    detect: Callable[[], bool]
    install: Callable[[Ctx], None]
    blurb: str
    tags: list[str] = field(default_factory=list)


def _kitty(ctx: Ctx) -> None:
    d = CONFIG / "kitty"
    ctx.put("kitty/tubewm.conf.in", d / "tubewm.conf")
    ctx.ensure_line(d / "kitty.conf", "include tubewm.conf")
    run_quiet("pkill", "-USR1", "-x", "kitty")  # kitty reloads its config on SIGUSR1


def _alacritty(ctx: Ctx) -> None:
    d = CONFIG / "alacritty"
    theme = ctx.put("alacritty/tubewm.toml.in", d / "tubewm.toml")
    main = d / "alacritty.toml"
    ref = str(theme).replace(str(HOME), "~", 1)
    if not main.exists():
        write_text(main, f'[general]\nimport = ["{ref}"]\n')
        ctx.rec.setdefault("files", {})[str(main)] = sha(main.read_text())
    elif "tubewm.toml" not in main.read_text(encoding="utf-8"):
        ctx.note(f'alacritty: add "{ref}" to the import list under [general] in {main}')


def _wezterm(ctx: Ctx) -> None:
    ctx.put("wezterm/tubewm.toml.in", CONFIG / "wezterm" / "colors" / "tubewm.toml")
    ctx.note('wezterm: set  config.color_scheme = "tubewm Metro"  in wezterm.lua (once)')


def _tmux(ctx: Ctx) -> None:
    d = CONFIG / "tmux"
    f = ctx.put("tmux/tubewm.conf.in", d / "tubewm.conf")
    main = d / "tmux.conf" if (d / "tmux.conf").exists() or not (HOME / ".tmux.conf").exists() \
        else HOME / ".tmux.conf"
    ref = str(f).replace(str(HOME), "~", 1)
    ctx.ensure_line(main, f"source-file {ref}")
    run_quiet("tmux", "source-file", str(f))


def _neovim(ctx: Ctx) -> None:
    ctx.put("neovim/tubewm.lua.in", CONFIG / "nvim" / "colors" / "tubewm.lua")
    ctx.note("neovim: run  :colorscheme tubewm  (add vim.cmd.colorscheme('tubewm') to init.lua to keep it)")


def _helix(ctx: Ctx) -> None:
    d = CONFIG / "helix"
    ctx.put("helix/tubewm.toml.in", d / "themes" / "tubewm.toml")
    cfg = d / "config.toml"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    m = re.search(r'^\s*theme\s*=\s*"([^"]*)"', text, re.M)
    if m and m.group(1) != "tubewm":
        ctx.note(f'helix: your config sets theme = "{m.group(1)}"; change it to "tubewm" to switch')
    elif not m:
        # top-level keys must come before any [table], so prepend
        kv_set(ctx, cfg, "theme", "tubewm", 'theme = "{}"', top=True)


def _zed(ctx: Ctx) -> None:
    d = CONFIG / "zed"
    ctx.put("zed/tubewm.json.in", d / "themes" / "tubewm.json")
    want = {"mode": "system", "dark": "tubewm Metro Dark", "light": "tubewm Metro Light"}
    if not json_set(ctx, d / "settings.json", "theme", want):
        ctx.note('zed: pick "tubewm Metro Dark" in the theme selector (Ctrl+K Ctrl+T)')


def firefox_profiles() -> list[Path]:
    """Default profile of each Firefox install found (classic, XDG and Flatpak)."""
    roots = [HOME / ".mozilla" / "firefox", CONFIG / "mozilla" / "firefox",
             HOME / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox"]
    out = []
    for root in roots:
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        cp = configparser.RawConfigParser(strict=False)
        cp.read(ini, encoding="utf-8")
        chosen = None
        for s in cp.sections():  # the [Install...] default is the one Firefox opens
            if s.startswith("Install") and cp.has_option(s, "Default"):
                chosen = root / cp.get(s, "Default")
                break
        if chosen is None:
            for s in cp.sections():
                if s.startswith("Profile") and cp.get(s, "Default", fallback="0") == "1":
                    rel = cp.get(s, "IsRelative", fallback="1") == "1"
                    p = cp.get(s, "Path")
                    chosen = root / p if rel else Path(p)
                    break
        if chosen and chosen.is_dir():
            out.append(chosen)
    return out


def _firefox(ctx: Ctx) -> None:
    profiles = firefox_profiles()
    if not profiles:
        ctx.note("firefox: no profile found; start Firefox once and re-run")
        return
    for prof in profiles:
        chrome = prof / "chrome"
        ctx.put("firefox/tubewm-metro.css.in", chrome / "tubewm-metro.css")
        ctx.put("firefox/userContent.css.in", chrome / "tubewm-content.css")
        # @import must come first in a stylesheet
        ctx.ensure_line(chrome / "userChrome.css", '@import url("tubewm-metro.css");', where="prepend")
        ctx.ensure_line(chrome / "userContent.css", '@import url("tubewm-content.css");', where="prepend")
        ctx.ensure_line(prof / "user.js",
                        'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);')
    ctx.note("firefox: restart Firefox to load the new chrome")


def _qt(ctx: Ctx) -> None:
    for name in ("qt5ct", "qt6ct"):
        if not (which(name) or (CONFIG / name).is_dir()):
            continue
        d = CONFIG / name
        f = ctx.put(f"qt/{name}-tubewm.conf.in", d / "colors" / "tubewm.conf")
        conf = d / f"{name}.conf"
        ini_set(ctx, conf, "Appearance", "custom_palette", "true")
        ini_set(ctx, conf, "Appearance", "color_scheme_path", str(f))
        ini_set(ctx, conf, "Appearance", "style", "Fusion")
    if ENV.get("QT_QPA_PLATFORMTHEME", "") not in ("qt5ct", "qt6ct"):
        ctx.note("qt: Qt apps follow this only with QT_QPA_PLATFORMTHEME=qt5ct (Qt 5) or qt6ct (Qt 6) set in your session")


def _spicetify(ctx: Ctx) -> None:
    out = subprocess.run(["spicetify", "-c"], capture_output=True, text=True) if which("spicetify") else None
    base = Path(out.stdout.strip()).parent if out and out.returncode == 0 and out.stdout.strip() \
        else CONFIG / "spicetify"
    d = base / "Themes" / "tubewm"
    ctx.put("spicetify/color.ini.in", d / "color.ini")
    ctx.put("spicetify/user.css.in", d / "user.css")
    if not which("spicetify"):
        return
    ok = run_quiet("spicetify", "config", "current_theme", "tubewm",
                   "color_scheme", ctx.toks["MODE"], "inject_css", "1", "replace_colors", "1")
    if ok and run_quiet("spicetify", "apply"):
        ctx.rec["spicetify_applied"] = True
    else:
        ctx.note("spicetify: theme files are in place; run  spicetify backup apply  to load them")


def _btop(ctx: Ctx) -> None:
    d = CONFIG / "btop"
    ctx.put("btop/tubewm.theme.in", d / "themes" / "tubewm.theme")
    kv_set(ctx, d / "btop.conf", "color_theme", "tubewm", 'color_theme = "{}"')
    ctx.note("btop: takes effect next start (quit btop first, it rewrites btop.conf on exit)")


def _zathura(ctx: Ctx) -> None:
    d = CONFIG / "zathura"
    ctx.put("zathura/tubewm.in", d / "tubewm")
    ctx.ensure_line(d / "zathurarc", "include tubewm")


def _mpv(ctx: Ctx) -> None:
    d = CONFIG / "mpv"
    ctx.put("mpv/tubewm.conf.in", d / "tubewm.conf")
    ctx.ensure_line(d / "mpv.conf", 'include="~~/tubewm.conf"')


APPS_LIST: list[App] = [
    App("kitty", "kitty", lambda: which("kitty") or (CONFIG / "kitty").is_dir(), _kitty,
        "colours, 20px padding, accent focus border, lowercase pivot tabs", ["terminal"]),
    App("alacritty", "Alacritty", lambda: which("alacritty") or (CONFIG / "alacritty").is_dir(), _alacritty,
        "colours, no decorations, 20px padding, accent selection and hints", ["terminal"]),
    App("wezterm", "WezTerm", lambda: which("wezterm") or (CONFIG / "wezterm").is_dir(), _wezterm,
        "colour scheme with a flat pivot tab bar", ["terminal"]),
    App("tmux", "tmux", lambda: which("tmux"), _tmux,
        "accent status strip, accent active pane border, flat menus", ["terminal"]),
    App("neovim", "Neovim", lambda: which("nvim") or (CONFIG / "nvim").is_dir(), _neovim,
        "full colorscheme incl. treesitter, LSP and telescope; accent statusline", ["editor"]),
    App("helix", "Helix", lambda: which("hx", "helix") or (CONFIG / "helix").is_dir(), _helix,
        "theme with accent statusline and menus", ["editor"]),
    App("zed", "Zed", lambda: which("zed", "zeditor") or (CONFIG / "zed").is_dir(), _zed,
        "dark and light themes following the system", ["editor"]),
    App("firefox", "Firefox", lambda: which("firefox") or bool(firefox_profiles()), _firefox,
        "userChrome: pivot tabs, flat accent-focus URL bar, square menus; new-tab tiles", ["browser"]),
    App("qt", "Qt apps (qt5ct / qt6ct)", lambda: which("qt5ct", "qt6ct") or (CONFIG / "qt5ct").is_dir()
        or (CONFIG / "qt6ct").is_dir(), _qt,
        "Fusion style with the tubewm palette: flat, square, accent selection", ["toolkit"]),
    App("spicetify", "Spotify (spicetify)", lambda: which("spicetify"), _spicetify,
        "Zune-style: big light lowercase headings, flat tiles, accent play button", ["music"]),
    App("btop", "btop", lambda: which("btop") or (CONFIG / "btop").is_dir(), _btop,
        "black canvas, every graph an accent ramp", ["tool"]),
    App("zathura", "zathura", lambda: which("zathura") or (CONFIG / "zathura").is_dir(), _zathura,
        "PDF viewer: accent status bar, Open Sans UI", ["tool"]),
    App("mpv", "mpv", lambda: which("mpv") or (CONFIG / "mpv").is_dir(), _mpv,
        "Open Sans OSD, flat bottom bar with an accent seek line", ["music"]),
]
BY_NAME = {a.name: a for a in APPS_LIST}


# -------------------------------------------------------------------- state

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_text(STATE_FILE, json.dumps(state, indent=2) + "\n")


def prune(d: Path) -> None:
    """Remove now-empty folders upward, stopping at the config roots."""
    stop = {HOME, CONFIG, HOME / ".mozilla", HOME / ".var"}
    while d not in stop and d != d.parent:
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def uninstall_app(name: str, rec: dict, say) -> None:
    for e in reversed(rec.get("edits", [])):
        RESTORERS[e["kind"]](e)
    for path, line in rec.get("lines", []):
        p = Path(path)
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = [ln for ln in lines if ln.rstrip("\n") != line]
        if len(keep) != len(lines):
            if path not in rec.get("created", []):
                backup(p)
            write_text(p, "".join(keep))
    for path, digest in rec.get("files", {}).items():
        p = Path(path)
        if not p.exists():
            continue
        if sha(p.read_text(encoding="utf-8")) == digest:
            p.unlink()
            prune(p.parent)
        else:
            say(f"{name}: kept {p} (you edited it)")
    for path in rec.get("created", []):
        p = Path(path)
        # a config file we created only to hold our line: drop it if that's all it held
        if p.exists() and p.read_text(encoding="utf-8").strip() in ("", "{}", "[Appearance]", "[Appearance]\n"):
            p.unlink()
            prune(p.parent)
    if rec.get("spicetify_applied") and which("spicetify"):
        run_quiet("spicetify", "config", "current_theme", "SpicetifyDefault", "color_scheme", "")
        run_quiet("spicetify", "apply")


# ---------------------------------------------------------------------- CLI

def pick(only: str | None, skip: str | None) -> list[App]:
    names = [n.strip() for n in (only or "").split(",") if n.strip()]
    bad = [n for n in names + [s.strip() for s in (skip or "").split(",") if s.strip()] if n not in BY_NAME]
    if bad:
        raise SystemExit(f"unknown app(s): {', '.join(bad)}; known: {', '.join(BY_NAME)}")
    chosen = [BY_NAME[n] for n in names] if names else APPS_LIST
    skipped = {s.strip() for s in (skip or "").split(",")}
    return [a for a in chosen if a.name not in skipped]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("op", choices=("list", "install", "uninstall"))
    ap.add_argument("--only", help="comma-separated app names (default: every app found)")
    ap.add_argument("--skip", help="comma-separated app names to leave alone")
    ap.add_argument("--accent", help="accent name from palette/accents, or #RRGGBB")
    ap.add_argument("--light", action="store_true", help="use the light polarity")
    ap.add_argument("--status-bar", choices=T.STATUS_STYLES, default="plain",
                    help="status bars: plain black (default) or a solid accent strip")
    ap.add_argument("--force", action="store_true", help="install even where the app wasn't found")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    say = (lambda *_: None) if a.quiet else (lambda m: print(m))

    if a.op == "list":
        state = load_state()
        for app in APPS_LIST:
            mark = "installed" if app.name in state else ("found" if app.detect() else "-")
            print(f"{app.name:<10} {mark:<10} {app.title}: {app.blurb}")
        return 0

    apps = pick(a.only, a.skip)
    state = load_state()

    if a.op == "uninstall":
        for app in apps:
            if app.name in state:
                uninstall_app(app.name, state.pop(app.name), say)
                say(f"{app.name}: removed")
        save_state(state)
        return 0

    try:
        pal = P.load(accent=a.accent)
    except ValueError as e:
        print(f"appthemes: {e}", file=sys.stderr)
        return 2
    mode = "light" if a.light else "dark"
    toks = T.tokens(pal, mode, a.status_bar)
    for m in ("dark", "light"):
        toks.update({f"{m.upper()}_{k}": v for k, v in T.tokens(pal, m, a.status_bar).items()})

    notes, failed = [], []
    for app in apps:
        explicit = bool(a.only) or a.force
        if not (explicit or app.detect()):
            continue
        rec = state.setdefault(app.name, {})
        ctx = Ctx(toks, rec, a.quiet)
        try:
            app.install(ctx)
        except Exception as e:  # one broken app must not stop the rest
            failed.append(app.name)
            print(f"{app.name}: failed: {e}", file=sys.stderr)
        else:
            say(f"{app.name}: themed ({pal['TUBEWM_ACCENT']}, {mode})")
            notes += ctx.notes
        finally:
            if not rec:
                state.pop(app.name, None)
            save_state(state)
    if notes and not a.quiet:
        print("\nOne-time steps:")
        for n in notes:
            print(f"  - {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
