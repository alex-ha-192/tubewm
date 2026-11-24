# tubewm Metro for Qt apps (qt5ct / qt6ct)

```sh
apps/install.sh --only qt              # or just apps/install.sh for every app found
apps/install.sh --only qt --accent cobalt --light
apps/install.sh --only qt --uninstall
```

For each of qt5ct and qt6ct that is installed: writes `colors/tubewm.conf` and sets `style=Fusion`, `custom_palette=true` and `color_scheme_path` in its config. Fusion with this palette gives flat, square widgets with accent selection, matching the GTK theme from `desktop/`.

Qt apps only read this when the session exports `QT_QPA_PLATFORMTHEME`: `qt5ct` for Qt 5 apps, `qt6ct` for Qt 6 apps. Add it to your Sway environment if it isn't there. KDE apps that force their own Breeze style ignore it.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
