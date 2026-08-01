#!/usr/bin/env sh
set -eu

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
APP_DIR="${HOME}/.local/lib/unityscraper"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
APPLICATIONS_DIR="${DATA_HOME}/applications"
ICON_DIR="${DATA_HOME}/icons/hicolor/1024x1024/apps"
METAINFO_DIR="${DATA_HOME}/metainfo"

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS_DIR" "$ICON_DIR" "$METAINFO_DIR"

install -m 0755 "$PACKAGE_DIR/unityscraper" "$APP_DIR/unityscraper"
install -m 0755 "$PACKAGE_DIR/uninstall.sh" "$APP_DIR/uninstall.sh"
install -m 0644 "$PACKAGE_DIR/"*.md "$PACKAGE_DIR/LICENSE" "$APP_DIR/"
install -m 0644 "$PACKAGE_DIR/unityscraper.png" \
    "$ICON_DIR/io.github.trapemall.UnityScraper.png"
install -m 0644 "$PACKAGE_DIR/io.github.trapemall.UnityScraper.metainfo.xml" \
    "$METAINFO_DIR/io.github.trapemall.UnityScraper.metainfo.xml"
ln -sfn "$APP_DIR/unityscraper" "$BIN_DIR/unityscraper"

sed \
    -e "s|@EXEC@|$APP_DIR/unityscraper|g" \
    -e "s|@ICON@|$ICON_DIR/io.github.trapemall.UnityScraper.png|g" \
    "$PACKAGE_DIR/io.github.trapemall.UnityScraper.desktop" \
    > "$APPLICATIONS_DIR/io.github.trapemall.UnityScraper.desktop"
chmod 0644 "$APPLICATIONS_DIR/io.github.trapemall.UnityScraper.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

cat <<EOF
UnityScraper is installed.

Launch it from your application menu or run:
  $BIN_DIR/unityscraper

If $BIN_DIR is not on PATH, add it to your shell profile.

Uninstall with:
  $APP_DIR/uninstall.sh
EOF
