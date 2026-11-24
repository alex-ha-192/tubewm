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
        reply = json.loads(_recv(s, n))
    if isinstance(reply, dict) and reply.get("result") == "error":
        raise WayfireError(reply.get("error", "error"))
    return reply


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
        msg = json.loads(_recv(s, n))
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


def snap(win_id, zone):
    """zone: left, right, top-left, top-right, bottom-left, bottom-right, max."""
    if WAYFIRE:
        o = _focused_output()
        if not o:
            return
        a = o.get("workarea") or o.get("geometry")
        x, y, w, h = a["x"], a["y"], a["width"], a["height"]
        half_w, half_h = w // 2, h // 2
        geo = {
            "left": (x, y, half_w, h), "right": (x + half_w, y, w - half_w, h),
            "top-left": (x, y, half_w, half_h), "top-right": (x + half_w, y, w - half_w, half_h),
            "bottom-left": (x, y + half_h, half_w, h - half_h),
            "bottom-right": (x + half_w, y + half_h, w - half_w, h - half_h),
            "max": (x, y, w, h),
        }[zone]
        _try(lambda: _wf("window-rules/configure-view", {
            "id": win_id, "geometry": dict(zip(("x", "y", "width", "height"), geo))}))
    elif SWAY:
        side = "left" if "left" in zone else "right" if "right" in zone else None
        if zone == "max":
            _sway("[con_id=%d] fullscreen enable" % win_id)
        elif side:
            _sway("[con_id=%d] focus" % win_id)
            subprocess.run(["tube-snap", side], check=False)


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
