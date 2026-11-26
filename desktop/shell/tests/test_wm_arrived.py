"""wm.arrived: a window moved to another desktop finds room there instead of
landing on top of what's already on it, and the windows it left behind
grow into its space. Wayfire's answers are faked."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import wm  # noqa: E402

AREA = {"x": 0, "y": 40, "width": 1920, "height": 1040}
W = AREA["width"]


def out(cur):
    return {"id": 1, "geometry": {"x": 0, "y": 0, "width": W, "height": 1080},
            "workarea": AREA, "workspace": {"x": cur, "y": 0}}


def view(vid, desk, zone, cur):
    """A window filling `zone` on desktop `desk`, seen from desktop `cur`
    (Wayfire gives positions relative to the desktop on screen)."""
    x, y, w, h = wm.zone_rect(zone, AREA)
    return {"id": vid, "role": "toplevel", "type": "toplevel", "mapped": True,
            "parent": -1, "layer": "workspace", "output-id": 1, "app-id": "foot",
            "geometry": {"x": x + (desk - cur) * W, "y": y, "width": w, "height": h}}


@pytest.fixture
def compositor(monkeypatch):
    """Serve `views` on desktop `cur`; record what gets snapped."""
    state = {"views": [], "cur": 0, "snapped": []}

    def wf(method, data=None, timeout=2.0):
        if method == "window-rules/list-views":
            return state["views"]
        if method == "window-rules/list-outputs":
            return [out(state["cur"])]
        if method.startswith("grid/slot_"):
            slot = method[len("grid/slot_"):]
            zone = next(z for z, s in wm.GRID_SLOTS.items() if s == slot)
            state["snapped"].append((data["view_id"], zone))
            return {}
        raise AssertionError(method)

    monkeypatch.setattr(wm, "WAYFIRE", True)
    monkeypatch.setattr(wm, "_wf", wf)
    return state


def gap(zone):
    x, y, w, h = wm.zone_rect(zone, AREA)
    return {"x": x, "y": y, "width": w, "height": h}


def test_onto_a_desktop_with_a_window_they_share_it(compositor):
    # Firefox (1) taken from desktop 0 to desktop 1, where foot (2) fills
    # the screen: they go side by side rather than one covering the other.
    compositor["cur"] = 1
    compositor["views"] = [view(1, 1, "max", 1), view(2, 1, "max", 1)]
    plan = sorted(wm.arrived(1, set(), gap("max")))
    assert plan == [(1, "right"), (2, "left")]
    assert sorted(compositor["snapped"]) == plan


def test_into_free_space_it_takes_it(compositor):
    compositor["cur"] = 1
    compositor["views"] = [view(1, 1, "max", 1), view(2, 1, "left", 1)]
    assert wm.arrived(1, set(), gap("max")) == [(1, "right")]


def test_the_half_left_behind_fills_the_screen(compositor):
    # The right half (1) goes to desktop 1, which is empty; the left half
    # (2) left on desktop 0 grows over the gap.
    compositor["cur"] = 1
    compositor["views"] = [view(1, 1, "right", 1), view(2, 0, "left", 1)]
    plan = sorted(wm.arrived(1, {2}, gap("right")))
    assert plan == [(1, "max"), (2, "max")]


def test_sent_without_following_it(compositor):
    # Super+Shift+number from desktop 0: you stay on 0.
    compositor["cur"] = 0
    compositor["views"] = [view(1, 2, "right", 0), view(2, 0, "left", 0), view(3, 2, "max", 0)]
    plan = sorted(wm.arrived(1, {2}, view(1, 0, "right", 0)["geometry"]))
    assert plan == [(1, "right"), (2, "max"), (3, "left")]


def test_a_whole_desktop_moved_is_left_alone(compositor):
    # Moving a desktop left or right takes all its windows along.
    compositor["cur"] = 1
    compositor["views"] = [view(1, 1, "left", 1), view(2, 1, "right", 1)]
    assert wm.arrived(1, {2}, gap("left")) == []
    assert compositor["snapped"] == []


def test_a_window_placed_by_hand_left_behind_stays(compositor):
    compositor["cur"] = 1
    hand = view(2, 0, "max", 1)
    hand["geometry"].update(width=800, height=600)
    compositor["views"] = [view(1, 1, "right", 1), hand]
    assert wm.arrived(1, {2}, gap("right")) == [(1, "max")]


def test_a_dialog_is_not_tiled(compositor):
    compositor["cur"] = 1
    v = view(1, 1, "max", 1)
    v["app-id"] = "xdg-desktop-portal-gtk"
    compositor["views"] = [v, view(2, 1, "max", 1)]
    assert wm.arrived(1, set(), gap("max")) == []
