# tubewm Metro for Zed

```sh
apps/install.sh --only zed              # or just apps/install.sh for every app found
apps/install.sh --only zed --accent cobalt --light
apps/install.sh --only zed --uninstall
```

Writes both variants to `~/.config/zed/themes/tubewm.json`. If your `settings.json` has no `"theme"` key, it gets one that follows the system (`tubewm Metro Dark` / `tubewm Metro Light`). If it does, pick the theme with Ctrl+K Ctrl+T.

The settings file is JSON with comments. When the key is added, the file is rewritten and comments are lost; a timestamped `.bak` next to it keeps the original.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
