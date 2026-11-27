"""wfconfig picks tubewm's own Wayfire plugins once build.sh has built them,
and Wayfire's stock ones until then."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import wfconfig  # noqa: E402


def test_alt_tab_is_fast_switcher_until_tube_switch_is_built(tmp_path, monkeypatch):
    monkeypatch.setattr(wfconfig, "TUBE_SWITCH", str(tmp_path / "libtube-switch.so"))
    assert wfconfig.switcher() == "fast-switcher"


def test_alt_tab_is_tube_switch_once_built(tmp_path, monkeypatch):
    so = tmp_path / "libtube-switch.so"
    so.touch()
    monkeypatch.setattr(wfconfig, "TUBE_SWITCH", str(so))
    assert wfconfig.switcher() == "tube-switch"


def test_template_loads_exactly_one_switcher(tmp_path, monkeypatch):
    so = tmp_path / "libtube-switch.so"
    so.touch()
    monkeypatch.setattr(wfconfig, "TUBE_SWITCH", str(so))
    monkeypatch.setattr(wfconfig, "USER_INI", str(tmp_path / "none.ini"))
    monkeypatch.setattr(wfconfig, "outputs", lambda drm=None: "")
    pal = {k: "#1ba1e2" for k in ("ACCENT", "FG", "SHELL", "SURFACE")}
    text = wfconfig.build(pal)
    plugins = text.split("plugins =", 1)[1].split("\n#", 1)[0].replace("\\", " ").split()
    assert "tube-switch" in plugins
    assert "fast-switcher" not in plugins
    assert "[tube-switch]\nactivate = <alt> KEY_TAB\nactivate_backward = <alt> <shift> KEY_TAB" in text
