# tubewm

A flat, typographic Wayland desktop inspired by the Metro / Zune design language:
big lowercase headers, pivots, solid colour tiles, an app list down the side,
and a single accent colour shared by the desktop and your apps.

![tubewm start screen](desktop/docs/screenshots/start.png)

* [`desktop/`](desktop/README.md): the Sway desktop. It has a pivots bar, a start screen with live tiles and an app list, charms, snapping, toasts, a lock screen, wallpapers and GTK styling.
* [`apps/`](apps/README.md): themes for VS Code, Vivaldi, Firefox, terminals, editors and more, all following the same accent.
* `palette/`: the shared colour palette that every part reads from.

All fonts are open (Open Sans, plus JetBrains Mono for code), and all glyphs
and artwork are drawn for this project.

## Installation

Everything installs into your home directory. Nothing is written system-wide
except the packages you ask for with `--deps`, and every config file that
would be replaced is backed up first.

### 1. What you need

* A Linux system that can run **Sway 1.9 or newer** (any GPU that works with
  wlroots; NVIDIA needs the proprietary driver and `sway --unsupported-gpu`).
* `git`, `python3` 3.11 or newer (3.9 and 3.10 work if you also install the
  `tomli` package), and `sudo` if you want the installer to fetch packages.
* A supported package manager for `--deps`: `apt` (Debian, Ubuntu), `pacman`
  (Arch), `dnf` (Fedora) or `zypper` (openSUSE). On anything else, install the
  packages listed in step 3 yourself.

### 2. Get the code

```sh
git clone https://github.com/alex-ha-192/tubewm
cd tubewm
```

### 3. Install the desktop

```sh
desktop/install.sh --deps
```

`--deps` installs these packages with your package manager (it asks for your
sudo password):

| | Packages |
|---|---|
| Compositor and session | sway, swaybg, swayidle, swaylock |
| Bar, launcher, toasts, terminal | waybar, fuzzel, mako, foot |
| Screenshots and clipboard | grim, slurp, wl-clipboard |
| Media keys and helpers | playerctl, brightnessctl, wireplumber, libnotify, jq |
| Start screen and charms | python3-gobject, pycairo, GTK 3, gtk-layer-shell |
| Font | Open Sans |

Optional extras it will use when present: **gtklock** (a nicer lock screen),
**NetworkManager** (`nmcli`, for the wi-fi toggle and network tile),
**pavucontrol** and **blueman** (opened from the settings flyout), and
**curl** (for the weather tile).

Then the installer:

1. copies the desktop to `~/.local/share/tubewm` and links the `tube-*`
   commands into `~/.local/bin`;
2. writes the Sway, Waybar, mako, fuzzel, foot, swaylock and GTK configs to
   `~/.config`, copying anything it replaces to
   `~/.config/tubewm/backup/<date>/`;
3. renders every colour for the current accent (magenta unless you pick one);
4. draws the default **fade** wallpaper from the accent;
5. sets GTK to dark, Open Sans and no title-bar buttons, unless you pass
   `--no-gsettings`.

Other options:

```sh
desktop/install.sh --accent teal      # pick the accent now (a name from palette/accents, or '#RRGGBB')
desktop/install.sh --no-gsettings     # leave GTK / GNOME settings alone
desktop/install.sh --help
```

### 4. Put `~/.local/bin` on your PATH (for typing commands)

The desktop itself finds its `tube-*` commands without this, but you'll want
them on your PATH to type `tube-accent` or `tube-wallpaper` in a terminal.
Most distros add `~/.local/bin` already; Arch and its derivatives (CachyOS,
EndeavourOS, Manjaro) don't. If yours doesn't, add this to `~/.profile` (or
`fish_add_path ~/.local/bin` if you use fish):

```sh
export PATH="$HOME/.local/bin:$PATH"
```

### 5. Start the desktop

* **From a display manager** (GDM, SDDM, LightDM, greetd): log out, choose
  **Sway** in the session menu, and log in.
* **From a text console:** log in on a TTY and run `sway`.
* **Already inside Sway:** run `swaymsg reload`.

