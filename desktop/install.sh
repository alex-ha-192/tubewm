#!/usr/bin/env bash
# tubewm desktop installer.
#
#   desktop/install.sh                 install / update the desktop for this user
#   desktop/install.sh --deps          also install the packages it needs (sudo)
#   desktop/install.sh --accent teal   pick the accent at the same time
#   desktop/install.sh --no-gsettings  leave GTK / GNOME settings alone
#   desktop/install.sh --uninstall     remove tubewm and restore the last backup
#
# Nothing is installed system-wide except packages with --deps. Every config
# file that would be replaced is first copied to
# ~/.config/tubewm/backup/<date>/.
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
DEST=$DATA/tubewm
BIN=$HOME/.local/bin
BACKUPS=$CONFIG/tubewm/backup
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=$BACKUPS/$STAMP

deps=0 gsettings_ok=1 uninstall=0 accent=""
while [ $# -gt 0 ]; do
    case $1 in
        --deps) deps=1 ;;
        --no-gsettings) gsettings_ok=0 ;;
        --accent) accent=${2:?--accent needs a name or #hex}; shift ;;
        --uninstall) uninstall=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

BINARIES=(tube-accent tube-charms tube-lock tube-osd tube-render tube-share tube-snap tube-start tube-switcher)

# Static configs: installed once, yours to edit afterwards.
STATIC=(sway/config waybar/config.jsonc waybar/style.css)

