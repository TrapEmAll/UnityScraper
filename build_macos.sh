#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

"$PYTHON" -m pip install -r requirements.txt pyinstaller
"$PYTHON" -m PyInstaller --clean --noconfirm UnityScraper.spec

ARCH="$(uname -m)"
APP="dist/UnityScraper.app"
ARCHIVE="dist/UnityScraper-macOS-${ARCH}.tar.gz"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
install -m 0755 dist/UnityScraper "$APP/Contents/MacOS/UnityScraper"
install -m 0644 packaging/macos/Info.plist "$APP/Contents/Info.plist"
install -m 0644 assets/UnityScraper.png "$APP/Contents/Resources/UnityScraper.png"
tar -C dist -czf "$ARCHIVE" UnityScraper.app
shasum -a 256 "$ARCHIVE" > "$ARCHIVE.sha256"

printf '\nBuild complete: %s\nChecksum: %s.sha256\n' "$ARCHIVE" "$ARCHIVE"
