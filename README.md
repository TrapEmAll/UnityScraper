<img width="1097" height="829" alt="Screenshot 2026-05-13 210717" src="https://github.com/user-attachments/assets/b35b363a-140c-4b93-97fb-e08b0c4fded0" />
# UnityScraper

**UnityScraper** is a Python tool for archiving **Xbox 360 Title Updates (TUs)** and **custom cover art** from **XboxUnity.net**. It features a two-phase workflow: collect metadata first, then selectively download files through the GUI.

## Features

* ✅ **Auto-load TitleIDs** from `JSON.txt` file on startup
* ✅ **Metadata-only collection** - fetch and index covers/updates without downloading
* ✅ **SQLite database** for persistent storage and tracking
* ✅ **Download status tracking** (pending, downloaded, failed)
* ✅ **GUI integration** - view available items and download status before downloading
* ✅ **Parallel downloads** with configurable workers and rate limiting
* ✅ **Automatic retries** with exponential backoff
* ✅ **Raw JSON metadata** saved alongside downloaded files
* ✅ **CLI and GUI** - both use the same backend engine
* ✅ **HTTP-only XboxUnity compatibility** matching the service endpoints
* ✅ **ConsoleMods knowledge import** for TitleID, publisher, region, and Multi-ID enrichment

---

## Requirements

* Python **3.9+** recommended
* Python packages:

```bash
pip install -r requirements.txt
```

Tkinter is included with standard Python installs.

---

## Quick Start

### Windows Desktop App

Run the desktop app directly:

```bat
Run-UnityScraper.bat
```

Or build a standalone Windows executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The built app is written to:

```text
dist\UnityScraper.exe
```

All user data is stored locally under:

```text
%LOCALAPPDATA%\UnityScraper
```

That folder contains the SQLite database, editable `JSON.txt` TitleID list,
saved config, logs, and downloaded archive files.

### Option 1: Auto-Load from JSON.txt

Place a `JSON.txt` file in the same directory with comma-separated TitleIDs:

```
TESTID00,TESTID01,TESTID02
```

Then run:

```bash
python main.py
```

This will:
1. Load all TitleIDs from `JSON.txt`
2. Collect metadata (covers, updates) without downloading
3. Store everything in `unityscraper.db`
4. Print: "Metadata collection completed! Check GUI to view and download items."

### Option 2: Manual TitleID Entry

```bash
python main.py
# or
python main.py TESTID00,TESTID01
```

### Option 3: Launch GUI

```bash
python GUI.py
```

---

## Usage (CLI)

### Basic Commands

```bash
# Auto-load from JSON.txt (metadata-only)
python main.py

# Manual TitleIDs (metadata-only by default)
python main.py TESTID00,TESTID01

# Download content for specific TitleIDs
python main.py TESTID00 --metadata-only=false

# Metadata-only explicitly
python main.py TESTID00 --metadata-only
```

### CLI Options

```bash
python main.py [TITLEIDS] [options]
```

| Option              | Description                                           |
| ------------------- | ----------------------------------------------------- |
| `TITLEIDS`          | Comma-separated TitleIDs (e.g. `TESTID00,TESTID01`)   |
| `--out PATH`        | Output directory (default: `unityscrape`)             |
| `--workers N`       | Parallel workers (default: 4)                         |
| `--rate SECONDS`    | Min seconds between requests (default: 0.35)          |
| `--config PATH`     | Load config from JSON file                            |
| `--save-config`     | Save current settings to `config.json`                |
| `--metadata-only`   | Only collect metadata, don't download files           |
| `--log-level LEVEL` | DEBUG, INFO, WARNING, ERROR                           |
| `--force-http`      | Use XboxUnity HTTP endpoints (always enabled)         |

### Examples

```bash
# Auto-load JSON.txt and collect metadata
python main.py

# Manual entry with custom output directory
python main.py TESTID00 --out D:\Archive --workers 8

# Metadata-only mode
python main.py TESTID00 --metadata-only

# Download with saved config
python main.py --config config.json
```

---

## Usage (GUI)

Launch the GUI:

```bash
python GUI.py
```

### GUI Features

* View all TitleIDs in database with metadata
* See download status for each cover and update:
  * 🟡 **Pending** - metadata available, not yet downloaded
  * 🟢 **Downloaded** - file successfully saved
  * 🔴 **Failed** - download failed (can retry)
