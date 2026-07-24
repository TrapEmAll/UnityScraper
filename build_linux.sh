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
STAGE="dist/UnityScraper-Linux-${ARCH}"
ARCHIVE="dist/UnityScraper-Linux-${ARCH}.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE"
install -m 0755 dist/UnityScraper "$STAGE/unityscraper"
install -m 0755 packaging/linux/install.sh "$STAGE/install.sh"
install -m 0755 packaging/linux/uninstall.sh "$STAGE/uninstall.sh"
install -m 0644 packaging/linux/io.github.trapemall.UnityScraper.desktop \
    "$STAGE/io.github.trapemall.UnityScraper.desktop"
install -m 0644 packaging/linux/io.github.trapemall.UnityScraper.metainfo.xml \
    "$STAGE/io.github.trapemall.UnityScraper.metainfo.xml"
install -m 0644 assets/UnityScraper.png "$STAGE/unityscraper.png"
install -m 0644 README.md CHANGELOG.md LICENSE "$STAGE/"
install -m 0644 DOCS_INDEX.md BACKUP_MANAGER.md COLLECTION_INTELLIGENCE.md \
    CONSOLE_SYNC.md KNOWLEDGE_SOURCES.md LINUX.md PLUGIN_API.md "$STAGE/"

tar -C dist -czf "$ARCHIVE" "UnityScraper-Linux-${ARCH}"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"

printf '\nBuild complete: %s\nChecksum: %s.sha256\n' "$ARCHIVE" "$ARCHIVE"
