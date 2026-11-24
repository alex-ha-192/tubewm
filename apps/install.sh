#!/bin/sh
# Theme every supported app that is installed, in the tubewm Metro style.
#
#   apps/install.sh [options]
#
#   --accent NAME|#HEX   accent colour (default: the desktop's current accent)
#   --light              light polarity instead of dark
#   --only a,b           just these apps (see --list for names)
#   --skip a,b           everything found except these
#   --list               show the apps and whether they were found / themed
#   --uninstall          undo everything this script did
#   --no-hook            don't follow accent changes made with tube-accent
#   --quiet              only print errors
#
# VSCode and Vivaldi have their own installers (apps/vscode, apps/vivaldi);
# this calls them too, under the names "vscode" and "vivaldi".

set -eu

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
HOOK=$CONFIG_HOME/tubewm/accent.d/40-apps

accent='' light=0 only='' skip='' list=0 uninstall=0 hook=1 quiet=0
die() { printf 'apps/install.sh: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case $1 in
        --accent) [ $# -ge 2 ] || die "--accent needs a value"; accent=$2; shift ;;
        --accent=*) accent=${1#*=} ;;
        --light) light=1 ;;
        --only) [ $# -ge 2 ] || die "--only needs a value"; only=$2; shift ;;
        --only=*) only=${1#*=} ;;
        --skip) [ $# -ge 2 ] || die "--skip needs a value"; skip=$2; shift ;;
        --skip=*) skip=${1#*=} ;;
        --list) list=1 ;;
        --uninstall) uninstall=1 ;;
        --no-hook) hook=0 ;;
        --quiet|-q) quiet=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
done
command -v python3 >/dev/null 2>&1 || die "python3 is required"

# split vscode/vivaldi out of --only/--skip; the rest goes to appthemes.py
wants() {  # wants NAME: is NAME selected?
    case ",$skip," in *",$1,"*) return 1 ;; esac
    [ -z "$only" ] && return 0
    case ",$only," in *",$1,"*) return 0 ;; esac
    return 1
}
strip_names() { printf '%s' "$1" | tr ',' '\n' | grep -v -x -e vscode -e vivaldi | paste -sd, -; }
rest_only=$(strip_names "$only")
rest_skip=$(strip_names "$skip")

if [ "$list" = 1 ]; then
    python3 "$HERE/lib/appthemes.py" list
    found() { command -v "$1" >/dev/null 2>&1 || [ -d "$2" ] && echo found || echo -; }
    printf '%-10s %-10s %s\n' vscode "$(found code "$CONFIG_HOME/Code")" "VSCode / VSCodium / Code - OSS: apps/vscode"
    printf '%-10s %-10s %s\n' vivaldi "$(found vivaldi "$CONFIG_HOME/vivaldi")" "Vivaldi: apps/vivaldi"
    exit 0
fi

set --
[ -n "$accent" ] && set -- "$@" --accent "$accent"
[ "$quiet" = 1 ] && set -- "$@" --quiet
common="$*"   # accent/quiet, reused for the per-app installers below

status=0
if [ -n "$only" ] && [ -z "$rest_only" ]; then
    :   # only vscode and/or vivaldi were asked for
elif [ "$uninstall" = 1 ]; then
    set -- uninstall ${rest_only:+--only "$rest_only"}
    [ "$quiet" = 1 ] && set -- "$@" --quiet
    python3 "$HERE/lib/appthemes.py" "$@" || status=1
else
    # shellcheck disable=SC2086
    set -- install $common ${rest_only:+--only "$rest_only"} ${rest_skip:+--skip "$rest_skip"}
    [ "$light" = 1 ] && set -- "$@" --light
    python3 "$HERE/lib/appthemes.py" "$@" || status=1
fi

run_sub() {  # run_sub DIR: the app's own installer, if it finds its app
    sub=$HERE/$1/install.sh
    set --
    if [ "$uninstall" = 1 ]; then
        set -- --uninstall
        [ "$quiet" = 1 ] && set -- "$@" --quiet
    else
        # shellcheck disable=SC2086
        set -- $common
        [ "$light" = 1 ] && set -- "$@" --light
        [ "$hook" = 0 ] && set -- "$@" --no-hook
    fi
    sh "$sub" "$@" 2>&1 | sed "s/^vscode\/install.sh: no VSCode.*/vscode: not found, skipped/" || true
}
if wants vscode; then
    if command -v code >/dev/null 2>&1 || command -v codium >/dev/null 2>&1 || command -v code-oss >/dev/null 2>&1 \
        || [ -d "$CONFIG_HOME/Code" ] || [ -d "$CONFIG_HOME/VSCodium" ] || [ -d "$CONFIG_HOME/Code - OSS" ]; then
        run_sub vscode
    fi
fi
if wants vivaldi; then
    if command -v vivaldi >/dev/null 2>&1 || command -v vivaldi-stable >/dev/null 2>&1 \
        || [ -d "$CONFIG_HOME/vivaldi" ] || [ -d "$CONFIG_HOME/vivaldi-snapshot" ]; then
        run_sub vivaldi
    fi
fi

if [ "$uninstall" = 1 ]; then
    rm -f "$HOOK"
elif [ "$hook" = 1 ] && { [ -z "$only" ] || [ -n "$rest_only" ]; }; then
    mkdir -p "$(dirname "$HOOK")"
    {
        echo '#!/bin/sh'
        echo '# Installed by tubewm apps/install.sh: re-theme the apps for the new accent.'
        echo 'unset TUBEWM_ACCENT   # the accent file written by tube-accent wins'
        printf 'exec python3 "%s" install --quiet' "$HERE/lib/appthemes.py"
        [ -n "$rest_only" ] && printf ' --only "%s"' "$rest_only"
        [ -n "$rest_skip" ] && printf ' --skip "%s"' "$rest_skip"
        [ "$light" = 1 ] && printf ' --light'
        echo
    } > "$HOOK"
    chmod +x "$HOOK"
fi
exit "$status"
