"""wm.refill: when a window closes, the tiled windows beside it grow into
the space it left. Pure geometry, no compositor needed."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tubewm_shell import wm  # noqa: E402

AREA = {"x": 0, "y": 40, "width": 1920, "height": 1040}
OUT = {"id": 1, "geometry": {"x": 0, "y": 0, "width": 1920, "height": 1080},
       "workarea": AREA, "workspace": {"x": 0, "y": 0}}


def view(vid, zone=None, rect=None, **extra):
    x, y, w, h = rect or wm.zone_rect(zone, AREA)
    v = {"id": vid, "role": "toplevel", "type": "toplevel", "mapped": True,
         "parent": -1, "layer": "workspace", "output-id": 1, "app-id": "foot",
         "geometry": {"x": x, "y": y, "width": w, "height": h}}
    v.update(extra)
    return v


def refill(gone, *rest):
    return sorted(wm.refill(gone, [gone] + list(rest), OUT))


def test_two_halves_become_one_maximised():
    assert refill(view(1, "left"), view(2, "right")) == [(2, "max")]
    assert refill(view(2, "right"), view(1, "left")) == [(1, "max")]


def test_two_stacked_halves_become_one_maximised():
    assert refill(view(1, "top"), view(2, "bottom")) == [(2, "max")]


def test_three_quarter_on_the_right_grows_to_half():
    left, tr, br = view(1, "left"), view(2, "top-right"), view(3, "bottom-right")
    assert refill(br, left, tr) == [(2, "right")]
    assert refill(tr, left, br) == [(3, "right")]


def test_three_left_half_closes_quarters_become_top_and_bottom():
    left, tr, br = view(1, "left"), view(2, "top-right"), view(3, "bottom-right")
    assert refill(left, tr, br) == [(2, "top"), (3, "bottom")]


def test_four_quarters_one_closes_the_one_above_or_below_grows():
    tl, tr = view(1, "top-left"), view(2, "top-right")
    bl, br = view(3, "bottom-left"), view(4, "bottom-right")
    assert refill(br, tl, tr, bl) == [(2, "right")]
    assert refill(tl, tr, bl, br) == [(3, "left")]


def test_lone_quarter_left_fills_the_screen():
    assert refill(view(1, "top-left"), view(2, "bottom-right")) == [(2, "max")]


def test_already_maximised_survivor_is_left_alone():
    assert refill(view(1, "left"), view(2, "max")) == []


def test_hand_placed_windows_are_left_alone():
    loose = view(2, rect=(300, 200, 800, 600))
    assert refill(view(1, "left"), loose) == []
    assert refill(view(1, "left"), view(3, "top-right"), loose) == []


def test_closing_an_untiled_or_special_window_moves_nothing():
    right = view(2, "right")
    assert refill(view(1, rect=(300, 200, 800, 600)), right) == []
    assert refill(view(1, "max"), right) == []
    assert refill(view(1, "left", fullscreen=True), right) == []
    assert refill(view(1, "left", **{"app-id": "zenity"}), right) == []
    assert refill(view(1, "left", parent=7), right) == []


def test_windows_on_other_desktops_and_minimised_ones_are_ignored():
    elsewhere = view(2, rect=(1920 + 960, 40, 960, 1040))   # next desktop over
    hidden = view(3, "right", minimized=True)
    assert refill(view(1, "left"), elsewhere, hidden) == []


def test_closed_window_still_listed_is_not_counted():
    gone = view(1, "left", mapped=False)
    assert refill(gone, view(2, "right")) == [(2, "max")]


def test_new_half_zones_map_to_grid_slots():
    assert wm.GRID_SLOTS["top"] == "t" and wm.GRID_SLOTS["bottom"] == "b"
    assert wm.zone_rect("top", AREA) == (0, 40, 1920, 520)
    assert wm.zone_rect("bottom", AREA) == (0, 560, 1920, 520)


# ── windows you put in a corner yourself keep their size ──────────────────

def chosen(*ids):
    wm.CHOSEN.clear()
    wm.CHOSEN.update(ids)


def test_your_corner_window_is_not_maximised_when_the_other_closes():
    try:
        chosen(2)
        assert refill(view(1, "left"), view(2, "top-right")) == []
        assert refill(view(1, "bottom-left"), view(2, "top-right")) == []
    finally:
        chosen()


def test_your_corner_window_is_not_grown_but_others_still_are():
    tl, tr = view(1, "top-left"), view(2, "top-right")
    bl, br = view(3, "bottom-left"), view(4, "bottom-right")
    try:
        chosen(2)
        # top-right would grow down; it's yours, so bottom-left grows across.
        assert refill(br, tl, tr, bl) == [(3, "bottom")]
        chosen(2, 3)
        assert refill(br, tl, tr, bl) == []
    finally:
        chosen()


def test_halves_still_grow_after_a_corner_was_chosen_elsewhere():
    try:
        chosen(9)
        assert refill(view(1, "left"), view(2, "right")) == [(2, "max")]
    finally:
        chosen()


def test_chose_remembers_corners_and_forgets_on_any_other_tiling():
    try:
        chosen()
        wm.chose({"id": 5}, 9)          # top|right
        assert 5 in wm.CHOSEN
        wm.chose({"id": 5}, 11)         # right half
        assert 5 not in wm.CHOSEN
        wm.chose({"id": 5}, 6)          # bottom|left
        wm.chose({"id": 5}, 0)          # untiled
        assert 5 not in wm.CHOSEN
    finally:
        chosen()
