#!/bin/sh
# Install the tubewm Metro look into Vivaldi.
#
#   apps/vivaldi/install.sh [options]
#
#   --accent NAME|#HEX   accent colour (default: the desktop's current accent)
#   --light              make the light theme the active one
#   --profile DIR        Vivaldi profile folder (default: the first found,
#                        ~/.config/vivaldi/Default, snapshot or Flatpak)
#   --no-prefs           only build the files; import the theme by hand
#   --no-hook            don't follow accent changes made with tube-accent
#   --uninstall          remove the themes, CSS folder setting and the hook
#   --quiet              only print errors
#
# Files go to ${XDG_DATA_HOME:-~/.local/share}/tubewm/vivaldi/. When Vivaldi
# is closed the two themes are added to the profile and the CSS folder is
# set; when it is open, the script tells you how to import instead.

set -eu

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
DEST=$DATA_HOME/tubewm/vivaldi
HOOK=$CONFIG_HOME/tubewm/accent.d/50-vivaldi

accent='' light=0 profile='' prefs=1 hook=1 uninstall=0 quiet=0

say() { [ "$quiet" = 1 ] || printf '%s\n' "$*"; }
die() { printf 'vivaldi/install.sh: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case $1 in
        --accent) [ $# -ge 2 ] || die "--accent needs a value"; accent=$2; shift ;;
        --accent=*) accent=${1#*=} ;;
        --light) light=1 ;;
        --profile) [ $# -ge 2 ] || die "--profile needs a value"; profile=$2; shift ;;
        --profile=*) profile=${1#*=} ;;
        --no-prefs) prefs=0 ;;
        --no-hook) hook=0 ;;
        --uninstall) uninstall=1 ;;
        --quiet|-q) quiet=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

command -v python3 >/dev/null 2>&1 || die "python3 is required"

if [ -z "$profile" ]; then
    for p in "$CONFIG_HOME/vivaldi/Default" \
             "$CONFIG_HOME/vivaldi-snapshot/Default" \
             "$HOME/.var/app/com.vivaldi.Vivaldi/config/vivaldi/Default"; do
        if [ -f "$p/Preferences" ]; then profile=$p; break; fi
    done
fi

vivaldi_running() {
    command -v pgrep >/dev/null 2>&1 || return 1
    pgrep -x vivaldi-bin >/dev/null 2>&1 || pgrep -f '/vivaldi(-snapshot)?/vivaldi-bin' >/dev/null 2>&1
}

can_edit_prefs() {
    [ "$prefs" = 1 ] || return 1
    if [ -z "$profile" ] || [ ! -f "$profile/Preferences" ]; then
        say "No Vivaldi profile found (start Vivaldi once, or pass --profile)."
        return 1
    fi
    if vivaldi_running; then
        say "Vivaldi is running, so its settings were left alone (it would overwrite them on exit)."
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------- uninstall
if [ "$uninstall" = 1 ]; then
    if can_edit_prefs; then
        python3 "$HERE/prefs.py" remove "$profile/Preferences" 2>/dev/null
        say "Removed the tubewm themes from $profile."
    else
        say "Close Vivaldi and re-run --uninstall to remove the themes from the profile,"
        say "or delete them in Settings > Themes."
    fi
    rm -rf "$DEST"
    rm -f "$HOOK"
    exit 0
fi

# ------------------------------------------------------------------ install
set --
[ -n "$accent" ] && set -- --accent "$accent"
mkdir -p "$DEST"
info=$(python3 "$HERE/build.py" "$@" --out "$DEST") || die "theme build failed"
say "Built Vivaldi theme files in $DEST ${info##* }"

if can_edit_prefs; then
    set -- --css-dir "$DEST/css"
    [ "$light" = 1 ] && set -- "$@" --light
    python3 "$HERE/prefs.py" apply "$profile/Preferences" "$DEST" "$@" 2>/dev/null \
        || die "could not update $profile/Preferences (left untouched)"
    say "Added 'tubewm Metro Dark' and 'tubewm Metro Light' to $profile and set the CSS folder."
    say ""
    say "One manual step, once: open vivaldi://experiments, tick"
    say "'Allow for using CSS modifications', and restart Vivaldi."
else
    mode=dark; [ "$light" = 1 ] && mode=light
    say ""
    say "To finish by hand:"
    say "  1. Settings > Themes > Import, pick $DEST/themes/tubewm-metro-$mode.zip"
    say "  2. vivaldi://experiments > tick 'Allow for using CSS modifications'"
    say "  3. Settings > Appearance > Custom UI Modifications > choose $DEST/css"
    say "  4. restart Vivaldi"
fi

if [ "$hook" = 1 ]; then
    mkdir -p "$(dirname "$HOOK")"
    {
        echo '#!/bin/sh'
        echo '# Installed by tubewm apps/vivaldi/install.sh: rebuild the theme for the new accent.'
        echo '# The CSS is rewritten at once; the theme colours update next time Vivaldi is closed.'
        echo 'unset TUBEWM_ACCENT'
        printf 'exec "%s" --quiet --no-hook' "$HERE/install.sh"
        [ -n "$profile" ] && printf ' --profile "%s"' "$profile"
        [ "$light" = 1 ] && printf ' --light'
        echo
    } > "$HOOK"
    chmod +x "$HOOK"
fi
