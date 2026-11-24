#!/usr/bin/env bash
# Install, on Arch Linux, everything the CI checks run: the desktop's own
# packages (the same list desktop/install.sh --deps uses), the apps we can
# check headlessly, and the linters. Needs root.
set -euo pipefail

desktop=(sway swaybg swayidle swaylock waybar fuzzel mako foot
         grim slurp wl-clipboard jq playerctl brightnessctl libnotify wireplumber
         python-gobject python-cairo gtk3 gtk-layer-shell ttf-opensans)
session=(dbus xorg-xwayland procps-ng util-linux mesa gtk4 python-pytest)
apps=(tmux neovim mpv kitty helix python-lupa)
lint=(shellcheck python-pyflakes git)

pacman -Syu --noconfirm --needed "${desktop[@]}" "${session[@]}" "${apps[@]}" "${lint[@]}"

echo "versions:"
for c in foot waybar fuzzel swaylock nvim mpv kitty helix shellcheck python3; do
    printf '  %-10s %s\n' "$c" "$($c --version 2>&1 | grep -m1 -E '[0-9]+\.[0-9]+')"
done
printf '  %-10s %s\n' tmux "$(tmux -V)"
pacman -Q sway mako gtk3 gtk4 | sed 's/^/  /'
