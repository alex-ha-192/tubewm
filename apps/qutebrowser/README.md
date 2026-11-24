# tubewm Metro for qutebrowser

```sh
apps/install.sh --only qutebrowser              # or just apps/install.sh for every app found
apps/install.sh --only qutebrowser --accent cobalt --light
apps/install.sh --only qutebrowser --uninstall
```

Writes `~/.config/qutebrowser/tubewm.py` and adds `config.source("tubewm.py")` to `config.py`. If you had no `config.py`, it is created with `config.load_autoconfig()` first, so the settings you made in qutebrowser itself keep working.

Tab titles are a readable grey and the current tab is white on charcoal. The status bar is black, with the mode in the accent. Hints are solid accent squares, and the completion list highlights the match in the accent. The UI font is Open Sans.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
