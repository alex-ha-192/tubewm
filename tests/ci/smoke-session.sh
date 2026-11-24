#!/usr/bin/env bash
# Start a real, headless sway session the way a display manager would (a
# clean environment and a PATH without ~/.local/bin), then check that:
#   * sway, waybar, mako and swayidle come up and stay up;
#   * every program the sway and waybar configs run can be found from inside
#     the session (what bit us on a display-manager login);
#   * the start screen, charms and the terminal actually open;
#   * nothing in the session log looks like a config error or a traceback.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SETTLE=${SMOKE_SETTLE:-6}

for c in sway swaymsg dbus-run-session; do
    have "$c" || { fail "$c is not installed"; finish; }
done

new_sandbox
C=$SANDBOX_HOME/.config
LOG=$SANDBOX_HOME/session.log
PROBE=$SANDBOX_HOME/probe
run() { as_user "$SANDBOX_USER" "$@"; }

section "install"
if out=$(install_desktop 2>&1); then pass "install.sh ran"; else
    fail "install.sh failed"; printf '%s\n' "$out" | sed 's/^/        /'; finish
fi

section "start sway (headless, minimal PATH: $MINIMAL_PATH)"
# WLR_* pick the headless backend and the software renderer; everything else
# is what a display manager would hand the session.
run env WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 \
        XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=sway \
    dbus-run-session -- sway -d > "$LOG" 2>&1 &
sway_pid=$!

sock=""
for _ in $(seq 1 50); do
    sock=$(find "$SANDBOX_RUNTIME" -maxdepth 1 -name 'sway-ipc.*.sock' 2>/dev/null | head -n1)
    [ -n "$sock" ] && break
    kill -0 "$sway_pid" 2>/dev/null || break
    sleep 0.2
done
msg() { run env SWAYSOCK="$sock" swaymsg "$@"; }

cleanup() {
    [ -n "$sock" ] && msg exit >/dev/null 2>&1
    sleep 1
    kill "$sway_pid" 2>/dev/null
    pkill -u "$SANDBOX_USER" 2>/dev/null
    wait "$sway_pid" 2>/dev/null
}
trap cleanup EXIT

if [ -z "$sock" ] || ! msg -t get_version >/dev/null 2>&1; then
    fail "sway did not start"
    grep -vE '^\S+ \[DEBUG\]' "$LOG" | tail -n 60 | sed 's/^/        /'
    trap - EXIT; cleanup; finish
fi
pass "sway is up ($(msg -t get_version -r | jq -r .human_readable 2>/dev/null))"
sleep "$SETTLE"

section "session processes"
for p in waybar mako swayidle; do
    if pgrep -u "$SANDBOX_USER" -x "$p" >/dev/null; then pass "$p is running"
    else fail "$p is not running (see the session log below)"; fi
done

section "programs the configs run, as seen from inside the session"
# Optional extras the desktop uses when present but doesn't need.
OPTIONAL=" pavucontrol blueman-manager nmcli nm-connection-editor gtklock curl "
mapfile -t progs < <(python3 "$CI_DIR/parse.py" commands "$C/sway/config" "$C/waybar/config.jsonc")
printf '%s\n' "${progs[@]}" > "$PROBE.names"
cat > "$PROBE.sh" <<PROBE_EOF
while IFS= read -r p; do
    case \$p in "~/"*) q="\$HOME/\${p#"~/"}" ;; *) q=\$p ;; esac
    if command -v "\$q" >/dev/null 2>&1; then echo "found \$p"; else echo "missing \$p"; fi
done < "$PROBE.names" > "$PROBE.tmp"
echo "path \$PATH" >> "$PROBE.tmp"
mv "$PROBE.tmp" "$PROBE"
PROBE_EOF
chown "$SANDBOX_USER:" "$PROBE.names" "$PROBE.sh" 2>/dev/null
# swaymsg exec runs the probe with sway's own environment, the same way a
# key binding or a waybar click runs its command.
msg exec "sh $PROBE.sh" >/dev/null
for _ in $(seq 1 20); do [ -f "$PROBE" ] && break; sleep 0.25; done
[ -f "$PROBE" ] || fail "the PATH probe never ran inside the session"
for p in "${progs[@]}"; do
    if grep -qx "found $p" "$PROBE"; then pass "$p"
    elif [[ $OPTIONAL == *" $p "* ]]; then warn "$p not found (optional)"
    else fail "$p is not on the session's PATH"; fi
done
spath=$(sed -n 's/^path //p' "$PROBE" 2>/dev/null)
echo "        sway's PATH: ${spath:-unknown}"

