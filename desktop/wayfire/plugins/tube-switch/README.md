# tube-switch

Wayfire's own `fast-switcher` plugin (MIT) with minimised windows in the
list. Hold Alt and tap Tab (Shift+Tab to go back) to go through the windows
on the current desktop, most recently used first; the others are see-through
while you choose. A minimised window is drawn in its place while you hold
Alt. Let go on it and it is restored and focused; let go on another and it
stays minimised. Options live in `[tube-switch]` and match
`[fast-switcher]`'s.

One copy builds against Wayfire 0.10 and 0.11: the switcher only uses API
the two share. Changed from upstream: the views are collected without
`WSET_EXCLUDE_MINIMIZED`, minimised ones are shown while the switcher is
open (as Wayfire's `switcher` plugin does) and hidden again when it closes,
the option section name, and `tube-switch.xml`. It also leaves show-desktop
first, as fast-switcher does from 0.11. See `LICENSE` for the upstream
notice.
