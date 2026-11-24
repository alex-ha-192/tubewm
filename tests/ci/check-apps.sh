#!/usr/bin/env bash
# Theme every app into a throwaway home with apps/install.sh, then load the
# results with the real programs wherever they can check a config headlessly.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

new_sandbox
C=$SANDBOX_HOME/.config
run() { as_user "$SANDBOX_USER" "$@"; }

# Make every app look installed, so its theme is written even when the
# program itself isn't in this container.
for d in kitty alacritty wezterm nvim helix zed qt5ct qt6ct btop zathura mpv; do
    mkdir -p "$C/$d"
done
[ "$(id -un)" = "$SANDBOX_USER" ] || chown -R "$SANDBOX_USER:" "$C"

section "apps/install.sh into $SANDBOX_HOME"
if out=$(run sh "$SANDBOX_REPO/apps/install.sh" --no-hook --skip vscode,vivaldi,firefox 2>&1); then
    pass "apps/install.sh ran"
else
    fail "apps/install.sh exited non-zero"
fi
printf '%s\n' "$out" | sed 's/^/        /'

section "generated files parse"
while IFS= read -r f; do
    rel=${f#"$SANDBOX_HOME/"}
    case $f in
        *.json) jq empty "$f" >/dev/null 2>&1 && pass "$rel" || fail "$rel is not valid JSON: $(jq empty "$f" 2>&1 | head -n1)" ;;
        *.toml) out=$(python3 "$CI_DIR/parse.py" toml "$f" 2>&1) && pass "$rel" || fail "$rel: $out" ;;
    esac
done < <(find "$C" -type f \( -name '*.json' -o -name '*.toml' \) | sort)
if grep -rnE '@[A-Z][A-Z0-9_]*(\.[a-z]+)?@' "$C" >/dev/null 2>&1; then
    fail "unfilled placeholders: $(grep -rlE '@[A-Z][A-Z0-9_]*(\.[a-z]+)?@' "$C" | sed "s|$SANDBOX_HOME/||" | tr '\n' ' ')"
fi

section "the real programs load their themes"

if have tmux; then
    if out=$(run tmux -L tubewm-ci -f /dev/null new-session -d \; source-file "$C/tmux/tubewm.conf" \; kill-server 2>&1) \
            && [ -z "$out" ]; then
        pass "tmux $(version_of tmux -V) sources tmux/tubewm.conf"
    else
        fail "tmux rejects tmux/tubewm.conf:"; printf '%s\n' "$out" | sed 's/^/        /'
        run tmux -L tubewm-ci kill-server >/dev/null 2>&1
    fi
else skip "tmux not installed"; fi

if have nvim; then
    out=$(run nvim --headless -u NONE -i NONE --cmd "set rtp^=$C/nvim" \
              -c 'colorscheme tubewm' -c 'if v:errmsg != "" | cquit | endif' -c 'qa!' 2>&1)
    rc=$?
    if [ $rc = 0 ] && ! printf '%s' "$out" | grep -qE 'E[0-9]+:|Error'; then
        pass "neovim $(version_of nvim --version) loads colorscheme tubewm"
    else
        fail "neovim fails on colorscheme tubewm:"; printf '%s\n' "$out" | sed 's/^/        /'
    fi
else skip "neovim not installed"; fi

if have mpv; then
    out=$(run mpv --idle=no --vo=null --ao=null 2>&1)
    if printf '%s' "$out" | grep -qiE 'error parsing|option .* not found|unknown option|invalid value'; then
        fail "mpv rejects its config:"; printf '%s\n' "$out" | grep -iE 'error|option|invalid' | sed 's/^/        /'
    else
        pass "mpv $(version_of mpv --version) reads mpv.conf + tubewm.conf without errors"
    fi
else skip "mpv not installed"; fi

if have kitty; then
    out=$(run kitty --debug-config 2>&1); rc=$?
    if printf '%s' "$out" | grep -qiE 'invalid|ignoring|unknown'; then
        fail "kitty complains about its config:"; printf '%s\n' "$out" | grep -iE 'invalid|ignoring|unknown' | sed 's/^/        /'
    elif [ $rc = 0 ]; then
        pass "kitty $(version_of kitty --version) reads kitty.conf + tubewm.conf without complaint"
    else
        warn "kitty --debug-config could not run here (exit $rc)"
    fi
else skip "kitty not installed"; fi

if have hx; then
    # helix validates the theme named in config.toml when it loads it; a bad
    # theme is reported by --health's config check on recent versions.
    out=$(run hx --health 2>&1 | head -n 20)
    if printf '%s' "$out" | grep -qiE 'error|failed'; then
        fail "helix reports a config problem:"; printf '%s\n' "$out" | sed 's/^/        /'
    else
        pass "helix $(version_of hx --version) health check is clean"
    fi
else skip "helix not installed"; fi

section "uninstall restores the home"
if out=$(run sh "$SANDBOX_REPO/apps/install.sh" --uninstall 2>&1); then
    pass "apps/install.sh --uninstall ran"
else
    fail "apps/install.sh --uninstall exited non-zero"; printf '%s\n' "$out" | sed 's/^/        /'
fi

rm -rf "$SANDBOX_HOME" "$SANDBOX_RUNTIME"
finish
