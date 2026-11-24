#!/usr/bin/env bash
# Static checks on the source tree: shellcheck on every shell script,
# Python syntax + pyflakes, and every JSON / JSONC / TOML file parses.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$REPO" || exit 1

files() { git ls-files 2>/dev/null || find . -path ./.git -prune -o -type f -print | sed 's|^\./||'; }
shebang() { head -n1 "$1" 2>/dev/null; }

section "shell scripts (shellcheck)"
if have shellcheck; then
    while IFS= read -r f; do
        case $f in
            # Sourced palette library: its variables are used by whoever
            # sources it, and it sources a user file by computed path.
            palette/tubewm-colors.sh) extra=(-s sh -e SC2034 -e SC1090) ;;
            # Fills templates via ${!name} indirection, which shellcheck
            # can't see, so the derived colours look unused.
            desktop/bin/tube-render) extra=(-e SC2034) ;;
            *) extra=() ;;
        esac
        if out=$(shellcheck -x -S warning -f gcc "${extra[@]}" "$f" 2>&1); then
            pass "$f"
        else
            fail "$f"; printf '%s\n' "$out" | sed 's/^/        /'
        fi
    done < <(files | while IFS= read -r f; do
                 case $f in *.sh) echo "$f"; continue ;; esac
                 case $(shebang "$f") in '#!'*/sh|'#!'*bash|'#!'*' sh') echo "$f" ;; esac
             done | sort -u)
else
    fail "shellcheck is not installed"
fi

section "python (compile + pyflakes)"
mapfile -t py < <(files | while IFS= read -r f; do
    case $f in *.py) echo "$f"; continue ;; esac
    case $(shebang "$f") in '#!'*python*) echo "$f" ;; esac
done | sort -u)
for f in "${py[@]}"; do
    if out=$(python3 - "$f" 2>&1 <<'EOF'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
compile(src, sys.argv[1], "exec")
EOF
    ); then :; else fail "$f does not compile"; printf '%s\n' "$out" | sed 's/^/        /'; fi
done
if python3 -m pyflakes --version >/dev/null 2>&1; then
    if out=$(python3 -m pyflakes "${py[@]}" 2>&1); then
        pass "pyflakes: ${#py[@]} files"
    else
        fail "pyflakes"; printf '%s\n' "$out" | sed 's/^/        /'
    fi
else
    warn "pyflakes not installed; only checked that ${#py[@]} files compile"
fi

section "data files (JSON, JSONC, TOML)"
while IFS= read -r f; do
    case $f in
        *.json)
            if have jq; then
                jq empty "$f" >/dev/null 2>&1 && pass "$f" || fail "$f: $(jq empty "$f" 2>&1 | head -n1)"
            else
                python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" && pass "$f" || fail "$f"
            fi ;;
        *.jsonc)
            if out=$(python3 "$CI_DIR/parse.py" jsonc "$f" 2>&1); then pass "$f"; else fail "$f: $out"; fi ;;
        *.toml)
            if out=$(python3 "$CI_DIR/parse.py" toml "$f" 2>&1); then pass "$f"; else fail "$f: $out"; fi ;;
    esac
done < <(files)

finish
