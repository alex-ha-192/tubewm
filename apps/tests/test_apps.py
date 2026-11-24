"""Tests for the tubewm app themes. Run: python3 -m pytest apps/tests"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

APPS = Path(__file__).resolve().parents[1]
REPO = APPS.parent
sys.path.insert(0, str(APPS / "lib"))

import importlib.util  # noqa: E402

import palette as P  # noqa: E402
import jsonc  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vscode_build = _load("vscode_build", APPS / "vscode" / "build.py")
vivaldi_build = _load("vivaldi_build", APPS / "vivaldi" / "build.py")

HEX = re.compile(r"^#[0-9A-F]{6}([0-9A-F]{2})?$")
SWATCHES = sorted(P.accent_swatches())


def clean_env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TUBEWM_", "XDG_"))}
    env.update(HOME=str(tmp_path), PATH="/usr/bin:/bin:" + str(Path(sys.executable).parent))
    env.update(extra)
    return env


# ---- palette ---------------------------------------------------------------

def test_palette_reads_shared_file():
    pal = P.load(env={"HOME": "/nonexistent"})
    assert pal["TUBEWM_BG"] == "#000000"
    assert pal["TUBEWM_ACCENT"] == pal["TUBEWM_ACCENT_DEFAULT"]
    assert "magenta" in SWATCHES and "cobalt" in SWATCHES


def test_accent_precedence(tmp_path):
    (tmp_path / "tubewm").mkdir()
    (tmp_path / "tubewm" / "accent").write_text("TUBEWM_ACCENT=#123456\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert P.load(env=env)["TUBEWM_ACCENT"] == "#123456"
    assert P.load(env={**env, "TUBEWM_ACCENT": "teal"})["TUBEWM_ACCENT"] == P.accent_swatches()["teal"]
    assert P.load(env={**env, "TUBEWM_ACCENT": "teal"}, accent="abcdef")["TUBEWM_ACCENT"] == "#ABCDEF"


def test_accent_matches_shell_resolution(tmp_path):
    """Our parser must agree with actually sourcing tubewm-colors.sh."""
    (tmp_path / "tubewm").mkdir()
    (tmp_path / "tubewm" / "accent").write_text("TUBEWM_ACCENT=#0A0B0C\n")
    out = subprocess.run(
        ["sh", "-c", '. "$1"; echo "$TUBEWM_ACCENT"', "sh", str(REPO / "palette" / "tubewm-colors.sh")],
        env={"XDG_CONFIG_HOME": str(tmp_path), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert P.load(env={"XDG_CONFIG_HOME": str(tmp_path)})["TUBEWM_ACCENT"] == out.upper()


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_greys_stay_readable(mode):
    """Inactive tabs and labels use fg_subtle; disabled text fg_disabled."""
    c = P.polarity(P.load(env={"HOME": "/nonexistent"}), mode)
    for ground in ("bg", "shell"):
        assert P.contrast(c["fg_subtle"], c[ground]) >= 4.5, ground
        assert P.contrast(c["fg_disabled"], c[ground]) >= 3.0, ground


def test_vivaldi_close_button_is_visible(tmp_path):
    vivaldi_build.build(tmp_path, None)
    css = (tmp_path / "css" / "tubewm-metro.css").read_text()
    rule = css[css.index(".tab.active .close,"):]
    assert "color: var(--tubewm-fg)" in rule.split("}")[0]
    assert "fill: currentColor" in css
    # no rule may fade or hide the close button on the active tab
    assert "opacity: 0" not in css


def test_unknown_accent_is_an_error():
    with pytest.raises(ValueError, match="unknown accent"):
        P.load(accent="chartreuse-ish")


# ---- VSCode theme ------------------------------------------------------------

@pytest.mark.parametrize("accent", SWATCHES)
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_vscode_theme_colours_and_contrast(accent, mode):
    pal = P.load(accent=accent)
    t = vscode_build.theme(mode, pal)
    c = P.polarity(pal, mode)
    for key, val in t["colors"].items():
        assert HEX.match(val), f"{key}={val}"
    assert P.contrast(t["colors"]["editor.foreground"], t["colors"]["editor.background"]) >= 7
    # every syntax colour reads on the canvas; comments may be quieter
    for rule in t["tokenColors"]:
        need = 3.0 if rule["name"] in ("Comments", "Markup quote") else 4.5
        fg = rule["settings"]["foreground"]
        assert P.contrast(fg, c["bg"]) >= need - 0.05, (rule["name"], fg)
    # text on the accent status bar and selected list rows
    on = t["colors"]["statusBar.foreground"]
    assert P.contrast(on, t["colors"]["statusBar.background"]) >= 3.0


def test_vscode_theme_is_flat():
    t = vscode_build.theme("dark", P.load())
    for key in ("widget.shadow", "scrollbar.shadow", "editorStickyScroll.shadow"):
        assert t["colors"][key].endswith("00")


def test_vscode_vsix_layout(tmp_path):
    out = vscode_build.build(tmp_path / "ext", "cobalt")
    vsix = vscode_build.vsix(out, tmp_path / "t.vsix")
    with zipfile.ZipFile(vsix) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json",
                "extension/themes/tubewm-metro-dark.json", "extension/themes/tubewm-metro-light.json"} <= names
        pkg = json.loads(z.read("extension/package.json"))
        for th in pkg["contributes"]["themes"]:
            assert "extension/" + th["path"].lstrip("./") in names
        assert 'Id="tubewm-metro"' in z.read("extension.vsixmanifest").decode()


# ---- jsonc ---------------------------------------------------------------------

def test_strip_jsonc_keeps_strings():
    src = '{\n // c\n "a": "http://x//y /* no */", /* gone */ "b": [1, 2,],\n}'
    assert json.loads(jsonc.strip_jsonc(src)) == {"a": "http://x//y /* no */", "b": [1, 2]}


def test_merge_keeps_user_values_and_remove_restores(tmp_path):
    target, state = tmp_path / "settings.json", tmp_path / "state.json"
    target.write_text('{ // mine\n "editor.fontSize": 12, "workbench.colorTheme": "Mine", }')
    patch = {"editor.fontSize": 14, "workbench.colorTheme": "Ours", "editor.minimap.enabled": False}
    p = tmp_path / "patch.json"
    p.write_text(json.dumps(patch))
    run = lambda *a: subprocess.run([sys.executable, str(APPS / "lib" / "jsonc.py"), *a],
                                    capture_output=True, text=True, check=True).stdout.split()
    wrote = run("merge", str(target), str(p), "--force", "workbench.colorTheme", "--state", str(state))
    assert sorted(wrote) == ["editor.minimap.enabled", "workbench.colorTheme"]
    data = jsonc.load(target)
    assert data["editor.fontSize"] == 12 and data["workbench.colorTheme"] == "Ours"
    run("remove", str(target), str(p), "--state", str(state))
    assert jsonc.load(target) == {"editor.fontSize": 12, "workbench.colorTheme": "Mine"}
    assert not state.exists()


# ---- install scripts -----------------------------------------------------------

def sh(script, tmp_path, *args, env=None):
    return subprocess.run(["sh", str(APPS / script), *args], env=env or clean_env(tmp_path),
                          capture_output=True, text=True)


def test_vscode_install_roundtrip(tmp_path):
    user = tmp_path / ".config" / "Code" / "User"
    user.mkdir(parents=True)
    original = '{\n  // keep me\n  "editor.fontSize": 12,\n  "workbench.colorTheme": "Default Dark+"\n}\n'
    (user / "settings.json").write_text(original)
    r = sh("vscode/install.sh", tmp_path, "--accent", "lime", "--editor", "code")
    assert r.returncode == 0, r.stderr
    ext = tmp_path / ".vscode" / "extensions" / "tubewm.tubewm-metro-0.1.0"
    dark = json.loads((ext / "themes" / "tubewm-metro-dark.json").read_text())
    assert dark["colors"]["focusBorder"] == P.accent_swatches()["lime"]
    s = jsonc.load(user / "settings.json")
    assert s["workbench.colorTheme"] == "tubewm Metro Dark" and s["editor.fontSize"] == 12
    hook = tmp_path / ".config" / "tubewm" / "accent.d" / "50-vscode"
    assert os.access(hook, os.X_OK)

    r = sh("vscode/install.sh", tmp_path, "--uninstall", "--editor", "code")
    assert r.returncode == 0, r.stderr
    assert jsonc.load(user / "settings.json") == json.loads(jsonc.strip_jsonc(original))
    assert not ext.exists() and not hook.exists()


def test_vscode_hook_follows_accent_file(tmp_path):
    r = sh("vscode/install.sh", tmp_path, "--editor", "code", "--no-settings")
    assert r.returncode == 0, r.stderr
    cfg = tmp_path / ".config" / "tubewm"
    (cfg / "accent").write_text("TUBEWM_ACCENT=#0078D7\n")
    # a stale env accent must not win over the freshly written file
    env = clean_env(tmp_path, TUBEWM_ACCENT="#E3008C")
    subprocess.run([str(cfg / "accent.d" / "50-vscode")], env=env, check=True)
    ext = tmp_path / ".vscode" / "extensions" / "tubewm.tubewm-metro-0.1.0"
    dark = json.loads((ext / "themes" / "tubewm-metro-dark.json").read_text())
    assert dark["colors"]["focusBorder"] == "#0078D7"


def test_vscode_install_fails_cleanly_without_editor(tmp_path):
    r = sh("vscode/install.sh", tmp_path)
    assert r.returncode != 0 and "no VSCode" in r.stderr


# ---- Vivaldi --------------------------------------------------------------------

def test_vivaldi_css_has_no_placeholders(tmp_path):
    info = vivaldi_build.build(tmp_path, "orange")
    css = (tmp_path / "css" / "tubewm-metro.css").read_text()
    assert not re.search(r"@[A-Z_]+@", css)
    assert f"var(--colorHighlightBg, {info['accent']})" in css
    with zipfile.ZipFile(tmp_path / "themes" / "tubewm-metro-dark.zip") as z:
        t = json.loads(z.read("settings.json"))
    assert t["colorHighlightBg"] == info["accent"] and t["radius"] == 0


def test_vivaldi_install_roundtrip(tmp_path):
    prof = tmp_path / ".config" / "vivaldi" / "Default"
    prof.mkdir(parents=True)
    original = {"browser": {"x": 1}, "vivaldi": {"themes": {"current": "Vivaldi2", "user": [{"id": "mine"}]},
                                                  "appearance": {"css_ui_mods_directory": "/old"}}}
    (prof / "Preferences").write_text(json.dumps(original))
    r = sh("vivaldi/install.sh", tmp_path, "--accent", "violet")
    assert r.returncode == 0, r.stderr
    v = json.loads((prof / "Preferences").read_text())["vivaldi"]
    assert v["themes"]["current"] == vivaldi_build.IDS["dark"]
    assert [t["id"] for t in v["themes"]["user"]][0] == "mine" and len(v["themes"]["user"]) == 3
    assert v["appearance"]["css_ui_mods_directory"].endswith("tubewm/vivaldi/css")
    # re-running replaces our themes instead of duplicating them
    assert sh("vivaldi/install.sh", tmp_path, "-q").returncode == 0
    assert len(json.loads((prof / "Preferences").read_text())["vivaldi"]["themes"]["user"]) == 3

    r = sh("vivaldi/install.sh", tmp_path, "--uninstall")
    assert r.returncode == 0, r.stderr
    assert json.loads((prof / "Preferences").read_text()) == original


def test_vivaldi_refuses_non_vivaldi_prefs(tmp_path):
    prof = tmp_path / "p"
    prof.mkdir()
    (prof / "Preferences").write_text('{"browser": {}}')
    r = sh("vivaldi/install.sh", tmp_path, "--profile", str(prof))
    assert r.returncode != 0
    assert json.loads((prof / "Preferences").read_text()) == {"browser": {}}
