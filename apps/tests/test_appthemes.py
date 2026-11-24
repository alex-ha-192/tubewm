"""Tests for the multi-app installer (apps/install.sh, apps/lib/appthemes.py)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APPS / "lib"))
import palette as P  # noqa: E402
import tokens as T  # noqa: E402

TEMPLATES = sorted(p for p in APPS.rglob("*.in") if "vivaldi" not in p.parts)
LEFTOVER = re.compile(r"@[A-Z][A-Z0-9_]*(\.[a-z]+)?@")


def all_tokens(accent, mode, status="plain"):
    pal = P.load(accent=accent)
    toks = T.tokens(pal, mode, status)
    for m in ("dark", "light"):
        toks.update({f"{m.upper()}_{k}": v for k, v in T.tokens(pal, m).items()})
    return toks


@pytest.mark.parametrize("accent", ["magenta", "lime", "brown", "#FFFFFF"])
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_every_template_renders_and_parses(accent, mode):
    toks = all_tokens(accent, mode)
    for tpl in TEMPLATES:
        out = T.render(tpl.read_text(), toks)
        assert not LEFTOVER.search(out), tpl
        name = tpl.name[:-3]
        if name.endswith(".toml"):
            tomllib.loads(out)
        elif name.endswith(".json"):
            json.loads(out)


def test_render_forms():
    toks = {"A": "#0A0B0C"}
    assert T.render("@A@ @A.bare@ @A.argb@ @A.rgb@", toks) == "#0A0B0C 0A0B0C #FF0A0B0C 10, 11, 12"
    with pytest.raises(KeyError):
        T.render("@NOPE@", toks)


def test_qt_palettes_have_one_colour_per_role():
    toks = all_tokens("cobalt", "dark")
    for name, n in (("qt5ct", 21), ("qt6ct", 22)):
        out = T.render((APPS / "qt" / f"{name}-tubewm.conf.in").read_text(), toks)
        for key in ("active_colors", "disabled_colors", "inactive_colors"):
            line = re.search(rf"^{key}=(.*)$", out, re.M).group(1)
            cols = [c.strip() for c in line.split(",")]
            assert len(cols) == n and all(re.fullmatch(r"#FF[0-9A-F]{6}", c) for c in cols)


def test_neovim_colorscheme_runs():
    lupa = pytest.importorskip("lupa")
    L = lupa.LuaRuntime()
    L.execute("""groups = {}
      vim = { o = {}, g = {}, fn = { exists = function() return 0 end }, cmd = function() end,
              api = { nvim_set_hl = function(_, name, spec) groups[name] = spec end } }""")
    src = (APPS / "neovim" / "tubewm.lua.in").read_text()
    L.execute(T.render(src, all_tokens("teal", "dark", "accent")))
    g = L.globals()
    assert g.groups["StatusLine"]["bg"] == P.accent_swatches()["teal"]
    L.execute(T.render(src, all_tokens("teal", "dark", "plain")))
    assert g.groups["StatusLine"]["bg"] == "#000000"
    assert g.groups["StatusLineEmphasis"]["fg"] == P.accent_swatches()["teal"]
    assert g.groups["Normal"]["bg"] == "#000000"
    assert g.vim.g["terminal_color_15"]
    assert g.vim.g.colors_name == "tubewm"


# ---- installer round trips -----------------------------------------------------

def tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and not p.name.endswith(".bak") and not rel.startswith(".config/tubewm/"):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir() and not rel.startswith(".config/tubewm"):
            out[rel + "/"] = "dir"
    return out


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    prof = h / ".mozilla" / "firefox" / "abc.default-release"
    prof.mkdir(parents=True)
    (h / ".mozilla" / "firefox" / "profiles.ini").write_text(
        "[Install4F96D1932A9F858E]\nDefault=abc.default-release\n\n"
        "[Profile0]\nName=default\nIsRelative=1\nPath=abc.default-release\n")
    (prof / "chrome").mkdir()
    (prof / "chrome" / "userChrome.css").write_text("/* mine */\n#nav-bar { color: red; }\n")
    cfg = h / ".config"
    for d in ("kitty", "helix", "btop", "qt6ct", "zed", "alacritty"):
        (cfg / d).mkdir(parents=True)
    (cfg / "kitty" / "kitty.conf").write_text("font_size 12\n")
    (cfg / "helix" / "config.toml").write_text('[editor]\nline-number = "relative"\n')
    (cfg / "btop" / "btop.conf").write_text('color_theme = "Default"\nupdate_ms = 1000\n')
    (cfg / "qt6ct" / "qt6ct.conf").write_text("[Appearance]\nicon_theme=Papirus\nstyle=kvantum\n")
    (cfg / "zed" / "settings.json").write_text('// zed\n{ "ui_font_size": 16, }\n')
    (cfg / "alacritty" / "alacritty.toml").write_text("[font]\nsize = 11\n")
    return h


def run(home, *args, script="lib/appthemes.py"):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TUBEWM_", "XDG_"))}
    env.update(HOME=str(home), PATH="/usr/bin:/bin:" + str(Path(sys.executable).parent))
    cmd = [sys.executable, str(APPS / script)] if script.endswith(".py") else ["sh", str(APPS / script)]
    return subprocess.run(cmd + list(args), env=env, capture_output=True, text=True)


def test_install_then_uninstall_restores_everything(home):
    before = tree(home)
    r = run(home, "install", "--force", "--accent", "violet")
    assert r.returncode == 0, r.stderr
    cfg = home / ".config"
    assert "include tubewm.conf" in (cfg / "kitty" / "kitty.conf").read_text()
    assert (cfg / "helix" / "config.toml").read_text().startswith('theme = "tubewm"\n')
    assert 'color_theme = "tubewm"' in (cfg / "btop" / "btop.conf").read_text()
    qt = (cfg / "qt6ct" / "qt6ct.conf").read_text()
    assert "style=Fusion" in qt and "icon_theme=Papirus" in qt and "custom_palette=true" in qt
    chrome = (home / ".mozilla/firefox/abc.default-release/chrome/userChrome.css").read_text()
    assert chrome.startswith('@import url("tubewm-metro.css");\n') and "#nav-bar" in chrome
    zed = json.loads((cfg / "zed" / "settings.json").read_text())
    assert zed["theme"]["dark"] == "tubewm Metro Dark" and zed["ui_font_size"] == 16
    # alacritty.toml existed without our import: left alone, with a note
    assert "tubewm" not in (cfg / "alacritty" / "alacritty.toml").read_text()
    assert "alacritty: add" in r.stdout

    # re-install with a new accent: no duplicate lines
    assert run(home, "install", "--force", "--accent", "lime").returncode == 0
    assert (cfg / "kitty" / "kitty.conf").read_text().count("include tubewm.conf") == 1
    assert P.accent_swatches()["lime"] in (cfg / "kitty" / "tubewm.conf").read_text()

    r = run(home, "uninstall")
    assert r.returncode == 0, r.stderr
    after = tree(home)
    # settings.json is JSONC: the rewrite drops comments (the .bak keeps them),
    # so compare that one by value
    zed = ".config/zed/settings.json"
    assert json.loads((home / zed).read_text()) == {"ui_font_size": 16}
    before.pop(zed), after.pop(zed)
    assert after == before


def test_user_edits_survive_uninstall(home):
    assert run(home, "install", "--only", "kitty,helix").returncode == 0
    theme = home / ".config" / "kitty" / "tubewm.conf"
    theme.write_text(theme.read_text() + "# my tweak\n")
    (home / ".config" / "helix" / "config.toml").write_text('theme = "onedark"\n')
    r = run(home, "uninstall")
    assert theme.exists() and "kept" in r.stdout
    assert (home / ".config" / "helix" / "config.toml").read_text() == 'theme = "onedark"\n'


def test_helix_existing_theme_is_respected(home):
    cfgf = home / ".config" / "helix" / "config.toml"
    cfgf.write_text('theme = "gruvbox"\n')
    r = run(home, "install", "--only", "helix")
    assert cfgf.read_text() == 'theme = "gruvbox"\n'
    assert 'change it to "tubewm"' in r.stdout
    assert (home / ".config/helix/themes/tubewm.toml").exists()


def test_unknown_app_name_is_an_error(home):
    r = run(home, "install", "--only", "kittty")
    assert r.returncode != 0 and "unknown app" in r.stderr


def test_wrapper_hook_rethemes_with_accent_file(home):
    r = run(home, "--accent", "magenta", "--skip", "vscode,vivaldi", script="install.sh")
    assert r.returncode == 0, r.stderr
    hook = home / ".config" / "tubewm" / "accent.d" / "40-apps"
    assert os.access(hook, os.X_OK)
    (home / ".config" / "tubewm" / "accent").write_text("TUBEWM_ACCENT=#0078D7\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TUBEWM_", "XDG_"))}
    env.update(HOME=str(home), TUBEWM_ACCENT="#E3008C")  # stale env must not win
    subprocess.run([str(hook)], env=env, check=True)
    assert "#0078D7" in (home / ".config" / "kitty" / "tubewm.conf").read_text()
    r = run(home, "--uninstall", "-q", script="install.sh")
    assert r.returncode == 0 and not hook.exists()
