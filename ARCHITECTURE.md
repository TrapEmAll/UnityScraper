# Architecture

UnityScraper is a desktop-first Python application with shared service modules
for CLI and optional REST automation. SQLite is the durable local store.

## Entry Points

| Entry point | Purpose |
| --- | --- |
| `desktop_app.py` | Primary library-first desktop application |
| `main.py` | XboxUnity, knowledge, backup, export, and API CLI |
| `GUI.py` | Legacy advanced scraper controls |
| `api.py` | Optional local automation API |

## Layers

### Presentation

- `modern_gui.py` builds the dark navigation shell and core pages.
- `knowledge_gui.py` renders knowledge search, imports, sources, and conflicts.
- `backup_gui.py` renders inventory, package, FTP, and converter workflows.
- `setup_wizard.py` handles first-run storage setup.

GUI operations that can block are dispatched to background threads and return
results to Tk's main loop.

### Application Services

- `library_service.py` provides library summaries and archive-health data.
- `knowledge_service.py` provides search, source status, imports, and details.
- `backup_service.py` coordinates scans, installs, exports, verification, FTP,
  and audit records.
- `knowledge_sync.py` exposes complete source-import workflows to CLI and GUI.

### Domain and Adapters

- `main.py` contains the XboxUnity collector and shared configuration.
- `resume.py` handles partial download state and verification.
- `backup_manager.py` parses public STFS/XBE fields and performs safe
  filesystem or FTP operations.
- `knowledge_base.py` defines normalized knowledge records and resolution.
- `consolemods_adapters.py`, `wiki_adapters.py`, and `dat_adapters.py` parse
  source-specific data into shared records.
- `knowledge_sources.py` handles cache-aware, rate-limited source retrieval.

### Persistence

`database.py` creates the legacy library tables and invokes additive knowledge
and backup schema creation.

Main schema groups:

- Library: `titleids`, `title_updates`, `covers`, `download_history`
- Knowledge: sources, documents, revisions, entities, names, identifiers,
  facts, citations, relationships, import runs, and conflicts
- Backups: targets, scans, inventory, and operations

Schema initialization is idempotent. New migrations should preserve existing
data and be covered by tests.

## Data Flow

### Knowledge Import

```text
source discovery
  -> rate-limited fetch
  -> raw cache
  -> source adapter
  -> normalized records
  -> citations and conflicts
  -> preferred fact selection
  -> fill unknown library metadata
```

Raw documents and retrieval metadata remain attached to their source. A parser
failure is recorded against its import run and should not erase prior data.

### Backup Import

```text
user-selected file or ZIP
  -> archive/path validation
  -> STFS or content-tree identification
  -> content-aware destination
  -> .partial copy
  -> SHA-256 verification
  -> atomic publication
  -> operation audit record
```

Game payloads are not stored in SQLite. Inventory records contain paths,
identifiers, sizes, statuses, and notes.

## Storage

Normal Windows data:

```text
%LOCALAPPDATA%\UnityScraper\
  config\
  data\
  diagnostics\
  downloads\
  exports\
  logs\
```

Portable mode uses `UnityScraperData` beside the application when a
`portable.mode` marker is present.

Linux follows the XDG Base Directory specification and separates data,
configuration, cache, and logs under `XDG_DATA_HOME`, `XDG_CONFIG_HOME`,
`XDG_CACHE_HOME`, and `XDG_STATE_HOME`.

Bundled read-only assets are resolved through `app_paths.resource_path`, which
works in source and PyInstaller one-file builds.

## Security Model

- XboxUnity is fixed to its HTTP endpoints.
- The REST API is localhost-only by default; remote binds require a token.
- API configuration mutation uses an explicit validated allowlist.
- FTP credentials stay in memory and are omitted from database settings.
- ZIP imports reject traversal, symlinks, excessive entries, and excessive
  expanded size.
- Package and export copies use temporary files and verification.
- External converters run only through explicit user configuration.

See [SECURITY.md](SECURITY.md) for reporting and operational guidance.

## Packaging

`UnityScraper.spec` is the canonical cross-platform PyInstaller definition.
Assets and modules loaded indirectly by the GUI are listed explicitly. GitHub
Actions validates Windows and Linux one-file builds on pull requests. Version
tags publish a Windows ZIP and Linux tarball with separate SHA-256 files.
