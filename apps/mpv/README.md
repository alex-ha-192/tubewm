# tubewm Metro for mpv

```sh
apps/install.sh --only mpv              # or just apps/install.sh for every app found
apps/install.sh --only mpv --accent cobalt --light
apps/install.sh --only mpv --uninstall
```

Writes `~/.config/mpv/tubewm.conf` and adds `include="~~/tubewm.conf"` to `mpv.conf`. The OSD and subtitles use Open Sans with no shadows, and the built-in controller becomes a flat bottom bar with an accent seek line. The seek bar colour options need mpv 0.39 or newer; older versions ignore them.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
