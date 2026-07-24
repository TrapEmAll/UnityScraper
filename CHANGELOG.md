# Changelog

Notable changes to UnityScraper are documented here. The project follows
[Semantic Versioning](https://semver.org/) for published releases.

## [Unreleased]

### Added

- Read-only XDBF/GPD inspection with bounded entry parsing, achievement state,
  gamerscore summaries, extracted-folder discovery, and local inventory.
- Profile comparison for save hashes and imported achievement state.
- Snapshot-first Xenia migration previews with atomic verified copies and
  non-overwriting conflict handling.
- Additive schema migration 7 for GPDs, achievements, comparisons, Xenia
  migration runs, source priorities, conflict decisions, sync schedules, and
  opt-in remote hash verification.
- Field-specific knowledge source priorities, auditable conflict resolution,
  and opt-in app-start knowledge refresh scheduling.
- Feature-detected remote SHA-256 verification for compatible console FTP
  dashboards.
- Profiles & Saves workspace with read-only Content-tree discovery, masked
  profile inventory, STFS ownership metadata, save search, duplicate and
  mismatch reporting, verified snapshots, manifests, and conflict-safe restore.
- Additive schema migration 6 for profile scans, profiles, saves, snapshots,
  snapshot files, and auditable operations.
- Dalavin / DJ SkunkieButt attribution and preserved GPLv3 provenance for the
  X360 library and Le Fluffie technical reference.
- Bundled Windows XeXTool 6.3 integration with automatic discovery, xorloser
  attribution, provenance, checksum, and preserved third-party license.
- External Tools workspace with XeXTool inspection presets, custom CLI
  arguments, command previews, captured output, cancellation, and timeouts.
- Project creator attribution and a community message from TrapEmAll in About.
- Offline XboxUnity title catalog with background refresh, sync history,
  TitleID/name autocomplete, and a manual/CLI refresh path.
- Additive schema migration 5 for cached XboxUnity titles and catalog sync
  runs.
- Versioned additive migrations for collection snapshots, preservation
  matches, repair plans, console inventories, resumable jobs, overrides, and
  recovery state.
- XEX2 identity parsing, mounted-storage discovery, and immutable read-only
  Aurora database import.
- Exact MediaID Title Update comparison, collection health scoring, and
  non-destructive repair-plan previews.
- Redump/No-Intro file matching, offline HTML reports, manifests, and
  provenance exports.
- Persistent resumable FTP upload/download jobs, bandwidth limits, transfer
  verification, and read-only console snapshots.
- Database backups, plugin API v1, Italian and Portuguese translation
  foundations, UI scaling, and keyboard navigation.
- CycloneDX SBOM generation and GitHub build-provenance attestations.
- Native Linux desktop support with XDG data, configuration, cache, and state
  directories.
- Linux x86_64 release bundle with user-level installation, application-menu
  integration, AppStream metadata, and safe uninstallation.
- Linux source setup, launcher, packaging script, platform tests, and dedicated
  support documentation.
- Parallel Windows and Linux CI artifacts and tag-driven release publishing.
- Authenticated remote REST API mode and validated configuration updates.
- Cross-platform CI with Windows executable smoke builds.
- Tagged-release packaging with SHA-256 checksums.
- Contributor, security, community, and architecture documentation.

### Changed

- Cached XboxUnity titles now resolve immediately in library lists and details,
  enrich matching rows page by page, and recover after interrupted refreshes.
- Library rows now show `Unknown game` instead of duplicating the TitleID when
  no real game name is known.
- Cached XboxUnity names enrich only blank, unknown, or TitleID-shaped values
  and never replace an existing preferred title.
- Library queries now close SQLite handles immediately after use.
- Version advanced to `1.0.0-beta.1`.
- Download queues now use atomic writes and recover interrupted items.
- Update checks select a platform artifact and require its SHA-256 sidecar
  before staging it.
- PyInstaller configuration and desktop entry point now support Windows and
  Linux from the same source tree.
- Knowledge source snapshots use the platform cache directory.
- Repository-generated executables are published through releases and CI
  artifacts instead of being committed to source control.
- Source checkouts use normal application storage unless the user creates a
  `portable.mode` marker.
- Windows setup now creates and uses a project virtual environment.
- Documentation now reflects the library-first desktop application.

### Removed

- Stale drop-in background instructions and historical integration reports.
- Duplicate background-only requirement file.

## [0.10.0-beta.1] - 2026-07-23

### Added

- Source-attributed Xbox 360 knowledge browser.
- ConsoleMods, XenonLibrary, and Free60 wiki ingestion.
- User-supplied Redump and No-Intro DAT imports.
- Normalized entities, identifiers, facts, citations, import runs, and
  conflicts.
- Local backup inventory, STFS/XBE inspection, safe package and ZIP imports,
  verified exports, FTP transfer, and external ISO converter integration.
- Additive backup target, scan, inventory, and operation tables.

### Security

- ZIP traversal and archive symlink protection.
- SHA-256 verified temporary-file publication.
- FTP passwords omitted from persisted target settings.
