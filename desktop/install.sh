#!/usr/bin/env bash
# tubewm desktop installer.
#
#   desktop/install.sh                 install / update the desktop for this user
#   desktop/install.sh --deps          also install the packages it needs (sudo)
#   desktop/install.sh --accent teal   pick the accent at the same time
#   desktop/install.sh --no-gsettings  leave GTK / GNOME settings alone
#   desktop/install.sh --uninstall     remove tubewm and put your old configs back
#
# Most people want ./install.sh at the top of the repository instead, which
# runs this and also sets up the login screen and keyboard.
#
# Nothing is installed system-wide except packages with --deps. Every config
# file that would be replaced is first copied to
# ~/.config/tubewm/backup/<date>/, and the very first install also keeps
# ~/.config/tubewm/backup/original/, which --uninstall puts back.
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
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "install.sh: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }

# Every command in desktop/bin, so new ones are linked without editing this.
BINARIES=()
for b in "$REPO"/desktop/bin/*; do
    [ -f "$b" ] && [ -x "$b" ] && BINARIES+=("$(basename "$b")")
done

# Managed snippets for sway: replaced on every update, removed on uninstall.
MANAGED=()
for f in "$REPO"/desktop/config/sway/config.d/*.conf; do
    [ -f "$f" ] && MANAGED+=("sway/config.d/$(basename "$f")")
done
ORIGINAL=$BACKUPS/original

# Static configs: installed once, yours to edit afterwards.
STATIC=(sway/config waybar/config.jsonc waybar/style.css)

# ── uninstall ────────────────────────────────────────────────────────────
if [ "$uninstall" = 1 ]; then
    say "Removing tubewm"
    # Links into our install, whatever their name (older installs had fewer).
    for l in "$BIN"/tube-*; do
        [ -L "$l" ] && case $(readlink "$l") in "$DEST"/*) rm -f "$l" ;; esac
    done
    rm -rf "$DEST"
    rm -f "$DATA/applications/tubewm-update.desktop"
    # Plugins built by desktop/wayfire/plugins/build.sh, and its build dir.
    for p in tube-decor tube-switch; do
        rm -f "$DATA/wayfire/plugins/lib$p.so" "$DATA/wayfire/metadata/$p.xml"
    done
    rmdir "$DATA/wayfire/plugins" "$DATA/wayfire/metadata" "$DATA/wayfire" 2>/dev/null || true
    rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/tubewm/wayfire-plugins"
    for rel in "${MANAGED[@]}" sway/config.d/10-tubewm-keyboard.conf sway/config.d/50-tubewm-wallpaper.conf; do
        rm -f "$CONFIG/$rel"
    done
    # Put back what was there before tubewm: the original backup if there is
    # one, else the oldest dated backup (installs from before 'original').
    src=$ORIGINAL
    [ -d "$src" ] || src=$(ls -1d "$BACKUPS"/2*/ 2>/dev/null | head -n1 || true)
    src=${src%/}
    if [ -n "$src" ] && [ -d "$src" ]; then
        note "restoring configs from $src"
        (cd "$src" && find . -type f ! -name gsettings.txt ! -name created.txt -print0) | while IFS= read -r -d '' f; do
            f=${f#./}
            mkdir -p "$CONFIG/$(dirname "$f")"
            cp -f "$src/$f" "$CONFIG/$f"
        done
        # Files tubewm created where there was nothing before.
        if [ -f "$src/created.txt" ]; then
            while IFS= read -r f; do
                [ -n "$f" ] && rm -f "$CONFIG/$f"
            done < "$src/created.txt"
        fi
        if [ -f "$src/gsettings.txt" ] && command -v gsettings >/dev/null; then
            while read -r schema key value; do
                gsettings set "$schema" "$key" "$value" 2>/dev/null || true
            done < "$src/gsettings.txt"
        fi
    else
        note "no backup found; generated configs in $CONFIG were left in place"
    fi
    # Empty include files tube-render made for you, and folders left empty.
    for f in gtk-3.0/user.css gtk-4.0/user.css foot/local.ini; do
        [ -f "$CONFIG/$f" ] && [ ! -s "$CONFIG/$f" ] && rm -f "$CONFIG/$f"
    done
    for d in sway/config.d sway waybar/icons waybar mako fuzzel foot swaylock gtklock gtk-3.0 gtk-4.0 xdg-desktop-portal; do
        rmdir "$CONFIG/$d" 2>/dev/null || true
    done
    note "kept ~/.config/tubewm (start tiles, accent, backups)"
    exit 0
fi

# ── packages ─────────────────────────────────────────────────────────────
if [ "$deps" = 1 ]; then
    say "Installing packages"
    "$REPO/install.sh" --packages-only
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
# The first install keeps what was there before tubewm in backup/original,
# including a list of the files that didn't exist yet, for --uninstall.
first_install=0
[ -d "$ORIGINAL" ] || [ -d "$DEST" ] || first_install=1
backup() { # path relative to $CONFIG
    local f=$CONFIG/$1
    if [ "$first_install" = 1 ]; then
        mkdir -p "$ORIGINAL"
        if [ -e "$f" ]; then
            mkdir -p "$ORIGINAL/$(dirname "$1")"
            [ -e "$ORIGINAL/$1" ] || cp -a "$f" "$ORIGINAL/$1"
        else
            grep -qxF "$1" "$ORIGINAL/created.txt" 2>/dev/null || echo "$1" >> "$ORIGINAL/created.txt"
        fi
    fi
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
      "$REPO/desktop/start" "$REPO/desktop/config" "$REPO/desktop/wayfire" \
      "$DEST.new/desktop/"
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
# Wayfire's config is rendered too, when this checkout has it.
[ -d "$REPO/desktop/wayfire" ] && backup wayfire.ini
for rel in "${MANAGED[@]}"; do
    backup "$rel"
    mkdir -p "$CONFIG/$(dirname "$rel")"
    cp "$REPO/desktop/config/$rel" "$CONFIG/$rel"
done
mkdir -p "$CONFIG/sway/config.d" "$CONFIG/tubewm/accent.d"

# "update tubewm" in start: opens tube-update in a terminal.
APPS=$DATA/applications
mkdir -p "$APPS"
cat > "$APPS/tubewm-update.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=update tubewm
Comment=Get the newest version of your desktop
Exec=$BIN/tube-update
Terminal=true
Icon=system-software-update
Categories=System;Settings;
DESKTOP

if [ -n "$accent" ]; then
    TUBEWM_HOME=$DEST "$DEST/desktop/bin/tube-accent" "$accent" >/dev/null
fi
TUBEWM_HOME=$DEST "$DEST/desktop/bin/tube-render"

# A wallpaper drawn from the accent, unless you've picked one (or turned it off).
if [ ! -e "$CONFIG/tubewm/wallpaper" ] && [ ! -e "$CONFIG/tubewm/wallpaper-off" ]; then
    if TUBEWM_HOME=$DEST "$DEST/desktop/bin/tube-wallpaper" fade 2>/dev/null; then
        note "wallpaper: fade (change it with tube-wallpaper list, or in settings)"
    fi
fi

# ── GTK / GNOME settings ─────────────────────────────────────────────────
if [ "$gsettings_ok" = 1 ] && command -v gsettings >/dev/null \
        && gsettings list-schemas 2>/dev/null | grep -x org.gnome.desktop.interface >/dev/null; then
    say "Setting GTK preferences (dark, Open Sans, close button only)"
    mkdir -p "$BACKUP"
    if [ "$first_install" = 1 ]; then
        for kv in "org.gnome.desktop.interface color-scheme" "org.gnome.desktop.interface font-name" \
                  "org.gnome.desktop.interface gtk-theme" "org.gnome.desktop.wm.preferences button-layout"; do
            # shellcheck disable=SC2086
            printf '%s %s\n' "$kv" "$(gsettings get $kv 2>/dev/null)" >> "$ORIGINAL/gsettings.txt" || true
        done
    fi
    for kv in "org.gnome.desktop.interface color-scheme" "org.gnome.desktop.interface font-name" \
              "org.gnome.desktop.interface gtk-theme" "org.gnome.desktop.wm.preferences button-layout"; do
        # shellcheck disable=SC2086
        printf '%s %s\n' "$kv" "$(gsettings get $kv 2>/dev/null)" >> "$BACKUP/gsettings.txt" || true
    done
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' || true
    gsettings set org.gnome.desktop.interface gtk-theme 'Adwaita-dark' || true
    gsettings set org.gnome.desktop.interface font-name 'Open Sans 10' || true
    gsettings set org.gnome.desktop.wm.preferences button-layout ':close' || true
fi

[ -d "$BACKUP" ] || note "nothing needed backing up"

say "Done"
[ -n "${TUBEWM_FROM_INSTALLER:-}" ] && exit 0
note "Log into sway (or run 'swaymsg reload' if it is already running)."
note "Super+S start · Super+C charms · Super+Tab switch · Super+, / Super+. snap"
note "Change the accent any time: tube-accent list"
