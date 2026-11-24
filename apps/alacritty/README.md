# tubewm Metro for Alacritty

```sh
apps/install.sh --only alacritty              # or just apps/install.sh for every app found
apps/install.sh --only alacritty --accent cobalt --light
apps/install.sh --only alacritty --uninstall
```

Writes `~/.config/alacritty/tubewm.toml`. If you have no `alacritty.toml` yet, the installer creates one that imports it. If you do have one, nothing in it is touched. Add the file to your import list yourself, once:

```toml
[general]
import = ["~/.config/alacritty/tubewm.toml"]
```

Alacritty reloads live. The theme also sets no window decorations, a 20px padding and a solid beam cursor.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
