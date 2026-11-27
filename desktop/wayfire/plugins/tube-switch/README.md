# tube-switch

Wayfire's own `fast-switcher` plugin (MIT) with minimised windows in the
list. Hold Alt and press Tab to open it on the window you're in; each Tab
after that (Shift+Tab to go back) moves on through the windows on the
current desktop, most recently used first. The chosen window has the accent
title bar and the others are see-through; let go of Alt and the window with
the accent is the one that has the keyboard. Letting go of Shift alone
doesn't end it. A minimised window is drawn in its place while you hold
Alt. Let go on it and it is restored and focused; let go on another and it
stays minimised. Options live in `[tube-switch]` and match
`[fast-switcher]`'s.

One copy builds against Wayfire 0.10 and 0.11: the switcher only uses API
the two share. Changed from upstream: the views are collected without
`WSET_EXCLUDE_MINIMIZED`, minimised ones are shown while the switcher is
open (as Wayfire's `switcher` plugin does) and hidden again when it closes,
it opens on the focused window rather than the next one, only the
non-Shift modifiers end it, title bars are set from the seat's focus once it
closes, the option section name, and `tube-switch.xml`. It also leaves show-desktop
first, as fast-switcher does from 0.11. See `LICENSE` for the upstream
notice.
