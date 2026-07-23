#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.10 or newer is required." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "Python 3.10 or newer is required." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    cat >&2 <<'EOF'
Tkinter is required for the desktop interface.

Debian/Ubuntu: sudo apt install python3-tk
Fedora:        sudo dnf install python3-tkinter
Arch Linux:    sudo pacman -S tk
openSUSE:      sudo zypper install python311-tk
EOF
    exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
    "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

cat <<'EOF'

UnityScraper is ready.
Launch it with:
  ./run-unityscraper.sh
EOF
