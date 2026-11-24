# tubewm Metro for Obsidian

```sh
apps/install.sh --only obsidian              # or just apps/install.sh for every app found
apps/install.sh --only obsidian --accent cobalt --light
apps/install.sh --only obsidian --uninstall
```

Finds your vaults in `~/.config/obsidian/obsidian.json` (the Flatpak too) and writes `.obsidian/themes/tubewm Metro/` into each one. A vault with no theme chosen is switched to it; for the others, pick **tubewm Metro** in Settings, Appearance, Themes.

It works in dark and light mode. Corners are square, there are no shadows, the first heading is big and light like a Zune page title, links and the active tab underline take the accent, and the side panels are black or white rather than grey slabs.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
