#!/usr/bin/env bash
# Run every CI check in order and report which ones failed. Each check is
# also runnable on its own. Expects the packages from arch-deps.sh.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "$here/../.." && pwd)

failed=()
step() { local name=$1; shift; printf '\n\033[1;34m### %s\033[0m\n' "$name"; "$@" || failed+=("$name"); }

step lint        "$here/lint.sh"
step "unit tests" python3 -m pytest -q "$repo/apps/tests" "$repo/desktop/shell/tests"
step desktop     "$here/check-desktop.sh"
step apps        "$here/check-apps.sh"
step session     "$here/smoke-session.sh"

if [ ${#failed[@]} -gt 0 ]; then
    printf '\n\033[31mfailed: %s\033[0m\n' "${failed[*]}"; exit 1
fi
printf '\n\033[32meverything passed\033[0m\n'
