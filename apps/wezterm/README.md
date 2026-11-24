# tubewm Metro for WezTerm

```sh
apps/install.sh --only wezterm              # or just apps/install.sh for every app found
apps/install.sh --only wezterm --accent cobalt --light
apps/install.sh --only wezterm --uninstall
```

Writes the colour scheme to `~/.config/wezterm/colors/tubewm.toml`. WezTerm loads schemes from that folder by itself, so select it once in `wezterm.lua`:

```lua
config.color_scheme = "tubewm Metro"
config.use_fancy_tab_bar = false   -- the flat pivot-style tab bar
config.window_decorations = "NONE"
config.window_padding = { left = 20, right = 20, top = 20, bottom = 20 }
```

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