# ── uninstall ────────────────────────────────────────────────────────────
if [ "$uninstall" = 1 ]; then
    say "Removing tubewm"
    for b in "${BINARIES[@]}"; do
        [ -L "$BIN/$b" ] && rm -f "$BIN/$b"
    done
    rm -rf "$DEST"
    last=$(ls -1d "$BACKUPS"/*/ 2>/dev/null | tail -n1 || true)
    if [ -n "$last" ]; then
        note "restoring configs from $last"
        (cd "$last" && find . -type f ! -name gsettings.txt -print0) | while IFS= read -r -d '' f; do
            mkdir -p "$CONFIG/$(dirname "$f")"
            cp -f "$last/$f" "$CONFIG/$f"
        done
        if [ -f "$last/gsettings.txt" ] && command -v gsettings >/dev/null; then
            while read -r schema key value; do
                gsettings set "$schema" "$key" "$value" 2>/dev/null || true
            done < "$last/gsettings.txt"
        fi
    else
        note "no backup found; generated configs in $CONFIG were left in place"
    fi
    note "kept ~/.config/tubewm (start tiles, accent, backups)"
    exit 0
fi

# ── packages ─────────────────────────────────────────────────────────────
if [ "$deps" = 1 ]; then
    say "Installing packages"
    if command -v apt-get >/dev/null; then
        sudo apt-get install -y sway swaybg swayidle swaylock waybar fuzzel mako-notifier foot \
            grim slurp wl-clipboard jq playerctl brightnessctl libnotify-bin wireplumber \
            python3-gi gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 fonts-open-sans
    elif command -v pacman >/dev/null; then
        sudo pacman -S --needed sway swaybg swayidle swaylock waybar fuzzel mako foot \
            grim slurp wl-clipboard jq playerctl brightnessctl libnotify wireplumber \
            python-gobject gtk3 gtk-layer-shell ttf-opensans
    elif command -v dnf >/dev/null; then
        sudo dnf install -y sway swaybg swayidle swaylock waybar fuzzel mako foot \
            grim slurp wl-clipboard jq playerctl brightnessctl libnotify wireplumber \
            python3-gobject gtk3 gtk-layer-shell open-sans-fonts
    elif command -v zypper >/dev/null; then
        sudo zypper install -y sway swaybg swayidle swaylock waybar fuzzel mako foot \
            grim slurp wl-clipboard jq playerctl brightnessctl libnotify-tools wireplumber \
            python3-gobject-Gdk typelib-1_0-GtkLayerShell-0_1 open-sans-fonts
    else
        note "unknown package manager; install the packages listed in desktop/README.md yourself"
    fi
fi

# ── checks ───────────────────────────────────────────────────────────────
say "Checking for the pieces tubewm uses"
missing=()
for c in sway waybar mako fuzzel foot swaylock swayidle jq python3 grim; do
    command -v "$c" >/dev/null || missing+=("$c")
done
if ! python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("GtkLayerShell","0.1")' 2>/dev/null; then
    missing+=("python3-gi + gtk-layer-shell (start screen, charms)")
fi
fc-list : family 2>/dev/null | grep -i "open sans" >/dev/null || missing+=("Open Sans font")
if [ ${#missing[@]} -gt 0 ]; then
    note "not found: ${missing[*]}"
    note "run with --deps to install them, or install them yourself; continuing"
else
    note "all present"
fi

# ── files ────────────────────────────────────────────────────────────────
backup() { # path relative to $CONFIG
    local f=$CONFIG/$1
    [ -e "$f" ] || return 0
    mkdir -p "$BACKUP/$(dirname "$1")"
    cp -a "$f" "$BACKUP/$1"
}

say "Installing to $DEST"
rm -rf "$DEST.new"
mkdir -p "$DEST.new"
cp -r "$REPO/palette" "$DEST.new/palette"
mkdir -p "$DEST.new/desktop"
cp -r "$REPO/desktop/bin" "$REPO/desktop/shell" "$REPO/desktop/templates" \
      "$REPO/desktop/start" "$REPO/desktop/config" "$DEST.new/desktop/"
find "$DEST.new" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$DEST"
mv "$DEST.new" "$DEST"

mkdir -p "$BIN"
for b in "${BINARIES[@]}"; do
    ln -sf "$DEST/desktop/bin/$b" "$BIN/$b"
done
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) note "NOTE: $BIN is not on your PATH. Sway runs the tube-* commands from there,"
       note "      so add it, e.g. in ~/.profile:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

say "Writing configs (old ones go to $BACKUP)"
for rel in "${STATIC[@]}"; do
    src=$REPO/desktop/config/$rel
    if [ -e "$CONFIG/$rel" ] && cmp -s "$src" "$CONFIG/$rel"; then continue; fi
    backup "$rel"
    mkdir -p "$CONFIG/$(dirname "$rel")"
    cp "$src" "$CONFIG/$rel"
    note "$rel"
done
# waybar reads ~/.config/waybar/config before config.jsonc on some versions.
if [ -e "$CONFIG/waybar/config" ]; then
    backup waybar/config
    rm -f "$CONFIG/waybar/config"
    note "moved old waybar/config aside"
fi
(cd "$REPO/desktop/templates" && find . -type f | sed 's|^\./||') | while read -r rel; do
    backup "$rel"
done
mkdir -p "$CONFIG/sway/config.d" "$CONFIG/tubewm/accent.d"

if [ ! -e "$CONFIG/tubewm/start.toml" ]; then
    cp "$REPO/desktop/start/start.toml" "$CONFIG/tubewm/start.toml"
    note "tubewm/start.toml (your start tiles)"
fi

if [ -n "$accent" ]; then
    TUBEWM_HOME=$DEST "$DEST/desktop/bin/tube-accent" "$accent" >/dev/null
fi
TUBEWM_HOME=$DEST "$DEST/desktop/bin/tube-render"

# ── GTK / GNOME settings ─────────────────────────────────────────────────
if [ "$gsettings_ok" = 1 ] && command -v gsettings >/dev/null \
        && gsettings list-schemas 2>/dev/null | grep -x org.gnome.desktop.interface >/dev/null; then
    say "Setting GTK preferences (dark, Open Sans, no title bar buttons)"
    mkdir -p "$BACKUP"
    for kv in "org.gnome.desktop.interface color-scheme" "org.gnome.desktop.interface font-name" \
              "org.gnome.desktop.interface gtk-theme" "org.gnome.desktop.wm.preferences button-layout"; do
        # shellcheck disable=SC2086
        printf '%s %s\n' "$kv" "$(gsettings get $kv 2>/dev/null)" >> "$BACKUP/gsettings.txt" || true
    done
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' || true
    gsettings set org.gnome.desktop.interface gtk-theme 'Adwaita-dark' || true
    gsettings set org.gnome.desktop.interface font-name 'Open Sans 10' || true
    gsettings set org.gnome.desktop.wm.preferences button-layout ':' || true
fi

[ -d "$BACKUP" ] || note "nothing needed backing up"

say "Done"
note "Log into sway (or run 'swaymsg reload' if it is already running)."
note "Super+S start · Super+C charms · Super+Tab switch · Super+, / Super+. snap"
note "Change the accent any time: tube-accent list"