* Adjust worker count and rate limiting
* Progress tracking with live log output
* Selective download of items
* Search and filter available content

---

## Workflow: Metadata Collection → Selective Download

### Phase 1: Collect Metadata (Fast)

```bash
python main.py
# Reads JSON.txt → fetches metadata → stores in database
# Takes seconds, no large files downloaded
```

Database now contains:
- All available covers with URLs
- All available updates with versions
- Download status for each item

### Phase 2: Selective Download (Via GUI)

```bash
python GUI.py
# View all metadata
# Select items to download
# Download marked items
```

---

## Database Schema

**UnityScraper** uses SQLite (`unityscraper.db`) to store:

### Tables

| Table | Purpose |
|-------|---------|
| `titleids` | Tracked TitleIDs with metadata |
| `covers` | Cover art info with status |
| `title_updates` | Update versions with status |
| `download_history` | Download attempts and results |

### Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Metadata found, not yet downloaded |
| `downloaded` | File successfully saved |
| `failed` | Download attempt failed |

---

## Output Structure

```
unityscrape/
└── TITLEID/
    ├── covers_data.json
    ├── updates_data.json
    ├── covers/
    │   ├── cover1.jpg
    │   └── cover2.png
    └── MEDIAID1/
        └── version_3/
            └── update_FILE.bin
```

Raw JSON responses are **always saved** for reference:
* `covers_data.json` - API response with cover metadata
* `updates_data.json` - API response with update metadata

---

## Configuration

### Config File

Save your settings to `config.json`:

```bash
python main.py TESTID00 --workers 8 --rate 0.5 --save-config
```

This creates `config.json` for future runs:

```bash
python main.py --config config.json
```

---

## TitleID Format

* **Must be 8 hexadecimal characters** (0-9, A-F)
* Automatically normalized to **uppercase**
* Invalid TitleIDs are skipped with warnings
* Test placeholders: `TESTID00`, `TESTID01`, etc.

---

## Networking

* **XboxUnity uses HTTP-only endpoints**
* **Global rate limiting** across all parallel downloads
* **Automatic retries** with exponential backoff
* **429 handling** for rate-limited requests
* Configurable request timeout (default: 30s)

---

## Knowledge Import

Import ConsoleMods TitleID and Multi-ID reference data, then enrich only unknown
library title/publisher fields:

```bash
python main.py --sync-knowledge
```

The normalized knowledge schema stores sources, documents, revisions, entities,
identifiers, facts, citations, import runs, and conflicts. See
[`KNOWLEDGE_SOURCES.md`](KNOWLEDGE_SOURCES.md) for migration notes, source and
licensing considerations, and next steps for XenonLibrary, Free60, Redump DAT,
and No-Intro DAT adapters.

---

## Advanced Usage

### JSON.txt Format

Create a file named `JSON.txt` with comma-separated TitleIDs:

```
TESTID00,TESTID01,TESTID02,TESTID03
```

On next run, these will automatically load in metadata-only mode.

### Batch Processing

```bash
# Metadata collection with custom settings
python main.py --rate 0.5 --workers 4 --log-level INFO

# Then download via GUI at your own pace
python GUI.py
```

### Resume Failed Downloads

The database tracks which items failed. Use the GUI to retry without re-scanning metadata.

---

## Testing

Run the test suite:

```bash
python -m pytest tests.py -v
```

Tests use **test-only TitleIDs** (`TESTID00`, `TESTID01`) for safety.

---

## Limitations

* No authentication (public endpoints only)
* GUI stop button is **best-effort**
* Resume support for partial files (planned)
* No duplicate detection yet

---

## Intended Use

✅ **Recommended for:**
* Offline archiving and preservation
* Research and analysis
* Metadata collection
* Personal use

❌ **Not recommended for:**
* High-frequency automated scraping
* Commercial redistribution
* Bypassing site restrictions
* Concurrent instance scraping

Be respectful of XboxUnity's infrastructure.

---

## License

No explicit license is currently defined.
If you plan to redistribute or contribute, clarify licensing first.

---

## Author

Created and maintained by **Sthornberry9**

---

## Future Enhancements

1. **Resume support** for interrupted downloads
2. **Batch operations** for bulk downloads
3. **Search/filter** in database for large collections
4. **Export** metadata to CSV/JSON
5. **Notifications** when metadata is updated

---
