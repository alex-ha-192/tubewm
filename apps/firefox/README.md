# tubewm Metro for Firefox

```sh
apps/install.sh --only firefox              # or just apps/install.sh for every app found
apps/install.sh --only firefox --accent cobalt --light
apps/install.sh --only firefox --uninstall
```

For the default profile of each Firefox install found (`~/.mozilla/firefox`, `~/.config/mozilla/firefox`, Flatpak):

- writes `chrome/tubewm-metro.css` (browser UI) and `chrome/tubewm-content.css` (new-tab page only; websites keep their own look),
- puts an `@import` line at the top of `userChrome.css` and `userContent.css`, keeping what you had below it,
- adds `toolkit.legacyUserProfileCustomizations.stylesheets = true` to `user.js`.

Restart Firefox afterwards. Tab titles are a readable grey; the active tab is white with an accent underline, and its close button is always visible. The URL bar is a flat field with an accent border when focused, menus and panels are square charcoal sheets with accent hover, and new-tab shortcuts are flat accent tiles. Firefox renames internals now and then; every rule is cosmetic and just stops applying if its target goes away.

Everything here is generated from `palette/`, so it follows `tube-accent`. Edit the `.in` template in this folder, not the generated file: generated files are rewritten on every accent change, and `--uninstall` keeps a generated file only if you changed it.
