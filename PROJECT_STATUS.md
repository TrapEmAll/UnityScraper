# UnityScraper Project Status

UnityScraper is an Xbox 360 library, title-update, artwork, archive-health,
backup-management, and source-attributed knowledge application.

## Completed

- Library-first dark desktop interface with portable storage support.
- XboxUnity cover and title-update collection using its required HTTP endpoints.
- Persistent SQLite library, queue, retries, resumable downloads, diagnostics,
  archive health checks, JSON/CSV exports, and advanced tools.
- Normalized knowledge schema for sources, documents, revisions, entities,
  identifiers, names, facts, citations, relationships, import runs, and
  conflicts.
- ConsoleMods TitleID and Multi-ID parsing with safe publisher/title enrichment.
- Searchable ConsoleMods, XenonLibrary, and Free60 wiki article ingestion using
  MediaWiki API or sitemap discovery, local caching, attribution, and per-source
  failure isolation.
- User-selected Redump and No-Intro XML DAT import for release identity, serial,
  size, status, and checksum metadata.
- Desktop knowledge browser with source status, licenses, citations, import
  actions, and conflict review.
- Windows packaging rules that include the full visual asset set and dynamically
  loaded knowledge adapters.
- Local inventory for Xbox content roots, USB drives, archive folders, Games on
  Demand, XBLA, DLC, title updates, and extracted Xbox/Xbox 360 games.
- Public STFS and XBE header inspection for TitleID, MediaID, content type, disc,
  and display metadata.
- Safe bare-package and ZIP installation with path validation, `.partial`
  staging, SHA-256 verification, and atomic final placement.
- Verified archive export with portable JSON manifests and per-file checksums.
- Aurora-oriented FTP package upload with one connection per operation,
  temporary remote names, and no stored passwords.
- Explicit external converter integration for user-owned ISO images.

## Validation

- Offline tests cover scraper configuration, database behavior, ConsoleMods parsing,
  DAT parsing, wiki parsing, knowledge search/provenance, downloads, queueing,
  STFS/XBE inspection, safe archives, backup scanning, atomic copies, and an
  end-to-end local workflow.
- Network-backed source syncs remain dependent on each source's availability and
  access policy. Cached copies are used when available.

## Deliberate Boundaries

- No commercial game images, firmware, keys, leaked SDK files, or other
  copyrighted payloads are bundled or downloaded.
- Redump and No-Intro DAT files must be obtained by the user from their source.
- Imported facts retain their source and conflicts are shown rather than silently
  discarded.
- Known local or XboxUnity title/publisher data is not replaced by fallback
  knowledge values.
- ISO conversion remains an external-tool boundary. UnityScraper does not
  implement copy-protection bypass or bundle third-party converter binaries.
- Traditional FTP is intended for trusted local networks. Passwords are kept in
  memory and omitted from database records.

## Future Work

- Parse additional XEX fields and link scanned file identifiers directly to
  normalized knowledge entities.
- Add field-specific source-priority controls and conflict resolution actions.
- Add optional scheduled knowledge refreshes and offline HTML reports.
- Add resumable FTP queues and optional Aurora database inventory.
