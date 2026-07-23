#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python desktop_app.py "$@"
fi

exec python3 desktop_app.py "$@"
