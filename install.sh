#!/bin/sh
# tubewm: install, update or remove the desktop.
#
#   ./install.sh               install or update (a full-screen guide)
#   ./install.sh --uninstall   remove it and put your old settings back
#   ./install.sh --help        every option
#
# This only finds Python and hands over to installer/install.py.
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

for py in /usr/bin/python3 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
        exec "$py" "$HERE/installer/install.py" "$@"
    fi
done

echo "tubewm needs Python 3.9 or newer. Install it, then run ./install.sh again:"
if command -v pacman >/dev/null 2>&1; then echo "  sudo pacman -S python"
elif command -v apt-get >/dev/null 2>&1; then echo "  sudo apt install python3"
elif command -v dnf >/dev/null 2>&1; then echo "  sudo dnf install python3"
elif command -v zypper >/dev/null 2>&1; then echo "  sudo zypper install python3"
fi
exit 1
