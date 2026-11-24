# tubewm shared palette (POSIX sh, sourceable).
#
# Every part of tubewm (desktop shell, app themes) reads colours from here.
# Precedence for the accent colour:
#   1. $TUBEWM_ACCENT already set in the environment
#   2. ${XDG_CONFIG_HOME:-$HOME/.config}/tubewm/accent  (one line: TUBEWM_ACCENT=#RRGGBB),
#      written by `desktop/bin/tube-accent`
#   3. the default below
#
# Values are #RRGGBB, upper case.

TUBEWM_BG=#000000          # full-bleed app canvas (terminals, editors)
TUBEWM_SHELL=#111111       # obsidian: start screen, switcher, bar
TUBEWM_SURFACE=#1D1D1D     # charcoal: charms, flyouts, menus
TUBEWM_SURFACE_HI=#2B2B2B  # hover / pressed on a surface
TUBEWM_FG=#FFFFFF          # primary text
TUBEWM_SUBTLE=#8A8A8A      # secondary text, inactive pivots
TUBEWM_DIM=#5E5E5E         # disabled text, hairlines
TUBEWM_LIGHT_BG=#F3F3F3    # alabaster: light-polarity dialogs
TUBEWM_LIGHT_FG=#111111
TUBEWM_URGENT=#E81123

TUBEWM_ACCENT_DEFAULT=#E3008C   # "magenta", the tubewm default

_tubewm_env_accent=${TUBEWM_ACCENT:-}
_tubewm_accent_file=${XDG_CONFIG_HOME:-$HOME/.config}/tubewm/accent
if [ -z "$_tubewm_env_accent" ] && [ -r "$_tubewm_accent_file" ]; then
    . "$_tubewm_accent_file"
fi
TUBEWM_ACCENT=${_tubewm_env_accent:-${TUBEWM_ACCENT:-$TUBEWM_ACCENT_DEFAULT}}
unset _tubewm_env_accent _tubewm_accent_file
