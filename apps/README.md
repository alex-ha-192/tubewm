# tubewm app themes

Metro / Zune styling for **VSCode** (and VSCodium, Code - OSS) and **Vivaldi**:
black canvas, white type, one accent colour, square corners, lowercase pivot
headers. Both themes are generated from the shared palette in `palette/`, so
they use the same accent as the Sway desktop and follow it when it changes.

Requirements: `python3` (standard library only) and a POSIX shell. Fonts are
open: [Open Sans](https://fonts.google.com/specimen/Open+Sans) for UI text and
[JetBrains Mono](https://www.jetbrains.com/lp/mono/) for code. Install them
from your distro (for example `ttf-opensans ttf-jetbrains-mono` on Arch,
`fonts-open-sans fonts-jetbrains-mono` on Debian/Ubuntu).

## VSCode

```sh
apps/vscode/install.sh                    # current desktop accent, dark theme
apps/vscode/install.sh --accent cobalt    # any name from palette/accents, or '#RRGGBB'
apps/vscode/install.sh --light            # make the light variant active
apps/vscode/install.sh --editor codium    # limit to one editor (default: every one found)
apps/vscode/install.sh --no-settings      # theme only
apps/vscode/install.sh --ui-css           # also hook up metro-ui.css (see below)
apps/vscode/install.sh --uninstall
```

What it does:

1. Generates the **tubewm Metro Dark** and **tubewm Metro Light** colour
   themes for the chosen accent (`build.py`), packs them as a `.vsix`, and
   installs it with the editor's CLI. With no CLI on `PATH` it copies the
   extension into `~/.vscode/extensions` or `~/.vscode-oss/extensions`.
2. Merges `settings.jsonc` into your user `settings.json`: the theme, open
   fonts, no minimap, smooth scrolling and caret motion, hidden layout and
   command-centre chrome. **Keys you have already set are left alone**; only
   the three colour-theme keys are always written. Edit `settings.jsonc`
   first if you want fewer changes.

The colour theme handles every colour. What a theme cannot do (UI font,
square corners on every widget, lowercase pivot-style tabs, the short
"turnstile" animation on menus and the command palette) is in
`metro-ui.css`. To use it, install the *Custom CSS and JS Loader* extension
(`be5invis.vscode-custom-css`), run `install.sh --ui-css`, then run
**Enable Custom CSS and JS** from the command palette. VSCode then reports
the installation as "corrupt"; that warning is expected with any workbench CSS
patch and is harmless.

## Vivaldi

```sh
apps/vivaldi/install.sh                   # current desktop accent
apps/vivaldi/install.sh --accent teal --light
apps/vivaldi/install.sh --profile ~/.config/vivaldi/"Profile 1"
apps/vivaldi/install.sh --uninstall
```

It writes everything to `~/.local/share/tubewm/vivaldi/`:

- `themes/tubewm-metro-{dark,light}.zip`: importable themes. The accent is
  Vivaldi's *Highlight* colour; the tab bar stays black, with 0px corner
  radius and solid scrollbars.
- `css/tubewm-metro.css`: UI modifications. Tabs become a lowercase pivot
  row with an accent underline on the active tab. The address bar is a flat
  field with an accent border on focus. Panels get big light headers, the V
  button becomes a solid accent square, speed dials become flat accent tiles
  with bottom-left labels, and menus get a short turnstile animation.

**With Vivaldi closed**, the script adds both themes to the profile's
`Preferences`, makes one active, and points *Custom UI Modifications* at the
CSS folder. It backs up `Preferences` first. **With Vivaldi open** it changes
nothing in the profile, because Vivaldi would overwrite the file on exit, and
prints the manual steps instead.

One step is always manual, once: open `vivaldi://experiments`, tick **Allow
for using CSS modifications**, and restart Vivaldi.

Vivaldi renames its internal UI classes now and then. Every rule in the CSS
is cosmetic, so a rule that stops matching just stops applying. The theme
colours work with or without the stylesheet.

## Accent changes

Both installers drop a hook in `~/.config/tubewm/accent.d/` (`50-vscode`,
`50-vivaldi`). The desktop's `tube-accent` runs those hooks after changing
the accent, so both apps rebuild for the new colour. VSCode needs a window
reload to pick it up. Vivaldi picks up the CSS on restart, and the theme
colours the next time the hook runs with Vivaldi closed. Pass `--no-hook` to
opt out.

Accent precedence is the same as `palette/tubewm-colors.sh`: `--accent`, then
`$TUBEWM_ACCENT`, then `~/.config/tubewm/accent`, then the palette default
(magenta).

## Undoing it

`--uninstall` removes the extension or themes, the CSS folder setting and the
hooks. In `settings.json` it restores the value each key had before the first
install, or removes the key if there was none. Keys you changed after
installing are left as you set them. Timestamped `.bak` copies of
`settings.json` and `Preferences` sit next to the originals.

## Layout

```
apps/
  lib/palette.py     reads palette/ (no shell execution), colour helpers
  lib/jsonc.py       comment-tolerant settings.json merge / restore
  vscode/            build.py, install.sh, settings.jsonc, metro-ui.css
  vivaldi/           build.py, install.sh, prefs.py, metro.css.in
  tests/             python3 -m pytest apps/tests
```
