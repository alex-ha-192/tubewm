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

```sh
git clone https://github.com/alex-ha-192/tubewm
cd tubewm
./install.sh
```

That's all. The installer is a few screens in your terminal:

1. **your keyboard.** It starts on the layout your system already uses
   (English (UK) on a British machine). Type to search if it's wrong.
2. **ready to install.** A list of what it will do, all ticked. Press Enter.
   Space turns a step off.
3. **your password**, once, if any ticked step needs it.
4. **installing**, with each step ticked off as it finishes.

What it does:

| | |
|---|---|
| In your home folder | The desktop, start screen and charms in `~/.local/share/tubewm`, the `tube-*` commands in `~/.local/bin`, and configs for Sway, Waybar, mako, fuzzel, foot, the lock screen and GTK. Anything it replaces is backed up first. |
| App themes | Themes every supported app it finds (see below), in the same colour. |
| Packages (password) | Only the ones that are missing. On Arch and CachyOS this is a full `pacman -Syu`, which is the supported way to install and also fixes "failed retrieving file" mirror errors. Supports pacman, apt, dnf and zypper. |
| Keyboard (password) | Uses your layout on the sign-in screen and the text consoles too (`localectl set-x11-keymap`). |
| Sign-in screen (password) | Adds **tubewm** to the session menu of SDDM, GDM, LightDM or greetd. |

Then log out, pick **tubewm** on the sign-in screen and sign in. (No sign-in
screen? Log in on a console and type `tubewm-session`.) The first time, a short
welcome lets you pick your colour and check your keyboard. After that, start
opens when you log in: `Super+S` brings it back, `Super+C` opens the charms and
`Super+I` settings. The full key list is in
[desktop/docs/keys.html](desktop/docs/keys.html) ([view it rendered](https://htmlpreview.github.io/?https://github.com/alex-ha-192/tubewm/blob/main/desktop/docs/keys.html)).

Other ways to run it:

```sh
./install.sh --home-only    # nothing that needs a password
./install.sh --yes          # no questions, take the defaults (e.g. over ssh)
./install.sh --keyboard us:intl --yes
./install.sh --uninstall    # take it all out again
```

### What you need

* A Linux system that can run **Sway 1.9 or newer** (any GPU that works with
  wlroots; the session launcher adds `--unsupported-gpu` for NVIDIA itself).
* `git` and `python3` 3.9 or newer. Everything else the installer fetches.

### Laptops

* **Closing the lid** locks the screen, then the laptop sleeps. Opening it
  shows the lock screen, in your keyboard layout. With another monitor plugged
  in, closing the lid just turns the laptop screen off.
* **The power button** opens the power choices (sleep, sign out, restart, shut
  down) instead of switching off straight away. Holding it still forces power
  off.
* Your keyboard layout is the same on the desktop, the lock screen, the
  sign-in screen and the consoles. Change it any time with
  `tube-keyboard set gb`, and `tube-keyboard system` to copy it to the sign-in
  screen.

### App themes

The installer runs `apps/install.sh` for you. Run it again yourself after
installing a new app, or to choose which apps:

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
./install.sh                # close Vivaldi first if you use its theme
```

Your start layout, accent, wallpaper choice and any config files you've edited
(`~/.config/sway/config`, `~/.config/waybar/`) are kept. Then `swaymsg reload`.

## Uninstalling

```sh
./install.sh --uninstall
```

It removes the desktop and the app themes and puts back the configs and GTK
settings you had before tubewm. It also offers, unticked, to delete your
tubewm settings (colour, tiles, backups) and the packages it installed. Your
keyboard layout on the sign-in screen is left as it is.

## Troubleshooting

* **Something went wrong while installing:** the installer says what failed
  and how to fix it, and `r` tries again. The whole log is in
  `~/.local/state/tubewm/install.log`.
* **The session drops straight back to the sign-in screen:** the reason is at
  the end of `~/.local/state/tubewm/session.log`.
* **The touchpad still picks up your palm:** libinput's palm detection can be
  tuned per touchpad. Run `sudo libinput measure touch-size` and
  `sudo libinput measure touchpad-pressure` (from `libinput-tools`), then put
  the values they suggest in `/etc/libinput/local-overrides.quirks`, as
  described in the libinput "Device quirks" documentation.
* **`Super+S` does nothing:** run `~/.local/bin/tube-start` from a terminal
  (`Super+Return`) to see the error. A missing GtkLayerShell or Open Sans is
  the usual cause.
* **Stuck with no way out:** `Super+Return` opens a terminal and
  `Super+Shift+E` has sign out. From any text console (`Ctrl+Alt+F3`),
  `./install.sh --uninstall` in the tubewm folder puts your old desktop back.
* **"GtkLayerShell not found" or start won't open:** install gtk-layer-shell's
  GObject bindings (`gir1.2-gtklayershell-0.1` on Debian/Ubuntu,
  `gtk-layer-shell` elsewhere).
* **Text looks wrong:** check that Open Sans is installed with
  `fc-list | grep -i "open sans"`.
* **Vivaldi looks half-styled:** the experiments checkbox (see App themes) isn't
  ticked yet, or Vivaldi needs a restart.
* **Start looks wrong after an update:** `tube-start --reset` puts back the
  default tiles.
