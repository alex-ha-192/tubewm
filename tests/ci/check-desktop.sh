#!/usr/bin/env bash
# Install the desktop into a throwaway home exactly as a user would, then ask
# the real tools whether they accept every config it wrote.
#
#   tests/ci/check-desktop.sh [ACCENT...]     default: the default accent and lime
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

accents=("$@")
[ ${#accents[@]} -gt 0 ] || accents=("" lime)

new_sandbox
C=$SANDBOX_HOME/.config
run() { as_user "$SANDBOX_USER" "$@"; }

section "install (desktop/install.sh into $SANDBOX_HOME)"
if out=$(install_desktop 2>&1); then
    pass "install.sh ran"
else
    fail "install.sh exited non-zero"
fi
printf '%s\n' "$out" | sed 's/^/        /'

# The placeholders tube-render fills: @NAME@ and @NAME_RAW@ for each name
# in its names=(...) list.
palette_names=$(sed -n 's/^names=(\(.*\))$/\1/p' "$REPO/desktop/bin/tube-render" | tr ' ' '|')
[ -n "$palette_names" ] || palette_names='[A-Z][A-Z0-9_]*'
palette_re="@($palette_names)(_RAW)?@"

check_render() { # check_render LABEL
    local label=$1 f out

    section "configs rendered for $label"

    # Every template became a file, with none of tube-render's palette
    # placeholders left behind. Others (gtklock's @USERNAME@, filled in by
    # tube-lock at lock time) are not tube-render's to fill.
    while IFS= read -r rel; do
        f=$C/$rel
        if [ ! -f "$f" ]; then fail "$rel was not written"; continue; fi
        if grep -nE "$palette_re" "$f" >/dev/null; then
            fail "$rel has unfilled palette placeholders: $(grep -noE "$palette_re" "$f" | head -n3 | tr '\n' ' ')"
        fi
    done < <(cd "$REPO/desktop/templates" && find . -type f | sed 's|^\./||' | sort)

    # foot: the exact check that failed on a CachyOS laptop. tube-render
    # silently rewrites foot.ini into the old [colors] form when it thinks
    # foot is old, so also check that it didn't do that on a new foot.
    if have foot; then
        f=$C/foot/foot.ini
        if out=$(run foot --check-config --config="$f" 2>&1) && [ -z "$out" ]; then
            pass "foot $(version_of foot --version) accepts foot/foot.ini"
        elif [ -z "$out" ] || ! printf '%s' "$out" | grep -qi error; then
            warn "foot accepts foot/foot.ini but says: $out"
        else
            fail "foot rejects foot/foot.ini:"; printf '%s\n' "$out" | sed 's/^/        /'
        fi
        local fv; fv=$(version_of foot --version)
        if [ -n "$fv" ] && version_ge "$fv" 1.22 && ! grep -qx '\[colors-dark\]' "$f"; then
            fail "foot $fv is new, but tube-render rewrote foot.ini into the pre-1.22 [colors] form"
        fi
    else
        fail "foot is not installed, cannot check foot.ini"
    fi

    # sway: parse the whole config, including the generated colours.
    if have sway; then
        # sway 1.9 still creates a backend for -C, so give it one that needs
        # no seat or GPU.
        if out=$(run env WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 \
                     sway -C -c "$C/sway/config" 2>&1); then
            pass "sway $(version_of sway --version) accepts sway/config"
            printf '%s\n' "$out" | grep -iE 'error|warn' | sed 's/^/        /'
        else
            fail "sway -C rejects sway/config:"; printf '%s\n' "$out" | grep -v '^\s*$' | tail -n 30 | sed 's/^/        /'
        fi
    else
        fail "sway is not installed, cannot check sway/config"
    fi

    # fuzzel has a real config check (since 1.10).
    if have fuzzel && ! fuzzel --help 2>&1 | grep -q -- --check-config; then
        warn "fuzzel $(version_of fuzzel --version) has no --check-config; fuzzel.ini not checked"
    elif have fuzzel; then
        if out=$(run fuzzel --check-config --config="$C/fuzzel/fuzzel.ini" 2>&1); then
            pass "fuzzel $(version_of fuzzel --version) accepts fuzzel/fuzzel.ini"
            [ -z "$out" ] || printf '%s\n' "$out" | sed 's/^/        /'
        else
            fail "fuzzel rejects fuzzel/fuzzel.ini:"; printf '%s\n' "$out" | sed 's/^/        /'
        fi
    else
        fail "fuzzel is not installed"
    fi

    # swaylock reads its config as long options; compare against --help.
    if have swaylock; then
        local help; help=$(mktemp)
        swaylock --help > "$help" 2>&1 || true
        if out=$(python3 "$CI_DIR/parse.py" keys-vs-help "$C/swaylock/config" "$help"); then
            pass "every swaylock/config key is a swaylock option"
        else
            fail "swaylock/config has options this swaylock doesn't know:"; printf '%s\n' "$out" | sed 's/^/        /'
        fi
        rm -f "$help"
    fi

    # waybar's config: valid JSONC, and modules waybar actually has.
    if out=$(python3 "$CI_DIR/parse.py" jsonc "$C/waybar/config.jsonc" 2>&1); then
        pass "waybar/config.jsonc parses"
    else
        fail "waybar/config.jsonc: $out"
    fi

    # GTK's own CSS parser, for everything GTK 3 / GTK 4 will load.
    local css3=() css4=()
    for f in waybar/style.css waybar/tubewm.css gtk-3.0/gtk.css gtklock/style.css; do
        [ -f "$C/$f" ] && css3+=("$C/$f")
    done
    [ -f "$SANDBOX_HOME/.local/share/tubewm/desktop/shell/style.css" ] \
        && css3+=("$SANDBOX_HOME/.local/share/tubewm/desktop/shell/style.css")
    [ -f "$C/gtk-4.0/gtk.css" ] && css4+=("$C/gtk-4.0/gtk.css")
    for spec in "3:css3" "4:css4"; do
        local major=${spec%%:*} arr="${spec#*:}[@]"
        local list=("${!arr}")
        [ ${#list[@]} -gt 0 ] || continue
        if out=$(python3 "$CI_DIR/parse.py" gtk-css "$major" "${list[@]}" 2>&1); then
            pass "GTK $major parses ${#list[@]} stylesheet(s)"
            [ -z "$out" ] || printf '%s\n' "$out" | sed "s|$C/||; s/^/        /"
        else
            fail "GTK $major rejects CSS:"; printf '%s\n' "$out" | sed "s|$C/||; s/^/        /"
        fi
    done

    # mako has no --check; the session smoke test starts it for real.
}

for a in "${accents[@]}"; do
    if [ -n "$a" ]; then
        # Run it as a plain user would from a terminal, with ~/.local/bin on
        # PATH; smoke-session.sh checks it from inside a display-manager session.
        if out=$(run env PATH="$SANDBOX_HOME/.local/bin:$MINIMAL_PATH" \
                     "$SANDBOX_HOME/.local/bin/tube-accent" "$a" 2>&1); then :; else
            fail "tube-accent $a failed:"; printf '%s\n' "$out" | sed 's/^/        /'; continue
        fi
        check_render "accent $a"
    else
        check_render "the default accent"
    fi
done

section "uninstall"
if out=$(as_user "$SANDBOX_USER" bash "$SANDBOX_REPO/desktop/install.sh" --uninstall 2>&1); then
    pass "install.sh --uninstall ran"
    for b in "$SANDBOX_HOME"/.local/bin/tube-*; do
        [ -e "$b" ] && fail "uninstall left $b"
    done
else
    fail "install.sh --uninstall exited non-zero"; printf '%s\n' "$out" | sed 's/^/        /'
fi

rm -rf "$SANDBOX_HOME" "$SANDBOX_RUNTIME"
finish
