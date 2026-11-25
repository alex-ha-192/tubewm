#!/usr/bin/env bash
# Build tubewm's Wayfire plugins (desktop/wayfire/plugins) against the
# Wayfire that Arch ships today, the way the installer does, and load them in
# a headless Wayfire. Catches a new Wayfire release breaking the title bars
# before it reaches a laptop.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

PLUGINS=$REPO/desktop/wayfire/plugins
SANDBOX=$(mktemp -d)
trap 'kill "${wf_pid:-0}" 2>/dev/null; rm -rf "$SANDBOX"' EXIT
unset XDG_DATA_HOME XDG_CACHE_HOME
export HOME=$SANDBOX/home
mkdir -p "$HOME"
lib=$HOME/.local/share/wayfire/plugins
meta=$HOME/.local/share/wayfire/metadata

section "build ($(pkg-config --modversion wayfire 2>/dev/null || echo 'no wayfire'))"
out=$(bash "$PLUGINS/build.sh" 2>&1); rc=$?
echo "$out" | sed 's/^/        /'
if [ "$rc" != 0 ]; then
    fail "build.sh failed"
    cat "$HOME/.cache/tubewm/wayfire-plugins/build.log" 2>/dev/null | tail -40
    finish
fi
for d in "$PLUGINS"/*/; do
    p=$(basename "$d")
    [ -f "$d/meson.build" ] || continue
    if [ -f "$lib/lib$p.so" ] && [ -f "$meta/$p.xml" ]; then pass "$p installed"; else fail "$p not installed"; fi
    if nm -D --defined-only "$lib/lib$p.so" 2>/dev/null | grep -q ' newInstance$'; then
        pass "$p is a Wayfire plugin"
    else
        fail "$p exports no newInstance"
    fi
done
out=$(bash "$PLUGINS/build.sh" 2>&1)
if echo "$out" | grep -q "up to date"; then pass "second run skips the build"; else fail "second run rebuilt: $out"; fi

section "load in a headless Wayfire"
if ! have wayfire; then
    skip "wayfire is not installed"
    finish
fi
cat >"$SANDBOX/wayfire.ini" <<'EOF'
[core]
plugins = tube-decor
EOF
# Wayfire refuses to run as root, so in a root container run it as an
# ordinary user, pointed at the plugins built above.
run=()
user=
if [ "$(id -u)" = 0 ]; then
    user=$(ci_user)
    chmod -R a+rX "$SANDBOX"
    run=(runuser -u "$user" --)
fi
export XDG_RUNTIME_DIR=$SANDBOX/run
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
if [ -n "$user" ]; then chown "$user" "$XDG_RUNTIME_DIR"; fi
touch "$SANDBOX/wayfire.log" && chmod a+w "$SANDBOX/wayfire.log"
"${run[@]}" env HOME="$HOME" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
    WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 \
    WAYFIRE_PLUGIN_PATH="$lib" WAYFIRE_PLUGIN_XML_PATH="$meta" \
    wayfire -d -c "$SANDBOX/wayfire.ini" >>"$SANDBOX/wayfire.log" 2>&1 &
wf_pid=$!
for _ in $(seq 1 40); do
    grep -q -e "Loaded plugin" -e "error loading plugin" -e "Failed to load" "$SANDBOX/wayfire.log" && break
    kill -0 "$wf_pid" 2>/dev/null || break
    sleep 0.25
done
sleep 0.5
if grep -q -e "error loading plugin.*tube-decor" -e 'Failed to load plugin "tube-decor"' "$SANDBOX/wayfire.log"; then
    fail "Wayfire could not load tube-decor:"
    grep -e "error loading" -e "Failed to load" "$SANDBOX/wayfire.log" | head -5
elif grep -q "Loaded plugin.*libtube-decor.so" "$SANDBOX/wayfire.log"; then
    pass "Wayfire loaded tube-decor"
else
    warn "Wayfire did not get as far as loading plugins here (no GPU?); log tail:"
    tail -15 "$SANDBOX/wayfire.log"
fi
finish