Start opens when you log in. Press `Super+S` to bring it back, `Super+C` for charms and `Super+I` for settings.
The full key list is in [desktop/README.md](desktop/README.md#keys).

### 6. Theme your apps (optional)

`apps/install.sh` themes every supported app it finds installed, in the same
accent as the desktop. It needs only `python3`.

```sh
apps/install.sh --list               # which apps are supported, found and themed
apps/install.sh                      # theme everything it finds
apps/install.sh --only vscode,vivaldi
apps/install.sh --skip firefox
apps/install.sh --light              # light polarity instead of dark
```

Supported: **VS Code** (and VSCodium, Code - OSS), **Vivaldi**, Firefox,
kitty, Alacritty, WezTerm, tmux, Neovim, Helix, Zed, Qt apps (qt5ct / qt6ct),
Spotify (through spicetify), btop, zathura and mpv. Your own config files are
only ever given one include or theme line, and every file it changes is backed
up as `<file>.tubewm-<date>.bak`. A few apps need one line from you; the
installer prints it, and each app's notes are in [apps/README.md](apps/README.md).

JetBrains Mono is the code font. Install it from your distro
(`fonts-jetbrains-mono` on Debian/Ubuntu, `ttf-jetbrains-mono` on Arch,
`jetbrains-mono-fonts` on Fedora).

**VS Code.** The installer adds the **tubewm Metro Dark / Light** themes and
merges a few settings (fonts, no minimap, quieter chrome) into your
`settings.json`, keeping any setting you've already set yourself. Reload the
window to see it. For the full look (square corners everywhere, lowercase
pivot tabs, the UI font), also:

1. install the **Custom CSS and JS Loader** extension (`be5invis.vscode-custom-css`);
2. run `apps/vscode/install.sh --ui-css`;
3. in VS Code, run **Enable Custom CSS and JS** from the command palette and restart.

VS Code then says the installation is "corrupt". That is expected for any
workbench CSS patch and is harmless.

**Vivaldi.**

1. **Close Vivaldi first.** The installer can only write the profile while
   Vivaldi is closed. If it's open, nothing in the profile changes and the
   script prints manual import steps instead.
2. Run `apps/install.sh` (or just `apps/vivaldi/install.sh`; add
   `--profile ~/.config/vivaldi/"Profile 1"` for a profile other than Default).
   It adds the **tubewm Metro** themes, makes one active, and points
   *Custom UI Modifications* at the tubewm stylesheet.
3. **One-time manual step:** start Vivaldi, open `vivaldi://experiments`, tick
   **Allow for using CSS modifications**, and restart Vivaldi. Without this the
   theme colours still apply, but the pivot tabs, flat address bar and
   tile-style speed dials don't.

The app themes register hooks in `~/.config/tubewm/accent.d/`, so they follow
the desktop when you change the accent (pass `--no-hook` to opt out).

## Everyday use

**Change the accent** everywhere at once:

```sh
tube-accent list
tube-accent cobalt          # or '#1BA1E2', or random
```

or click a swatch in the settings flyout (`Super+I`). The wallpaper and the
themed apps follow.

**Change the wallpaper:** pick one in the settings flyout, or

```sh
tube-wallpaper list
tube-wallpaper bands
tube-wallpaper off          # back to the plain backdrop
```

To use your own picture, run `tube-wallpaper off` and put
`output * bg ~/Pictures/wall.jpg fill` in a file in `~/.config/sway/config.d/`.

**Edit start:** right-click a tile (or long-press) to resize, recolour, set it
up or unpin it; drag tiles to move them; press the **+** under the tiles to add
a live tile; right-click an app in the list to pin it. See
[desktop/README.md](desktop/README.md#start) for the details.

## Updating

```sh
cd tubewm
git pull
desktop/install.sh
apps/install.sh             # if you use the app themes; close Vivaldi first
```

Your start layout, accent, wallpaper choice and any config files you've edited
(`~/.config/sway/config`, `~/.config/waybar/`) are kept. Then `swaymsg reload`.

## Uninstalling

```sh
apps/install.sh --uninstall     # with Vivaldi closed
desktop/install.sh --uninstall
```

The desktop uninstaller removes the `tube-*` commands and
`~/.local/share/tubewm`, then restores your configs and GTK settings from the
most recent backup. The app uninstaller puts back each setting it changed,
unless you've changed it again since. `~/.config/tubewm` (backups, accent,
start layout) is kept; delete it yourself if you want a clean slate. The
packages installed with `--deps` are left installed.

## Troubleshooting

* **`Super+S` does nothing:** run `~/.local/bin/tube-start` from a terminal
  (`Super+Return`) to see the error. A missing GtkLayerShell or Open Sans is
  the usual cause.
* **Stuck with no way out:** `Super+Return` opens a terminal and
  `Super+Shift+E` has sign out. From any text console (`Ctrl+Alt+F3`),
  `desktop/install.sh --uninstall` puts your old configs back.
* **"GtkLayerShell not found" or start won't open:** install gtk-layer-shell's
  GObject bindings (`gir1.2-gtklayershell-0.1` on Debian/Ubuntu,
  `gtk-layer-shell` elsewhere).
* **Text looks wrong:** check that Open Sans is installed with
  `fc-list | grep -i "open sans"`.
* **Vivaldi looks half-styled:** the experiments checkbox in step 6 isn't
  ticked yet, or Vivaldi needs a restart.
* **Start looks wrong after an update:** `tube-start --reset` puts back the
  default tiles.
