# tubewm Metro for kitty

```sh
apps/install.sh --only kitty              # or just apps/install.sh for every app found
apps/install.sh --only kitty --accent cobalt --light
apps/install.sh --only kitty --uninstall
```

Writes `~/.config/kitty/tubewm.conf` and adds `include tubewm.conf` to the end of `kitty.conf`. Running kitty windows reload straight away (the installer sends kitty `SIGUSR1`).

You get the palette, the accent as selection and cursor, a 20px padding, a 2px accent border on the focused split, and tab titles in lowercase. Fonts are left to you. To use the shared ones, add `font_family JetBrains Mono` to `kitty.conf`.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
