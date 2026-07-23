#!/usr/bin/env sh
set -eu

APP_DIR="${HOME}/.local/lib/unityscraper"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"

rm -f "$BIN_DIR/unityscraper"
rm -f "$DATA_HOME/applications/io.github.trapemall.UnityScraper.desktop"
rm -f "$DATA_HOME/icons/hicolor/1024x1024/apps/io.github.trapemall.UnityScraper.png"
rm -f "$DATA_HOME/metainfo/io.github.trapemall.UnityScraper.metainfo.xml"
rm -rf "$APP_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
fi

cat <<'EOF'
UnityScraper was uninstalled.
Your library, configuration, downloads, and logs were left intact.
See LINUX.md for their XDG locations and optional manual cleanup.
EOF
