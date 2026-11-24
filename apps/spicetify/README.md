# tubewm Metro for Spotify (spicetify)

```sh
apps/install.sh --only spicetify              # or just apps/install.sh for every app found
apps/install.sh --only spicetify --accent cobalt --light
apps/install.sh --only spicetify --uninstall
```

Needs [spicetify](https://spicetify.app) installed. Writes the `tubewm` theme (`color.ini` with `dark` and `light` schemes, plus `user.css`) into spicetify's Themes folder, selects it and runs `spicetify apply`. If spicetify has never been set up on this machine, run `spicetify backup apply` once yourself.

This is the most Zune-like of the set. Headings are huge and light, the gradient washes behind album headers are gone, cards are flat tiles, and the play button and progress line take the accent. `--uninstall` switches spicetify back to its default theme.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
