#!/bin/sh
# Build tubewm's own Wayfire plugins against the installed Wayfire and put
# them where Wayfire looks without any setup:
#   ~/.local/share/wayfire/plugins/lib<name>.so
#   ~/.local/share/wayfire/metadata/<name>.xml
#
# No arguments, never asks anything. Builds in ~/.cache/tubewm, so the
# checkout stays clean. Does nothing when neither the sources nor Wayfire
# changed since the last build. One line per plugin; exits non-zero if a
# plugin could not be built.
#
# Needs meson, ninja, a C++ compiler, pkg-config and Wayfire's headers
# (Arch/CachyOS: in the wayfire package; Debian: wayfire-dev;
# Fedora: wayfire-devel).
set -u

here=$(cd "$(dirname "$0")" && pwd)
data=${XDG_DATA_HOME:-$HOME/.local/share}
cache=${XDG_CACHE_HOME:-$HOME/.cache}/tubewm/wayfire-plugins
build=$cache/build
stamp=$cache/stamp
plugins=$(cd "$here" && for d in */; do [ -f "$d/meson.build" ] && echo "${d%/}"; done)

say() { for p in $plugins; do echo "$p: $1"; done; }

for tool in meson ninja pkg-config; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        say "not built, $tool is not installed"
        exit 1
    fi
done
if ! pkg-config --exists wayfire; then
    say "not built, Wayfire's headers are not installed"
    exit 1
fi

# What the build depends on: every source file, and the Wayfire and wlroots
# versions the plugins are compiled against (plugins must match exactly).
want=$( {
    pkg-config --modversion wayfire wlroots-0.19 2>/dev/null
    cd "$here" && find . -type f ! -name '*.md' | LC_ALL=C sort | xargs cat
} | cksum)

built=yes
for p in $plugins; do
    [ -f "$data/wayfire/plugins/lib$p.so" ] || built=no
done
if [ "$built" = yes ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]; then
    say "up to date"
    exit 0
fi

mkdir -p "$cache"
log=$cache/build.log
rm -rf "$build"
if meson setup "$build" "$here" --prefix="$HOME/.local" \
        --libdir="$data/wayfire/plugins" --datadir="$data/wayfire/metadata" \
        >"$log" 2>&1 \
    && ninja -C "$build" >>"$log" 2>&1 \
    && meson install -C "$build" --quiet >>"$log" 2>&1; then
    echo "$want" >"$stamp"
    say "built for Wayfire $(pkg-config --modversion wayfire)"
    # Pick the new plugins up in wayfire.ini (Wayfire reloads it by itself).
    for cfg in "$(command -v tube-wayfire-config)" "$HOME/.local/bin/tube-wayfire-config"; do
        if [ -x "$cfg" ]; then
            "$cfg" >/dev/null 2>&1 || true
            break
        fi
    done
    exit 0
fi
rm -f "$stamp"
say "build failed, see $log"
exit 1
