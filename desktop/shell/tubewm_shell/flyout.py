"""tube-flyout: the panel that drops down when you click something on the bar.

    tube-flyout volume | power | network | calendar | notifications | window

Each panel is one of the applets (applets.py) under a lowercase heading.
Clicking the same thing again, clicking anywhere else, or Escape closes it.
"""

import argparse
import sys

from . import common

from gi.repository import Gtk  # noqa: E402

# kind: (heading, side of the screen it hangs from)
PANELS = {
    "volume": ("volume", "right"),
    "power": ("power", "right"),
    "network": ("network", "right"),
    "calendar": ("calendar", "right"),
    "notifications": ("notifications", "right"),
    "window": ("window", "left"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tube-flyout", description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=sorted(PANELS))
    a = parser.parse_args(argv)

    # One flyout at a time; asking again for any of them closes the open one.
    if not common.toggle_instance("flyout"):
        return 0

    from . import applets
    heading, side = PANELS[a.kind]
    common.apply_css()
    win, box = common.popup_window("flyout", side, 12 if side == "right" else 68)
    box.get_style_context().add_class("tube-flyout")

    applet = applets.build(a.kind, {})
    title = Gtk.Label(label=heading, xalign=0)
    title.get_style_context().add_class("tube-flyout-title")
    box.pack_start(title, False, False, 0)
    applet.closes = Gtk.main_quit
    box.pack_start(applet, True, True, 0)

    win.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
