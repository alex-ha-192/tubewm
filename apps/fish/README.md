# tubewm Metro for fish shell

```sh
apps/install.sh --only fish              # or just apps/install.sh for every app found
apps/install.sh --only fish --accent cobalt --light
apps/install.sh --only fish --uninstall
```

Writes `~/.config/fish/conf.d/tubewm.fish`, which fish runs at start-up. It sets session colours with `set -g`, so your own universal colours are not changed and come back if you uninstall.

Commands are bold white, keywords take the accent, strings and comments follow the editor themes, the current folder is in the accent, and the completion pager marks the selected entry with the accent. Run `exec fish` to see it in the shell you are in.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
