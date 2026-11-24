# tubewm app themes

Metro / Zune styling for the apps you live in: black canvas, white type, one
accent colour, square corners, lowercase pivot headers. Every theme is
generated from the shared palette in `palette/`, so it uses the same accent as
the Sway desktop and follows it when you change it with `tube-accent`.

The desktop itself (Sway, Waybar, foot, fuzzel, mako, GTK, the lock screen)
is themed by `desktop/`. This folder covers the applications.

## Everything at once

```sh
apps/install.sh                      # theme every supported app that is installed
apps/install.sh --list               # what is supported, found and themed
apps/install.sh --accent cobalt      # any name from palette/accents, or '#RRGGBB'
apps/install.sh --light              # light polarity
apps/install.sh --only kitty,neovim  # just these
apps/install.sh --skip firefox       # everything found but these
apps/install.sh --uninstall          # undo all of it
```

| App | What changes | Notes |
| --- | --- | --- |
| [VSCode / VSCodium](#vscode) | colour themes, settings, optional workbench CSS | `apps/vscode` |
| [Vivaldi](#vivaldi) | themes, UI CSS mods, tile-style speed dials | `apps/vivaldi` |
| [Firefox](firefox/README.md) | pivot tabs, flat accent-focus URL bar, square menus, new-tab tiles | restart Firefox |
| [kitty](kitty/README.md) | colours, padding, accent focus border, lowercase tabs | reloads live |
| [Alacritty](alacritty/README.md) | colours, no decorations, padding | one import line if you already have a config |
| [WezTerm](wezterm/README.md) | colour scheme with a flat tab bar | select it in `wezterm.lua` |
| [tmux](tmux/README.md) | accent status strip, accent pane border | reloads live |
| [Neovim](neovim/README.md) | full colorscheme (treesitter, LSP, telescope) | `:colorscheme tubewm` |
| [Helix](helix/README.md) | theme with accent status line | set automatically if you had none |
| [Zed](zed/README.md) | dark + light themes following the system | set automatically if you had none |
| [Qt apps](qt/README.md) | qt5ct / qt6ct palette on the Fusion style | needs `QT_QPA_PLATFORMTHEME` |
| [Spotify](spicetify/README.md) | Zune-style headings, flat tiles (via spicetify) | needs spicetify |
| [btop](btop/README.md) | black canvas, accent graph ramps | quit btop first |
| [zathura](zathura/README.md) | accent status bar, Open Sans | |
| [mpv](mpv/README.md) | Open Sans OSD, flat bar with accent seek line | |

Each app's folder has a short README with exactly what is written where.
Your own config files are only ever edited to add one include/import line or
a theme name, and only when that is unambiguous. Otherwise the installer
prints the one line to add. Everything it changes is recorded, and every file
it modifies is backed up as `<file>.tubewm-<date>.bak` first.

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

The installers drop hooks in `~/.config/tubewm/accent.d/` (`40-apps`,
`50-vscode`, `50-vivaldi`). The desktop's `tube-accent` runs those hooks after changing
the accent, so every themed app rebuilds for the new colour. VSCode needs a window
reload to pick it up. Vivaldi picks up the CSS on restart, and the theme
colours the next time the hook runs with Vivaldi closed. Pass `--no-hook` to
opt out.

Accent precedence is the same as `palette/tubewm-colors.sh`: `--accent`, then
`$TUBEWM_ACCENT`, then `~/.config/tubewm/accent`, then the palette default
(magenta).

## Undoing it

`--uninstall` removes the generated files (except any you edited), the lines
it added to your configs, the extension or themes, the CSS folder setting and
the hooks. In `settings.json` it restores the value each key had before the first
install, or removes the key if there was none. Keys you changed after
installing are left as you set them. Timestamped `.bak` copies of
`settings.json` and `Preferences` sit next to the originals.

## Layout

```
apps/
  install.sh         themes everything found (calls the per-app installers)
  lib/palette.py     reads palette/ (no shell execution), colour helpers
  lib/tokens.py      palette -> @TOKEN@ values (ANSI, syntax, ...) + template renderer
  lib/appthemes.py   the app catalogue, installer and exact-undo state
  lib/jsonc.py       comment-tolerant settings.json merge / restore
  <app>/             one folder per app: .in templates and a README
  vscode/            build.py, install.sh, settings.jsonc, metro-ui.css
  vivaldi/           build.py, install.sh, prefs.py, metro.css.in
  tests/             python3 -m pytest apps/tests
```
