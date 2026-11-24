# Shared helpers for the tubewm CI checks. Source it; don't run it.
# shellcheck shell=bash

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
# shellcheck disable=SC2034 # used by the scripts that source this
CI_DIR=$REPO/tests/ci

# What a display manager (greetd, ly, a bare `sway` from a TTY) gives the
# session: no ~/.local/bin, no /usr/local/games, nothing from a shell rc.
MINIMAL_PATH=${TUBEWM_CI_PATH:-/usr/local/sbin:/usr/local/bin:/usr/bin}

fails=0
pass() { printf '  \033[32mok\033[0m    %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; fails=$((fails + 1));
         [ -n "${GITHUB_ACTIONS:-}" ] && printf '::error::%s\n' "$*"; return 0; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*";
         [ -n "${GITHUB_ACTIONS:-}" ] && printf '::warning::%s\n' "$*"; return 0; }
skip() { printf '  skip  %s\n' "$*"; }
section() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
finish() {
    if [ "$fails" -gt 0 ]; then
        printf '\n\033[31m%s: %d check(s) failed\033[0m\n' "$(basename "$0")" "$fails"
        exit 1
    fi
    printf '\n\033[32m%s: all checks passed\033[0m\n' "$(basename "$0")"
}

have() { command -v "$1" >/dev/null 2>&1; }

# The user the session runs as. sway and friends dislike running as root, so
# in a root container we make (once) and use an ordinary user.
ci_user() {
    if [ "$(id -u)" != 0 ]; then id -un; return; fi
    id tubewm-ci >/dev/null 2>&1 || useradd -m -s /bin/bash tubewm-ci
    echo tubewm-ci
}

# as_user USER CMD...: run CMD as USER with a clean, DM-like environment.
# HOME, PATH and XDG_RUNTIME_DIR come from the caller's SANDBOX_* variables.
as_user() {
    local user=$1; shift
    local env=(env -i "HOME=$SANDBOX_HOME" "USER=$user" "LOGNAME=$user" "SHELL=/bin/bash"
               "PATH=$MINIMAL_PATH" "LANG=C.UTF-8" "XDG_RUNTIME_DIR=$SANDBOX_RUNTIME"
               "TERM=${TERM:-dumb}")
    if [ "$(id -un)" = "$user" ]; then
        "${env[@]}" "$@"
    else
        runuser -u "$user" -- "${env[@]}" "$@"
    fi
}

# new_sandbox: a throwaway home owned by the CI user, with tubewm installed
# into it exactly as desktop/install.sh does for a real user.
#   sets SANDBOX_USER SANDBOX_HOME SANDBOX_RUNTIME
new_sandbox() {
    SANDBOX_USER=$(ci_user)
    SANDBOX_HOME=$(mktemp -d "${TMPDIR:-/tmp}/tubewm-home.XXXXXX")
    SANDBOX_RUNTIME=$(mktemp -d "${TMPDIR:-/tmp}/tubewm-run.XXXXXX")
    chmod 700 "$SANDBOX_RUNTIME"
    # The installer copies from the repo; give the user a readable copy so a
    # root-owned checkout with a strict umask still works.
    SANDBOX_REPO=$SANDBOX_HOME/src/tubewm
    mkdir -p "$SANDBOX_REPO"
    (cd "$REPO" && git ls-files -z 2>/dev/null | xargs -0 cp --parents -t "$SANDBOX_REPO" 2>/dev/null) \
        || cp -r "$REPO/." "$SANDBOX_REPO/"
    if [ "$(id -un)" != "$SANDBOX_USER" ]; then
        chown -R "$SANDBOX_USER:" "$SANDBOX_HOME" "$SANDBOX_RUNTIME"
    fi
    export SANDBOX_USER SANDBOX_HOME SANDBOX_RUNTIME SANDBOX_REPO
}

install_desktop() { # install_desktop [install.sh args...]
    as_user "$SANDBOX_USER" bash "$SANDBOX_REPO/desktop/install.sh" --no-gsettings "$@"
}

# The version of a tool as major.minor, e.g. "1.24", or empty.
version_of() {
    "$@" 2>&1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -n1
}
version_ge() { # version_ge A B: is A >= B?
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}
