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
- `profile_gui.py` renders privacy-aware profile/save inventory and snapshots.
- `collection_gui.py` renders collection analysis, matching, reports, and
  repair previews.
- `community_gui.py` renders unified search and the cross-domain community
  workspaces.
- `setup_wizard.py` handles first-run storage setup.

GUI operations that can block are dispatched to background threads and return
results to Tk's main loop.

### Application Services

- `library_service.py` provides library summaries and archive-health data.
- `knowledge_service.py` provides search, source status, imports, and details.
- `backup_service.py` coordinates scans, installs, exports, verification, FTP,
  and audit records.
- `profile_manager.py` owns Content-tree discovery, STFS ownership inspection,
  profile/save indexing, verified snapshots, and conflict-safe restore.
- `knowledge_sync.py` exposes complete source-import workflows to CLI and GUI.
- `offline_knowledge.py` safely imports browser-saved pages and renders the
  self-contained local reading library.
- `collection_intelligence.py` coordinates snapshots, exact MediaID matching,
  health, preservation matching, repair previews, and offline exports.
- `console_sync.py` owns durable transfer jobs, resumable FTP, remote
  snapshots, and PC/console comparisons.
- `database_migrations.py` applies additive schema versions and provides
  consistent SQLite backup/restore helpers.
- `community_services.py` coordinates guided sync plans, package workspaces,
  artwork, disc and dedup audits, storage, plugins, recovery, compatibility,
  and accessibility.
- `unified_search.py` ranks local results across the application domains.
- `structured_knowledge.py` extracts typed records from cached source documents
  while retaining document and source relationships.
- `tool_catalog.py` declares supported community tools, reviewed operations,
  platform constraints, executable discovery, saved paths, and checksums.
- `external_tools.py` validates path contracts and runs argument vectors without
  a command shell; detached GUI launches remain separate from captured CLI jobs.

### Domain and Adapters

- `main.py` contains the XboxUnity collector and shared configuration.
- `resume.py` handles partial download state and verification.
- `backup_manager.py` parses public STFS/XBE/XEX fields and performs safe
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
  facts, citations, relationships, import runs, conflicts, source priorities,
  conflict decisions, scheduled sync state, and offline archive/import runs
- Backups: targets, scans, inventory, and operations
- Profiles: scan runs, profiles, saves, snapshots, snapshot files, GPD
  inventories, achievements, comparisons, Xenia migration runs, and auditable
  operations
- Community: structured records, guided sync plans, ownership previews, played
  titles and images, save comparisons, artwork exports, disc and dedup audits,
  storage audits, plugin state, recovery, compatibility, and accessibility

Schema initialization is idempotent. New migrations should preserve existing
data and be covered by tests.

## Data Flow

### Knowledge Import

```text
source discovery
  -> rate-limited fetch
  -> raw cache or validated browser-saved page
  -> source adapter
  -> normalized records
  -> citations and conflicts
  -> preferred fact selection
  -> fill unknown library metadata
  -> script-free offline HTML archive
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

### Profile Intelligence

```text
standalone/extracted XDBF file
  -> bounded table and offset validation
  -> read-only achievement/setting parsing
  -> local inventory and profile comparison

indexed saves + Xenia content root
  -> non-mutating migration preview
  -> verified automatic snapshot
  -> .partial copy and SHA-256 verification
  -> skip identical / retain conflicts
  -> migration audit record
```

### Profile Snapshot

```text
user-selected Content tree
  -> read-only profile and save discovery
  -> STFS ownership/header inspection
  -> local inventory and mismatch detection
  -> selected profile or saves
  -> .partial verified copies
  -> atomic snapshot manifest
  -> conflict-preserving restore
```

Profile identifiers are masked in the UI by default. Snapshot payloads remain
on disk under the local application data directory; SQLite stores paths,
hashes, identifiers, and operation history.

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
- Profile scans never modify source content, and restores never overwrite a
  different existing file.

See [SECURITY.md](SECURITY.md) for reporting and operational guidance.

## Packaging

`UnityScraper.spec` is the canonical cross-platform PyInstaller definition.
Assets and modules loaded indirectly by the GUI are listed explicitly. GitHub
Actions validates Windows and Linux one-file builds plus an unsigned macOS
Apple Silicon application bundle. Version tags publish platform archives with
separate SHA-256 files.
