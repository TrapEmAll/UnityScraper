# Xbox Backup Manager

UnityScraper can inventory, verify, install, export, and transfer Xbox content
that the user supplies. It does not download game images, firmware, keys, SDK
files, or commercial game payloads.

## Supported discovery

Choose **Backup Manager** in the desktop application and select a console, USB,
or archive folder. The scanner recognizes:

- `Content/0000000000000000/<TitleID>/<ContentType>/`
- A content root that starts directly with TitleID folders
- Extracted games under `Games/<Game>/`
- Original Xbox `default.xbe` certificate metadata
- Extracted Xbox 360 folders containing `default.xex`
- Folder names ending in `[TITLEID]`

Known content directories include:

| Directory | Content |
| --- | --- |
| `00000002` | Downloadable content |
| `00005000` | Original Xbox game |
| `00007000` | Xbox 360 Games on Demand |
| `000B0000` | Title update |
| `000D0000` | Xbox Live Arcade |

The scanner marks support-only TitleID folders as incomplete when DLC or title
updates are present without a base game. Scans and operation summaries are
recorded in SQLite. Game files are not copied into the database.

## Package installation

**Install Package** reads public STFS header fields from `CON`, `LIVE`, or
`PIRS` packages and places supported content in the correct TitleID and content
type directory. Copies are written to a `.partial` file, verified with SHA-256,
and atomically renamed. Existing files are skipped by default.

**Import ZIP** applies the same checks to packages in a user-supplied ZIP.
Absolute paths, parent traversal, and archive symlinks are rejected.

## Export and verification

**Export Selected** copies an inventoried title to a separate archive folder
and generates `unityscraper-manifest.json` with:

- TitleID, format, source path, and scan metadata
- Relative file names and sizes
- SHA-256 for every exported file
- Manifest schema and creation time

**Verify Selected** checks for missing item paths, abandoned partial files,
empty GOD data directories, and scan-time structural warnings. It is a
structural health check, not a substitute for Redump or No-Intro verification.

## FTP console transfer

The Console Transfer tab supports a user-configured FTP server such as Aurora.
It persists resumable upload and download jobs, retains partial data, recovers
interrupted jobs, limits bandwidth, verifies final sizes, and can capture a
read-only console inventory. The default content root is:

`/Hdd1/Content/0000000000000000`

FTP passwords remain in memory and are deliberately omitted from SQLite.
Traditional FTP is unencrypted, so use it only on a trusted local network.
See [CONSOLE_SYNC.md](CONSOLE_SYNC.md) for queue and comparison behavior.

## ISO conversion

UnityScraper does not implement an ISO-to-GOD or ISO extraction engine. The ISO
Converter tab can run a converter executable selected by the user, using an
argument template with `{input}` and `{output}` placeholders.

This boundary allows users to choose a converter appropriate for their own
backups while keeping converter licensing and binary provenance explicit.

Example command-line form:

```powershell
python main.py --convert-iso game.iso `
  --converter C:\Tools\converter.exe `
  --converter-arg "{input}" `
  --converter-arg "{output}" `
  --converter-output D:\Converted
```

## Command line

```powershell
# Inventory a drive and create a JSON report
python main.py --scan-backups E:\ --backup-report inventory.json

# Install a bare STFS package
python main.py --install-package game.live --backup-target E:\

# Import supported packages from ZIP
python main.py --import-package-zip arcade.zip --backup-target E:\

# Verify a target and write findings
python main.py --verify-backups E:\ --backup-report health.json

# Upload a package to a console FTP server
python main.py --ftp-upload game.live --ftp-host 192.168.1.50
```

## Inspiration and licensing

The workflow was informed by
[TinyXbox360BackupManager](https://github.com/jeanmatthieud/TinyXbox360BackupManager),
which is licensed GPL-3.0-only. UnityScraper's implementation is original Python
code and does not copy or bundle that project's Rust source. The reference is
credited for its clear model of local, USB, and Aurora-oriented backup workflows.

