# tubewm Metro for Ghostty

```sh
apps/install.sh --only ghostty              # or just apps/install.sh for every app found
apps/install.sh --only ghostty --accent cobalt --light
apps/install.sh --only ghostty --uninstall
```

Writes `~/.config/ghostty/themes/tubewm-metro`. If your `config` sets no theme, `theme = tubewm-metro` is added. If you already chose another theme it is left alone and the installer tells you.

You get the palette, an accent cursor, the selection in the soft accent and quiet charcoal split dividers. Fonts and padding are left to you.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
