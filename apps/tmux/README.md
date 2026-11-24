# tubewm Metro for tmux

```sh
apps/install.sh --only tmux              # or just apps/install.sh for every app found
apps/install.sh --only tmux --accent cobalt --light
apps/install.sh --only tmux --uninstall
```

Writes `~/.config/tmux/tubewm.conf` and adds a `source-file` line to `~/.config/tmux/tmux.conf` (or `~/.tmux.conf` if that is the one you use). Running servers are reloaded.

The status line is black with the session name and current window in the accent (`--status-bar accent` makes it a solid accent strip). The active pane gets an accent border, and menus and popups are flat charcoal sheets.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
