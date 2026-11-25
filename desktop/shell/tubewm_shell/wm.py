"""Talk to the compositor: Wayfire through its IPC socket, Sway through swaymsg.

Everything above this module (start, charms, the bar flyouts, the switcher)
uses the same small API, so tubewm runs on either.
"""

import json
import os
import socket
import struct
import subprocess

WAYFIRE = bool(os.environ.get("WAYFIRE_SOCKET"))
SWAY = not WAYFIRE and bool(os.environ.get("SWAYSOCK"))


def name():
    return "wayfire" if WAYFIRE else "sway" if SWAY else "none"


# ── wayfire ────────────────────────────────────────────────────────────────

class WayfireError(RuntimeError):
    pass


def _wf(method, data=None, timeout=2.0):
    """One request over a fresh connection (Wayfire answers in order)."""
    path = os.environ["WAYFIRE_SOCKET"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        body = json.dumps({"method": method, "data": data or {}}).encode()
        s.sendall(struct.pack("<I", len(body)) + body)
        head = _recv(s, 4)
        (n,) = struct.unpack("<I", head)
        reply = _whole(json.loads(_recv(s, n)))
    if isinstance(reply, dict) and reply.get("result") == "error":
        raise WayfireError(reply.get("error", "error"))
    return reply


# Positions and sizes, which Wayfire 0.11 sends as decimals (1440.0) where
# 0.10 sent whole numbers. Everything here counts in whole pixels: range(),
# grim's "x,y wxh" and GTK sizes all refuse 1440.0.
_PIXELS = ("x", "y", "width", "height")


def _whole(obj):
    """Wayfire's reply with every position and size as a whole number."""
    if isinstance(obj, dict):
        return {k: (int(round(v)) if k in _PIXELS and isinstance(v, float) else _whole(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_whole(v) for v in obj]
    return obj


def _recv(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise WayfireError("wayfire closed the connection")
        buf += chunk
    return buf


def wf_watch(events=None):
    """Yield Wayfire events forever (blocking); for use on a thread."""
    path = os.environ["WAYFIRE_SOCKET"]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    body = json.dumps({"method": "window-rules/events/watch",
                       "data": {"events": events} if events else {}}).encode()
    s.sendall(struct.pack("<I", len(body)) + body)
    while True:
        (n,) = struct.unpack("<I", _recv(s, 4))
        msg = _whole(json.loads(_recv(s, n)))
        if "event" in msg:
            yield msg


def _sway(*args):
    try:
        out = subprocess.run(["swaymsg", "-r"] + list(args), capture_output=True,
                             text=True, timeout=3).stdout
        return json.loads(out) if out.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


# ── windows ────────────────────────────────────────────────────────────────

class Window(dict):
    """id, title, app_id, workspace (0-based), focused, minimized, geometry."""

    @property
    def label(self):
        return self.get("title") or self.get("app_id") or "window"


def windows():
    """Every app window, most recently used first."""
    out = []
    if WAYFIRE:
        try:
            views = _wf("window-rules/list-views")
        except (OSError, WayfireError):
            return []
        outs = {o["id"]: o for o in _wf_outputs()}
        for v in views:
            if v.get("role") != "toplevel" or not v.get("mapped") or v.get("layer") not in ("workspace", None):
                continue
            o = outs.get(v.get("output-id"))
            ws = _wf_view_workspace(v, o)
            out.append(Window(id=v["id"], title=v.get("title", ""), app_id=v.get("app-id", ""),
                              workspace=ws, focused=bool(v.get("activated")),
                              minimized=bool(v.get("minimized")), geometry=v.get("geometry"),
                              ts=v.get("last-focus-timestamp", 0)))
        out.sort(key=lambda w: -w.get("ts", 0))
    elif SWAY:
        tree = _sway("-t", "get_tree") or {}
        names = [w["name"] for w in (_sway("-t", "get_workspaces") or [])]

        def walk(node, ws=None):
            if node.get("type") == "workspace":
                ws = node.get("name")
            for c in node.get("nodes", []) + node.get("floating_nodes", []):
                walk(c, ws)
            if node.get("type") in ("con", "floating_con") and node.get("pid") and ws != "__i3_scratch":
                out.append(Window(id=node["id"], title=node.get("name") or "",
                                  app_id=node.get("app_id") or (node.get("window_properties") or {}).get("class", ""),
                                  workspace=names.index(ws) if ws in names else 0,
                                  focused=node.get("focused", False), minimized=False,
                                  geometry=node.get("rect"), ts=0))
        walk(tree)
        out.sort(key=lambda w: not w["focused"])
    return out


def window_rects():
    """The windows you can see right now, as (x, y, width, height) in screen
    coordinates (the same ones grim takes), with whether each is focused.
    The most recently used come first, so the one on top wins a tie."""
    found = []
    if WAYFIRE:
        try:
            views = _wf("window-rules/list-views")
        except (OSError, WayfireError):
            return []
        outs = {o["id"]: o.get("geometry") or {} for o in _wf_outputs()}
        for v in sorted(views, key=lambda v: -v.get("last-focus-timestamp", 0)):
            og = outs.get(v.get("output-id"))
            if v.get("role") != "toplevel" or not v.get("mapped") or v.get("minimized") or not og:
                continue
            g = v.get("geometry") or {}
            r = (g.get("x", 0), g.get("y", 0), g.get("width", 0), g.get("height", 0))
            # Positions are relative to the desktop on screen: anything
            # outside it is on another desktop.
            if _overlap(r, (0, 0, og.get("width", 0), og.get("height", 0))):
                found.append(((r[0] + og.get("x", 0), r[1] + og.get("y", 0), r[2], r[3]),
                              bool(v.get("activated"))))
    elif SWAY:
        tree = _sway("-t", "get_tree") or {}
        shown = {w["name"] for w in (_sway("-t", "get_workspaces") or []) if w.get("visible")}

        def walk(node, ws=None, floating=False):
            if node.get("type") == "workspace":
                ws = node.get("name")
            for c in node.get("floating_nodes", []):
                walk(c, ws, True)
            for c in node.get("nodes", []):
                walk(c, ws, floating)
            if node.get("pid") and ws in shown:
                r = node.get("rect") or {}
                found.append(((r.get("x", 0), r.get("y", 0), r.get("width", 0), r.get("height", 0)),
                              bool(node.get("focused")), floating))
        walk(tree)
        found.sort(key=lambda f: (not f[2], not f[1]))  # floating ones sit on top
        found = [f[:2] for f in found]
    return found


def wf_views():
    """Every view Wayfire knows about, as it describes them."""
    return _wf("window-rules/list-views")


def _wf_outputs():
    try:
        return _wf("window-rules/list-outputs")
    except (OSError, WayfireError):
        return []


def _wf_view_workspace(view, output):
    """Which column of the grid a view sits in (Wayfire gives geometry
    relative to the current workspace)."""
    if not output:
        return 0
    g, og = view.get("geometry") or {}, output.get("geometry") or {}
    w = og.get("width") or 1
    cur = (output.get("workspace") or {}).get("x", 0)
    cx = (g.get("x", 0) + g.get("width", 0) / 2)
    return max(0, cur + int(cx // w))


def focused():
    for w in windows():
        if w.get("focused"):
            return w
    return None


def focus(win_id):
    if WAYFIRE:
        _try(lambda: _wf("window-rules/focus-view", {"id": win_id}))
        for w in windows():
            if w["id"] == win_id and w.get("minimized"):
                _try(lambda: _wf("wm-actions/set-minimized", {"view_id": win_id, "state": False}))
    elif SWAY:
        _sway("[con_id=%d] focus" % win_id)


def close(win_id):
    if WAYFIRE:
        _try(lambda: _wf("window-rules/close-view", {"id": win_id}))
    elif SWAY:
        _sway("[con_id=%d] kill" % win_id)


def minimize(win_id, state=True):
    if WAYFIRE:
        _try(lambda: _wf("wm-actions/set-minimized", {"view_id": win_id, "state": state}))
    elif SWAY:
        _sway("[con_id=%d] move scratchpad" % win_id if state else "[con_id=%d] scratchpad show" % win_id)


def set_always_on_top(win_id, state=True):
    if WAYFIRE:
        _try(lambda: _wf("wm-actions/set-always-on-top", {"view_id": win_id, "state": state}))
    elif SWAY:
        _sway("[con_id=%d] floating enable, sticky %s" % (win_id, "enable" if state else "disable"))


def fullscreen(win_id, state=True):
    if WAYFIRE:
        _try(lambda: _wf("wm-actions/set-fullscreen", {"view_id": win_id, "state": state}))
    elif SWAY:
        _sway("[con_id=%d] fullscreen %s" % (win_id, "enable" if state else "disable"))


GRID_SLOTS = {"left": "l", "right": "r", "top-left": "tl", "top-right": "tr",
              "bottom-left": "bl", "bottom-right": "br", "max": "c"}
# wlroots edge bits: top 1, bottom 2, left 4, right 8.
HALF_EDGES = {7: "left", 11: "right"}
OPPOSITE = {"left": "right", "right": "left"}


def snap(win_id, zone):
    """zone: left, right, top-left, top-right, bottom-left, bottom-right, max."""
    if WAYFIRE:
        # Through the grid plugin, so the window is properly tiled (and
        # animates), and the desktops daemon hears about it and pairs it.
        _try(lambda: _wf("grid/slot_" + GRID_SLOTS[zone], {"view_id": win_id}))
    elif SWAY:
        side = "left" if "left" in zone else "right" if "right" in zone else None
        if zone == "max":
            _sway("[con_id=%d] fullscreen enable" % win_id)
        elif side:
            _sway("[con_id=%d] focus" % win_id)
            subprocess.run(["tube-snap", side], check=False)


def pair(view):
    """A window was just snapped to half the screen: put the window you used
    before it on the same desktop into the other half, so the two share the
    screen. `view` is Wayfire's description of the snapped window."""
    side = HALF_EDGES.get(view.get("tiled-edges"))
    if not WAYFIRE or not side:
        return None
    try:
        views = _wf("window-rules/list-views")
    except (OSError, WayfireError):
        return None
    outs = {o["id"]: o for o in _wf_outputs()}
    out = outs.get(view.get("output-id"))
    here = _wf_view_workspace(view, out)
    others = [v for v in views
              if v.get("id") != view.get("id") and v.get("role") == "toplevel"
              and v.get("mapped") and v.get("parent", -1) == -1
              and v.get("layer") in ("workspace", None)
              and not v.get("minimized") and not v.get("fullscreen")
              and v.get("output-id") == view.get("output-id")
              and _wf_view_workspace(v, out) == here]
    if not others:
        return None
    partner = max(others, key=lambda v: v.get("last-focus-timestamp", 0))
    if HALF_EDGES.get(partner.get("tiled-edges")) == OPPOSITE[side]:
        return None  # already sharing
    snap(partner["id"], OPPOSITE[side])
    return partner["id"]


# ── new windows find room ──────────────────────────────────────────────────

# Where each window goes when a desktop has 1, 2, 3 or 4 of them.
LAYOUTS = {1: ["max"], 2: ["left", "right"], 3: ["left", "top-right", "bottom-right"],
           4: ["top-left", "top-right", "bottom-left", "bottom-right"]}
# Free space a new window may take, best first.
FREE_ORDER = ["right", "left", "bottom-right", "top-right", "bottom-left", "top-left"]
MOST_PER_DESKTOP = 4


def zone_rect(zone, area):
    """(x, y, w, h) of a zone inside a work area {x, y, width, height}."""
    x, y, w, h = area["x"], area["y"], area["width"], area["height"]
    hw, hh = w // 2, h // 2
    return {
        "max": (x, y, w, h),
        "left": (x, y, hw, h), "right": (x + hw, y, w - hw, h),
        "top-left": (x, y, hw, hh), "top-right": (x + hw, y, w - hw, hh),
        "bottom-left": (x, y + hh, hw, h - hh), "bottom-right": (x + hw, y + hh, w - hw, h - hh),
    }[zone]


def _rect(v, out):
    """A view's rectangle, folded onto the output (Wayfire gives positions
    relative to the desktop on screen)."""
    g = v.get("geometry") or {}
    ow = ((out or {}).get("geometry") or {}).get("width") or 1
    return (g.get("x", 0) % ow, g.get("y", 0), g.get("width", 0), g.get("height", 0))


def _overlap(a, b):
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def _centre(r):
    return (r[0] + r[2] / 2, r[1] + r[3] / 2)


# Windows that are really dialogs, though Wayfire can't tell: the file
# picker apps show through the desktop portal, password prompts and the like.
# They open centred over everything and are never tiled.
FLOATING_APPS = {"zenity", "yad", "gcr-prompter", "org.gnome.keyring.systemprompter",
                 "blueman-sendto", "nm-openconnect-auth-dialog", "org.kde.polkit-kde-authentication-agent-1"}
FLOATING_PARTS = ("xdg-desktop-portal", "impl.portal", "pinentry", "polkit", "policykit")


def floating(v):
    app = (v.get("app-id") or "").lower()
    return app in FLOATING_APPS or any(p in app for p in FLOATING_PARTS)


def _tileable(v):
    mn, mx = v.get("min-size") or {}, v.get("max-size") or {}
    fixed = mx.get("width") and mx.get("width") == mn.get("width") and mx.get("height") == mn.get("height")
    return (v.get("role") == "toplevel" and v.get("type", "toplevel") == "toplevel"
            and v.get("mapped") and v.get("parent", -1) == -1
            and v.get("layer") in ("workspace", None)
            and not v.get("minimized") and not v.get("fullscreen") and not fixed
            and not floating(v))


def arrange(view, views, out):
    """Where everything on a desktop should go now that `view` has opened.

    Returns ([(window id, zone), ...], overflow). The new window takes free
    space if there is a half or a quarter nobody is using; otherwise the
    desktop is retiled, up to four windows, so nothing is covered. A fifth
    window sets overflow, meaning it should go to a desktop of its own."""
    area = out.get("workarea") or out.get("geometry")
    here = _wf_view_workspace(view, out)
    others = [v for v in views if v.get("id") != view.get("id") and _tileable(v)
              and v.get("output-id") == view.get("output-id")
              and _wf_view_workspace(v, out) == here]
    if not others:
        # Alone: fill the screen.
        if _same(_rect(view, out), zone_rect("max", area)):
            return [], False
        return [(view["id"], "max")], False
    rects = {v["id"]: _rect(v, out) for v in others}
    for zone in FREE_ORDER:
        z = zone_rect(zone, area)
        if all(_overlap(z, r) < 0.1 * z[2] * z[3] for r in rects.values()):
            return [(view["id"], zone)], False
    if len(others) >= MOST_PER_DESKTOP:
        return [], True
    slots = list(LAYOUTS[len(others) + 1])
    # Each window goes to the nearest place; on a tie, the earlier one, so
    # the newcomer ends up last (to the right and below).
    pairs = sorted(((_dist(_centre(rects[v["id"]]), _centre(zone_rect(z, area))), n, v["id"], z)
                    for v in others for n, z in enumerate(slots)))
    plan, placed = [], set()
    for _d, _n, vid, z in pairs:
        if vid in placed or z not in slots:
            continue
        placed.add(vid)
        slots.remove(z)
        if not _same(rects[vid], zone_rect(z, area)):
            plan.append((vid, z))
    plan.append((view["id"], slots[0]))
    return plan, False


def _dist(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _same(a, b, slack=8):
    return all(abs(p - q) <= slack for p, q in zip(a, b))


def _view(views, win_id):
    return next((v for v in views if v.get("id") == win_id), None)


def place(win_id):
    """Give a window that has just opened room of its own (Wayfire).
    Returns [(window id, zone)] for what was moved, to check on later."""
    if not WAYFIRE:
        return []
    try:
        views = _wf("window-rules/list-views")
    except (OSError, WayfireError):
        return []
    view = _view(views, win_id)   # as it is now, not as it was when it opened
    if not view or not _tileable(view):
        return []
    out = {o["id"]: o for o in _wf_outputs()}.get(view.get("output-id"))
    if not out:
        return []
    plan, overflow = arrange(view, views, out)
    if overflow:
        used = {_wf_view_workspace(v, out) for v in views if _tileable(v) and v.get("id") != win_id}
        free = next(i for i in range(len(used) + 1) if i not in used)
        send_to_pivot(win_id, free)
        go_to_pivot(free)
        return [(win_id, "max")]
    for vid, zone in plan:
        snap(vid, zone)
    return plan


def settle(plan):
    """Some apps resize themselves just after they open, undoing their
    place: put back anything that isn't where it was sent. Returns the ids
    moved again."""
    if not WAYFIRE or not plan:
        return []
    try:
        views = _wf("window-rules/list-views")
    except (OSError, WayfireError):
        return []
    outs = {o["id"]: o for o in _wf_outputs()}
    again = []
    for vid, zone in plan:
        v = _view(views, vid)
        if not v or not _tileable(v):
            continue
        out = outs.get(v.get("output-id")) or {}
        area = out.get("workarea") or out.get("geometry")
        if area and not _same(_rect(v, out), zone_rect(zone, area)):
            snap(vid, zone)
            again.append(vid)
    return again


# ── pivots (workspaces) ────────────────────────────────────────────────────

def _focused_output():
    if WAYFIRE:
        try:
            return _wf("window-rules/get-focused-output").get("info")
        except (OSError, WayfireError):
            return None
    return None


def current_pivot():
    """0-based index of the pivot on screen."""
    if WAYFIRE:
        o = _focused_output() or {}
        return (o.get("workspace") or {}).get("x", 0)
    if SWAY:
        for i, w in enumerate(_sway("-t", "get_workspaces") or []):
            if w.get("focused"):
                return i
    return 0


def go_to_pivot(i, names=None):
    if WAYFIRE:
        o = _focused_output()
        if o:
            _try(lambda: _wf("vswitch/set-workspace", {"x": i, "y": 0, "output-id": o["id"]}))
    elif SWAY:
        names = names or []
        _sway("workspace", "%d:%s" % (i + 1, names[i]) if i < len(names) else str(i + 1))


def send_to_pivot(win_id, i, names=None):
    if WAYFIRE:
        o = _focused_output()
        if o:
            _try(lambda: _wf("vswitch/send-view", {"x": i, "y": 0, "view-id": win_id}))
    elif SWAY:
        names = names or []
        target = "%d:%s" % (i + 1, names[i]) if i < len(names) else str(i + 1)
        _sway("[con_id=%d] move container to workspace %s" % (win_id, target))


def desktop_names():
    """The names on the bar, left to right."""
    if WAYFIRE:
        try:
            from . import desktops
            return desktops.names()
        except ImportError:
            pass
    if SWAY:
        return [w["name"].split(":", 1)[-1] for w in (_sway("-t", "get_workspaces") or [])]
    return ["home"]


def windows_on_pivot(i):
    return [w for w in windows() if w.get("workspace") == i]


def shift_pivots_after_removal(removed):
    """Before a pivot is removed: its windows go to the pivot on its left (or
    the next one), and windows on later pivots move one to the left, so every
    window stays with its pivot's name."""
    if not WAYFIRE:
        return
    target = max(0, removed - 1)
    for w in windows():
        ws = w.get("workspace", 0)
        if ws == removed:
            _try(lambda w=w: _wf("vswitch/send-view", {"x": target, "y": 0, "view-id": w["id"]}))
        elif ws > removed:
            _try(lambda w=w: _wf("vswitch/send-view", {"x": ws - 1, "y": 0, "view-id": w["id"]}))
    if current_pivot() >= removed and removed > 0:
        go_to_pivot(current_pivot() - 1)


def _try(fn):
    try:
        return fn()
    except (OSError, WayfireError, KeyError):
        return None


def wf_version():
    if not WAYFIRE:
        return None
    try:
        return _wf("wayfire/configuration").get("api-version")
    except (OSError, WayfireError):
        return None
