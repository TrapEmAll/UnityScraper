# Changelog

Notable changes to UnityScraper are documented here. The project follows
[Semantic Versioning](https://semver.org/) for published releases.

## [Unreleased]

### Added

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
