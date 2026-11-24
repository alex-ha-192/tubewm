# tubewm Metro for btop

```sh
apps/install.sh --only btop              # or just apps/install.sh for every app found
apps/install.sh --only btop --accent cobalt --light
apps/install.sh --only btop --uninstall
```

Writes `~/.config/btop/themes/tubewm.theme` and sets `color_theme = "tubewm"` in `btop.conf`. Quit btop before installing, because btop rewrites `btop.conf` on exit. Every graph is drawn as one accent ramp on the black canvas.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