section "open things the way the key bindings do"
opened() { pgrep -u "$SANDBOX_USER" -f "$1" >/dev/null; }
# try_open CMD PATTERN: exec CMD in the session; did a process matching
# PATTERN come up? Prints why not.
try_open() {
    local cmd=$1 pat=$2 before
    pkill -u "$SANDBOX_USER" -f "$pat" 2>/dev/null; sleep 0.5
    before=$(($(wc -l < "$LOG") + 1))
    msg exec "$cmd" >/dev/null
    sleep 3
    opened "$pat" && return 0
    tail -n +"$before" "$LOG" | grep -E 'not found|Permission denied|Traceback|Error' -A30 | head -n 40 > "$LOG.why"
    return 1
}
# What the key bindings actually run, straight from the installed config.
for spec in '$mod+s|bin/tube-start' '$mod+c|bin/tube-charms' '$mod+i|bin/tube-charms'; do
    key=${spec%%|*} pat=${spec#*|}
    if ! cmd=$(python3 "$CI_DIR/parse.py" binding "$C/sway/config" "$key" 2>&1); then
        fail "$key: $cmd"; continue
    fi
    bin=${cmd%% *}; bin=${bin##*/}
    if try_open "$cmd" "$pat"; then
        pass "$key ($cmd) opened and stayed open"
    else
        if grep -qE "$bin: (not found|command not found|Permission denied|No such file)" "$LOG.why"; then
            fail "$key ($cmd): sway can't find $bin, so the key does nothing in a display-manager session"
            # Still check the program itself works, by its full path.
            args=${cmd#"${cmd%% *}"}
            if try_open "$SANDBOX_HOME/.local/bin/$bin$args" "$pat"; then
                pass "$bin opens when run by full path"
            elif grep -q Traceback "$LOG.why"; then
                fail "$bin crashed:"; sed 's/^/        /' "$LOG.why"
            else
                warn "$bin is not running 3s after starting it by full path"
            fi
        elif grep -q Traceback "$LOG.why"; then
            fail "$key ($cmd) crashed:"; sed 's/^/        /' "$LOG.why"
        else
            warn "$key ($cmd) is not running 3s after starting it (no error logged)"
        fi
    fi
    pkill -u "$SANDBOX_USER" -f "$pat" 2>/dev/null
done

# Changing the accent from inside the session must reach every config, which
# means tube-accent has to find tube-render on the session's PATH. Run it by
# full path, the way charms (which puts its own bin dir on PATH) reaches it.
want=$(awk '$1 == "lime" { print toupper($2) }' "$REPO/palette/accents")
msg exec "$SANDBOX_HOME/.local/bin/tube-accent lime > $SANDBOX_HOME/accent.out 2>&1" >/dev/null
recoloured() {
    grep -qiE "^set \\\$tube_accent +$want\$" "$C/sway/tubewm-colors" 2>/dev/null \
        && grep -qix "selection-background=${want#\#}" "$C/foot/foot.ini" 2>/dev/null
}
for _ in $(seq 1 80); do recoloured && break; sleep 0.25; done
if recoloured; then
    pass "tube-accent lime, run inside the session, recoloured foot and sway"
else
    fail "tube-accent lime, run inside the session, did not recolour the configs:"
    sed 's/^/        /' "$SANDBOX_HOME/accent.out" 2>/dev/null
fi

if have foot; then
    msg exec foot >/dev/null
    ok=0
    for _ in $(seq 1 15); do
        msg -t get_tree -r | jq -e '.. | objects | select(.app_id? == "foot")' >/dev/null 2>&1 && { ok=1; break; }
        sleep 0.3
    done
    if [ "$ok" = 1 ]; then pass "foot (\$mod+Return) opened a window"
    else fail "foot did not open a window"; fi
fi

section "session log"
# Lines that mean a config or a script is broken, not that CI has no GPU,
# audio or network.
problems=$(grep -nE 'Error on line|Failed to (open|parse|load) config|not a valid option|invalid section|invalid (value|option)|unknown option|Traceback|command not found|: not found$|No such file or directory: .tube-|\[error\].*(config|style|css|json)' "$LOG" \
           | grep -vE '\[DEBUG\]' | head -n 40)
if [ -z "$problems" ]; then
    pass "no config errors or tracebacks in the session log"
else
    fail "the session log has errors:"; printf '%s\n' "$problems" | sed 's/^/        /'
fi

trap - EXIT
cleanup
if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::group::full session log (without DEBUG)"; fi
grep -vE '\[DEBUG\]' "$LOG" | tail -n 300
if [ -n "${GITHUB_ACTIONS:-}" ]; then echo "::endgroup::"; fi
[ -n "${SMOKE_LOG_OUT:-}" ] && cp "$LOG" "$SMOKE_LOG_OUT"
rm -rf "$SANDBOX_HOME" "$SANDBOX_RUNTIME"
finish
