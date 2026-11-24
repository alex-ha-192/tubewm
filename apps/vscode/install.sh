#!/bin/sh
# Install the tubewm Metro theme into VSCode, VSCodium and/or Code - OSS.
#
#   apps/vscode/install.sh [options]
#
#   --accent NAME|#HEX   accent colour (default: the desktop's current accent)
#   --editor NAME        code | codium | code-oss; repeatable (default: all found)
#   --light              make the light theme the active one
#   --status-bar STYLE   plain (black, the default) or accent (a solid strip)
#   --no-settings        install the theme only, leave settings.json alone
#   --ui-css             also wire metro-ui.css into the Custom CSS loader
#   --no-hook            don't follow accent changes made with tube-accent
#   --uninstall          remove the theme, our settings and the hook
#   --quiet              only print errors
#
# Needs python3. Safe to re-run. Settings you already set yourself are kept;
# only the colour-theme keys are always written. Every settings.json it
# touches is backed up first, next to the original, as
# settings.json.tubewm-<date>.bak, and --uninstall puts back what each key
# held before (skipping any you have changed since).

set -eu

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH='' cd -- "$HERE/../.." && pwd)
LIB=$REPO/apps/lib
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
EXT_ID=tubewm.tubewm-metro

status=plain accent='' editors='' light=0 settings=1 uicss=0 hook=1 uninstall=0 quiet=0

say() { [ "$quiet" = 1 ] || printf '%s\n' "$*"; }
die() { printf 'vscode/install.sh: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case $1 in
        --accent) [ $# -ge 2 ] || die "--accent needs a value"; accent=$2; shift ;;
        --accent=*) accent=${1#*=} ;;
        --editor) [ $# -ge 2 ] || die "--editor needs a value"; editors="$editors $2"; shift ;;
        --editor=*) editors="$editors ${1#*=}" ;;
        --light) light=1 ;;
        --status-bar) [ $# -ge 2 ] || die "--status-bar needs a value"; status=$2; shift ;;
        --status-bar=*) status=${1#*=} ;;
        --no-settings) settings=0 ;;
        --ui-css) uicss=1 ;;
        --no-hook) hook=0 ;;
        --uninstall) uninstall=1 ;;
        --quiet|-q) quiet=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

command -v python3 >/dev/null 2>&1 || die "python3 is required"

# editor -> CLI name, user settings dir, extensions dir
editor_cli() { case $1 in code) echo code ;; codium) echo codium ;; code-oss) echo code-oss ;; esac; }
editor_user_dir() {
    case $1 in
        code) echo "$CONFIG_HOME/Code/User" ;;
        codium) echo "$CONFIG_HOME/VSCodium/User" ;;
        code-oss) echo "$CONFIG_HOME/Code - OSS/User" ;;
    esac
}
editor_ext_dir() {
    case $1 in
        code) echo "$HOME/.vscode/extensions" ;;
        codium|code-oss) echo "$HOME/.vscode-oss/extensions" ;;
    esac
}

if [ -z "$editors" ]; then
    for e in code codium code-oss; do
        if command -v "$(editor_cli "$e")" >/dev/null 2>&1 || [ -d "$(editor_user_dir "$e")" ]; then
            editors="$editors $e"
        fi
    done
    [ -n "$editors" ] || die "no VSCode, VSCodium or Code - OSS found (use --editor to force one)"
fi
for e in $editors; do
    [ -n "$(editor_cli "$e")" ] || die "unknown editor '$e' (code, codium or code-oss)"
done

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

# A settings patch with only the keys we own, used for merge and for removal.
make_patch() {
    python3 - "$HERE/settings.jsonc" "$LIB" "$light" "$uicss" "$HERE/metro-ui.css" > "$TMP/patch.json" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[2])
import jsonc
patch = json.loads(jsonc.strip_jsonc(open(sys.argv[1], encoding="utf-8").read()))
if sys.argv[3] == "1":
    patch["workbench.colorTheme"] = "tubewm Metro Light"
if sys.argv[4] == "1":
    patch["vscode_custom_css.imports"] = ["file://" + sys.argv[5]]
