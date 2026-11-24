# tubewm Metro for zathura

```sh
apps/install.sh --only zathura              # or just apps/install.sh for every app found
apps/install.sh --only zathura --accent cobalt --light
apps/install.sh --only zathura --uninstall
```

Writes `~/.config/zathura/tubewm` and adds `include tubewm` to `zathurarc`. The status bar is accent, the UI font is Open Sans, and search highlights use the accent. Toggle recolouring of the page itself with Ctrl+R.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