json.dump(patch, sys.stdout, indent=2)
PY
}

hook_path=$CONFIG_HOME/tubewm/accent.d/50-vscode
state_dir=$CONFIG_HOME/tubewm/state
FORCE_KEYS=workbench.colorTheme,workbench.preferredDarkColorTheme,workbench.preferredLightColorTheme

# ---------------------------------------------------------------- uninstall
if [ "$uninstall" = 1 ]; then
    make_patch
    for e in $editors; do
        cli=$(editor_cli "$e")
        if command -v "$cli" >/dev/null 2>&1; then
            "$cli" --uninstall-extension "$EXT_ID" >/dev/null 2>&1 || true
        fi
        rm -rf "$(editor_ext_dir "$e")/$EXT_ID"-*
        settings_file=$(editor_user_dir "$e")/settings.json
        state_file=$state_dir/vscode-$e.json
        if [ -f "$settings_file" ]; then
            python3 "$LIB/jsonc.py" remove "$settings_file" "$TMP/patch.json" \
                --state "$state_file" >/dev/null
        fi
        rm -f "$state_file"
        say "$e: removed tubewm Metro"
    done
    rm -f "$hook_path"
    exit 0
fi

# ------------------------------------------------------------------ install
set --
[ -n "$accent" ] && set -- --accent "$accent"
python3 "$HERE/build.py" "$@" --status-bar "$status" --out "$TMP/extension" --vsix "$TMP/tubewm-metro.vsix" >/dev/null \
    || die "theme build failed"
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$TMP/extension/package.json")
used_accent=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["description"].rsplit(" ",1)[-1].rstrip(").") )' "$TMP/extension/package.json")

[ "$settings" = 1 ] && make_patch

for e in $editors; do
    cli=$(editor_cli "$e")
    ext_dir=$(editor_ext_dir "$e")
    if command -v "$cli" >/dev/null 2>&1 \
        && "$cli" --install-extension "$TMP/tubewm-metro.vsix" --force >/dev/null 2>&1; then
        how="via $cli --install-extension"
    else
        # No CLI (or it refused): drop the unpacked extension in place.
        mkdir -p "$ext_dir"
        rm -rf "$ext_dir/$EXT_ID"-*
        cp -R "$TMP/extension" "$ext_dir/$EXT_ID-$version"
        how="into $ext_dir"
    fi
    say "$e: installed tubewm Metro $version ($used_accent) $how"

    if [ "$settings" = 1 ]; then
        user_dir=$(editor_user_dir "$e")
        mkdir -p "$user_dir"
        if changed=$(python3 "$LIB/jsonc.py" merge "$user_dir/settings.json" "$TMP/patch.json" \
                --force "$FORCE_KEYS" --state "$state_dir/vscode-$e.json" 2>"$TMP/err"); then
            n=$(printf '%s' "$changed" | grep -c . || true)
            say "$e: $n setting(s) written to $user_dir/settings.json (your existing values kept)"
            [ "$quiet" = 1 ] || sed 's/^/  /' "$TMP/err"
        else
            cat "$TMP/err" >&2
        fi
    fi
done

# Follow `tube-accent` from the desktop: it runs every executable in
# ~/.config/tubewm/accent.d/ after the accent file changes.
if [ "$hook" = 1 ]; then
    mkdir -p "$(dirname "$hook_path")"
    {
        echo '#!/bin/sh'
        echo '# Installed by tubewm apps/vscode/install.sh: rebuild the theme for the new accent.'
        echo '# The accent file is the source of truth here, not a possibly stale environment.'
        echo 'unset TUBEWM_ACCENT'
        printf 'exec "%s" --quiet --no-settings --no-hook --status-bar %s' "$HERE/install.sh" "$status"
        for e in $editors; do printf ' --editor %s' "$e"; done
        echo
    } > "$hook_path"
    chmod +x "$hook_path"
fi

if [ "$uicss" = 1 ]; then
    say "UI CSS: install the 'Custom CSS and JS Loader' extension, then run 'Enable Custom CSS and JS'."
fi
say "Reload the window (Ctrl+Shift+P, 'Developer: Reload Window') to see the change."
